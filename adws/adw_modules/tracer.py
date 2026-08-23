"""Tracer: every event lands in JSONL and SQLite AS IT HAPPENS.

Files are the raw record; sssf.db is the queryable mirror the UI polls.
No push transport — the flow is always: agents -> sqlite -> web ui.
WAL mode so the UI can read while ADW processes write.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .data_types import AgentConfig, EventRecord, GateReport, Phase
from .utils import ensure_dir, new_id, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  adw_id        TEXT PRIMARY KEY,
  adw_name      TEXT,                -- ADW script(s) run, e.g. "adw_plan + adw_build_test"
  request       TEXT,
  status        TEXT,
  engineer      TEXT,
  started_at    TEXT, ended_at TEXT,
  total_tokens  INTEGER DEFAULT 0, total_cost REAL DEFAULT 0,
  archived      INTEGER DEFAULT 0,  -- review triage, set by the UI; never by a run
  pane_id       TEXT                -- Herdr pane the run was launched from (HERDR_PANE_ID), for Collie
);
CREATE TABLE IF NOT EXISTS phases (
  phase_id      TEXT PRIMARY KEY,
  adw_id        TEXT REFERENCES sessions,
  seq           INTEGER,
  name TEXT, kind TEXT, owner TEXT, description TEXT,
  status        TEXT DEFAULT 'fail',
  attempt       INTEGER DEFAULT 0, retries INTEGER DEFAULT 0,
  error         TEXT,
  started_at    TEXT, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  event_id      TEXT PRIMARY KEY,
  adw_id        TEXT REFERENCES sessions,
  phase_id      TEXT REFERENCES phases,
  parent_id     TEXT,
  type          TEXT,
  name          TEXT,
  payload_json  TEXT,
  tokens        INTEGER,
  started_at    TEXT, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS envelopes (
  envelope_id   TEXT PRIMARY KEY,
  adw_id        TEXT REFERENCES sessions,
  phase_id      TEXT REFERENCES phases,
  agent         TEXT,
  output_type   TEXT,
  payload_json  TEXT,
  valid         INTEGER,
  attempt       INTEGER,
  created_at    TEXT
);
CREATE TABLE IF NOT EXISTS gate_results (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  adw_id        TEXT REFERENCES sessions,
  phase_id      TEXT REFERENCES phases,
  attempt       INTEGER,
  gate          TEXT,
  passed        INTEGER,
  violations_json TEXT,
  checks_json   TEXT,               -- [{item, ok, note}] — WHAT the gate verified
  created_at    TEXT
);
CREATE TABLE IF NOT EXISTS processes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  adw_id        TEXT REFERENCES sessions,
  kind          TEXT,                -- 'adw' (the workflow process) | 'agent' (a coding-agent child)
  name          TEXT,                -- '' for the adw, the agent name for a child
  pid           INTEGER,
  command       TEXT,                -- what the pid was, so a recycled pid is not killed by mistake
  started_at    TEXT, ended_at TEXT  -- ended_at NULL = believed alive
);
CREATE TABLE IF NOT EXISTS agent_sessions (
  adw_id        TEXT REFERENCES sessions,
  agent         TEXT,
  coding_agent  TEXT, model TEXT, color TEXT,
  session_id    TEXT,
  context_tokens INTEGER,           -- window occupancy after the agent's last turn
  context_window INTEGER,           -- the model's ceiling; 0/NULL = unknown
  created_at    TEXT, last_used_at TEXT,
  PRIMARY KEY (adw_id, agent)
);
"""

# Columns added after a schema shipped. CREATE TABLE IF NOT EXISTS never
# revisits an existing table, so additive changes need an explicit ALTER.
MIGRATIONS = [("agent_sessions", "color", "TEXT"),
              ("gate_results", "checks_json", "TEXT"),
              ("sessions", "adw_name", "TEXT"),
              ("agent_sessions", "context_tokens", "INTEGER"),
              ("agent_sessions", "context_window", "INTEGER"),
              ("sessions", "archived", "INTEGER DEFAULT 0"),
              ("sessions", "pane_id", "TEXT")]


# Phases whose output a review was ruling on. Once a reject is seen in the
# checkpoint, replaying these hands the builder its own rejected work back.
REDO_AFTER_A_REJECT = ("build", "revise", "fix")
REVIEW = "review"
NEVER_REPLAYED = ("revise",)


def usable_checkpoint(envelopes: dict[str, str]) -> dict[str, str]:
    """Filter envelopes to only those that represent reusable completed work.

    Rules (#69):
    1. A review phase is a checkpoint ONLY when its envelope parses and says
       `approved: true`. An explicit `approved: false` also marks the run
       as rejected; an unreadable or missing verdict is dropped without
       setting the reject flag.
    2. A revise phase is NEVER replayed: it answered findings that no longer
       exist on a subsequent invocation.
    3. If any review rejected, drop all builder phases (build / revise / fix)
       that the review was ruling on, forcing them to re-run.
    4. The plan survives. It is not what was rejected, and re-planning would
       move the commit the reviewer's diff is measured from.
    """
    kept: dict[str, str] = {}
    rejected = False
    for name, payload_json in envelopes.items():
        if name.startswith(NEVER_REPLAYED):
            continue
        if name.startswith(REVIEW):
            try:
                data = json.loads(payload_json or "{}")
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            approved = data.get("approved")
            if approved is False:
                rejected = True
            elif approved is True:
                kept[name] = payload_json
            continue
        kept[name] = payload_json

    if rejected:
        kept = {name: payload for name, payload in kept.items()
                if not name.startswith(REDO_AFTER_A_REJECT)}
    return kept


class Tracer:
    def __init__(self, db_path: str | Path, events_jsonl: str | Path):
        ensure_dir(Path(db_path).parent)
        self.db_path = str(db_path)
        self.events_jsonl = Path(events_jsonl)
        ensure_dir(self.events_jsonl.parent)
        self.conn = sqlite3.connect(self.db_path, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA busy_timeout=5000;")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Additive column migrations, so a db from an older SSSF still opens."""
        for table, column, decl in MIGRATIONS:
            columns = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # ── events ──────────────────────────────────────────────────────────────
    def event(self, record: EventRecord) -> str:
        event_id = f"evt_{new_id(12)}"
        ts = now_iso()
        line = {"event_id": event_id, "ts": ts, **record.model_dump()}
        with self.events_jsonl.open("a") as f:
            f.write(json.dumps(line) + "\n")
        self.conn.execute(
            "INSERT INTO events (event_id, adw_id, phase_id, parent_id, type, name,"
            " payload_json, tokens, started_at, ended_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (event_id, record.adw_id, record.phase_id, record.parent_id, record.type,
             record.name, json.dumps(record.payload), record.tokens,
             record.started_at or ts, record.ended_at),
        )
        return event_id

    # ── sessions ────────────────────────────────────────────────────────────
    def session_start(self, adw_id: str, engineer: str, adw_name: str | None = None) -> None:
        # Herdr exports HERDR_PANE_ID into every pane's shell, so an ADW launched from a
        # pane (directly, or by an agent's shell tool) inherits it. Collie uses it to hang the
        # run off the pane that started it. Unset (a scheduler, a plain terminal) stays NULL.
        pane_id = os.environ.get("HERDR_PANE_ID") or None
        self.conn.execute(
            "INSERT INTO sessions (adw_id, status, engineer, started_at, pane_id) VALUES (?,?,?,?,?) "
            "ON CONFLICT(adw_id) DO UPDATE SET status='running', "
            "pane_id=COALESCE(excluded.pane_id, sessions.pane_id)",
            (adw_id, "running", engineer, now_iso(), pane_id),
        )
        if not adw_name:
            return
        # A joined session chains ADWs — record each distinct one, in run order.
        row = self.conn.execute("SELECT adw_name FROM sessions WHERE adw_id=?",
                                (adw_id,)).fetchone()
        names = row[0].split(" + ") if row and row[0] else []
        if adw_name not in names:
            names.append(adw_name)
            self.conn.execute("UPDATE sessions SET adw_name=? WHERE adw_id=?",
                              (" + ".join(names), adw_id))

    def session_request(self, adw_id: str, request: str) -> None:
        self.conn.execute("UPDATE sessions SET request=? WHERE adw_id=?",
                          (request[:500], adw_id))

    def session_finish(self, adw_id: str, ok: bool) -> None:
        self.conn.execute(
            "UPDATE sessions SET status=?, ended_at=? WHERE adw_id=?",
            ("success" if ok else "fail", now_iso(), adw_id),
        )
        self.processes_end_all(adw_id)   # nothing of this run is alive any more

    def session_add_usage(self, adw_id: str, tokens: int, cost: float) -> None:
        self.conn.execute(
            "UPDATE sessions SET total_tokens=total_tokens+?, total_cost=total_cost+? WHERE adw_id=?",
            (tokens, cost, adw_id),
        )

    # ── processes (adw_id → pid, so a hung run can be found and killed) ─────
    def process_start(self, adw_id: str, kind: str, name: str, pid: int,
                      command: str) -> None:
        """Record a live process for this run.

        A coding agent that hangs produces no events at all, which is exactly
        when you need its pid — and `ps` cannot tell you which adw_id it
        belongs to. Writing it here makes the trace the answer to "what is this
        run running, and how do I stop it".
        """
        self.conn.execute(
            "INSERT INTO processes (adw_id, kind, name, pid, command, started_at)"
            " VALUES (?,?,?,?,?,?)",
            (adw_id, kind, name, pid, command[:500], now_iso()),
        )

    def process_end(self, adw_id: str, pid: int) -> None:
        """Mark the newest live row for this pid as finished."""
        self.conn.execute(
            "UPDATE processes SET ended_at=? WHERE id = ("
            "  SELECT id FROM processes WHERE adw_id=? AND pid=? AND ended_at IS NULL"
            "  ORDER BY id DESC LIMIT 1)",
            (now_iso(), adw_id, pid),
        )

    def processes_end_all(self, adw_id: str) -> None:
        """Close out every live row for a run — called when the session ends."""
        self.conn.execute(
            "UPDATE processes SET ended_at=? WHERE adw_id=? AND ended_at IS NULL",
            (now_iso(), adw_id),
        )

    # ── phases ──────────────────────────────────────────────────────────────
    def max_phase_seq(self, adw_id: str) -> int:
        """Highest seq already recorded for this session; 0 when it is new.

        A joined run continues the sequence instead of restarting at 1 — which
        would collide with the first run's phases on both `seq` (breaking
        ordering) and `phase_id` (silently overwriting a row through the
        phase_upsert conflict clause).
        """
        row = self.conn.execute("SELECT MAX(seq) FROM phases WHERE adw_id = ?",
                                (adw_id,)).fetchone()
        return row[0] if row and row[0] is not None else 0

    def phase_upsert(self, phase: Phase) -> None:
        p = phase.params
        self.conn.execute(
            "INSERT INTO phases (phase_id, adw_id, seq, name, kind, owner, description,"
            " status, attempt, retries, error, started_at, ended_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(phase_id) DO UPDATE SET status=excluded.status,"
            " attempt=excluded.attempt, error=excluded.error, ended_at=excluded.ended_at",
            (phase.phase_id, phase.adw_id, phase.seq, p.name, p.kind, p.owner,
             p.description, phase.status, phase.attempt, p.retries, phase.error,
             phase.started_at, phase.ended_at),
        )

    # ── envelopes / gates / agent sessions ──────────────────────────────────
    def envelope_row(self, phase: Phase, agent: str, output_type: str,
                     payload_json: str, valid: bool, attempt: int) -> None:
        self.conn.execute(
            "INSERT INTO envelopes (envelope_id, adw_id, phase_id, agent, output_type,"
            " payload_json, valid, attempt, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"env_{new_id(12)}", phase.adw_id, phase.phase_id, agent, output_type,
             payload_json, int(valid), attempt, now_iso()),
        )

    def gate_row(self, phase: Phase, gate: str, report: GateReport, attempt: int) -> None:
        """The report carries both the verdict and the evidence behind it."""
        self.conn.execute(
            "INSERT INTO gate_results (adw_id, phase_id, attempt, gate, passed,"
            " violations_json, checks_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (phase.adw_id, phase.phase_id, attempt, gate, int(report.passed),
             json.dumps(report.violations),
             json.dumps([c.model_dump() for c in report.checks]), now_iso()),
        )

    # ── guards (Phase 2c: budget + checkpointing) ────────────────────────────
    def total_spend(self) -> float:
        """Every dollar this box's trace has recorded, across all sessions.

        Deliberately the whole db, not just this adw_id: the budget is the
        BOX's allowance, and a second workflow in the same box spends the
        same subscription. Matches what `sbx.py status` prints.
        """
        row = self.conn.execute("SELECT COALESCE(SUM(total_cost), 0) FROM sessions").fetchone()
        return float(row[0] or 0.0)

    def completed_envelopes(self, adw_id: str) -> dict[str, str]:
        """phase name -> its valid envelope JSON, for phases that succeeded.

        The checkpoint. Keyed by phase NAME (not phase_id) because a resumed
        run mints new phase_ids as it continues the sequence. The newest
        matching envelope per phase name wins, in case a phase name repeats
        (a joined run that re-enters the same phase).
        """
        rows = self.conn.execute(
            "SELECT phases.name, envelopes.payload_json, envelopes.created_at "
            "FROM envelopes JOIN phases ON envelopes.phase_id = phases.phase_id "
            "WHERE phases.adw_id = ? AND phases.status = 'success' AND envelopes.valid = 1 "
            "ORDER BY envelopes.created_at ASC",
            (adw_id,),
        ).fetchall()
        out: dict[str, str] = {}
        for name, payload_json, _created_at in rows:
            out[name] = payload_json   # later rows overwrite earlier ones -- newest wins
        return usable_checkpoint(out)

    def prompt_fingerprints(self, adw_id: str) -> dict[str, str]:
        """phase name -> fingerprint of the prompt that phase was given.

        Read out of the events for the same reason completed_envelopes is: the
        checkpoint is keyed by phase NAME, and a joined run reuses those names
        with a DIFFERENT prompt. Replaying `build` then hands the builder the
        previous ask (#69). This is how execute() tells "the run died here, redo
        nothing" apart from "same session, new ask".

        Written by agents.execute() once a phase has produced a valid envelope,
        so only finished work is fingerprinted. Later rows win.
        """
        out: dict[str, str] = {}
        rows = self.conn.execute(
            "SELECT payload_json FROM events WHERE adw_id = ? AND type = 'log' "
            "AND name = 'phase_prompt' ORDER BY rowid", (adw_id,)).fetchall()
        for (payload_json,) in rows:
            try:
                payload = json.loads(payload_json or "{}")
            except ValueError:
                continue
            if not isinstance(payload, dict):
                continue
            phase = payload.get("phase")
            if phase:
                out[str(phase)] = str(payload.get("fingerprint") or "")
        return out

    def paths_touched(self, adw_id: str) -> dict[str, list[str]]:
        """agent name -> every repo path it changed in this run, in order seen.

        Read back out of the events rather than kept in memory, for the same
        reason completed_envelopes is: a resumed run replays phases it never
        executed, and a commit phase still has to stage what those phases
        changed. Written by agents.execute() from permissions.enforce(), so
        this is git's account of what the agent touched, not the agent's.
        """
        out: dict[str, list[str]] = {}
        rows = self.conn.execute(
            "SELECT payload_json FROM events WHERE adw_id = ? AND type = 'log' "
            "AND name = 'paths_touched' ORDER BY rowid", (adw_id,)).fetchall()
        for (payload_json,) in rows:
            try:
                payload = json.loads(payload_json or "{}")
            except ValueError:
                continue
            seen = out.setdefault(str(payload.get("agent") or ""), [])
            for path in payload.get("paths") or []:
                if path not in seen:
                    seen.append(str(path))
        return out

    def paths_touched_any(self) -> set[str]:
        """Every repo path ANY run in this db has changed. No adw_id filter.

        paths_touched answers "what did THIS run touch". This answers "has a run
        ever touched this file at all", which is the only form of the question a
        dirty tree at startup can be checked against: git records that a file
        changed, not who changed it, so at commit time the operator's own work
        and the last run's rejected build are the same string (#85). The ledger
        can tell them apart, so ask it before the run starts rather than guess
        after it finishes.
        """
        out: set[str] = set()
        rows = self.conn.execute(
            "SELECT payload_json FROM events WHERE type = 'log' "
            "AND name = 'paths_touched' ORDER BY rowid").fetchall()
        for (payload_json,) in rows:
            try:
                payload = json.loads(payload_json or "{}")
            except ValueError:
                continue
            for path in payload.get("paths") or []:
                out.add(str(path))
        return out

    def agent_session_row(self, adw_id: str, agent: AgentConfig, session_id: str,
                          context_tokens: int = 0, context_window: int = 0) -> None:
        """The agent's config row is the source of truth for its label and color.

        Context is carried here rather than derived from events because the lane
        wants one number per agent — the latest — and a session that runs the
        same agent twice overwrites it, exactly like model and session_id.
        """
        ts = now_iso()
        self.conn.execute(
            "INSERT INTO agent_sessions (adw_id, agent, coding_agent, model, color,"
            " session_id, context_tokens, context_window, created_at, last_used_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(adw_id, agent) DO UPDATE SET model=excluded.model,"
            " color=excluded.color, session_id=excluded.session_id,"
            " context_tokens=excluded.context_tokens,"
            " context_window=excluded.context_window,"
            " last_used_at=excluded.last_used_at",
            (adw_id, agent.name, agent.coding_agent, agent.model, agent.color,
             session_id, context_tokens, context_window, ts, ts),
        )

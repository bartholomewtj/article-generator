"""Config loading/validation and agent execution.

Every ADW validates its agents before running (fail fast, nothing spawns
against a half-valid config). Every agent call parses against a concrete
output type; parse failures and gate violations re-prompt the SAME session
with a correction — context intact, bounded retries. Agent proposes, code
disposes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

import yaml

from . import agent_agy, agent_cc, agent_grok, agent_pi, control, permissions, prompts
from .data_types import (AgentCall, AgentConfig, EnvelopeBase, EventRecord,
                         GateCheck, GateReport, Phase, PiRequest, PiResult,
                         SSSFConfig, UsageBreakdown)
from .utils import new_id

JSON_FIX_ATTEMPTS = 2      # continue-with-correction attempts for malformed JSON

# Which module drives which coding agent. All expose the same three names —
# run(), resolve_model(), ToolCallTracker — so everything below this line is
# written once and works either way.
INTERFACES = {
    "pi": agent_pi,
    "claude_code": agent_cc,
    "grok": agent_grok,
    "agy": agent_agy,
}


def interface(agent: AgentConfig):
    """The coding-agent module this agent runs on."""
    return INTERFACES[agent.coding_agent]


class GateFailure(RuntimeError):
    pass


# ── config ───────────────────────────────────────────────────────────────────

ROSTERS_PATH = "adws/adw_sssf_config/rosters.yaml"
ROSTER_MARKER = "adws/adw_sssf_config/.roster"
ROSTER_KEYS = ("coding_agent", "model", "thinking")


def infer_coding_agent(model: Optional[str]) -> Optional[str]:
    """Which interface a model id belongs on, when the agent did not set one.

    The prefix is the route: ``openrouter/`` is cash through pi, a bare
    ``grok-*`` (or ``xai/grok-*``) is the grok CLI, a bare ``gemini-*``
    (or ``agy/gemini-*``) is agy, and everything else stays on Claude Code.
    ``openrouter/x-ai/grok-4.5`` therefore bills OpenRouter; ``grok-4.5``
    spends the Grok subscription. That is the mix-and-match: change the
    model, keep or omit ``coding_agent``. An explicit ``coding_agent:`` on
    the agent (or a roster overlay) still wins — this only fills a gap.
    """
    if not model:
        return None
    name = str(model).strip()
    if not name:
        return None
    if name.startswith("openrouter/"):
        return "pi"
    if "/" in name:
        prefix, _, bare = name.partition("/")
        if prefix == "xai" and bare.startswith("grok"):
            return "grok"
        if prefix == "agy" and bare.startswith("gemini-"):
            return "agy"
        # vendor/model without openrouter/ is not a subscription id — leave
        # the inherited coding_agent in place so validate() names the miss.
        return None
    if name.startswith("grok"):
        return "grok"
    if name.startswith("gemini-"):
        return "agy"
    return "claude_code"


def load_rosters(path: str = ROSTERS_PATH) -> dict:
    """The tier overlays, or {} when the repo has no rosters.yaml."""
    if not Path(path).is_file():
        return {}
    return (yaml.safe_load(Path(path).read_text()) or {}).get("rosters", {}) or {}


def active_roster(explicit: Optional[str] = None,
                  marker: str = ROSTER_MARKER) -> Optional[str]:
    """Which tier to apply: the flag, else the marker file, else none.

    None means "use sssf.config.yaml exactly as written" — the pre-roster
    behaviour, and what an unconfigured repo gets.
    """
    if explicit:
        return explicit
    p = Path(marker)
    if p.is_file():
        return p.read_text().strip() or None
    return None


def load_config(path: str = "adws/adw_sssf_config/sssf.config.yaml",
                roster: Optional[str] = None) -> SSSFConfig:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    defaults = raw.get("defaults", {}) or {}
    agents_list = raw.get("agents", []) or []
    # A coding_agent written on the agent itself is a chosen route. An
    # inherited defaults.coding_agent is not — mix-and-match is "change the
    # model, the route follows", and that only works if we can replace the
    # inherited value after we know the model.
    explicit_route = {a.get("name") for a in agents_list if "coding_agent" in a}
    for agent in agents_list:
        for key in ("coding_agent", "model", "thinking", "color", "tools", "writes"):
            if key in defaults:
                agent.setdefault(key, defaults[key])
        agent.setdefault("harness_engineering", defaults.get("harness_engineering", []))

    # The roster overlay lands AFTER defaults, so a tier's model beats an
    # inherited one, and BEFORE SSSFConfig(**raw), so validate() sees the
    # models that will actually run. Structure — prompts, tools, writes —
    # is never touched: a tier only says who runs each agent.
    overlay: dict = {}
    name = active_roster(roster)
    if name:
        rosters = load_rosters()
        if name not in rosters:
            raise SystemExit(f"roster {name!r} is not defined in {ROSTERS_PATH} — "
                             f"available: {sorted(rosters) or '(none)'}")
        overlay = (rosters[name] or {}).get("agents", {}) or {}
        known = {a.get("name") for a in agents_list}
        for missing in sorted(set(overlay) - known):
            raise SystemExit(f"roster {name!r} assigns agent {missing!r}, which is not "
                             f"in {path} — available: {sorted(known)}")
        for agent in agents_list:
            for key, value in (overlay.get(agent.get("name")) or {}).items():
                if key not in ROSTER_KEYS:
                    raise SystemExit(f"roster {name!r} sets {key!r} on {agent['name']!r}; "
                                     f"a roster may only set {', '.join(ROSTER_KEYS)}")
                agent[key] = value

    for agent in agents_list:
        roster_route = "coding_agent" in (overlay.get(agent.get("name")) or {})
        if agent.get("name") in explicit_route or roster_route:
            continue
        inferred = infer_coding_agent(agent.get("model"))
        if inferred:
            agent["coding_agent"] = inferred

    return SSSFConfig(**raw)


def resolve(cfg: SSSFConfig, name: str) -> AgentConfig:
    for agent in cfg.agents:
        if agent.name == name:
            return agent
    raise SystemExit(f"agent {name!r} is not defined in the config — "
                     f"available: {[a.name for a in cfg.agents]}")


def validate(cfg: SSSFConfig, required: list[str]) -> None:
    """Fail fast: every required name must resolve to a usable agent."""
    problems = []
    for name in required:
        try:
            agent = resolve(cfg, name)
        except SystemExit as e:
            problems.append(str(e))
            continue
        if agent.coding_agent not in INTERFACES:
            problems.append(f"agent {name!r}: coding_agent {agent.coding_agent!r} "
                            f"is not a known interface — "
                            f"available: {sorted(INTERFACES)}")
            continue          # every check below needs an interface to ask
        for label, ref in (("system", agent.prompt_engineering.system),
                           ("user", agent.prompt_engineering.user)):
            if not Path(ref).is_file():
                problems.append(f"agent {name!r}: {label} prompt not found: {ref}")
        try:
            interface(agent).resolve_model(agent.model)
        except ValueError as e:
            problems.append(f"agent {name!r}: {e}")
    if problems:
        raise SystemExit("config validation failed:\n- " + "\n- ".join(problems))


# ── execution ────────────────────────────────────────────────────────────────

def execute(run, phase: Phase, call: AgentCall) -> EnvelopeBase:
    """One agent call: render prompts -> agent run -> typed parse -> gates -> envelope."""
    stored = getattr(run, "completed_envelopes", {}).get(phase.params.name)
    if stored is not None:
        # This phase already finished in an earlier invocation of this same
        # adw-id. Re-running the agent would pay for an answer we already
        # have, and would probably give a different one -- which is worse.
        fingerprint = _prompt_fingerprint(call.prompt)
        try:
            recorded = run.tracer.prompt_fingerprints(run.adw_id).get(phase.params.name)
        except Exception:
            recorded = None

        if recorded and recorded != fingerprint:
            run.console.note(f"{phase.params.name}: the prompt changed since the last invocation — "
                             f"running the agent instead of replaying")
            run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                         type="log", name="prompt_changed",
                                         payload={"phase": phase.params.name,
                                                  "was": recorded,
                                                  "now": fingerprint}))
        else:
            try:
                envelope = call.output_type.model_validate_json(stored)
            except Exception as error:  # noqa: BLE001 -- a bad checkpoint must never be fatal
                run.console.note(f"{phase.params.name}: stored envelope did not match "
                                 f"{call.output_type.__name__} ({error}) -- running the agent instead")
            else:
                run.console.note(f"{phase.params.name}: replayed from the previous "
                                 f"invocation (no agent call, no spend)")
                run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                             type="log", name="replayed",
                                             payload={"phase": phase.params.name}))
                return envelope

    agent = resolve(run.cfg, phase.params.owner)
    coding_agent = interface(agent)
    agent_dir = run.session_dir / agent.name
    agent_dir.mkdir(parents=True, exist_ok=True)

    variables = {
        "prompt": call.prompt,
        "previous_envelope": call.previous.model_dump_json(indent=2) if call.previous else "(none)",
        "context_handoff_dir": str(run.context_handoff_dir),
    }
    system_text = prompts.render(agent.prompt_engineering.system, variables)
    user_text = prompts.render(agent.prompt_engineering.user, variables)
    prompts.save(agent_dir / "prompts", "system.md", system_text)
    prompts.save(agent_dir / "prompts", "user.md", user_text)

    session_id = _agent_session_id(run, agent)
    run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                 type="agent_start", name=agent.name,
                                 payload={"model": agent.model, "thinking": agent.thinking,
                                          "color": agent.color,
                                          "session_id": session_id,
                                          "coding_agent": agent.coding_agent,
                                          "purpose": agent.purpose,
                                          "tools": agent.tools,  # None = all tools
                                          "harness_engineering": agent.harness_engineering}))
    run.console.agent_started(agent.name, agent.model, session_id)

    # Parse retries and gate corrections re-enter the SAME coding-agent session,
    # so the last send is the one whose context occupancy is current — while
    # spend is the opposite: every send costs, so usage accumulates across all.
    latest: PiResult | None = None
    spent = UsageBreakdown()

    def send(prompt_text: str) -> PiResult:
        nonlocal latest
        request = PiRequest(
            prompt=prompt_text,
            system_prompt=system_text,
            model=agent.model,
            thinking=agent.thinking,
            session_id=session_id,
            # absolute: these are read by the coding-agent subprocess, which
            # runs in repo_root
            session_dir=str((agent_dir / "agent_sessions").resolve()),
            raw_output_path=str((agent_dir / "raw_output.jsonl").resolve()),
            tools=agent.tools,
            extensions=agent.harness_engineering,
            cwd=str(run.repo_root),
            # The same protected paths enforce() checks below, handed to the
            # coding agent up front so a CLI that can refuse the tool call
            # does. Interfaces with no such flag ignore it.
            deny_writes=permissions.deny_globs(agent, run.cfg),
        )
        def _notify(message: str, sleep_seconds: float, detail: str) -> None:
            run.console.note(message)
            run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                         type="log", name="rate_limited",
                                         payload={"sleep_seconds": sleep_seconds,
                                                  "detail": detail}))

        # Every send here -- the first prompt, a JSON retry, a gate correction
        # -- is wrapped so a rate limit sleeps and re-sends the SAME request
        # rather than spending one of the JSON-retry or gate-correction
        # attempts on something that was never the agent's fault.
        result = control.with_rate_limit_retries(
            lambda: coding_agent.run(
                request,
                on_event=_event_forwarder(run, phase, agent.name, coding_agent),
                on_spawn=lambda pid: run.tracer.process_start(
                    run.adw_id, "agent", agent.name, pid,
                    f"{agent.coding_agent} {agent.name} {agent.model}"),
                on_exit=lambda pid: run.tracer.process_end(run.adw_id, pid)),
            notify=_notify)
        run.add_usage(result.tokens, result.cost)
        spent.merge(result.usage)
        latest = result
        return result

    # What the tree looked like before this agent got its hands on it. Every
    # send in this phase — first prompt, JSON retries, gate corrections — is
    # measured against this one baseline.
    tree_before = permissions.snapshot(run)

    result = send(user_text)
    envelope, attempt = _parse_with_retries(run, phase, call, result, send)

    # claim gates — violations flow back into the SAME session as corrections
    for gate_attempt in range(1, max(1, phase.params.retries + 1) + 1):
        violations = []
        for gate in call.gates:
            report = _as_report(gate(envelope, run))
            found = report.violations
            run.tracer.gate_row(phase, gate.__name__, report, gate_attempt)
            run.tracer.event(EventRecord(
                adw_id=run.adw_id, phase_id=phase.phase_id,
                type="gate_fail" if found else "gate_pass", name=gate.__name__,
                payload={"attempt": gate_attempt, "violations": found,
                         "checks": [c.model_dump() for c in report.checks]}))
            run.console.gate_result(gate.__name__, report)
            violations.extend(found)
        if not violations:
            break
        if gate_attempt > phase.params.retries:
            raise GateFailure(f"{agent.name} failed gates after {gate_attempt} attempt(s):\n- "
                              + "\n- ".join(violations))
        phase.attempt = gate_attempt
        run.console.retry(agent.name, gate_attempt, phase.params.retries,
                          f"{len(violations)} gate violation(s)")
        correction = ("Your previous response failed validation:\n- "
                      + "\n- ".join(violations)
                      + "\n\nFix these problems, then re-emit ONLY your Report JSON.")
        result = send(correction)
        envelope, attempt = _parse_with_retries(run, phase, call, result, send)

    # Permission is checked after every send is done, and before the envelope is
    # accepted: an agent does not get to report success on a phase in which it
    # wrote somewhere it was not allowed to.
    try:
        touched = permissions.enforce(run, phase, agent, tree_before)
    except permissions.PermissionBreach as breach:
        run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                     type="error", name="permission_breach",
                                     payload={"agent": agent.name, "error": str(breach),
                                              "writes": agent.writes,
                                              "protected_files": run.cfg.defaults.protected_files}))
        raise
    if touched:
        run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                     type="log", name="paths_touched",
                                     payload={"agent": agent.name, "paths": touched}))

    _persist_envelope(run, phase, agent.name, call, envelope, attempt, valid=True)
    run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                 type="log", name="phase_prompt",
                                 payload={"phase": phase.params.name,
                                          "fingerprint": _prompt_fingerprint(call.prompt)}))
    run.console.envelope_summary(envelope)
    context = latest or result
    run.tracer.agent_session_row(run.adw_id, agent, session_id,
                                 context_tokens=context.context_tokens,
                                 context_window=context.context_window)
    run.save_agent_map(agent.name, {"session_id": session_id, "model": agent.model,
                                    "coding_agent": agent.coding_agent})
    run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                 type="handoff", name=agent.name,
                                 payload={"artifacts": envelope.artifacts,
                                          "summary": envelope.summary}))
    run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                 type="agent_end", name=agent.name,
                                 # Phase totals, not the last send's: a retried
                                 # phase paid for every attempt.
                                 tokens=spent.total_tokens,
                                 payload={"cost": spent.total_cost,
                                          "usage": spent.model_dump(),
                                          "context_tokens": context.context_tokens,
                                          "context_window": context.context_window}))
    run.console.agent_finished(agent.name, spent.total_tokens, spent.total_cost)
    if envelope.status != "success":
        raise RuntimeError(f"{agent.name} reported status={envelope.status!r}: {envelope.summary}")
    return envelope


# ── internals ────────────────────────────────────────────────────────────────

def _prompt_fingerprint(prompt: str) -> str:
    """Stable id of the ask a phase was given. Same prompt -> same hash."""
    return hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:16]

def _as_report(result) -> GateReport:
    """Accept a GateReport, or a legacy gate that returned a violations list."""
    if isinstance(result, GateReport):
        return result
    return GateReport(checks=[GateCheck(item=str(v), ok=False) for v in (result or [])])


def _agent_session_id(run, agent: AgentConfig) -> str:
    entry = run.agent_map.get(agent.name)
    if entry and entry.get("model") == agent.model:
        return entry["session_id"]           # rejoin the existing context window
    return f"sssf-{run.adw_id}-{agent.name}-{new_id(4)}"


def _event_forwarder(run, phase: Phase, agent_name: str, coding_agent):
    """One tool_call event per real tool call, with its exact args and result.

    The tracker comes from the coding agent because only it knows that agent's
    event shapes — pi announces a call on `tool_execution_start`, Claude Code on
    an assistant `tool_use` block. Both hand back the same record, so everything
    downstream of `observe()` is written once.
    """
    tracker = coding_agent.ToolCallTracker()

    def forward(event: dict) -> None:
        record = tracker.observe(event)
        if record is None:
            return
        # The call's span rides the columns; duration_ms stays in the payload as
        # pi's own authoritative number.
        run.tracer.event(EventRecord(adw_id=run.adw_id, phase_id=phase.phase_id,
                                     type="tool_call", name=record.pop("label"),
                                     started_at=record.pop("started_at", None),
                                     ended_at=record.pop("ended_at", None),
                                     payload={**record, "agent": agent_name}))
    return forward


def _extract_json(text: str) -> dict:
    candidate = text
    if "```" in text:
        for block in text.split("```")[1::2]:
            block = block.removeprefix("json").strip()
            if block.startswith("{"):
                candidate = block
                break
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in the response")
    return json.loads(candidate[start:end + 1])


def _parse_with_retries(run, phase: Phase, call: AgentCall, result, send):
    """Parse the final response against the declared output type; on failure,
    continue the SAME session with a correction (bounded)."""
    for attempt in range(1, JSON_FIX_ATTEMPTS + 2):
        try:
            payload = _extract_json(result.text)
            return call.output_type.model_validate(payload), attempt
        except Exception as error:
            _persist_envelope(run, phase, phase.params.owner, call, None, attempt,
                              valid=False, raw=result.text)
            if attempt > JSON_FIX_ATTEMPTS:
                raise RuntimeError(
                    f"{phase.params.owner} never produced valid "
                    f"{call.output_type.__name__} JSON: {error}") from error
            run.console.retry(phase.params.owner, attempt, JSON_FIX_ATTEMPTS,
                              f"invalid {call.output_type.__name__} JSON: {error}")
            fields = ", ".join(call.output_type.model_fields.keys())
            result = send(
                f"Your response was not valid JSON for the required structure "
                f"({error}). Respond again with ONLY a JSON object with these "
                f"fields: {fields}. No prose, no code fences.")


def _persist_envelope(run, phase: Phase, agent_name: str, call: AgentCall,
                      envelope: Optional[EnvelopeBase], attempt: int,
                      valid: bool, raw: str = "") -> None:
    payload_json = envelope.model_dump_json(indent=2) if envelope else json.dumps({"raw": raw[-2000:]})
    run.tracer.envelope_row(phase, agent_name, call.output_type.__name__,
                            payload_json, valid, attempt)
    if envelope:
        record = {"agent_name": agent_name, "purpose": resolve(run.cfg, agent_name).purpose,
                  "output_type": call.output_type.__name__, "attempt": attempt,
                  **envelope.model_dump()}
        (run.session_dir / agent_name / "envelope.json").write_text(json.dumps(record, indent=2))

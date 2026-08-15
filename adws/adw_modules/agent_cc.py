"""Claude Code coding agent interface — claudeSSSF's reason to exist.

Runs `claude -p --output-format stream-json` and tails its JSONL stdout line by
line, forwarding each event to a callback WHILE the agent works — the same
streaming contract `agent_pi` provides, so nothing upstream of this file needs
to know which coding agent ran.

Two things differ from pi and both are load-bearing:

1. **Sessions are UUIDs.** `--session-id` accepts a UUID and only for a NEW
   session; continuing one is `--resume <uuid>`. SSSF session keys are readable
   strings (`sssf-e852c05c-planner-0450`), so we hash the key into a stable
   UUIDv5 and remember which keys we have already created. Same key = same
   context window, which is the contract `execute()` relies on for its JSON
   retries and gate corrections.

2. **Billing is a subscription, not tokens.** `total_cost_usd` still arrives on
   the result event, but it is the notional API price of the turn, not money
   leaving an account. It is recorded so the trace stays comparable with pi
   runs; read it as "what this would have cost on the API".

3. **Rate limits are a first-class error.** The terminal `result` event is
   classified (structured fields first, string matching only as fallback --
   see adw_modules/control.py) before its returncode is trusted. A rate limit
   raises `RateLimited` with a sleep duration, so the caller can wait and send
   the identical request again rather than burning a JSON-retry or a gate
   correction on it. Any other terminal error this adapter does not recognise
   raises `UpstreamError` and is never retried -- an unfamiliar shape is more
   likely a changed CLI than a blip.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from .control import RateLimited, UpstreamError, classify_result_event, fake_rate_limit_due, reset_delay
from .data_types import PiRequest, PiResult
from .utils import now_iso, operator_env

# Where npm hides the real binary behind the shim it puts on PATH.
NPM_BINARY = Path("node_modules/@anthropic-ai/claude-code/bin")


def _resolve_cli() -> str:
    """Find the Claude Code executable, preferring the native binary.

    On Windows, npm puts `claude.CMD` on PATH and that is what `which` finds —
    but a .CMD runs through cmd.exe, and cmd.exe truncates argv at the first
    newline. Our `--system-prompt` is a whole rendered Markdown file, so it
    would arrive as its first line and the agent would run with almost no
    instructions: a silent, plausible-looking wrong answer rather than a crash.
    The shim sits next to a real `claude.exe`; use that instead.

    Set CC_PATH to override, on any platform.
    """
    override = os.environ.get("CC_PATH")
    if override:
        return override
    found = shutil.which("claude")
    if not found:
        return "claude"                       # let the OS produce the error
    path = Path(found)
    if path.suffix.lower() in (".cmd", ".bat", ".ps1"):
        native = path.parent / NPM_BINARY / "claude.exe"
        if native.is_file():
            return str(native)
    return str(path)


CC_PATH = _resolve_cli()

# SSSF polices the repo itself: `writes:` per agent and `protected_files` in
# defaults are enforced by permissions.py after every call, and unauthorized
# changes are rolled back. Prompting the operator per tool call would stall a
# headless run forever, so the agent acts freely and code disposes afterwards.
# Override for a more cautious posture: CC_PERMISSION_MODE=acceptEdits.
PERMISSION_MODE = os.environ.get("CC_PERMISSION_MODE", "bypassPermissions")

# Stable namespace for turning an SSSF session key into the UUID the CLI wants.
# Fixed forever: change it and every existing session key maps somewhere new,
# silently orphaning the context windows agents are meant to resume into.
SESSION_NAMESPACE = uuid.UUID("6f9d4a1c-3b7e-5d28-9a04-1e8c7b2f0d63")

RESULT_SNIPPET_CHARS = 20_000   # tool output rides along whole; clip only guards pathological cases
ARG_VALUE_CHARS = 20_000        # args too — the UI scrolls, it must not be handed cut-off data
LABEL_CHARS = 80                # "Bash: <command>" shown as the event name

# The arg that identifies a call at a glance, in the order Claude Code's tools
# tend to use. `command`/`file_path`/`pattern` cover Bash/Edit/Grep respectively.
PRIMARY_ARGS = ("command", "file_path", "path", "pattern", "query", "url", "prompt")

# The tools a roster `tools:` list is allowed to grant or withhold. Anything an
# agent does not name is passed as --disallowedTools, because that is the only
# flag that RESTRICTS: allow rules "have no effect in bypassPermissions because
# everything else is already approved" (permission-modes docs), while deny
# rules apply in every mode. Without the deny list, pi's hard `--tools` filter
# would arrive here as a no-op and every CC agent would run with everything.
DENYABLE_TOOLS = {"Read", "Grep", "Glob", "Bash", "Edit", "Write",
                  "NotebookEdit", "Task", "WebFetch", "WebSearch",
                  "SendMessage", "ListAgents"}

# `thinking` in the config is pi's vocabulary; Claude Code spends the same
# dimension through --effort. low/medium/high exist in both, so only the ends
# need naming, and the extra rungs are reachable by writing them in the config.
EFFORT = {"low": "low", "medium": "medium", "high": "high",
          "xhigh": "xhigh", "max": "max", "none": "low", "off": "low"}

# Aliases the CLI resolves itself, plus the canonical IDs behind them. Used to
# fail a bad model at validate() time rather than three phases into a run.
KNOWN_MODELS = {
    "opus", "sonnet", "haiku", "fable",
    "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
    "claude-sonnet-5", "claude-sonnet-4-6",
    "claude-haiku-4-5", "claude-fable-5",
}

# Fallback ceilings, used only until the run's own result event reports the real
# one via modelUsage. Keyed by the substring that identifies the family.
CONTEXT_WINDOWS = (("haiku", 200_000), ("fable", 1_000_000),
                   ("sonnet", 1_000_000), ("opus", 1_000_000))


def resolve_model(pattern: str) -> tuple[str, str]:
    """Validate a model pattern, returning ``(provider, model_id)``.

    Claude Code has no `--list-models`, so there is no catalog to match
    against — the check is that the pattern is an alias the CLI knows or an
    explicit `claude-*` id. Provider is always `anthropic`: that is the whole
    point of this interface.
    """
    name = pattern.split("/")[-1].strip()      # tolerate `anthropic/sonnet`
    if name in KNOWN_MODELS or name.startswith("claude-"):
        return "anthropic", name
    raise ValueError(
        f"model {pattern!r} is not a Claude Code model — use an alias "
        f"({', '.join(sorted(a for a in KNOWN_MODELS if '-' not in a))}) "
        f"or an explicit claude-* id")


def context_window(provider: str, model_id: str) -> int:
    """Best-known ceiling for a model, before the run reports its own."""
    for needle, window in CONTEXT_WINDOWS:
        if needle in model_id:
            return window
    return 0


def session_uuid(session_key: str) -> str:
    """Map an SSSF session key onto the UUID the CLI requires, deterministically."""
    return str(uuid.uuid5(SESSION_NAMESPACE, session_key))


def _text_of(message: dict) -> str:
    """Join the text blocks of a Claude Code message."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content or []
                   if isinstance(part, dict) and part.get("type") == "text")


def _result_text(block: dict) -> str:
    """Flatten a tool_result's content, which is a string or a block list."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content
                       if isinstance(part, dict) and part.get("type") == "text")
    return ""


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _label(tool: str, args: dict) -> str:
    """One-line human name for a tool call: `Bash: ls -la src`."""
    value = next((args[key] for key in PRIMARY_ARGS
                  if isinstance(args.get(key), str) and args[key].strip()), "")
    if not value:
        value = next((v for v in args.values() if isinstance(v, str) and v.strip()), "")
    value = " ".join(str(value).split())
    return f"{tool}: {_clip(value, LABEL_CHARS)}" if value else tool


def _pi_shaped_usage(usage: dict) -> dict:
    """Translate Claude Code's usage object into the shape UsageBreakdown reads.

    UsageBreakdown.add_turn speaks pi's vocabulary. Rather than teach it a
    second dialect — and have every consumer of the trace learn which run wrote
    which field — the translation happens here, once, at the boundary.

    Per-turn cost is deliberately absent: Claude Code prices the whole run on
    its result event, not each turn, so cost is folded in there instead.
    """
    return {
        "input": usage.get("input_tokens") or 0,
        "output": usage.get("output_tokens") or 0,
        "cacheRead": usage.get("cache_read_input_tokens") or 0,
        "cacheWrite": usage.get("cache_creation_input_tokens") or 0,
    }


def _context_tokens(usage: dict) -> int:
    """Tokens occupying the window after a turn.

    Cache reads count — cached prompt is still prompt, and it is still what the
    model has to fit. Mirrors the same reading agent_pi takes so the
    visualizer's context bar means one thing across both interfaces.
    """
    return int(sum(usage.get(part) or 0 for part in
                   ("input_tokens", "output_tokens",
                    "cache_read_input_tokens", "cache_creation_input_tokens")))


class ToolCallTracker:
    """Folds Claude Code's tool stream into ONE normalized record per call.

    Claude Code announces a call as a `tool_use` block on an assistant message,
    then reports it as a `tool_result` block on the following user message. Only
    the result knows whether it worked, so that is where a record is emitted —
    one trace event per real tool call, the moment it returns.

    Emits the same record shape as agent_pi.ToolCallTracker. The tracer writes
    `started_at`/`ended_at` to columns, so a Claude Code run and a pi run lay
    out identically on the visualizer's time axis.
    """

    def __init__(self) -> None:
        self._open: dict[str, dict] = {}

    def observe(self, event: dict) -> Optional[dict]:
        """Returns the record for a finished tool call, else None."""
        etype = event.get("type")

        if etype == "assistant":
            for block in event.get("message", {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self._announce(block.get("id"), block.get("name"),
                                   block.get("input"))
            return None

        if etype != "user":
            return None

        # A user event carries at most one tool_result in practice, but the
        # content is a list and nothing promises that, so take the first and
        # let a second arrive on its own event.
        for block in event.get("message", {}).get("content", []) or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            call_id = str(block.get("tool_use_id") or "")
            opened = self._open.pop(call_id, {})
            tool = str(opened.get("tool") or "tool")
            args = opened.get("args") or {}
            record = {
                "tool": tool,
                "tool_call_id": call_id,
                "args": {key: _clip(value, ARG_VALUE_CHARS) if isinstance(value, str) else value
                         for key, value in args.items()},
                "ok": not block.get("is_error", False),
                "label": _label(tool, args),
            }
            result_text = _result_text(block)
            if result_text:
                record["result_snippet"] = _clip(result_text, RESULT_SNIPPET_CHARS)
            record["ended_at"] = now_iso()
            if opened.get("clock"):
                record["duration_ms"] = int((time.monotonic() - opened["clock"]) * 1000)
            if opened.get("started_at"):
                record["started_at"] = opened["started_at"]
            return record
        return None

    def _announce(self, call_id, tool, args) -> None:
        """First sighting starts the clock; a later sighting only fills gaps."""
        if not call_id:
            return
        known = self._open.get(str(call_id), {})
        self._open[str(call_id)] = {
            "tool": tool or known.get("tool", ""),
            "args": args or known.get("args", {}),
            "started_at": known.get("started_at") or now_iso(),   # wall clock, for the row
            "clock": known.get("clock") or time.monotonic(),      # monotonic, for duration
        }


def _session_ledger(session_dir: Path) -> Path:
    """Where we remember which session keys have already been created.

    The CLI rejects `--session-id` for a session that exists and `--resume` for
    one that does not, so the interface has to know which call it is making.
    A file on disk survives the process boundary between phases; an in-memory
    set would not, and every phase is its own process.
    """
    return session_dir / "created_sessions.json"


def _is_new_session(session_dir: Path, key: str) -> bool:
    ledger = _session_ledger(session_dir)
    try:
        known = set(json.loads(ledger.read_text()))
    except (OSError, ValueError):
        known = set()
    return key not in known


def _record_session(session_dir: Path, key: str) -> None:
    ledger = _session_ledger(session_dir)
    try:
        known = set(json.loads(ledger.read_text()))
    except (OSError, ValueError):
        known = set()
    known.add(key)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(sorted(known), indent=2))


def run(request: PiRequest, on_event: Optional[Callable[[dict], None]] = None,
        on_spawn: Optional[Callable[[int], None]] = None,
        on_exit: Optional[Callable[[int], None]] = None) -> PiResult:
    """Run one non-interactive Claude Code turn.

    `on_spawn(pid)` and `on_exit(pid)` bracket the child process so the caller
    can record it as killable — a hung coding agent is otherwise a pid you have
    to hunt for in `ps` while the run sits there.
    """
    faked = fake_rate_limit_due()
    if faked is not None:
        # Deliberately before Popen: a drill must not cost a call, need a
        # network, or depend on a box being logged in.
        seconds, why = reset_delay(faked)
        raise RateLimited(f"(fake) rate limited — {why}", seconds, faked)

    _, model_id = resolve_model(request.model)
    session_dir = Path(request.session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    cc_session = session_uuid(request.session_id)
    starting = _is_new_session(session_dir, request.session_id)

    cmd = [
        CC_PATH, "-p",
        "--output-format", "stream-json", "--verbose",
        "--model", model_id,
        "--effort", EFFORT.get(request.thinking, request.thinking),
        "--permission-mode", PERMISSION_MODE,
        "--system-prompt", request.system_prompt,
    ]
    # Creating and continuing are different flags for the same idea. Getting
    # this backwards is not a soft failure: --session-id on a live session
    # errors out, and --resume on a missing one starts from nothing, which
    # looks like an agent that forgot the plan it just wrote.
    cmd += (["--session-id", cc_session] if starting else ["--resume", cc_session])
    # --allowedTools/--disallowedTools are variadic: they consume every
    # following argument until the next flag. A prompt appended after them is
    # silently eaten as another tool name, and the CLI then dies claiming no
    # prompt was given. Keep them last in argv and send the prompt through
    # stdin, which the CLI documents as the equal alternative.
    #
    # Both flags are needed to reproduce pi's `--tools` semantics. The deny
    # list is the enforcing half — under bypassPermissions an allow list
    # approves nothing that was not already approved. The allow list still
    # matters the moment the operator flips CC_PERMISSION_MODE to something
    # stricter, so it is kept.
    if request.tools:
        cmd += ["--allowedTools", ",".join(request.tools)]
        denied = sorted(DENYABLE_TOOLS - set(request.tools))
        if denied:
            cmd += ["--disallowedTools", ",".join(denied)]

    raw_path = Path(request.raw_output_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    result = PiResult(session_id=request.session_id,
                      context_window=context_window("anthropic", model_id))

    # encoding is pinned because the CLI's JSONL is UTF-8 no matter what the
    # OS thinks. Without it, Windows decodes these pipes with the locale code
    # page (cp1252) unless PYTHONUTF8=1 happens to be set machine-wide — emoji
    # in agent output becomes mojibake in the trace, and a few byte values
    # crash the decoder mid-run. errors="replace" keeps a bad byte from
    # killing an otherwise healthy stream.
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace",
                               bufsize=1, cwd=request.cwd,
                               env=operator_env())
    if on_spawn:
        on_spawn(process.pid)

    # Write the prompt and close immediately. Closing is the part that matters:
    # the CLI reads stdin to EOF before it starts work, so a stdin left open is
    # a run that hangs at 0% CPU with an empty raw_output.jsonl. The prompt is
    # small and the pipe buffer swallows it whole, so this cannot deadlock
    # against the stdout reader below.
    assert process.stdin is not None
    process.stdin.write(request.prompt)
    process.stdin.close()

    terminal: dict | None = None   # the last `result` event seen, for classification below
    with raw_path.open("a") as raw:
        assert process.stdout is not None
        for line in process.stdout:
            raw.write(line)
            raw.flush()                      # events land on disk as they happen
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "assistant":
                message = event.get("message", {}) or {}
                usage = message.get("usage", {}) or {}
                turn = _context_tokens(usage)
                result.tokens += turn
                result.usage.add_turn(_pi_shaped_usage(usage), turn)
                if turn:
                    result.context_tokens = turn
            elif etype == "result":
                # The result event is authoritative for the answer and the
                # price: `result` is the final assistant text with subagent
                # chatter already excluded, and total_cost_usd covers every
                # turn including the ones this loop never saw usage for.
                if event.get("result"):
                    result.text = str(event["result"])
                cost = float(event.get("total_cost_usd") or 0.0)
                result.cost += cost
                result.usage.total_cost += cost
                window = _reported_window(event, model_id)
                if window:
                    result.context_window = window
                terminal = event

            if on_event:
                on_event(event)

    stderr = process.stderr.read() if process.stderr else ""
    result.returncode = process.wait()
    if on_exit:
        on_exit(process.pid)

    # Only mark the session created once the CLI has actually made it. Recording
    # it up front would send the next call to --resume a session that a crashed
    # start never wrote, turning one failure into every failure after it.
    if starting and result.returncode == 0:
        _record_session(session_dir, request.session_id)

    if terminal is not None:
        verdict, detail = classify_result_event(terminal)
        if verdict == "rate_limit":
            seconds, why = reset_delay(terminal)
            raise RateLimited(f"rate limited — {detail}; {why}", seconds, terminal)
        if verdict == "upstream":
            raise UpstreamError(
                "Claude Code ended with an error this adapter does not "
                "recognise, so it is NOT being retried — an unfamiliar error "
                "is more likely a changed CLI than a blip.\n"
                f"  the CLI said: {detail}\n"
                "  what to do: read the last lines of the raw stream at\n"
                f"    {raw_path}\n"
                "  if it turns out to be a rate limit, add its shape to "
                "RATE_LIMIT_TYPES / RATE_LIMIT_MARKERS in adw_modules/control.py")

    if result.returncode != 0 and not result.text:
        raise RuntimeError(f"claude exited {result.returncode}: {stderr.strip()[-800:]}")
    return result


def _reported_window(result_event: dict, model_id: str) -> int:
    """The context ceiling Claude Code itself reports for the model that ran.

    `modelUsage` is keyed by dated model id (`claude-sonnet-5`,
    `claude-haiku-4-5-20251001`), so an alias like `sonnet` never matches by
    equality — match on the canonical name each entry carries, and ignore the
    small-model entries the CLI uses for its own housekeeping.
    """
    usage = result_event.get("modelUsage") or {}
    for key, entry in usage.items():
        canonical = str(entry.get("canonicalModel") or key)
        if model_id in canonical or canonical in model_id:
            return int(entry.get("contextWindow") or 0)
    return 0

"""agy coding agent interface — Google's Gemini CLI, on free Gemini quota.

Runs `agy -p @<file> --output-format stream-json` and tails its JSONL stdout,
forwarding each event to a callback WHILE the agent works — the same streaming
contract every other interface in this package provides.

agy speaks its OWN dialect, unrelated to Claude Code's:

    {"event":"init","conversation_id":"<uuid>", "init":{...}}
    {"event":"step_update","step_update":{"step_type":..., "state":..., "usage":{...}}}
    {"event":"result","result":{"status":"SUCCESS","response":"...","usage":{...}}}

Five things are load-bearing here:

1. **The CLI assigns the session id.** There is no --session-id; a new
   conversation's id arrives on the init event and continuing it is
   `--conversation <id>`. So the ledger maps SSSF session keys to the
   conversation ids the CLI minted — same contract as the other interfaces
   (same key = same context window), different bookkeeping. The ledger
   follows the CLI every call, not just the first: agy answers a
   `--conversation` it no longer has by warning and opening a fresh one under
   its own id, and a ledger left pointing at the rejected id would start a new
   context window on every phase for the rest of the run (issue #37).

2. **There is no system-prompt flag.** The first send of a session folds the
   system prompt into the prompt file above a divider; continuations send only
   the new prompt, because the conversation already holds the identity. This is
   a real weakening versus the API-backed interfaces — the "system" text is
   just early user text — which is why the format demand also lives at the
   *end* of SSSF user prompts.

3. **The prompt goes over as `@<file>`.** agy ignores stdin in print mode, and
   argv on Windows caps at 32,767 chars. When the session dir sits outside the
   repo, `--add-dir` grants it so the file is readable — but NEVER when it is
   inside, because agy treats an added dir as its working root and shell
   commands then run there instead of in the repo (measured: a probe's
   `git log` hit "not a git repository" until the flag was dropped). With the
   default in-repo `data_dir` the flag is never sent.

4. **`--print-timeout` defaults to 5 minutes.** A builder phase runs far
   longer; the flag is raised to hours or every long phase dies looking like a
   hang.

5. **The `schedule` tool never fires in print mode.** An agent that calls it
   waits forever, silently. The stream is watched for silence
   (AGY_IDLE_TIMEOUT_SECONDS, default 10 min): a stalled child is killed and
   the turn re-sent, and the builder prompt forbids the tool outright.

6. **Cost is zero by construction.** agy draws on Gemini subscription quota;
   there is no per-token bill and the CLI reports no cost. Traces show tokens
   but 0.0 dollars — that is correct, not missing data.

Tool steps arrive as step_update events with `step_type: "tool"`, a
`tool_name`, and a `tool_info` object carrying `parameters` (the call's args,
CamelCase keys like CommandLine / AbsolutePath) and, on DONE, `output`. The
tracker folds the ACTIVE/DONE pair into one normalized record — the same
shape the other interfaces' trackers emit.
"""

from __future__ import annotations

import json
import os
import shutil
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .control import (RateLimited, UpstreamError, capture_limit_event, capture_notice,
                      fake_rate_limit_due, reset_delay)
from .data_types import PiRequest, PiResult
from .utils import now_iso, operator_env


def _resolve_cli() -> str:
    """Find the agy executable. Set AGY_PATH to override."""
    override = os.environ.get("AGY_PATH")
    if override:
        return override
    return shutil.which("agy") or "agy"      # let the OS produce the error


AGY_PATH = _resolve_cli()

# Same posture as the other interfaces: SSSF polices the repo itself
# (permissions.py rolls back unauthorized writes after every call), so the
# agent acts freely and code disposes afterwards. agy's print mode otherwise
# sits at "request-review", which has no one to ask in a headless run.
# Set AGY_ASK_PERMISSIONS=1 for a more cautious posture (phases may then stall
# on tools agy declines to run).
SKIP_PERMISSIONS = os.environ.get("AGY_ASK_PERMISSIONS", "") != "1"

PRINT_TIMEOUT = os.environ.get("AGY_PRINT_TIMEOUT", "240m")

# How long the stream may go silent before the turn is judged stalled. agy's
# built-in `schedule` tool never fires in print mode, so a builder that calls
# it ("check vitest in 10 s") sits until --print-timeout — hours — with no
# events at all (issue #52). A working turn emits a step_update every few
# seconds; a long test suite is one tool step, but the CLI still streams its
# start. Silence for this long means nothing is coming. 0 disables the check.
IDLE_TIMEOUT_SECONDS = float(os.environ.get("AGY_IDLE_TIMEOUT_SECONDS", "600"))
IDLE_RESEND_SLEEP_SECONDS = 5.0
# A rejected tool call (missing required property) is transient per send —
# resend quickly, same loop as a stall. Not a quota event.
SCHEMA_RESEND_SLEEP_SECONDS = 5.0

# `thinking` in the config is pi's seven-rung ladder; agy's --effort has
# three. Clamp the ends rather than error. Most agy model ids ALREADY carry an
# effort suffix (gemini-3.6-flash-high), and the CLI rejects --effort beside
# one as a conflict — so the flag is only sent for suffix-less ids, and a
# suffixed id simply wins over the config's `thinking` (measured, 2026-08-15).
EFFORT = {"off": "low", "none": "low", "minimal": "low", "low": "low",
          "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}
EFFORT_SUFFIXES = ("-low", "-medium", "-high")


def _effort_args(model_id: str, thinking: str) -> list[str]:
    """The --effort flag, unless the model id already encodes its effort."""
    if model_id.endswith(EFFORT_SUFFIXES):
        return []
    return ["--effort", EFFORT.get(thinking, thinking)]

# Steps that are conversation plumbing, not tool work.
NON_TOOL_STEPS = {"user_input", "agent_response", "checkpoint", "unknown", ""}

# Where a reader is sent to correct the guess after a captured event. agy's
# markers are here, not in control.py, and naming the wrong file is how the
# correction never gets made.
AGY_MARKER_TABLE = "RATE_LIMIT_MARKERS in adw_modules/agent_agy.py"

# Markers that make a failed result a rate limit rather than an unknown error.
# Gemini quota exhaustion surfaces as 429 / RESOURCE_EXHAUSTED; per-minute
# quotas reset fast, so the default sleep is short.
# "timeout waiting for response" is not a quota event: it is agy's print mode
# giving up on a stalled response (seen when an agent calls the `schedule`
# tool, whose wake-up never fires in print mode). The stall is transient per
# send, so it earns the same sleep-and-resend treatment.
RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "429", "resource_exhausted",
                      "quota", "too many requests",
                      "timeout waiting for response")
RATE_LIMIT_SLEEP_SECONDS = 120.0

# Tool-call schema blips: the model omitted a field the CLI now requires.
# Retry the send. Seen on articlegenerator/1bdf74c3 (missing toolSummary).
RETRY_MARKERS = ("missing property 'toolsummary'",
                 'missing property "toolsummary"')

# Fatal on retry: agy only lets write_to_file land under its brain folder,
# so SSSF context_handoff paths never succeed. Fail with this message, not
# "unfamiliar". The agent can still recover via the shell — see
# _task_envelope_ok. Seen on articlegenerator/1bdf74c3 documenter.
ARTIFACT_PATH_MARKER = "is not a valid artifact path"

# Fallback ceilings. Gemini 3.x models advertise a 1M window; agy's stream
# reports no ceiling of its own, so this is what the UI gets.
CONTEXT_WINDOWS = (("gemini", 1_000_000), ("claude", 200_000), ("gpt", 128_000))

LABEL_CHARS = 80
RESULT_SNIPPET_CHARS = 20_000


def resolve_model(pattern: str) -> tuple[str, str]:
    """Validate a model pattern, returning ``(provider, model_id)``.

    agy's catalog is live (`agy models`) and changes without notice, so
    validation checks shape only: a lowercase id, optionally prefixed
    `agy/` or `google/`. A model the login cannot serve fails on first use —
    the same stance agent_cc takes with Claude aliases.
    """
    name = pattern.split("/")[-1].strip()
    if name and name == name.lower() and " " not in name:
        return "agy", name
    raise ValueError(
        f"model {pattern!r} is not an agy model id — use a lowercase id from "
        f"`agy models` (e.g. gemini-3.6-flash-high)")


def context_window(provider: str, model_id: str) -> int:
    """Best-known ceiling for a model; agy never reports one itself."""
    for needle, window in CONTEXT_WINDOWS:
        if needle in model_id:
            return window
    return 0


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


class ToolCallTracker:
    """Folds agy's step stream into one normalized record per tool step.

    A tool step is announced ACTIVE and finished DONE (or FAILED), keyed by
    step_index; the call's identity lives in `tool_name` and
    `tool_info.parameters`, and its result in `tool_info.output`.
    Conversational steps (user_input, agent_response, checkpoint) are not tool
    calls and are skipped. The emitted record matches the other interfaces'
    trackers, so the tracer and visualizer are written once.
    """

    def __init__(self) -> None:
        self._started: dict[int, dict] = {}

    def observe(self, event: dict) -> Optional[dict]:
        """Returns the record for a finished tool step, else None."""
        if event.get("event") != "step_update":
            return None
        step = event.get("step_update") or {}
        step_type = str(step.get("step_type") or "")
        if step_type in NON_TOOL_STEPS:
            return None
        index = step.get("step_index")
        state = str(step.get("state") or "")

        if state == "ACTIVE":
            known = self._started.get(index, {})
            self._started[index] = {
                "started_at": known.get("started_at") or now_iso(),
                "clock": known.get("clock") or time.monotonic(),
            }
            return None
        if state not in ("DONE", "FAILED"):
            return None

        opened = self._started.pop(index, {})
        info = step.get("tool_info") or {}
        tool = str(step.get("tool_name") or info.get("name") or step_type)
        params = info.get("parameters") or {}
        args = {key: value for key, value in params.items()
                if isinstance(value, (str, int, float, bool))}
        value = next((" ".join(str(v).split()) for v in params.values()
                      if isinstance(v, str) and v.strip()), "")
        record = {
            "tool": tool,
            "tool_call_id": f"step-{index}",
            "args": args,
            "ok": state == "DONE",
            "label": f"{tool}: {_clip(value, LABEL_CHARS)}" if value else tool,
            "ended_at": now_iso(),
        }
        output = info.get("output")
        if isinstance(output, str) and output.strip():
            record["result_snippet"] = _clip(output, RESULT_SNIPPET_CHARS)
        if opened.get("clock"):
            record["duration_ms"] = int((time.monotonic() - opened["clock"]) * 1000)
        elif step.get("duration_seconds"):
            record["duration_ms"] = int(float(step["duration_seconds"]) * 1000)
        if opened.get("started_at"):
            record["started_at"] = opened["started_at"]
        return record


def _usage_tokens(usage: dict) -> dict:
    """Translate agy's usage object into the shape UsageBreakdown reads.

    agy's `input_tokens` includes the whole conversation each step, and
    `thinking_tokens` bills as output. `input` here EXCLUDES cache reads to
    match pi's vocabulary.
    """
    cached = int(usage.get("cache_read_tokens") or 0)
    return {
        "input": max(0, int(usage.get("input_tokens") or 0) - cached),
        "output": int(usage.get("output_tokens") or 0) + int(usage.get("thinking_tokens") or 0),
        "cacheRead": cached,
        "cacheWrite": 0,
    }


def _context_tokens(usage: dict) -> int:
    """Tokens occupying the window after a step — cache reads included, same
    reading every other interface takes."""
    total = usage.get("total_tokens")
    if total:
        return int(total)
    return int(sum(int(usage.get(part) or 0) for part in
                   ("input_tokens", "output_tokens", "thinking_tokens",
                    "cache_read_tokens")))


def _conversation_ledger(session_dir: Path) -> Path:
    """Where SSSF session keys map to the conversation ids agy minted.

    A dict, not agent_cc's list: the CLI invents the id, so the mapping has to
    be remembered, not derived. A file survives the process boundary between
    phases; every phase is its own process.
    """
    return session_dir / "agy_conversations.json"


def _known_conversation(session_dir: Path, key: str) -> Optional[str]:
    try:
        known = json.loads(_conversation_ledger(session_dir).read_text())
    except (OSError, ValueError):
        known = {}
    value = known.get(key)
    return str(value) if value else None


def _record_conversation(session_dir: Path, key: str, conversation_id: str) -> None:
    ledger = _conversation_ledger(session_dir)
    try:
        known = json.loads(ledger.read_text())
    except (OSError, ValueError):
        known = {}
    known[key] = conversation_id
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(known, indent=2, sort_keys=True))


def _is_within(path: Path, root: Path) -> bool:
    """True when `path` sits under `root`, resolved so 8.3 names, symlinks and
    case differences on Windows cannot fake a mismatch."""
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def _compose_first_prompt(system_prompt: str, prompt: str) -> str:
    """Fold the system prompt into the first send, above a divider.

    agy has no system-prompt flag, so a new conversation's identity travels as
    the opening of its first message. Continuations must NOT repeat it — the
    conversation already holds it, and repeating it would bury the correction
    the send exists to deliver.
    """
    return (f"# SYSTEM INSTRUCTIONS\n\n{system_prompt}\n\n"
            f"---\n\n# TASK\n\n{prompt}")


def _task_envelope_ok(text: str) -> bool:
    """True when the response carries SSSF's success JSON.

    agy sets result.status ERROR if any tool call had invalid args, even when
    the agent recovered and finished the task. The envelope is the account of
    whether the work landed.
    """
    if not text:
        return False
    candidate = text
    if "```" in text:
        for block in text.split("```")[1::2]:
            block = block.removeprefix("json").strip()
            if block.startswith("{"):
                candidate = block
                break
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        return False
    try:
        payload = json.loads(candidate[start:end + 1])
    except ValueError:
        return False
    return isinstance(payload, dict) and str(payload.get("status") or "").lower() == "success"


def _classify_failure(result_obj: dict, stderr: str) -> tuple[str, str]:
    """Judge a non-SUCCESS result: ("rate_limit" | "retry" | "upstream", detail).

    The structured result event is the account of what went wrong; stderr is
    reported only when it says nothing. agy warns on stderr about things that
    are not the failure — a `--conversation` id it no longer has being the
    common one — and leading with that sent a reader after the wrong cause on
    a run whose real failure was a response timeout (issue #37).

    Detection still reads BOTH: a missed rate limit costs a run that would
    have retried, so breadth wins there even though narrowness wins in the
    message. Known tool-schema blips retry; a brain-folder artifact refusal
    is a recognised stop, not an unfamiliar CLI.
    """
    structured = " ".join(str(result_obj.get(key) or "") for key in
                          ("status", "error", "response")).strip()
    haystack = f"{structured} {stderr}".lower()
    for marker in RATE_LIMIT_MARKERS:
        if marker in haystack:
            return "rate_limit", f"matched {marker!r}"
    for marker in RETRY_MARKERS:
        if marker in haystack:
            return "retry", f"matched {marker!r}"
    if ARTIFACT_PATH_MARKER in haystack:
        return "upstream", ("agy refused write_to_file: SSSF artifact paths "
                            "are not in its brain folder")
    detail = structured or stderr.strip()
    return "upstream", detail[:400] or "no detail in the result event"


def _lines_or_stall(process, idle_seconds: float):
    """Yield stdout lines; yield None once and stop if the stream goes silent.

    A blocking `for line in process.stdout` cannot notice silence, so a
    thread reads and the main loop waits on a queue with a timeout. On a
    stall the child is killed here, so the caller's `process.wait()` returns.
    """
    lines: "queue.Queue[Optional[str]]" = queue.Queue()

    def pump():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    while True:
        try:
            line = lines.get(timeout=idle_seconds if idle_seconds > 0 else None)
        except queue.Empty:
            process.kill()
            yield None
            return
        if line is None:
            return
        yield line


def run(request: PiRequest, on_event: Optional[Callable[[dict], None]] = None,
        on_spawn: Optional[Callable[[int], None]] = None,
        on_exit: Optional[Callable[[int], None]] = None) -> PiResult:
    """Run one non-interactive agy turn."""
    faked = fake_rate_limit_due()
    if faked is not None:
        seconds, why = reset_delay(faked)
        raise RateLimited(f"(fake) rate limited — {why}", seconds, faked)

    _, model_id = resolve_model(request.model)
    session_dir = Path(request.session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    conversation = _known_conversation(session_dir, request.session_id)

    prompt_text = (request.prompt if conversation
                   else _compose_first_prompt(request.system_prompt, request.prompt))
    prompt_file = session_dir / "prompt.md"
    prompt_file.write_text(prompt_text, encoding="utf-8")

    cmd = [
        AGY_PATH,
        "-p", f"@{prompt_file}",
        "--output-format", "stream-json",
        "--model", model_id,
        *_effort_args(model_id, request.thinking),
        "--print-timeout", PRINT_TIMEOUT,
        "--disable-slash-commands",
    ]
    # --add-dir ONLY when the prompt file sits outside the workspace: agy
    # treats an added dir as its working root, and shell commands then run
    # THERE instead of in the repo — a builder that edits the wrong tree. With
    # the default in-repo data_dir the prompt file is already inside the
    # workspace and the flag is never sent.
    if not _is_within(prompt_file, Path(request.cwd)):
        cmd += ["--add-dir", str(session_dir)]
    if conversation:
        cmd += ["--conversation", conversation]
    if SKIP_PERMISSIONS:
        cmd += ["--dangerously-skip-permissions"]
    # No tools flag exists, so a roster `tools:` list cannot be enforced here.
    # That is a documented gap, not a silent one — and `writes:` (the actual
    # boundary) is enforced by permissions.py regardless of interface.

    raw_path = Path(request.raw_output_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    result = PiResult(session_id=request.session_id,
                      context_window=context_window("agy", model_id))

    process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace",
                               bufsize=1, cwd=request.cwd,
                               env=operator_env())
    if on_spawn:
        on_spawn(process.pid)

    minted: Optional[str] = None
    terminal: dict | None = None
    stalled = False
    with raw_path.open("a") as raw:
        assert process.stdout is not None
        for line in _lines_or_stall(process, IDLE_TIMEOUT_SECONDS):
            if line is None:
                stalled = True
                break
            raw.write(line)
            raw.flush()
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = event.get("event")
            if kind == "init":
                minted = str(event.get("conversation_id") or "") or None
            elif kind == "step_update":
                usage = (event.get("step_update") or {}).get("usage") or {}
                if usage:
                    turn = _context_tokens(usage)
                    result.tokens += turn
                    result.usage.add_turn(_usage_tokens(usage), turn)
                    if turn:
                        result.context_tokens = turn
            elif kind == "result":
                body = event.get("result") or {}
                if body.get("response"):
                    result.text = str(body["response"])
                usage = body.get("usage") or {}
                if usage:
                    result.context_tokens = _context_tokens(usage)
                terminal = event

            if on_event:
                on_event(event)

    stderr = process.stderr.read() if process.stderr else ""
    result.returncode = process.wait()
    if on_exit:
        on_exit(process.pid)

    if stalled:
        # Not a rate limit, but it wants the same treatment: sleep briefly and
        # send again without spending the phase's JSON/gate retries. The
        # conversation is not recorded (returncode is non-zero), so the
        # resend starts fresh; whatever the agent wrote to disk is still there.
        raise RateLimited(
            f"agy stalled — no stream event for {IDLE_TIMEOUT_SECONDS:.0f}s, killed "
            "(usually a `schedule`/background wait that never fires in print mode)",
            IDLE_RESEND_SLEEP_SECONDS, None)

    status = str(((terminal or {}).get("result") or {}).get("status") or "")
    body = (terminal or {}).get("result") or {}
    response_text = str(body.get("response") or result.text or "")
    recovered = (terminal is not None and status != "SUCCESS"
                 and _task_envelope_ok(response_text))

    # Remember whatever conversation the CLI actually used, once it finished
    # cleanly — recording a crashed start would send the next call to
    # --conversation an id whose context may hold nothing.
    #
    # A `minted` that differs from the id we PASSED means agy did not resume
    # the conversation it was given: it warns "conversation <id> not found"
    # and opens a new one under an id of its own. Following it is the only way
    # the next phase resumes anything; leaving the ledger pointing at the id
    # agy has already rejected would start a fresh context on every call for
    # the rest of the run, which is what issue #37 measured.
    #
    # Recovered success (CLI ERROR, but the agent still produced the success
    # envelope) also records: the work landed, the next phase should resume.
    if minted and minted != conversation and (result.returncode == 0 or recovered):
        _record_conversation(session_dir, request.session_id, minted)

    if terminal is not None and status != "SUCCESS" and not recovered:
        verdict, detail = _classify_failure(body, stderr)
        # Same reasoning as agent_cc: capture before raising, and capture the
        # unrecognised bucket too, because that is where a real limit lands if
        # the markers below are wrong. Issue #9. "retry" is not in the capture
        # table; it is a known schema blip, not a shape we are still hunting.
        captured = capture_limit_event(terminal, verdict, detail, raw_path,
                                       source="agy")
        if verdict == "rate_limit":
            notice = capture_notice(captured, verdict, AGY_MARKER_TABLE)
            if notice:
                print(notice)
            raise RateLimited(f"rate limited — {detail}",
                              RATE_LIMIT_SLEEP_SECONDS, terminal)
        if verdict == "retry":
            raise RateLimited(
                f"agy rejected a tool call — {detail}, so it is being resent",
                SCHEMA_RESEND_SLEEP_SECONDS, terminal)
        if detail.startswith("agy refused"):
            raise UpstreamError(
                f"{detail}. It is NOT being retried — the same path will be "
                "refused again.\n"
                f"  the CLI said: {detail}\n"
                "  what to do: write the artifact with the shell "
                "(run_command), not write_to_file, or read the raw stream at\n"
                f"    {raw_path}\n"
                + capture_notice(captured, verdict, AGY_MARKER_TABLE))
        raise UpstreamError(
            "agy ended with an error this adapter does not recognise, so it "
            "is NOT being retried — an unfamiliar error is more likely a "
            "changed CLI than a blip.\n"
            f"  the CLI said: {detail}\n"
            "  what to do: read the last lines of the raw stream at\n"
            f"    {raw_path}\n"
            + capture_notice(captured, verdict, AGY_MARKER_TABLE))

    if result.returncode != 0 and not result.text:
        raise RuntimeError(f"agy exited {result.returncode}: {stderr.strip()[-800:]}")
    return result

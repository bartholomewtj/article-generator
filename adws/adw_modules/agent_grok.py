"""Grok CLI coding agent interface — xAI's `grok`, on a Grok subscription.

Runs `grok --prompt-file <file> --output-format streaming-messages-json` and
tails its JSONL stdout, forwarding each event to a callback WHILE the agent
works — the same streaming contract `agent_pi` and `agent_cc` provide, so
nothing upstream of this file needs to know which coding agent ran.

The load-bearing discovery (measured, 2026-08-15): **grok speaks Claude Code's
stream-json dialect, byte for byte.** `system/init`, assistant messages with
`tool_use` blocks, user messages with `tool_result` blocks, and a terminal
`result` event carrying `total_cost_usd` and `modelUsage`. So this adapter
reuses agent_cc's ToolCallTracker, usage translation, and result
classification rather than growing a second copy that would drift. If a grok
release ever breaks that symmetry, split the shared pieces then — not before.

Three things differ from Claude Code:

1. **The prompt goes over as a file.** `--prompt-file` sidesteps the 32,767
   char Windows command-line ceiling that argv prompts would hit, and grok
   reads stdin only in interactive mode. `--verbatim` rides along so a prompt
   that happens to start with `/` is never expanded as a slash command.

2. **Billing is a subscription.** `total_cost_usd` still arrives on the result
   event and is recorded so traces stay comparable across interfaces — read it
   as "what this would have cost on the API", not money leaving an account.

3. **Model ids are `grok-*`.** There is a live catalog (`grok models`) but no
   stable offline list, so validation accepts any `grok-*` pattern and a model
   the subscription cannot serve fails on first use — same stance agent_cc
   takes with Claude aliases.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Optional

# Grok's stream is Claude Code's dialect, so the stream-side machinery is
# imported rather than copied. These are private to agent_cc by convention,
# but this module is the second consumer the convention anticipated.
from .agent_cc import (ToolCallTracker, apply_session_cost, _context_tokens,  # noqa: F401 — ToolCallTracker is part of this module's interface
                       _is_new_session, _pi_shaped_usage, _record_session)
from .control import RateLimited, UpstreamError, classify_result_event, fake_rate_limit_due, reset_delay
from .data_types import PiRequest, PiResult
from .utils import operator_env

import json


def _resolve_cli() -> str:
    """Find the grok executable. Set GROK_PATH to override."""
    override = os.environ.get("GROK_PATH")
    if override:
        return override
    return shutil.which("grok") or "grok"    # let the OS produce the error


GROK_PATH = _resolve_cli()

# Same posture as agent_cc: SSSF polices the repo itself (permissions.py rolls
# back unauthorized writes after every call), so the agent acts freely and code
# disposes afterwards. `-p` mode already defaults to bypassPermissions; passing
# it explicitly keeps the behaviour pinned rather than inherited.
PERMISSION_MODE = os.environ.get("GROK_PERMISSION_MODE", "bypassPermissions")

# Distinct from agent_cc's namespace ON PURPOSE: the same SSSF session key must
# never map onto the same CLI session id across two different CLIs' session
# stores. Fixed forever, same as cc's — changing it orphans every resumable
# context window.
SESSION_NAMESPACE = uuid.UUID("b4c2e8d0-7a15-5f39-8c6b-2d90e4a1f7c8")

# `thinking` in the config is pi's seven-rung ladder; grok's
# --reasoning-effort has three. Clamp the ends rather than error.
EFFORT = {"off": "low", "none": "low", "minimal": "low", "low": "low",
          "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}

# Grok's builtin tools, as the init event lists them (2026-08-15). Used the
# same way agent_cc uses DENYABLE_TOOLS: anything a roster `tools:` list does
# not name is passed as --disallowed-tools, because deny is the half that
# restricts under bypassPermissions.
DENYABLE_TOOLS = {
    "run_terminal_command", "read_file", "search_replace", "write", "list_dir",
    "grep", "todo_write", "spawn_subagent", "kill_command_or_subagent",
    "get_command_or_subagent_output", "search_tool", "use_tool", "workflow",
    "scheduler_create", "scheduler_delete", "scheduler_list", "monitor",
    "enter_plan_mode", "exit_plan_mode", "ask_user_question", "web_search",
    "image_gen", "image_edit", "image_to_video", "reference_to_video",
}

# The roster writes `tools:` in Claude Code's vocabulary, because claude_code
# is the default runtime. Flipping an agent to grok without rewriting that
# list used to pass Read/Bash to --tools; grok matched none of them, denied
# every real tool, and the agent stalled. Translate here so one list means
# the same thing on every interface — pi already does this in agent_pi.
CLAUDE_TO_GROK_TOOLS = {
    "Read": ["read_file"],
    "Bash": ["run_terminal_command"],
    "Edit": ["search_replace"],
    "Write": ["write"],
    "Grep": ["grep"],
    "Glob": ["list_dir"],
    "Task": ["spawn_subagent"],
    "WebSearch": ["web_search"],
    # WebFetch has no grok equivalent; dropping it is the same stance pi
    # takes with Task. Already-lowercase grok names pass through below.
}


def translate_tools(tools: Optional[list[str]]) -> list[str]:
    """Config tool names in grok's vocabulary.

    Already-lowercase names pass through untouched: they are grok builtins
    from a roster written before this translation existed.
    """
    if not tools:
        return []
    out: list[str] = []
    for name in tools:
        if name in CLAUDE_TO_GROK_TOOLS:
            out.extend(CLAUDE_TO_GROK_TOOLS[name])
        elif name.islower():
            out.append(name)
        # Capitalised names with no grok equivalent are dropped: passing
        # them through is what produced a toolless grok agent.
    seen = set()
    return [t for t in out if not (t in seen or seen.add(t))]

# Fallback ceiling until the run's own result event reports better. Grok 4-era
# models advertise a 256k window; the result event's modelUsage carries no
# contextWindow field today, so this is usually what the UI gets.
CONTEXT_WINDOWS = (("grok", 256_000),)


def resolve_model(pattern: str) -> tuple[str, str]:
    """Validate a model pattern, returning ``(provider, model_id)``.

    Accepts `grok-*` ids, with an optional `xai/` prefix tolerated. The live
    catalog (`grok models`) needs a network call, so validation checks shape
    only — a model the subscription cannot serve fails on first use.
    """
    name = pattern.split("/")[-1].strip()
    if name.startswith("grok"):
        return "xai", name
    raise ValueError(
        f"model {pattern!r} is not a grok model — use a grok-* id "
        f"(`grok models` lists what this login can serve)")


def context_window(provider: str, model_id: str) -> int:
    """Best-known ceiling for a model, before the run reports its own."""
    for needle, window in CONTEXT_WINDOWS:
        if needle in model_id:
            return window
    return 0


def session_uuid(session_key: str) -> str:
    """Map an SSSF session key onto the UUID the CLI wants, deterministically."""
    return str(uuid.uuid5(SESSION_NAMESPACE, session_key))


def run(request: PiRequest, on_event: Optional[Callable[[dict], None]] = None,
        on_spawn: Optional[Callable[[int], None]] = None,
        on_exit: Optional[Callable[[int], None]] = None) -> PiResult:
    """Run one non-interactive grok turn."""
    faked = fake_rate_limit_due()
    if faked is not None:
        seconds, why = reset_delay(faked)
        raise RateLimited(f"(fake) rate limited — {why}", seconds, faked)

    _, model_id = resolve_model(request.model)
    session_dir = Path(request.session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    grok_session = session_uuid(request.session_id)
    starting = _is_new_session(session_dir, request.session_id)

    # The prompt travels as a file: argv on Windows caps the whole command line
    # at 32,767 chars and a rendered user prompt with a previous envelope in it
    # can clear that on its own. Overwritten per send — the rendered prompts
    # prompts.save() keeps are the durable record, this file is transport.
    prompt_file = session_dir / "prompt.md"
    prompt_file.write_text(request.prompt, encoding="utf-8")

    cmd = [
        GROK_PATH,
        "--prompt-file", str(prompt_file),
        "--verbatim",
        "--output-format", "streaming-messages-json",
        "--model", model_id,
        "--reasoning-effort", EFFORT.get(request.thinking, request.thinking),
        "--permission-mode", PERMISSION_MODE,
        "--system-prompt-override", request.system_prompt,
    ]
    # Same flag semantics as Claude Code, same footgun: creating and resuming
    # are different flags for one idea, and getting it backwards either errors
    # (--session-id on a live session) or silently forgets the plan the agent
    # just wrote (--resume on a missing one).
    cmd += (["--session-id", grok_session] if starting else ["--resume", grok_session])
    tools = translate_tools(request.tools)
    if tools:
        cmd += ["--tools", ",".join(tools)]
        denied = sorted(DENYABLE_TOOLS - set(tools))
        if denied:
            cmd += ["--disallowed-tools", ",".join(denied)]
    # `request.deny_writes` is deliberately NOT sent. Claude Code takes
    # `Edit(<glob>)` path rules on this flag; grok's tool vocabulary is its own
    # (`run_terminal_command`, `write`), and whether it reads the same rule
    # grammar is unmeasured. A rule the CLI silently ignores looks like
    # protection and is none. Protected paths stay with permissions.enforce()
    # here until someone measures it.

    raw_path = Path(request.raw_output_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    result = PiResult(session_id=request.session_id,
                      context_window=context_window("xai", model_id))

    # encoding pinned for the same reason as agent_cc: the CLI's JSONL is UTF-8
    # regardless of the Windows locale code page.
    process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace",
                               bufsize=1, cwd=request.cwd,
                               env=operator_env())
    if on_spawn:
        on_spawn(process.pid)

    terminal: dict | None = None
    with raw_path.open("a") as raw:
        assert process.stdout is not None
        for line in process.stdout:
            raw.write(line)
            raw.flush()
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "assistant":
                usage = (event.get("message", {}) or {}).get("usage", {}) or {}
                turn = _context_tokens(usage)
                result.tokens += turn
                result.usage.add_turn(_pi_shaped_usage(usage), turn)
                if turn:
                    result.context_tokens = turn
            elif etype == "result":
                if event.get("result"):
                    result.text = str(event["result"])
                apply_session_cost(result, event)
                terminal = event

            if on_event:
                on_event(event)

    stderr = process.stderr.read() if process.stderr else ""
    result.returncode = process.wait()
    if on_exit:
        on_exit(process.pid)

    # Only mark the session created once the CLI actually made it — recording
    # up front would send the next call to --resume a session a crashed start
    # never wrote.
    # A terminal result event counts too: the CLI wrote the session before it
    # reported (say) a rate limit and exited non-zero, so the retry has to
    # --resume it -- sending --session-id again fails with 'already in use'.
    if starting and (result.returncode == 0 or terminal is not None):
        _record_session(session_dir, request.session_id)

    if terminal is not None:
        verdict, detail = classify_result_event(terminal)
        if verdict == "rate_limit":
            seconds, why = reset_delay(terminal)
            raise RateLimited(f"rate limited — {detail}; {why}", seconds, terminal)
        if verdict == "upstream":
            raise UpstreamError(
                "grok ended with an error this adapter does not recognise, so "
                "it is NOT being retried — an unfamiliar error is more likely "
                "a changed CLI than a blip.\n"
                f"  the CLI said: {detail}\n"
                "  what to do: read the last lines of the raw stream at\n"
                f"    {raw_path}\n"
                "  if it turns out to be a rate limit, add its shape to "
                "RATE_LIMIT_TYPES / RATE_LIMIT_MARKERS in adw_modules/control.py")

    if result.returncode != 0 and not result.text:
        raise RuntimeError(f"grok exited {result.returncode}: {stderr.strip()[-800:]}")
    return result

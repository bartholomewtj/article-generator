"""Guard rails the run enforces on itself -- rate limits, budget, checkpoints.

Stdlib only, and no imports from the rest of adw_modules, on purpose: the
fleet's unit tests load this file directly by path, without pydantic
installed. Keep it that way -- if this file ever needs data_types, the tests
that protect it stop running.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone


# ── exceptions ────────────────────────────────────────────────────────────

class RateLimited(RuntimeError):
    """The API said "not now". Wait, then send the same thing again.

    Carries how long to wait so the caller doesn't have to re-derive it.
    """

    def __init__(self, message: str, sleep_seconds: float, detail: dict | None = None):
        super().__init__(message)
        self.sleep_seconds = sleep_seconds
        self.detail = detail or {}


class UpstreamError(RuntimeError):
    """A terminal error we do not recognise.

    Deliberately NOT retried. Claude Code is a moving target; an error shape
    we've never seen is more likely a changed CLI than a transient blip, and
    retrying it silently burns a subscription against a bug. Stop, print the
    raw event, and let a human look.
    """


class BudgetExceeded(SystemExit):
    """The run spent its allowance. SystemExit so it stops cleanly.

    session.py already turns SIGTERM into SystemExit for exactly this reason:
    it unwinds the phase context manager (so the trace closes properly) and
    exits without dumping a traceback at a non-developer.
    """


# --- Detection ---------------------------------------------------------
#
# WHAT WE ACTUALLY KNOW: nothing. No real rate-limit event from `claude -p
# --output-format stream-json` has ever been captured for this project. That
# capture was a Phase 1 deliverable that never happened, and it is recorded
# here as a known gap rather than papered over.
#
# So detection is written by SHAPE, structured fields first, in the order
# below. When a real event is finally seen, correct the table -- that is the
# only edit needed, and `fleet/tests/test_rate_limit.py` will tell you if the
# correction broke anything.
#
# 1. event["error"]["type"]  in RATE_LIMIT_TYPES     (Anthropic API error shape)
# 2. event["subtype"]        contains a RATE_LIMIT_MARKER
# 3. event["error_type"]     in RATE_LIMIT_TYPES
# 4. a 429 in event["status"] / event["error"]["status"]
# 5. FALLBACK ONLY: RATE_LIMIT_MARKERS in the result text, lowercased.
#
# Anything else with is_error=true is an UpstreamError. Never a retry.

RATE_LIMIT_TYPES = {"rate_limit_error", "rate_limit", "usage_limit_error"}
RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "usage limit",
                      "too many requests", "429")

# Where a reset time might be, in the order we look. Values are read as:
#   > 1_000_000_000  -> unix epoch seconds
#   <= 1_000_000     -> seconds from now
#   ISO 8601 string  -> an absolute time
RESET_KEYS = ("resets_at", "resetsAt", "reset_at", "resetAt",
              "retry_after", "retryAfter", "retry_after_seconds")

# 15 min: no reset time was parseable. Subscription limits reset on a rolling
# multi-hour window, but a wait that is too long turns a blip into a dead
# evening; 15 minutes is short enough to resume promptly and long enough not
# to hammer the API. On waking, the same send runs again -- if it is still
# limited, it sleeps again, up to MAX_TOTAL_WAIT_SECONDS.
FIXED_SLEEP_SECONDS = 900
MIN_SLEEP_SECONDS = 5            # never hot-loop
MAX_SLEEP_SECONDS = 6 * 3600     # never sleep past a plausible window
MAX_TOTAL_WAIT_SECONDS = 6 * 3600  # total across one send; then stop and surface


def classify_result_event(event: dict) -> tuple[str, str]:
    """Judge a terminal stream-json `result` event.

    Returns (verdict, detail) where verdict is one of:
      "ok"          -- nothing wrong
      "rate_limit"  -- sleep and send it again
      "upstream"    -- unrecognised terminal error; stop and surface

    `detail` is a short human sentence naming what was matched, so the log
    says WHY it decided that.
    """
    event = event or {}
    error = event.get("error") if isinstance(event.get("error"), dict) else {}
    is_error = bool(event.get("is_error"))

    if not is_error and not error:
        return "ok", ""

    # 1. event["error"]["type"]
    err_type = error.get("type")
    if err_type in RATE_LIMIT_TYPES:
        return "rate_limit", f"matched error.type={err_type!r}"

    # 2. event["subtype"] contains a marker
    subtype = str(event.get("subtype") or "")
    for marker in RATE_LIMIT_MARKERS:
        if marker.replace(" ", "_") in subtype.lower() or marker in subtype.lower():
            return "rate_limit", f"matched subtype={subtype!r}"

    # 3. event["error_type"]
    top_error_type = event.get("error_type")
    if top_error_type in RATE_LIMIT_TYPES:
        return "rate_limit", f"matched error_type={top_error_type!r}"

    # 4. a 429 in event["status"] / event["error"]["status"]
    for status in (event.get("status"), error.get("status")):
        if status is not None and str(status) == "429":
            return "rate_limit", f"matched status=429"

    # 5. FALLBACK ONLY: string match over result + subtype, lowercased.
    haystack = (str(event.get("result", "")) + " " + subtype).lower()
    for marker in RATE_LIMIT_MARKERS:
        if marker in haystack:
            return "rate_limit", (
                f"matched the text {marker!r} (string fallback -- the "
                f"structured fields didn't say)")

    if is_error:
        detail = json.dumps(event, default=str)[:500]
        return "upstream", detail

    return "ok", ""


def _parse_reset_value(value, now: float) -> float | None:
    """A single RESET_KEYS value -> seconds from now, or None if unusable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1_000_000_000:
            return number - now
        if number <= 1_000_000:
            return number
        return number - now
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            number = float(stripped)
        except ValueError:
            try:
                dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp() - now
        if number > 1_000_000_000:
            return number - now
        if number <= 1_000_000:
            return number
        return number - now
    return None


def reset_delay(event: dict, now: float | None = None) -> tuple[float, str]:
    """How long to sleep, and a sentence saying where that number came from."""
    now = time.time() if now is None else now
    event = event or {}
    error = event.get("error") if isinstance(event.get("error"), dict) else {}

    for key in RESET_KEYS:
        for container, where in ((event, "event"), (error, "error")):
            if key in container:
                seconds = _parse_reset_value(container[key], now)
                if seconds is not None:
                    clamped = max(MIN_SLEEP_SECONDS, min(MAX_SLEEP_SECONDS, seconds))
                    return clamped, f"reset time came from {where}[{key!r}]"

    return FIXED_SLEEP_SECONDS, "no reset time in the event -- using the fixed 15 minute fallback"


def with_rate_limit_retries(send, *, sleep=time.sleep, now=time.time,
                            notify=None, max_total_wait: float = MAX_TOTAL_WAIT_SECONDS):
    """Call `send()`. If it raises RateLimited, wait and call it AGAIN.

    This is the whole of decision 8's "never by burning JSON-retry or
    gate-correction budget": those two loops live in agents.execute and count
    attempts. This loop counts nothing. A rate limit is not the agent's
    fault, so it must not consume the agent's chances to get it right.

    `sleep`/`now`/`notify` are injectable so the tests can drive it without
    actually waiting.
    """
    total_waited = 0.0
    while True:
        try:
            return send()
        except RateLimited as e:
            projected = total_waited + e.sleep_seconds
            if projected > max_total_wait:
                raise RateLimited(
                    f"rate limited for {total_waited + e.sleep_seconds:.0f}s, past the "
                    f"{max_total_wait:.0f}s cap for a single send -- stopping rather than "
                    f"waiting indefinitely.\n"
                    f"what to do: check status, then re-run when the limit has likely "
                    f"cleared -- the run stopped itself, nothing is broken.",
                    e.sleep_seconds, e.detail,
                ) from e
            total_waited += e.sleep_seconds
            when = time.strftime("%H:%M", time.localtime(now() + e.sleep_seconds))
            message = (
                f"rate limited: sleeping {e.sleep_seconds:.0f}s (until {when} local) "
                f"then sending the same request again -- no retry budget is being spent")
            if notify:
                notify(message, e.sleep_seconds, str(e))
            sleep(e.sleep_seconds)


# ── budget ───────────────────────────────────────────────────────────────

def budget_verdict(spend: float, threshold: float | None) -> tuple[bool, str]:
    """(ok, message). threshold None or <= 0 means "no budget set"."""
    if threshold is None or threshold <= 0:
        return True, ""
    if spend < threshold:
        return True, ""
    message = (
        "BUDGET REACHED -- stopping this run.\n"
        f"  spent:  ${spend:.2f} (notional, summed from this box's own trace)\n"
        f"  budget: ${threshold:.2f}, set when the box was created\n"
        "\n"
        "Nothing is broken. The run stopped itself on purpose, at a phase boundary,\n"
        "so the work it already committed is intact.\n"
        "\n"
        "What to do:\n"
        "  see what it got done:   uv run fleet/sbx.py status\n"
        "  keep going with more:   uv run fleet/sbx.py run <run-id> --resume --budget 20\n"
        "  get the work out:       uv run fleet/sbx.py down <run-id>"
    )
    return False, message


def budget_from_env(env=None) -> float | None:
    """Read SSSF_BUDGET_USD. Unparseable or absent -> None (no budget)."""
    env = os.environ if env is None else env
    raw = env.get("SSSF_BUDGET_USD")
    if raw is None or not str(raw).strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


# ── checkpoint decisions ────────────────────────────────────────────────

def replayable(phase_name: str, completed: dict[str, str]) -> bool:
    """True when this phase already finished successfully in an earlier
    invocation of the same adw-id, and its envelope was kept.

    `completed` maps phase name -> stored envelope JSON.
    """
    return phase_name in completed


def commit_already_made(porcelain: str, head_message: str, message: str) -> bool:
    """True when `git commit` would be a no-op repeat of the commit already
    at HEAD: nothing staged AND HEAD's message is the one we were about to
    write. This is what makes a resumed run walk past a commit phase instead
    of dying on "nothing to commit"."""
    return not porcelain.strip() and head_message.strip() == message.strip()


# --- The fake -------------------------------------------------------------
# SSSF_FAKE_RATE_LIMIT=<n>   make the next n agent calls in THIS PROCESS come
#                            back rate-limited, without spawning the CLI at
#                            all (so a drill costs nothing and needs no
#                            network). Unset or 0 = off.
# SSSF_FAKE_RATE_LIMIT_SLEEP=<seconds>  what the fake claims as its reset
#                            delay. Default 5, so a drill takes seconds.
#
# Drill:
#   SSSF_FAKE_RATE_LIMIT=1 SSSF_FAKE_RATE_LIMIT_SLEEP=5 <launch the ADW>
#   expect: one "rate limited: sleeping 5s" line, a 5 second pause, then the
#   same phase completing normally. No extra JSON retry, no gate attempt.

FAKE_ENV = "SSSF_FAKE_RATE_LIMIT"
FAKE_SLEEP_ENV = "SSSF_FAKE_RATE_LIMIT_SLEEP"

_fake_fired = 0


def fake_rate_limit_due(env=None) -> dict | None:
    """The synthetic result event to raise on, or None. Counts per process."""
    global _fake_fired
    env = os.environ if env is None else env
    try:
        remaining = int(env.get(FAKE_ENV, "0") or "0")
    except ValueError:
        remaining = 0
    if remaining <= 0 or _fake_fired >= remaining:
        return None
    _fake_fired += 1
    try:
        sleep_seconds = float(env.get(FAKE_SLEEP_ENV, "5") or "5")
    except ValueError:
        sleep_seconds = 5.0
    return {
        "type": "result",
        "is_error": True,
        "subtype": "error_rate_limit",
        "error": {"type": "rate_limit_error", "retry_after": sleep_seconds},
        "result": "(fake) rate limit for a drill",
    }


def reset_fake_rate_limit_counter() -> None:
    """Test/drill helper: reset the per-process fake counter to zero."""
    global _fake_fired
    _fake_fired = 0

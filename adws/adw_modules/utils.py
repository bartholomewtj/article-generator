"""Small shared helpers. Anything bigger belongs in its own module."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def operator_env() -> dict[str, str]:
    """The engineer's own environment, as their shell would hand it over.

    Agents and quality blocks are meant to see exactly what the operator sees:
    their PATH, their toolchains, their globally installed packages. Copying
    os.environ gets almost all the way there — but ADWs launch under `uv run`,
    which prepends its ephemeral venv's bin to PATH and sets VIRTUAL_ENV. That
    venv holds the ADW's OWN dependencies (pydantic, pyyaml), not the
    operator's, so anything a subprocess resolves through it — `python3`,
    `pip`, every globally pip-installed CLI — silently becomes the wrong one.

    Stripping the venv restores parity: `python3` in an agent's bash is the
    same `python3` the engineer gets in their terminal. The ADW's own imports
    are unaffected; this env is only ever handed to child processes.
    """
    env = os.environ.copy()
    venv = env.pop("VIRTUAL_ENV", "")
    if not venv:
        return env
    # The venv's executables live in `bin` on POSIX and `Scripts` on Windows.
    # Compare normalised (case-folded, separators fixed) so a PATH entry
    # written any way still matches — stripping only the POSIX name left the
    # ephemeral venv first on PATH on Windows, and every `python` a quality
    # block ran resolved to a venv without the project's own packages.
    venv_dirs = {os.path.normcase(os.path.normpath(str(Path(venv) / sub)))
                 for sub in ("bin", "Scripts")}
    parts = [p for p in env.get("PATH", "").split(os.pathsep)
             if p and os.path.normcase(os.path.normpath(p)) not in venv_dirs]
    env["PATH"] = os.pathsep.join(parts)
    return env


# What a run says when it refuses a placeholder suite. One string, five ADWs.
PLACEHOLDER_REASON = ("the test phase ran a placeholder — "
                      "edit adws/adw_modules/quality.py")


def placeholder_blocks_acceptance(result) -> bool:
    """True when a placeholder suite must stop the run being accepted.

    A placeholder exits 0, so `result.passed` is useless here — a stamped repo
    with no suite wired up reported success for a test phase that checked
    nothing (issue #88). The phase still succeeds (the runner did its job); the
    RUN must not.

    `SSSF_ALLOW_PLACEHOLDER_TESTS=1` is the deliberate opt-out, for a repo that
    genuinely has no suite yet and wants the chain to run end to end anyway.
    Read at call time, not import time, so setting it in `.env` or the shell
    both work.
    """
    if result is None or not getattr(result, "placeholder", False):
        return False
    return os.environ.get("SSSF_ALLOW_PLACEHOLDER_TESTS", "").strip() != "1"


def new_id(length: int = 8) -> str:
    return secrets.token_hex(length // 2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_prompt(arg: str) -> str:
    """CLI prompt arg: a file path resolves to its contents, else inline text."""
    try:
        p = Path(arg)
        if p.is_file():
            return p.read_text()
    except OSError:
        pass
    return arg


def review_fingerprint(review) -> str:
    """Stable id of what a review asked to change. Same ask → same hash.

    Used to stop a revise loop that is repeating itself. Order of findings
    does not matter; only the unmet requirements and blocking items do.
    """
    unmet = sorted(f.requirement for f in getattr(review, "findings", []) if not f.met)
    blocking = sorted(getattr(review, "blocking", []))
    payload = json.dumps({"blocking": blocking, "unmet": unmet}, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def engineer_name() -> str:
    name = os.environ.get("ENGINEER_NAME", "").strip()
    if name:
        return name
    try:
        out = subprocess.run(["git", "config", "user.name"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except OSError:
        pass
    return os.environ.get("USER", "engineer")

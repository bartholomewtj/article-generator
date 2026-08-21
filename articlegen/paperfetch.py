"""Full text via the `papers` CLI (the separate paperfetch project).

Optional. When `papers` is not installed, `available()` is False and the
pipeline behaves exactly as it did before this module existed.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from typing import Callable

# Resolved once per process. shutil.which is a PATH walk and the pipeline asks
# per paper. None means "not looked yet".
_AVAILABLE: bool | None = None
_ARGV: list[str] = []
# The "not installed" line is worth saying once per process, not per paper.
_WARNED = False

DEFAULT_TIMEOUT = 120.0

# papers statuses that mean "no open-access copy", not "OA but empty".
# `queued_ckn` is Unpaywall (and the rest of the ladder) saying the paper is
# paywalled; logging that as a failed OA fetch called landmarks fetch failures
# (#191). Other non-ok statuses (`unreadable_pdf`, `retry`, `no_doi`) stay
# fetch failures: those are not a confirmed absence of OA.
NOT_OA_STATUSES = frozenset({"queued_ckn"})

# Tests reset process state by setting paperfetch._AVAILABLE = None,
# paperfetch._ARGV = [], paperfetch._WARNED = False.


def _command() -> list[str]:
    global _ARGV
    if _ARGV:
        return list(_ARGV)
    raw = os.environ.get("ARTICLEGEN_PAPERS_CMD", "").strip()
    if raw:
        _ARGV = shlex.split(raw, posix=False)
    else:
        which = shutil.which("papers")
        _ARGV = [which] if which else []
    return list(_ARGV)


def available(log: Callable[[str], None] | None = None) -> bool:
    """True when the papers CLI executable or command is configured and available."""
    global _AVAILABLE, _WARNED
    if _AVAILABLE is None:
        cmd = _command()
        _AVAILABLE = bool(cmd)
    if not _AVAILABLE and not _WARNED:
        if callable(log):
            log("  papers CLI not installed; full text limited to Europe PMC")
        _WARNED = True
    return _AVAILABLE


def fetch_via_papers(
    doi: str,
    timeout: float = DEFAULT_TIMEOUT,
    log: Callable[[str], None] | None = None,
) -> str:
    """Fetch open-access full text via the `papers` CLI.

    Runs `papers get <doi>` as a subprocess without a shell.
    Never raises into the pipeline; on any error, timeout, non-ok status or missing
    file, returns "" so callers can fall back gracefully.
    """
    return fetch_via_papers_with_status(doi, timeout=timeout, log=log)[0]


def fetch_via_papers_with_status(
    doi: str,
    timeout: float = DEFAULT_TIMEOUT,
    log: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Like fetch_via_papers, plus the papers JSON status.

    Returns `(text, status)`. `status` is the CLI's `status` field when JSON
    parsed (`ok`, `queued_ckn`, `no_doi`, …), or `""` on transport/parse
    failure. `queued_ckn` means no open-access copy, not a failed OA fetch.
    """
    if not doi or not available(log):
        return "", ""

    try:
        cmd = _command()
        if not cmd:
            return "", ""
        argv = cmd + ["get", doi]

        env = dict(os.environ)
        mailto = (
            env.get("PAPERS_MAILTO")
            or env.get("OPENALEX_MAILTO")
            or env.get("UNPAYWALL_EMAIL")
            or ""
        )
        if mailto:
            env["PAPERS_MAILTO"] = mailto
        else:
            env.pop("PAPERS_MAILTO", None)

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                env=env,
            )
        except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
            if callable(log):
                log(f"  papers fetch failed for {doi}: {exc}")
            return "", ""

        try:
            record = json.loads(proc.stdout)
        except (json.JSONDecodeError, Exception) as exc:
            if callable(log):
                sample = (proc.stdout or proc.stderr or "")[:200]
                log(f"  papers returned invalid JSON for {doi} ({exc}): {sample!r}")
            return "", ""

        if not isinstance(record, dict):
            if callable(log):
                log(f"  papers returned non-dict JSON for {doi}")
            return "", ""

        status = record.get("status") or ""
        if status != "ok":
            if callable(log):
                log(f"  papers: {status} for {doi}")
            return "", str(status)

        path = record.get("read")
        if not path:
            return "", status

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(), status
        except OSError as exc:
            if callable(log):
                log(f"  papers could not read file {path}: {exc}")
            return "", status
    except Exception as exc:
        if callable(log):
            log(f"  papers fetch unexpected error for {doi}: {exc}")
        return "", ""

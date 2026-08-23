"""Validation gates: verify the envelope's CLAIMS, never guesses.

A gate is `gate(envelope, run) -> GateReport` — one check per item it looked at.
Violations are derived from the failed checks and sent back to the SAME agent
session as a correction. Every check is recorded either way, so a green gate
says WHAT it verified instead of only that it passed.

Gates check what is mechanically checkable; plan quality is a reviewer's job.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .data_types import EnvelopeBase, GateReport

TAIL_CHARS = 1000        # command output kept as evidence on a failure

# A place the reviewer claims to have opened. "looks good", a blank string,
# a bare number and a bare SHA do not match (#87). Shapes beyond file:N
# (#57, #58): pytest/bun node IDs, a repo-relative path, line ranges, and
# diff-stat prose ("README.md +15 lines").
_FILE_LINE = re.compile(
    r'(?:[A-Za-z0-9_.-]+[/\\])+[A-Za-z0-9_.-]+(?:::[A-Za-z_][A-Za-z0-9_]*)+'
    r'|(?:[A-Za-z0-9_.-]+[/\\])+[A-Za-z0-9_.-]+:\d+(?:-\d+)?'
    r'|(?:[A-Za-z0-9_.-]+[/\\])+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+'
    r'|[A-Za-z0-9_.-]+\.[A-Za-z0-9]+(?:::[A-Za-z_][A-Za-z0-9_]*)+'
    r'|[A-Za-z0-9_.-]+\.[A-Za-z0-9]+:\d+(?:-\d+)?'
    r'|[A-Za-z0-9_.-]+\.[A-Za-z0-9]+\s+lines?\s+\d+-\d+'
    r'|[A-Za-z0-9_.-]+\.[A-Za-z0-9]+\s*[+\-]\d+\s+lines?'
    r'|[A-Za-z_][A-Za-z0-9_]*\(\)\s+lines?\s+\d+-\d+'
    r'|[A-Za-z_][A-Za-z0-9_]*\s+lines?\s+\d+-\d+'
)


# A run the reviewer claims to have made, plus what it returned. Some
# requirements have no line to point at -- "the suite passes", "the verifier
# passes", "only these two files changed" are settled by running something,
# not by opening a file. A command with its outcome is that kind of place.
# A bare assertion still fails: "the suite passes" names no command and no
# result.
_COMMAND = re.compile(
    r'\b(?:pytest|docker run|just \w+|git (?:diff|status|log|show)\b'
    r'|python[^\n]*\.py|scripts/[\w./-]+\.py'
    r'|bunx?\s+\S+|npm\s+(?:test|run\s+\S+)|npx\s+\S+'
    r'|vitest\b|tsc\b|cargo\s+test|go\s+test|make\s+\S+)')
# The scope check ("only these files changed") is settled by `git diff --stat`
# or `git status --short`, whose outcomes are "N files changed" and status
# lines like "M src/x.yaml" -- so those count too. Batch 11 of #62 died on the
# reviewer quoting exactly that output and the gate not recognising it.
# #57 / #58: "40 tests passed", "clean"/"untouched", a commit SHA, and a
# comma-list of filenames after git status.
# #105: the commonest scope outcome is counted, not quoted -- "git diff --stat
# -> those two files only", "git status only the four planned files", "git diff
# --stat against those paths empty". The command is named and the result is
# given; only the wording was outside the list. This widens the OUTCOME half
# only, so a bare assertion with no command still fails.
_NUM = r'\d+|one|two|three|four|five|six|seven|eight|nine|ten'
_OUTCOME = re.compile(
    r'\b(?:\d+\s+(?:tests?\s+)?(?:pass(?:ed)?|fail(?:ed)?)'
    r'|\d+\s+(?:skipped|errors?|coords?|entries)'
    r'|\d+\s+files?\s+changed'
    r'|exit(?:\s+code)?\s+\d+|no\s+(?:errors|mismatches|changes)'
    r'|untouched|unchanged|unmodified|clean|empty'
    r'|absent from (?:the )?(?:diff|changed files))\b'
    r'|(?:^|\s)[MADR?]{1,2}\s+[\w./\\-]+\.\w+'
    r'|\b[0-9a-f]{7}(?:[0-9a-f]{33})?\b'
    r'|[A-Za-z0-9_.-]+\.[A-Za-z0-9]+(?:\s*,\s*[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)+'
    rf'|\b(?:only|just|exactly)\s+(?:the\s+)?(?:those|these|that|{_NUM})\b'
    rf'|\b(?:those|these)\s+(?:{_NUM})?\s*(?:files?|paths?|entries)\s+only\b',
    re.I)


def _has_run_evidence(evidence: str) -> bool:
    e = evidence or ""
    return bool(_COMMAND.search(e) and _OUTCOME.search(e))


def _has_file_line(evidence: str) -> bool:
    """Did the reviewer name somewhere it actually looked?

    A file:line (or a node ID, a path, a line range, diff-stat prose), or a
    command with the result it returned. Anything else -- "looks good", a
    blank string, a bare number, a bare SHA -- is not evidence. A SHA counts
    only alongside a git command, which _has_run_evidence handles (#87).
    """
    e = evidence or ""
    return bool(_FILE_LINE.search(e) or _has_run_evidence(e))


def _size(path: Path) -> str:
    n = path.stat().st_size
    return f"{n}B" if n < 1024 else f"{n / 1024:.1f}KB"


def artifacts_exist(envelope: EnvelopeBase, run) -> GateReport:
    report = GateReport()
    for a in envelope.artifacts:
        p = Path(a)
        report.check(a, p.exists(),
                     f"exists, {_size(p)}" if p.exists() else "declared artifact does not exist")
    return report


def files_non_empty(envelope: EnvelopeBase, run) -> GateReport:
    report = GateReport()
    for a in envelope.artifacts:
        p = Path(a)
        if not (p.exists() and p.is_file()):
            continue                       # existence is artifacts_exist's job
        empty = p.stat().st_size == 0
        report.check(a, not empty, "declared artifact is empty" if empty else _size(p))
    return report


def json_parses(envelope: EnvelopeBase, run) -> GateReport:
    report = GateReport()
    for a in envelope.artifacts:
        p = Path(a)
        if p.suffix != ".json" or not p.exists():
            continue
        try:
            parsed = json.loads(p.read_text())
            report.check(a, True, f"parses, {type(parsed).__name__}")
        except json.JSONDecodeError as e:
            report.check(a, False, f"declared JSON artifact does not parse: {e}")
    return report


def _deleted_from_head(path: str, cwd=None) -> bool:
    """True when the path is tracked in HEAD but gone from the working tree —
    the one honest way a claimed change can point at a file that does not exist.

    `cwd` is the repo to ask. Without it git answers about the process's own
    directory, which is right only while every caller runs from the repo root.
    """
    result = subprocess.run(["git", "cat-file", "-e", f"HEAD:{path}"],
                            cwd=cwd, capture_output=True)
    return result.returncode == 0


def diff_matches_claims(envelope: EnvelopeBase, run) -> GateReport:
    """Every file claimed changed must exist on disk, or be a real deletion
    (tracked in HEAD, absent from the tree)."""
    report = GateReport()
    for f in getattr(envelope, "changed_files", []):
        p = Path(f)
        if p.exists():
            report.check(f, True, f"exists, {_size(p)}")
        else:
            deleted = _deleted_from_head(f, cwd=run.repo_root)
            report.check(f, deleted,
                         "deleted — tracked in HEAD, absent from the tree" if deleted
                         else "claimed changed file does not exist")
    return report


def verdict_consistent(envelope: EnvelopeBase, run) -> GateReport:
    """A review's verdict must agree with the findings it just wrote down.

    Nothing here judges the code — that is the reviewer's job. This checks the
    envelope against itself: an approval that ships blocking items, or a
    rejection that names no problem, is a claim the harness can refute without
    reading a line of the diff.

    `met: true` with no `file:line` evidence is treated as unmet. Missing
    proof is a no, not a yes.
    """
    report = GateReport()
    approved = bool(getattr(envelope, "approved", False))
    blocking = list(getattr(envelope, "blocking", []))
    findings = list(getattr(envelope, "findings", []))
    bare = [f.requirement for f in findings
            if f.met and not _has_file_line(getattr(f, "evidence", ""))]
    unmet = [f.requirement for f in findings if not f.met] + bare

    report.check("met findings name a place", not bare,
                 "every met finding has file:line evidence" if not bare
                 else f"{len(bare)} met finding(s) with no file:line evidence: "
                      + "; ".join(bare))
    report.check("approved vs blocking", not (approved and blocking),
                 "no blocking items" if not blocking
                 else f"{len(blocking)} blocking item(s) while approved=true"
                 if approved else f"{len(blocking)} blocking item(s), not approved")
    report.check("approved vs findings", not (approved and unmet),
                 "every requirement met" if not unmet
                 else f"{len(unmet)} unmet requirement(s) while approved=true"
                 if approved else f"{len(unmet)} unmet requirement(s), not approved")
    report.check("rejection names a problem", approved or bool(blocking or unmet),
                 "verdict is supported" if approved or blocking or unmet
                 else "approved=false but no blocking item or unmet requirement was given")
    return report


def tests_pass(command: str):
    """Gate factory: the given shell command must exit 0."""
    def gate(envelope: EnvelopeBase, run) -> GateReport:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        ok = result.returncode == 0
        note = f"exit {result.returncode}"
        if not ok:
            note += "\n" + (result.stdout + result.stderr)[-TAIL_CHARS:]
        return GateReport().check(command, ok, note)
    gate.__name__ = f"tests_pass({command})"
    return gate

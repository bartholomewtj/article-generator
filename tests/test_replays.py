"""Replay a real run's manifest through the writer-free stages.

Every other offline test builds its own fixture, which only ever proves the
code agrees with a fixture someone wrote to make it pass. A run manifest
(`pipeline.Draft.to_dict`) holds the whole input side of a real accepted
run — the paper pool, the relevance labels, the full-text excerpts the writer
was shown, and the article it produced. This suite replays that manifest
through `verify.check_statistics`, `style.check_style`,
`sources.full_text_order`, `writer.cite_target` and both renderers, and pins
the counts the run had when it was accepted. A change that alters one of
those counts — for example to `verify._FIGURE_RE` — fails a test here instead
of being noticed by hand in a draft (issue #248).

Run with: python tests/test_replays.py
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

# Ensure the repo root is importable when run as `python tests/test_replays.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set before any articlegen import, same reason as test_offline.py: never let
# a replay touch the real search cache file.
import tempfile

os.environ["ARTICLEGEN_CACHE_DIR"] = tempfile.mkdtemp(prefix="articlegen-test-cache-")

from articlegen import verify  # noqa: E402
from articlegen.pipeline import MAX_FULLTEXT_REQUESTS, Draft  # noqa: E402
from articlegen.render import (  # noqa: E402
    MISATTRIBUTED_MARK,
    UNVERIFIED_MARK,
    render_article,
    render_markdown,
)
from articlegen.sources import full_text_excerpts, full_text_order  # noqa: E402
from articlegen.style import check_style  # noqa: E402
from articlegen.style import errors as style_errors  # noqa: E402
from articlegen.writer import cite_target  # noqa: E402

REPLAY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replays")

# Pins for each manifest in tests/replays/, keyed by file stem. A manifest with
# no entry here is a failed check, not a skip — the whole point of this suite
# is that nothing replays silently.
EXPECTED = {
    "2026-09-05-night-shift-health-risk": {
        "papers": 48, "figures_total": 43, "cited": 13,
        "cite_ceiling": 12, "shown": 37, "order_len": 37,
        "daggers": 0, "double_daggers": 0,
        "style_errors": 0, "style_warnings": 1,
        "summary": "13 of 48 screened sources cited; 13 directly on-topic; prose style clean",
    },
}

FAILURES: list[str] = []


def check(name: str, cond: bool) -> None:
    """Record a failed check. Raises instead when pytest is the runner.

    See tests/test_offline.py's `check` for why: a runner that only watches
    for exceptions must not see this suite pass while `main()` would exit 1.
    """
    print(("OK   " if cond else "FAIL ") + name)
    if not cond:
        FAILURES.append(name)
        if "PYTEST_CURRENT_TEST" in os.environ:
            raise AssertionError(name)


def replays():
    """(stem, Draft, raw manifest dict) for every manifest in tests/replays/."""
    out = []
    for path in sorted(glob.glob(os.path.join(REPLAY_DIR, "*.json"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        out.append((stem, Draft.from_dict(raw), raw))
    return out


def _render_args(draft: Draft) -> tuple:
    return (draft.article, draft.papers, draft.topic, draft.curation,
            draft.verification, draft.provenance, draft.style_report)


def _run_replay_checks(stem: str, draft: Draft, manifest: dict) -> None:
    if stem not in EXPECTED:
        check(f"{stem}: has a pin in EXPECTED", False)
        return
    expected = EXPECTED[stem]
    curation = draft.curation
    counts = curation.get("counts") or {}
    relevance = curation.get("relevance") or {}
    provenance = draft.provenance

    # a. The writer's haystack rebuilds.
    rebuilt = full_text_excerpts(draft.papers)
    check(f"{stem}: replayed excerpts match the recorded excerpts",
          rebuilt == draft.excerpts)
    check(f"{stem}: excerpt keys match provenance.full_text_sources",
          set(draft.excerpts.keys()) == set(provenance.get("full_text_sources") or []))

    # b. check_statistics replay.
    result = verify.check_statistics(draft.article, draft.papers)
    recorded = manifest["verification"]
    check(f"{stem}: replayed unverified list matches the recorded run",
          result["unverified"] == recorded["unverified"])
    check(f"{stem}: replayed misattributed list matches the recorded run",
          result["misattributed"] == recorded["misattributed"])
    check(f"{stem}: replayed figure total matches the recorded run",
          result["total"] == recorded["total"])
    check(f"{stem}: replayed details match the recorded run",
          result["details"] == recorded["details"])
    check(f"{stem}: replayed figure count matches EXPECTED",
          result["total"] == expected["figures_total"])

    # c. check_style replay.
    style_report = check_style(draft.article, direct_sources=counts.get("direct"))
    recorded_style = manifest["style_report"]
    check(f"{stem}: replayed style issues match the recorded run",
          style_report["issues"] == recorded_style["issues"])
    check(f"{stem}: replayed style stats match the recorded run",
          style_report["stats"] == recorded_style["stats"])
    n_errors = len(style_errors(style_report))
    n_warnings = len([i for i in style_report["issues"] if i["severity"] == "warning"])
    check(f"{stem}: replayed style error count matches EXPECTED",
          n_errors == expected["style_errors"])
    check(f"{stem}: replayed style warning count matches EXPECTED",
          n_warnings == expected["style_warnings"])

    # d. full_text_order replay.
    order = full_text_order(draft.papers, relevance)
    check(f"{stem}: full_text_order length matches EXPECTED",
          len(order) == expected["order_len"])
    check(f"{stem}: full_text_order length equals direct + related counts",
          len(order) == counts.get("direct", 0) + counts.get("related", 0))
    check(f"{stem}: no tangential or unlabelled index appears in full_text_order",
          all(relevance.get(i) in ("direct", "related") for i in order))
    fetched = provenance.get("full_text_sources") or []
    check(f"{stem}: every fetched index appears in full_text_order",
          all(i in order for i in fetched))
    check(f"{stem}: every fetched index sits within the request cap",
          all(order.index(i) < MAX_FULLTEXT_REQUESTS for i in fetched))
    check(f"{stem}: full_text_order is deterministic",
          full_text_order(draft.papers, relevance) == order)

    # e. cite_target replay.
    n_tangential = sum(1 for label in relevance.values() if label == "tangential")
    shown = len(draft.papers) - n_tangential
    check(f"{stem}: replayed shown count matches EXPECTED",
          shown == expected["shown"])
    ceiling = cite_target(counts.get("direct"), shown)
    check(f"{stem}: replayed cite ceiling matches EXPECTED",
          ceiling == expected["cite_ceiling"])
    # The accepted run cited one source above its own ceiling (12). That is
    # recorded reality about the model's behaviour on the day, not a bug to
    # fix and not a target to make pass — pin the observed 13 as-is.
    check(f"{stem}: replayed cited count matches EXPECTED (one over the ceiling, recorded as-is)",
          len(draft.cited_refs) == expected["cited"])

    # f. Render replay.
    args = _render_args(draft)
    page = render_article(*args)
    md = render_markdown(*args)

    for label, text in (("HTML", page), ("Markdown", md)):
        n_daggers = text.count(UNVERIFIED_MARK)
        n_double = text.count(MISATTRIBUTED_MARK)
        check(f"{stem}: {label} dagger count matches EXPECTED",
              n_daggers == expected["daggers"])
        check(f"{stem}: {label} double-dagger count matches EXPECTED",
              n_double == expected["double_daggers"])
        check(f"{stem}: {label} has a dagger iff unverified figures were recorded",
              (n_daggers > 0) == bool(recorded["unverified"]))
        check(f"{stem}: {label} has a double-dagger iff misattributed figures were recorded",
              (n_double > 0) == bool(recorded["misattributed"]))

        blocking_style_error = n_errors > 0
        flagged = bool(recorded["unverified"] or recorded["misattributed"])
        check(f"{stem}: {label} working-draft sentence iff flagged figures or a blocking style error",
              ("read as a working draft" in text) == (flagged or blocking_style_error))

        check(f"{stem}: {label} names the recorded databases",
              "OpenAlex, Europe PMC and arXiv" in text)
        check(f"{stem}: {label} does not claim the databases were not recorded",
              "were not recorded" not in text)
        check(f"{stem}: {label} names the model",
              provenance.get("model", "") in text)

    n_refs = len(re.findall(r'<li id="ref-\d+"', page))
    check(f"{stem}: rendered reference count matches EXPECTED",
          n_refs == expected["cited"])
    check(f"{stem}: draft.summary() matches EXPECTED",
          draft.summary() == expected["summary"])


def _figure_re_guard(stem: str, draft: Draft, manifest: dict) -> None:
    """The issue's 'done means': broadening `_FIGURE_RE` must fail a check.

    Named without a `test_` prefix so pytest, which collects by name at
    module scope, never tries to call this directly — it takes arguments and
    is only ever run per-manifest from `main()`, same as every other check in
    this file.

    The replacement pattern keeps the original alternatives (so it still
    finds everything the real regex found) and keeps the `range` and
    `quantity` named groups — `check_statistics` calls `match.group("range")`
    and `match.group("quantity")` on every match, so a bare `re.compile(r"\\d+")`
    would raise `IndexError` instead of failing a check.
    """
    recorded = manifest["verification"]
    original = verify._FIGURE_RE
    try:
        verify._FIGURE_RE = re.compile(
            original.pattern + r"|(?<![\d.,])\d+(?![\d.,])", original.flags)
        broadened = verify.check_statistics(draft.article, draft.papers)
        check(f"{stem}: a broadened _FIGURE_RE finds more figures than the recorded run",
              broadened["total"] > recorded["total"])
        check(f"{stem}: a broadened _FIGURE_RE changes the flag counts",
              (len(broadened["unverified"]), len(broadened["misattributed"]))
              != (len(recorded["unverified"]), len(recorded["misattributed"])))

        # This is the only coverage of the flagged render path — the real
        # replay is clean — and it still uses the real manifest, not an
        # invented fixture.
        page = render_article(
            draft.article, draft.papers, draft.topic, draft.curation,
            broadened, draft.provenance, draft.style_report)
        check(f"{stem}: the flagged path actually renders a double-dagger",
              MISATTRIBUTED_MARK in page or UNVERIFIED_MARK in page)
        check(f"{stem}: the flagged path renders the working-draft sentence",
              "read as a working draft" in page)
    finally:
        verify._FIGURE_RE = original

    # A leaked monkeypatch must not poison the rest of the run.
    restored = verify.check_statistics(draft.article, draft.papers)
    check(f"{stem}: _FIGURE_RE is restored after the guard test",
          restored["total"] == recorded["total"])


def main() -> int:
    FAILURES.clear()
    found = replays()
    check("tests/replays/ contains at least one manifest", bool(found))
    for stem, draft, manifest in found:
        print(f"\n# {stem}")
        _run_replay_checks(stem, draft, manifest)
        _figure_re_guard(stem, draft, manifest)

    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'ALL PASS'}")
    return 1 if FAILURES else 0


def test_replays() -> None:
    """The whole suite as one pytest case, so pytest cannot report a quiet zero."""
    FAILURES.clear()
    assert main() == 0, "; ".join(FAILURES)


if __name__ == "__main__":
    raise SystemExit(main())

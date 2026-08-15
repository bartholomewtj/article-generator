"""The draft pipeline, in one place, for every caller.

`cmd_draft` (CLI) and `/api/draft` (web) used to each run their own version of
this sequence, and the web one had quietly drifted: it skipped the prose-style
gate and never built `provenance`, so articles generated through the web app
came out without the enforced hedging and with a Methods section missing the
search that actually produced them. The pipeline is the product, so there is
now exactly one copy of it.

Callers differ only in what they do with the result: the CLI writes files into
`drafts/`, the server renders and returns them.
"""

from __future__ import annotations

import datetime
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .llm import resolve_provider
from .sources import (DATABASE_NAMES, DEFAULT_MAX_PAPERS, Paper, fetch_full_text,
                      full_text_order, gather_evidence, resolve_pmcid)
from .style import (SUBSTANCE_RULES, check_style, errors as style_errors,
                    format_report as format_style, revision_brief)
from .verify import check_statistics
from .writer import curate_sources, plan_queries, revise_prose, write_article

# A caller that wants progress reporting passes one of these; the default drops it.
Logger = Callable[[str], None]

# How many full texts a draft aims for, and what it will spend getting them.
#
# The target is 5 because that is what the reader can actually be shown:
# `sources.full_text_excerpts` allows 12,000 characters per paper inside a
# 60,000-character total, so the sixth full text is truncated and the seventh
# gets nothing. Fetching more than the excerpt budget can display is pure cost.
FULLTEXT_TARGET = 5

# Every candidate now costs up to two Europe PMC requests (a DOI lookup, then
# the fetch), where before a paper with no pmcid cost nothing. A topic whose
# sources are all paywalled would otherwise spend one request per paper and
# come back with nothing, against the one scholarly API that reliably answers.
MAX_FULLTEXT_REQUESTS = 18

# Fail before billing the caller, when the sources are the problem.
#
# `plan_queries` is a paid LLM call and it runs before anything touches a
# scholarly API, so on a day when every API is refusing the caller pays for a
# run that was doomed from the start (#96). A one-query probe against the topic
# costs less than the gather it would precede, and on the dead day it costs
# nothing at all after the first one.
#
# The two memos are what keep this from being a tax on the healthy path. A
# server that has heard from a source recently skips the probe entirely, so a
# busy deployment pays for it once every SOURCE_PROBE_TTL rather than per
# request; a server that just saw every source fail reuses that verdict for
# SOURCE_PROBE_FAIL_TTL rather than re-probing per request.
#
# It can only ever refuse on the same condition `generate_draft` already raises
# on after the fact — *every* source returned an error, not merely no results —
# so it cannot block a draft that would have worked, short of the sources
# recovering inside the two-minute failure window.
SOURCE_PROBE_TTL = 900
SOURCE_PROBE_FAIL_TTL = 120

_probe_lock = threading.Lock()
_sources_last_ok = 0.0
_sources_last_fail: tuple[float, str] = (0.0, "")


def _note_sources_answered() -> None:
    global _sources_last_ok
    with _probe_lock:
        _sources_last_ok = time.time()


def _preflight_sources(topic: str, log: Logger) -> None:
    """Raise NoPapersFound before the first paid call if every source is down."""
    global _sources_last_fail
    if os.environ.get("ARTICLEGEN_SOURCE_PROBE", "").strip() == "0":
        return
    now = time.time()
    with _probe_lock:
        if now - _sources_last_ok < SOURCE_PROBE_TTL:
            return
        failed_at, reasons = _sources_last_fail
        if now - failed_at < SOURCE_PROBE_FAIL_TTL:
            raise NoPapersFound(_SOURCES_DOWN + reasons, sources_failed=True)

    outcomes: list[dict] = []
    log("Checking the scholarly APIs are answering...")
    papers = gather_evidence([topic], max_papers=1, per_query=1, topic=topic,
                             log=_silent, outcomes=outcomes, patient=False)
    failures = [o for o in outcomes if o["error"]]
    if outcomes and len(failures) == len(outcomes):
        reasons = "; ".join(sorted({f"{o['source']}: {o['error']}" for o in failures}))
        with _probe_lock:
            _sources_last_fail = (time.time(), reasons)
        raise NoPapersFound(_SOURCES_DOWN + reasons, sources_failed=True)
    if papers or outcomes:
        _note_sources_answered()


_SOURCES_DOWN = (
    "The scholarly APIs are not responding, so no evidence could be gathered. "
    "This is not a problem with the topic, and nothing has been charged for this "
    "attempt. "
)


def _read_subset_skew(papers: list[Paper], fetched: list[int]) -> str:
    """How the deeply-read subset differs from the rest, in one line.

    The open-access skew is *visible* — Table 1's Read column shows it per
    source, and Limitations says the deeply read subset skews open access. It
    has never been *measured*, so "the reader should weigh that" is advice
    nobody can act on (#84). Median year and citation count are the two axes
    the concern is usually about: newer, and lower-impact.

    Deliberately descriptive. Two small samples cannot support a test, and a
    p-value on n=4 would be worse than the raw numbers.
    """
    read = [p for i, p in enumerate(papers, start=1) if i in fetched]
    rest = [p for i, p in enumerate(papers, start=1) if i not in fetched]
    if not read or not rest:
        return "read-subset skew: not comparable (nothing read, or everything was)"

    def median(values: list[int]) -> str:
        values = sorted(v for v in values if v is not None)
        if not values:
            return "?"
        mid = len(values) // 2
        return str(values[mid] if len(values) % 2 else
                   (values[mid - 1] + values[mid]) // 2)

    return (f"read-subset skew: read n={len(read)} "
            f"median year {median([p.year for p in read])}, "
            f"median citations {median([p.citation_count for p in read])}; "
            f"abstract-only n={len(rest)} "
            f"median year {median([p.year for p in rest])}, "
            f"median citations {median([p.citation_count for p in rest])}")


def _silent(message: str) -> None:
    pass


class NoPapersFound(RuntimeError):
    """No usable papers came back.

    `sources_failed` distinguishes the two cases that look identical from an
    empty list: the topic genuinely has no indexed literature with abstracts,
    or every API refused to answer. Telling a user their topic is unsearchable
    when the real problem is a rate limit sends them off rewording a query that
    was fine.
    """

    def __init__(self, message: str, sources_failed: bool = False):
        super().__init__(message)
        self.sources_failed = sources_failed


@dataclass
class Draft:
    """Everything the renderers need, plus the provenance of how it was made."""

    topic: str
    article: dict
    papers: list[Paper]
    curation: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    style_report: dict = field(default_factory=dict)

    @property
    def cited_refs(self) -> set[int]:
        return {
            r for r in self.article.get("references", [])
            if isinstance(r, int) and 1 <= r <= len(self.papers)
        }

    def summary(self) -> str:
        """One greppable line: what was cited, and what to distrust.

        The GitHub workflow surfaces this in its comment, so keep it one line.
        """
        relevance = self.curation.get("relevance") or {}
        cited = self.cited_refs
        direct = sum(1 for r in cited if relevance.get(r) == "direct") if relevance else None
        n_unverified = len(self.verification.get("unverified") or [])
        n_misattributed = len(self.verification.get("misattributed") or [])

        parts = f"{len(cited)} sources cited"
        if direct is not None:
            parts += f"; {direct} directly on-topic"
        if n_unverified:
            parts += f"; ⚠ {n_unverified} figure(s) not found in the cited sources"
        if n_misattributed:
            parts += f"; ⚠ {n_misattributed} figure(s) credited to the wrong source"
        if relevance and not direct:
            parts += "; ⚠ no directly on-topic source found"
        # style_report is optional on the dataclass; a report that never ran is
        # not the same as a clean one, but for a one-line summary "clean" is the
        # honest reading — generate_draft always populates it.
        n_style = len(style_errors(self.style_report)) if self.style_report else 0
        parts += "; prose style clean" if not n_style else f"; ⚠ {n_style} prose-style issue(s)"
        return parts


# How many times `enforce_style` may send the prose back to the model. The
# second pass is gated on the first having *worked*: a pass only repeats after
# a revision that was accepted, and acceptance means strictly fewer errors. So
# an error the model cannot fix costs one call, not two, and nothing loops.
# Two, not three: the runs that motivated this ended at 3 -> 1 and 2 -> 1, a
# residual of one, which is what a second pass is sized for (#146).
MAX_STYLE_PASSES = 2


def enforce_style(
    article: dict,
    model: str | None = None,
    api_key: str | None = None,
    log: Logger = _silent,
    papers: list[Paper] | None = None,
    curation: dict | None = None,
) -> tuple[dict, dict]:
    """Check the prose against journal conventions and, if it misses, revise.

    Allows up to MAX_STYLE_PASSES passes, with a second pass only running if the
    first pass was accepted (i.e. it reduced the error count). The revision is
    only accepted if it actually reduces the error count and keeps the draft
    intact — a revision that drops citations or sections is discarded.

    `papers` matters when the draft failed for thinness or repetition: those can
    only be fixed by adding grounded material, and without the sources the model
    has nothing to add but more words about the same points. They are forwarded
    to the revision only in that case — see the note at `needs_sources`.
    """
    # The section floor scales with how much directly on-topic evidence there is;
    # demanding five sections from three usable abstracts invites padding.
    direct_sources = ((curation or {}).get("counts") or {}).get("direct")
    report = check_style(article, direct_sources=direct_sources)
    problems = style_errors(report)
    if not problems:
        log("Prose style: clean.")
        log(format_style(report))
        return article, report

    for attempt in range(1, MAX_STYLE_PASSES + 1):
        log(
            f"Prose style: {len(problems)} issue(s) against journal conventions; "
            f"revising (pass {attempt} of {MAX_STYLE_PASSES})..."
        )
        # Both of these are recomputed from the *current* report: a second pass
        # is fixing whatever the first one left behind, which need not be the
        # kind of failure the first one was fixing.
        #
        # The revision replaces named blocks, which is far cheaper than
        # regenerating the article — but a block can only be replaced if it
        # exists. `too-few-sections` is the one failure whose fix is a section
        # that is not there yet, so it is also the one that still pays for a
        # whole rewrite.
        rewrite_whole = any(i["rule"] == "too-few-sections" for i in problems)

        # The sources go along only when the draft failed for thinness or
        # repetition. `revision_brief` already splits the two cases: a substance
        # failure is told to pull specific findings out of the sources, and a
        # register failure is told to reword and add nothing. Sending 20
        # abstracts and 60,000 characters of full text to fix a contraction is
        # ~30,000 input tokens the model is explicitly forbidden to use — and
        # material it cannot use is material it can still be distracted by.
        needs_sources = any(i["rule"] in SUBSTANCE_RULES for i in problems)
        if papers and not needs_sources:
            log("  (register-only fixes; revising against the draft alone)")

        try:
            revised = revise_prose(
                article, revision_brief(report), model=model, api_key=api_key,
                papers=papers if needs_sources else None,
                curation=curation, rewrite_whole=rewrite_whole,
            )
        except Exception as exc:
            log(f"  revision failed ({exc}); keeping the draft as it stands.")
            break

        # Intactness is measured against the draft in hand, not the draft this
        # function was handed: after an accepted pass, that is the revision.
        intact = (
            len(revised.get("references") or []) >= len(article.get("references") or [])
            and len(revised.get("sections") or []) == len(article.get("sections") or [])
        )
        revised_report = check_style(revised, direct_sources=direct_sources)
        revised_problems = style_errors(revised_report)
        if not intact or len(revised_problems) >= len(problems):
            reason = (
                "revision dropped citations or sections" if not intact
                else "revision did not improve"
            )
            log(f"  {reason}; keeping the draft as it stands.")
            break

        log(f"  revised: {len(problems)} -> {len(revised_problems)} issue(s).")
        article, report, problems = revised, revised_report, revised_problems
        if not problems:
            log("  prose style now clean.")
            break

    log(format_style(report))
    return article, report


def generate_draft(
    topic: str,
    *,
    style_note: str = "",
    max_papers: int = DEFAULT_MAX_PAPERS,
    model: str | None = None,
    api_key: str | None = None,
    log: Logger = _silent,
) -> Draft:
    """Research and write one article. Raises NoPapersFound if the search comes back empty.

    `api_key` overrides the environment for this call only — the server passes
    the caller's key here and must never route it through `os.environ`.
    """
    # Before anything paid. `plan_queries` is an LLM call, and on a day when
    # every scholarly API is refusing, the caller used to pay for it and then be
    # told the run was doomed from the start (#96).
    _preflight_sources(topic, log)

    log(f"Planning search queries for: {topic}")
    queries, core_entity = plan_queries(topic, model=model, api_key=api_key)
    log("Queries: " + "; ".join(queries) + (f"  (core: {core_entity})" if core_entity else ""))

    log("Fetching journal articles...")
    outcomes: list[dict] = []
    papers = gather_evidence(
        queries, max_papers=max_papers, topic=topic, core_entity=core_entity,
        log=log, outcomes=outcomes,
    )
    if not papers:
        failures = [o for o in outcomes if o["error"]]
        if len(failures) == len(outcomes) and outcomes:
            reasons = sorted({f"{o['source']}: {o['error']}" for o in failures})
            raise NoPapersFound(
                "The scholarly APIs did not respond, so no evidence could be gathered. "
                "This is not a problem with the topic. " + "; ".join(reasons),
                sources_failed=True,
            )
        raise NoPapersFound(
            "No papers with abstracts were found for this topic. Try a broader or "
            "differently worded topic — or wait a minute and retry, since the open "
            "APIs throttle under load."
        )
    log(f"Collected {len(papers)} candidate papers.")
    # Feeds the pre-flight memo: a server that has heard from a source this
    # recently has no reason to spend a probe on the next request.
    _note_sources_answered()

    log("Assessing source relevance...")
    curation = curate_sources(topic, papers, model=model, api_key=api_key)
    counts = curation.get("counts") or {}
    if counts:
        log(f"  relevance: {counts.get('direct', 0)} direct / "
            f"{counts.get('related', 0)} related / {counts.get('tangential', 0)} tangential")
    # `curate_sources` degrades to an empty result on any failure, so a curation
    # that returned nothing looks exactly like one that labelled every source
    # tangential: "0 direct / 0 related / 0 tangential", logged and passed over.
    # That is the quietest way this pipeline can go wrong — the relevance gate
    # is what stops topic drift, and full-text fetching skips every unlabelled
    # source, so the draft downgrades to abstracts-only for a reason nothing
    # reports. Say so.
    if papers and not curation.get("relevance"):
        log("  WARNING: curation returned no usable labels for any of the "
            f"{len(papers)} sources. The relevance gate is not protecting this "
            "draft from topic drift, and no full text will be fetched. "
            "Re-run, or draft on a different provider.")

    # Full-text grounding: after curation, fetch the open-access full text of
    # the sources that earned it — direct before related, newest first inside a
    # tier, search rank breaking ties (#143).
    #
    # This step used to be skipped whenever the provider was Groq, whose
    # per-minute token ceiling could not fit a single full text. Groq is gone,
    # so it now runs on every draft.
    #
    # Two separate bounds, because they limit different things. FULLTEXT_TARGET
    # stops once the excerpt budget is full; MAX_FULLTEXT_REQUESTS stops a topic
    # with no open-access literature from spending a request per paper to learn
    # that. Neither bounds tokens — `sources.full_text_excerpts` does that.
    #
    # A paper reaches the fetch only after `resolve_pmcid` has had a chance to
    # discover it is open access, which is what a paper found via OpenAlex
    # rather than Europe PMC always needed and never got.
    fetched: list[int] = []
    relevance = curation.get("relevance") or {}
    log("Fetching open-access full texts...")
    requests_spent = 0
    # Still direct and related only, relevance then recency. Tangential sources
    # are deliberately excluded even when that leaves the target unmet: they
    # are background, and handing the writer 12,000 characters of an off-topic
    # paper is exactly the topic drift the relevance gate exists to prevent.
    # Why the loop stopped is a different question from how many it got, and
    # they need completely different fixes: a request cap that bites is a
    # tuning problem, while genuinely absent open access is a property of the
    # literature and not fixable here at all. The old log reported only the
    # count and then *asserted* availability, so the two were indistinguishable
    # (#84). Each tally below is one of the exits.
    eligible = no_open_access = fetch_failed = 0
    stopped = "ran out of eligible sources"
    for index in full_text_order(papers, relevance):
        paper = papers[index - 1]
        if len(fetched) >= FULLTEXT_TARGET:
            stopped = f"target of {FULLTEXT_TARGET} reached"
            break
        if requests_spent >= MAX_FULLTEXT_REQUESTS:
            stopped = f"request cap of {MAX_FULLTEXT_REQUESTS} reached"
            break
        eligible += 1
        if not paper.pmcid and paper.doi:
            requests_spent += 1
            # The logger matters: both lookups inside fail soft, and without it
            # a blocked Unpaywall halves full-text coverage invisibly (#104).
            resolve_pmcid(paper, log=log)
        if not (paper.pmcid and paper.is_open_access):
            no_open_access += 1
            continue
        requests_spent += 1
        text = fetch_full_text(paper)
        if text:
            paper.full_text = text
            fetched.append(index)
        else:
            fetch_failed += 1
    log(f"  full text retrieved for {len(fetched)} source(s)"
        + (f": {fetched}" if fetched else " (none)")
        + f" in {requests_spent} request(s)")
    log(f"  stopped because: {stopped}. Of {eligible} eligible source(s), "
        f"{no_open_access} had no open-access copy and {fetch_failed} were "
        "open access but returned no text.")
    if stopped.startswith("request cap"):
        # The one case where the code, not the literature, is the constraint.
        log(f"  NOTE: the cap bound before the target. Raising "
            f"MAX_FULLTEXT_REQUESTS would find more, at more requests against "
            "the shared Europe PMC quota.")
    log("  " + _read_subset_skew(papers, fetched))

    log("Writing the article (this can take a few minutes)...")
    article = write_article(
        topic, papers, model=model, style_note=style_note, curation=curation, api_key=api_key
    )

    article, style_report = enforce_style(
        article, model=model, api_key=api_key, log=log, papers=papers, curation=curation
    )
    verification = check_statistics(article, papers)

    # Feeds the deterministic Methods section — the search actually performed.
    #
    # `databases` names only the sources that actually returned records. It used
    # to be a hardcoded constant in render.py, so every article stated that both
    # Semantic Scholar and OpenAlex had been searched even when one of them had
    # refused every request. Semantic Scholar's keyless tier currently 429s on
    # every call, which made that claim false in every article the pipeline
    # produced. The Methods section is the one place in this project that must
    # not overstate what was done.
    answered = {o["source"] for o in outcomes if o["count"]}
    databases = [name for key, name in DATABASE_NAMES.items() if key in answered]

    provenance = {
        "queries": queries,
        "core_entity": core_entity,
        "databases": databases,
        "model": resolve_provider(model, api_key)[1],
        "date": datetime.date.today().strftime("%d %B %Y").lstrip("0"),
        # Which sources (1-based indices) the writer saw full text for. The
        # Methods section is written from this — like `databases`, it records
        # what actually happened, never what was intended.
        "full_text_sources": sorted(fetched),
    }

    return Draft(
        topic=topic,
        article=article,
        papers=papers,
        curation=curation,
        verification=verification,
        provenance=provenance,
        style_report=style_report,
    )

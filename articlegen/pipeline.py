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
from dataclasses import dataclass, field
from typing import Callable

from .llm import resolve_provider
from .sources import DATABASE_NAMES, Paper, fetch_full_text, gather_evidence, resolve_pmcid
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

        parts = f"{len(cited)} sources cited"
        if direct is not None:
            parts += f"; {direct} directly on-topic"
        if n_unverified:
            parts += f"; ⚠ {n_unverified} figure(s) not found in source abstracts"
        if relevance and not direct:
            parts += "; ⚠ no directly on-topic source found"
        # style_report is optional on the dataclass; a report that never ran is
        # not the same as a clean one, but for a one-line summary "clean" is the
        # honest reading — generate_draft always populates it.
        n_style = len(style_errors(self.style_report)) if self.style_report else 0
        parts += "; prose style clean" if not n_style else f"; ⚠ {n_style} prose-style issue(s)"
        return parts


def enforce_style(
    article: dict,
    model: str | None = None,
    api_key: str | None = None,
    log: Logger = _silent,
    papers: list[Paper] | None = None,
    curation: dict | None = None,
) -> tuple[dict, dict]:
    """Check the prose against journal conventions and, if it misses, revise once.

    The revision is only accepted if it actually reduces the error count and keeps
    the draft intact — a revision that drops citations or sections is discarded.

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

    log(f"Prose style: {len(problems)} issue(s) against journal conventions; revising once...")
    # The revision replaces named blocks, which is far cheaper than regenerating
    # the article — but a block can only be replaced if it exists. `too-few-sections`
    # is the one failure whose fix is a section that is not there yet, so it is
    # also the one that still pays for a whole rewrite.
    rewrite_whole = any(i["rule"] == "too-few-sections" for i in problems)

    # The sources go along only when the draft failed for thinness or repetition.
    # `revision_brief` already splits the two cases: a substance failure is told
    # to pull specific findings out of the sources, and a register failure is
    # told to reword and add nothing. Sending 20 abstracts and 60,000 characters
    # of full text to fix a contraction is ~30,000 input tokens the model is
    # explicitly forbidden to use — and material it cannot use is material it can
    # still be distracted by.
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
        log(f"  revision failed ({exc}); keeping the original draft.")
        log(format_style(report))
        return article, report

    intact = (
        len(revised.get("references") or []) >= len(article.get("references") or [])
        and len(revised.get("sections") or []) == len(article.get("sections") or [])
    )
    revised_report = check_style(revised, direct_sources=direct_sources)
    if intact and len(style_errors(revised_report)) < len(problems):
        log(f"  revised: {len(problems)} -> {len(style_errors(revised_report))} issue(s).")
        log(format_style(revised_report))
        return revised, revised_report

    reason = "revision dropped citations or sections" if not intact else "revision did not improve"
    log(f"  {reason}; keeping the original draft.")
    log(format_style(report))
    return article, report


def generate_draft(
    topic: str,
    *,
    style_note: str = "",
    max_papers: int = 20,
    model: str | None = None,
    api_key: str | None = None,
    log: Logger = _silent,
) -> Draft:
    """Research and write one article. Raises NoPapersFound if the search comes back empty.

    `api_key` overrides the environment for this call only — the server passes
    the caller's key here and must never route it through `os.environ`.
    """
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
    # the sources that earned it — direct/related labels, in rank order.
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
    # Still direct and related only, in rank order. Tangential sources are
    # deliberately excluded even when that leaves the target unmet: they are
    # background, and handing the writer 12,000 characters of an off-topic
    # paper is exactly the topic drift the relevance gate exists to prevent.
    for index, paper in enumerate(papers, start=1):
        if len(fetched) >= FULLTEXT_TARGET or requests_spent >= MAX_FULLTEXT_REQUESTS:
            break
        if relevance.get(index) not in ("direct", "related"):
            continue
        if not paper.pmcid and paper.doi:
            requests_spent += 1
            resolve_pmcid(paper)
        if not (paper.pmcid and paper.is_open_access):
            continue
        requests_spent += 1
        text = fetch_full_text(paper)
        if text:
            paper.full_text = text
            fetched.append(index)
    log(f"  full text retrieved for {len(fetched)} source(s)"
        + (f": {fetched}" if fetched else " (none open access)")
        + f" in {requests_spent} request(s)")
    if len(fetched) < FULLTEXT_TARGET:
        # Open access is a property of the literature, not of this code: a draft
        # with fewer full texts than the target still passes cleanly.
        log(f"  (target is {FULLTEXT_TARGET}; the remaining cited sources have no "
            "open-access copy in Europe PMC, so they are grounded in their abstracts)")

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
        "full_text_sources": fetched,
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

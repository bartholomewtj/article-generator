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
from .sources import Paper, gather_evidence
from .style import check_style, errors as style_errors, format_report as format_style, revision_brief
from .verify import check_statistics
from .writer import curate_sources, plan_queries, revise_prose, write_article

# A caller that wants progress reporting passes one of these; the default drops it.
Logger = Callable[[str], None]


def _silent(message: str) -> None:
    pass


class NoPapersFound(RuntimeError):
    """The scholarly APIs returned nothing usable for this topic.

    Distinct from an API failure: the run was fine, the literature wasn't there
    (or the shared rate limit was). Callers report it differently.
    """


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
) -> tuple[dict, dict]:
    """Check the prose against journal conventions and, if it misses, revise once.

    The revision is only accepted if it actually reduces the error count and keeps
    the draft intact — a revision that drops citations or sections is discarded.
    """
    report = check_style(article)
    problems = style_errors(report)
    if not problems:
        log("Prose style: clean.")
        log(format_style(report))
        return article, report

    log(f"Prose style: {len(problems)} issue(s) against journal conventions; revising once...")
    try:
        revised = revise_prose(article, revision_brief(report), model=model, api_key=api_key)
    except Exception as exc:
        log(f"  revision failed ({exc}); keeping the original draft.")
        log(format_style(report))
        return article, report

    intact = (
        len(revised.get("references") or []) >= len(article.get("references") or [])
        and len(revised.get("sections") or []) == len(article.get("sections") or [])
    )
    revised_report = check_style(revised)
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
    papers = gather_evidence(
        queries, max_papers=max_papers, topic=topic, core_entity=core_entity, log=log
    )
    if not papers:
        raise NoPapersFound(
            "No papers with abstracts found. The scholarly APIs may be rate-limiting "
            "— wait a minute and retry, or set SEMANTIC_SCHOLAR_API_KEY / OPENALEX_MAILTO."
        )
    log(f"Collected {len(papers)} candidate papers.")

    log("Assessing source relevance...")
    curation = curate_sources(topic, papers, model=model, api_key=api_key)
    counts = curation.get("counts") or {}
    if counts:
        log(f"  relevance: {counts.get('direct', 0)} direct / "
            f"{counts.get('related', 0)} related / {counts.get('tangential', 0)} tangential")

    log("Writing the article (this can take a few minutes)...")
    article = write_article(
        topic, papers, model=model, style_note=style_note, curation=curation, api_key=api_key
    )

    article, style_report = enforce_style(article, model=model, api_key=api_key, log=log)
    verification = check_statistics(article, papers)

    # Feeds the deterministic Methods section — the search actually performed.
    provenance = {
        "queries": queries,
        "core_entity": core_entity,
        "model": resolve_provider(model, api_key)[1],
        "date": datetime.date.today().strftime("%d %B %Y").lstrip("0"),
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

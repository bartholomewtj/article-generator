"""Fetch candidate evidence (papers with abstracts) from open scholarly APIs.

Two free, keyless sources are queried:

- Semantic Scholar Graph API (an optional API key raises rate limits)
- OpenAlex (an optional mailto address gets you into the "polite pool")

Both can be flaky under shared rate limits, so each query tolerates failures —
as long as one source returns results the pipeline keeps going.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

import requests

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_URL = "https://api.openalex.org/works"

_SS_FIELDS = "title,abstract,year,authors,venue,citationCount,externalIds,url"
_OA_FIELDS = (
    "id,title,publication_year,authorships,primary_location,"
    "cited_by_count,abstract_inverted_index,doi"
)


@dataclass
class Paper:
    title: str
    abstract: str
    year: int | None = None
    authors: list[str] = field(default_factory=list)
    venue: str = ""
    citation_count: int = 0
    url: str = ""
    doi: str = ""
    source: str = ""  # which API it came from

    @property
    def author_line(self) -> str:
        if not self.authors:
            return "Unknown authors"
        if len(self.authors) > 3:
            return f"{self.authors[0]} et al."
        return ", ".join(self.authors)

    @property
    def link(self) -> str:
        if self.doi:
            doi = self.doi.removeprefix("https://doi.org/")
            return f"https://doi.org/{doi}"
        return self.url


class SearchFailure(Exception):
    """A scholarly API did not answer. Distinct from answering with nothing.

    These used to be indistinguishable: every failure collapsed to an empty
    list, so a rate-limited or blocked API produced "no papers found for this
    topic" — blaming the user's topic for an infrastructure problem, with
    nothing in the message to suggest retrying.
    """


def _get_with_retry(url: str, params: dict, headers: dict, tries: int = 3) -> requests.Response:
    """Return a 200 response, or raise SearchFailure explaining why not."""
    delay = 2.0
    last = ""
    for attempt in range(tries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
            resp = None
        else:
            if resp.status_code == 200:
                return resp
            last = f"HTTP {resp.status_code}"
            if resp.status_code not in (429, 500, 502, 503):
                raise SearchFailure(last)  # non-retryable
        if attempt < tries - 1:
            time.sleep(delay)
            delay *= 2
    raise SearchFailure(f"{last} after {tries} attempts")


def search_semantic_scholar(query: str, limit: int = 15) -> list[Paper]:
    headers = {}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    resp = _get_with_retry(
        SEMANTIC_SCHOLAR_URL,
        params={"query": query, "limit": limit, "fields": _SS_FIELDS},
        headers=headers,
    )
    papers = []
    for item in resp.json().get("data") or []:
        if not item.get("abstract"):
            continue
        external_ids = item.get("externalIds") or {}
        papers.append(
            Paper(
                title=item.get("title") or "",
                abstract=item["abstract"],
                year=item.get("year"),
                authors=[a.get("name", "") for a in item.get("authors") or []],
                venue=item.get("venue") or "",
                citation_count=item.get("citationCount") or 0,
                url=item.get("url") or "",
                doi=external_ids.get("DOI") or "",
                source="Semantic Scholar",
            )
        )
    return papers


def _rebuild_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        for i in indexes:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def search_openalex(query: str, limit: int = 15) -> list[Paper]:
    params = {
        "search": query,
        "per-page": limit,
        "filter": "has_abstract:true",
        "select": _OA_FIELDS,
    }
    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto
    resp = _get_with_retry(OPENALEX_URL, params=params, headers={})
    papers = []
    for item in resp.json().get("results") or []:
        abstract = _rebuild_abstract(item.get("abstract_inverted_index"))
        if not abstract:
            continue
        location = item.get("primary_location") or {}
        source_meta = location.get("source") or {}
        papers.append(
            Paper(
                title=item.get("title") or "",
                abstract=abstract,
                year=item.get("publication_year"),
                authors=[
                    (a.get("author") or {}).get("display_name", "")
                    for a in item.get("authorships") or []
                ],
                venue=source_meta.get("display_name") or "",
                citation_count=item.get("cited_by_count") or 0,
                url=location.get("landing_page_url") or item.get("id") or "",
                doi=item.get("doi") or "",
                source="OpenAlex",
            )
        )
    return papers


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _keyword_overlap(paper: Paper, terms: set[str]) -> int:
    if not terms:
        return 0
    hay = f"{paper.title} {paper.abstract}".lower()
    return sum(1 for t in terms if t in hay)


def _rank_score(paper: Paper, terms: set[str]) -> tuple:
    """Blend topic-keyword overlap, citation weight, and recency — so a famous but
    off-topic review no longer automatically outranks an on-topic study."""
    import math

    overlap = _keyword_overlap(paper, terms)
    citation_weight = math.log10(paper.citation_count + 1)
    recency = (paper.year or 0) / 1000.0
    return (overlap, citation_weight + recency)


def gather_evidence(
    queries: list[str],
    max_papers: int = 20,
    # Records without a retrievable abstract are discarded, and the yield is
    # poor: a real run of three queries against both APIs returned 10 usable
    # papers, which is thin for a review and leaves each section restating the
    # same few findings. Asking for more candidates costs one larger page per
    # query, not more requests, and the ranking still keeps only max_papers.
    per_query: int = 25,
    topic: str = "",
    core_entity: str = "",
    log=lambda msg: None,
    outcomes: list[dict] | None = None,
) -> list[Paper]:
    """Run every query against both sources, dedupe, and return the best candidates,
    ranked by a blend of topic relevance, citations, and recency.

    One source failing is survivable — the other may still answer — so failures
    are recorded rather than raised. `outcomes` collects them so the caller can
    tell "this topic has no literature" from "both APIs refused us", which look
    identical from the returned list alone.
    """
    seen: set[str] = set()
    collected: list[Paper] = []
    for query in queries:
        for search in (search_semantic_scholar, search_openalex):
            try:
                results = search(query, limit=per_query)
                error = ""
            except SearchFailure as exc:
                results, error = [], str(exc)
            except Exception as exc:  # malformed payload, etc.
                results, error = [], f"{type(exc).__name__}: {exc}"

            if outcomes is not None:
                outcomes.append({
                    "source": search.__name__.replace("search_", ""),
                    "query": query, "count": len(results), "error": error,
                })
            log(f"  {search.__name__}({query!r}) -> "
                + (f"{len(results)} papers" if not error else f"FAILED ({error})"))

            for paper in results:
                key = _normalize_title(paper.title)
                if not key or key in seen:
                    continue
                seen.add(key)
                collected.append(paper)

    # Build a keyword set from the topic + core entity for a relevance signal.
    raw = f"{topic} {core_entity}".lower()
    terms = {w for w in re.split(r"[^a-z0-9]+", raw) if len(w) > 3}
    collected.sort(key=lambda p: _rank_score(p, terms), reverse=True)
    return collected[:max_papers]

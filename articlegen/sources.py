"""Fetch candidate evidence (papers with abstracts) from open scholarly APIs.

Four free, keyless sources are queried:

- Semantic Scholar Graph API (an optional API key raises rate limits — but
  keys are no longer granted to free-domain emails or third-party apps, so
  in practice the contested keyless pool is all this source has, and it
  refuses more often than it answers)
- OpenAlex (an optional mailto address gets you into the "polite pool")
- Europe PMC (no key, no mailto; biomedical/life-science coverage, which
  suits the mental-health topics this is mostly used for)
- arXiv (no key, no mailto; preprints in computing, physics, engineering,
  statistics and economics — the disciplines Europe PMC does not index, and
  where a non-clinical topic would otherwise be left to the two general
  sources alone)

All can be flaky under shared rate limits, so each query tolerates failures —
as long as one source returns results the pipeline keeps going.
"""

from __future__ import annotations

import datetime
import os
import re
import threading
import time
from dataclasses import dataclass, field

import requests

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_URL = "https://api.openalex.org/works"
EUROPE_PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARXIV_URL = "https://export.arxiv.org/api/query"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"

# How each source is named in an article's Methods section. Keyed by the
# `source` value gather_evidence records in its outcomes.
DATABASE_NAMES = {
    "semantic_scholar": "Semantic Scholar Graph API",
    "openalex": "OpenAlex",
    "europe_pmc": "Europe PMC",
    "arxiv": "arXiv",
}

# Identify ourselves rather than sending requests' default
# "python-requests/x.y". OpenAlex sits behind a CDN, and a stock library
# user-agent arriving from a cloud provider's shared egress IP is the exact
# profile that gets throttled first. OpenAlex also documents the User-Agent as
# a way into the polite pool, so the mailto goes here as well as in the query
# string — belt and braces, since only the header reaches Semantic Scholar.
_UA_BASE = "articlegen/0.1.0 (+https://github.com/bartholomewtj/article-generator)"

# Longest we'll honour a Retry-After. A draft has a user watching a progress
# bar, so waiting out a 60s cool-off is worse than failing and letting the
# other source carry the run.
#
# Note what this means in combination with the `exhausted` set below: a source
# that asks for a longer cool-off fails *immediately*, without retrying, and is
# then skipped for the rest of the run. One long Retry-After therefore removes
# a source entirely rather than slowing it down. That is deliberate — but it
# means the pipeline routinely runs on fewer sources than it appears to offer,
# so measure live behaviour with `/api/diag` rather than assuming all three
# answered. OpenAlex sends exactly this kind of long cool-off from shared cloud
# egress IPs.
_MAX_BACKOFF = 30.0

# How long a search result stays usable. The literature for a topic does not
# change hour to hour, but the free tiers of these APIs refuse constantly — so
# the same query re-run an hour later is far more likely to fail than to return
# something new. Caching turns "unreliable" into "unreliable once per topic".
#
# Set ARTICLEGEN_SEARCH_CACHE_TTL=0 to disable (used by the tests, which need to
# observe every call).
_CACHE_TTL = float(os.environ.get("ARTICLEGEN_SEARCH_CACHE_TTL", 24 * 3600))

# A refusal is cached too, but only briefly. Without this, a rate-limited source
# is re-attempted — three tries with backoff, about ten seconds — by every
# request that arrives while the limit is still in force, which both stalls the
# caller and deepens the throttle that caused it.
_CACHE_FAILURE_TTL = 120.0

_CACHE_MAX_ENTRIES = 256

_cache_lock = threading.Lock()
# (source, query, limit) -> (expires_at, papers, error). A non-empty error means
# the entry records a refusal rather than a result.
_search_cache: dict[tuple[str, str, int], tuple[float, list["Paper"], str]] = {}

_SS_FIELDS = "title,abstract,year,authors,venue,citationCount,externalIds,url"
_OA_FIELDS = (
    "id,title,publication_year,authorships,primary_location,"
    "cited_by_count,abstract_inverted_index,doi"
)


# Inline formatting tags the publishers' JATS leaves in a title. Named
# explicitly rather than matched as `<[^>]+>` (what `_strip_markup` does to
# abstracts): a real title like "Outcomes in adults aged <65 versus >80 years"
# contains a substring a generic tag pattern would eat whole, taking the visible
# text with it. Every tag listed here is character-level, so removing it never
# joins two words.
_TITLE_MARKUP_RE = re.compile(
    r"</?(?:scp|sc|i|b|u|em|strong|italic|bold|underline|monospace|sub|sup|span)\b[^>]*>",
    re.IGNORECASE,
)


def _strip_title_markup(title: str) -> str:
    """Remove publisher markup from a title, leaving the visible text intact.

    OpenAlex returns JATS tags inline ("The <scp>N-PACT</scp> team"), which
    reached Table 1, the reference list and the writer's prompt verbatim — and
    defeated dedupe, because `_normalize_title` kept "scp" as a word and the
    tagged and untagged copies of one paper no longer matched (issue #140).

    The tag goes without a replacement space, then whitespace is collapsed and
    the gaps the tags leave beside brackets and punctuation are closed, so
    "( N-PACT ):" reads "(N-PACT):" whichever way the publisher spaced it.
    """
    text = _TITLE_MARKUP_RE.sub("", title)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]:;,.])", r"\1", text)
    return text


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
    # Full-text plumbing (issue: expand grounding beyond abstracts). `pmcid`
    # and `is_open_access` come from the Europe PMC search response; only a
    # paper with both can have its full text fetched. `full_text` is filled by
    # `fetch_full_text` later in the pipeline, never by search.
    pmcid: str = ""
    is_open_access: bool = False
    full_text: str = ""

    def __post_init__(self) -> None:
        # The one place a title is cleaned. Four search functions build Papers
        # and a fifth would be added without remembering to call this, so the
        # cleaning belongs to the object rather than to each parse site.
        self.title = _strip_title_markup(self.title)

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


def _user_agent() -> str:
    """Our User-Agent, carrying the contact address when one is configured."""
    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        return f"{_UA_BASE} mailto:{mailto}"
    return _UA_BASE


def _retry_delay(resp: requests.Response | None, fallback: float) -> float | None:
    """How long to wait before retrying, or None to stop trying now.

    A server that sends Retry-After is telling us exactly when it will answer;
    backing off less than that just burns an attempt. Backing off *more* than
    _MAX_BACKOFF isn't worth it either — return None and let the caller fail
    while the other source still has time to answer.
    """
    if resp is None:
        return fallback
    header = resp.headers.get("Retry-After", "")
    try:
        wanted = float(header)
    except ValueError:
        # Retry-After may also be an HTTP date. Neither API sends that form,
        # so fall back rather than carry a date parser for it.
        return fallback
    if wanted > _MAX_BACKOFF:
        return None
    return max(wanted, fallback)


def _get_with_retry(url: str, params: dict, headers: dict, tries: int = 3) -> requests.Response:
    """Return a 200 response, or raise SearchFailure explaining why not."""
    headers = {"User-Agent": _user_agent(), **headers}
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
            wait = _retry_delay(resp, delay)
            if wait is None:
                raise SearchFailure(f"{last}, cool-off longer than {_MAX_BACKOFF:.0f}s")
            time.sleep(wait)
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
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        if not word or not isinstance(indexes, list):
            continue
        for i in indexes:
            if isinstance(i, int) and i >= 0:
                positions[i] = word
    if not positions:
        return ""
    max_pos = max(positions.keys())
    return " ".join(positions.get(i, "") for i in range(max_pos + 1)).strip()


# How far back the recency-biased companion query reaches. Eight years is wide
# enough to include the consolidation work that follows a finding, and narrow
# enough that the query returns something other than what relevance already gave.
RECENCY_WINDOW_YEARS = 8

# Set when the recency companion query refuses, and cleared at the start of each
# gather. Mirrors gather_evidence's `exhausted` set, which exists because
# retrying a dead source on every query cost more than half the gather time.
_recency_query_refused = False


def _openalex_page(query: str, limit: int, from_year: int | None = None) -> list[Paper]:
    """One OpenAlex request."""
    filters = ["has_abstract:true"]
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    params = {
        "search": query,
        "per-page": limit,
        "filter": ",".join(filters),
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


def search_openalex(query: str, limit: int = 15) -> list[Paper]:
    """Relevance search, plus a recency-biased companion query over the same terms.

    OpenAlex's relevance ordering returns old, heavily-cited work. Measured over
    three topics, the median year of a 20-paper page was 2006-2016, with 13-18 of
    20 published before 2015 (issue #38). Ranking can only reorder what it is
    given, and asking for a bigger page makes it worse rather than better: one
    page of 50 returned *more* pre-2015 work, because it simply goes deeper into
    the same ordering.

    A second, date-filtered request fixes it without a hard cutoff that would
    exclude foundational work — on the same three topics the merged pool's median
    moved to 2018-2020 and the count of 2020-or-later papers rose three- to
    tenfold, while the number of pre-2015 papers was unchanged.

    The recency query is best-effort. If it refuses, the relevance results still
    stand: a thinner pool beats no pool, and the caller's `exhausted` bookkeeping
    treats OpenAlex as one source either way.

    A refusal also stops it being attempted again for the rest of the run, for
    the same reason `gather_evidence` keeps an `exhausted` set: the limits are
    per-minute and a run takes seconds, so re-attempting a dead query on every
    subsequent query would spend three tries and about ten seconds each time,
    which is what made gathering take 31s before that set existed.
    """
    global _recency_query_refused
    papers = _openalex_page(query, limit)
    if _recency_query_refused:
        return papers
    cutoff = datetime.date.today().year - RECENCY_WINDOW_YEARS
    try:
        recent = _openalex_page(query, limit, from_year=cutoff)
    except SearchFailure:
        _recency_query_refused = True
        return papers

    seen = {(p.doi or _normalize_title(p.title)) for p in papers}
    for paper in recent:
        key = paper.doi or _normalize_title(paper.title)
        if key not in seen:
            seen.add(key)
            papers.append(paper)
    return papers


def _strip_markup(text: str) -> str:
    """Europe PMC abstracts arrive with embedded HTML (<h4>, <i>, <p>...).

    verify.py checks statistics by substring presence in these abstracts, so
    markup left in place would hide a figure that sits next to a tag.
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _europe_pmc_author(author: dict) -> str:
    """One Europe PMC author, in the given-name-first order the renderer expects.

    Europe PMC returns `fullName` **surname-first** ("Kim SH"); OpenAlex's
    `display_name` is the opposite ("Ari Min"). `render._format_author` takes the
    last token as the surname, so passing `fullName` straight through printed
    "SH, K." for "Kim SH" — every Europe PMC reference in an article had its
    surname and initials swapped, while OpenAlex ones were correct.

    Rather than teach the formatter to guess an order it cannot infer, normalise
    here from the structured fields Europe PMC already returns. Initials are
    split apart ("SH" -> "S H") so each survives as its own initial instead of
    being collapsed into one.
    """
    last = (author.get("lastName") or "").strip()
    if last:
        initials = [c for c in (author.get("initials") or "") if c.isalpha()]
        if initials:
            return f"{' '.join(initials)} {last}"
        first = (author.get("firstName") or "").strip()
        return f"{first} {last}" if first else last
    # Consortium authors carry `collectiveName` and no surname. `fullName` is the
    # last resort: wrong-order for a person, but better than dropping the name.
    return (author.get("collectiveName") or author.get("fullName") or "").strip()


def search_europe_pmc(query: str, limit: int = 15) -> list[Paper]:
    params = {
        # HAS_ABSTRACT restricts server-side, like OpenAlex's has_abstract
        # filter — otherwise most of the page is records we would discard.
        "query": f"({query}) AND HAS_ABSTRACT:y",
        "format": "json",
        # "core" is the smallest result type that includes the abstract.
        "resultType": "core",
        "pageSize": limit,
    }
    resp = _get_with_retry(EUROPE_PMC_URL, params=params, headers={})
    papers = []
    for item in (resp.json().get("resultList") or {}).get("result") or []:
        abstract = _strip_markup(item.get("abstractText") or "")
        if not abstract:
            continue
        # pubYear is a string ("2026"); missing or malformed becomes None and
        # ranking treats it as old.
        try:
            year = int(item.get("pubYear") or "")
        except ValueError:
            year = None
        journal = ((item.get("journalInfo") or {}).get("journal") or {}).get("title") or ""
        authors = [
            name
            for a in (item.get("authorList") or {}).get("author") or []
            if (name := _europe_pmc_author(a))
        ]
        src, ext_id = item.get("source") or "", item.get("id") or ""
        papers.append(
            Paper(
                title=_strip_markup(item.get("title") or ""),
                abstract=abstract,
                year=year,
                authors=authors,
                venue=journal,
                citation_count=item.get("citedByCount") or 0,
                url=f"https://europepmc.org/article/{src}/{ext_id}" if src and ext_id else "",
                doi=item.get("doi") or "",
                source="Europe PMC",
                pmcid=item.get("pmcid") or "",
                # Both flags are needed: isOpenAccess without inEPMC means the
                # OA copy lives somewhere Europe PMC cannot serve from.
                is_open_access=(item.get("isOpenAccess") == "Y" and item.get("inEPMC") == "Y"),
            )
        )
    return papers


# arXiv asks callers to leave three seconds between requests. Nothing enforces
# it per-key (there is no key), so the penalty for ignoring it is a block on the
# egress IP — which on the hosted backend is shared. A draft makes one arXiv
# call per planned query, so honouring it costs at most a few seconds spread
# across a run that already takes a minute.
_ARXIV_MIN_INTERVAL = 3.0
_arxiv_lock = threading.Lock()
_arxiv_last_call = 0.0

# arXiv's query parser reads a space after `all:` as the end of the term, so a
# multi-word topic sent verbatim searches for the first word alone. Terms are
# ANDed instead.
#
# Measured against the live API, ANDing is the only one of the three
# expressions that behaves: "machine learning emergency department triage" as a
# five-term AND returns 35 on-topic papers, the same words ORed return 135,233
# about anything with a grid in it, and as a quoted phrase, 0.
#
# Function words are dropped before the AND. Not for precision — every paper
# contains "the", so ANDing it excludes nothing — but because a query made of
# nothing else would otherwise become `all:the`, which matches the whole
# archive and ranks it by relevance to "the".
_ARXIV_MAX_TERMS = 8
_ARXIV_STOPWORDS = frozenset(
    "a an and are as at be by for from in is of on or the to with".split())

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def _arxiv_query(query: str) -> str:
    """A free-text topic as an arXiv `search_query` expression.

    Short words are kept when they are all there is: "AI in ED" becomes
    `all:AI AND all:ED`, which returns 123 papers where the quoted phrase
    returns 0.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9]+", query) if w]
    terms = [w for w in words if w.lower() not in _ARXIV_STOPWORDS] or words
    return " AND ".join(f"all:{t}" for t in terms[:_ARXIV_MAX_TERMS])


def search_arxiv(query: str, limit: int = 15) -> list[Paper]:
    """Preprints from arXiv, in the disciplines Europe PMC does not cover.

    Two things differ from the other three sources and both are deliberate.
    arXiv publishes no citation counts, so every paper arrives at `_rank_score`
    with a citation weight of zero and is ranked on topic overlap and recency
    alone — right for a preprint server, where the newest work is the point.
    And these are preprints: `venue` says so unless the record carries a
    `journal_ref`, because the reference list is the only place a reader learns
    that a source was never peer reviewed.
    """
    import xml.etree.ElementTree as ET

    with _arxiv_lock:
        global _arxiv_last_call
        wait = _ARXIV_MIN_INTERVAL - (time.time() - _arxiv_last_call)
        if wait > 0:
            time.sleep(wait)
        _arxiv_last_call = time.time()

    resp = _get_with_retry(
        ARXIV_URL,
        params={
            "search_query": _arxiv_query(query),
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
        },
        headers={},
    )
    # Atom, not JSON — arXiv offers no JSON representation. A malformed body
    # raises ParseError, which `_search_once` records like any other failure.
    root = ET.fromstring(resp.text)

    papers = []
    for entry in root.findall(f"{_ATOM}entry"):
        entry_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        # arXiv reports a bad query as a normal-looking entry whose id points at
        # /api/errors. Parsed as a paper it becomes a source titled "Error".
        if "/api/errors" in entry_id:
            continue
        abstract = _collapse(entry.findtext(f"{_ATOM}summary") or "")
        if not abstract:
            continue
        published = (entry.findtext(f"{_ATOM}published") or "")[:4]
        try:
            year = int(published)
        except ValueError:
            year = None
        authors = [
            name
            for a in entry.findall(f"{_ATOM}author")
            if (name := (a.findtext(f"{_ATOM}name") or "").strip())
        ]
        journal_ref = _collapse(entry.findtext(f"{_ARXIV_NS}journal_ref") or "")
        papers.append(
            Paper(
                title=_collapse(entry.findtext(f"{_ATOM}title") or ""),
                abstract=abstract,
                year=year,
                authors=authors,
                venue=journal_ref or "arXiv preprint",
                # arXiv publishes no citation counts. Left at 0 rather than
                # guessed; see the docstring.
                citation_count=0,
                url=entry_id,
                doi=(entry.findtext(f"{_ARXIV_NS}doi") or "").strip(),
                source="arXiv",
            )
        )
    return papers


def _collapse(text: str) -> str:
    """Whitespace-collapse a field. arXiv wraps abstracts and titles at column 80.

    Same reason `_strip_markup` exists: `verify.py` checks a statistic by
    substring presence, so a figure split across a line break would be reported
    unverifiable.
    """
    return re.sub(r"\s+", " ", text).strip()


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _keyword_overlap(paper: Paper, terms: set[str]) -> int:
    if not terms:
        return 0
    hay = f"{paper.title} {paper.abstract}".lower()
    return sum(1 for t in terms if t in hay)


RECENCY_WEIGHT = 3.0      # value of a brand-new paper, comparable to ~1000 citations
RECENCY_HALF_LIFE = 12    # years over which that value decays to nothing


def _rank_score(paper: Paper, terms: set[str], now: int | None = None) -> tuple:
    """Blend topic-keyword overlap, citation weight, and recency.

    Recency used to be `year / 1000`, which spans 0.02 across two decades while
    the citation term spans 0 to 4 — so it was arithmetically a rounding error
    and old, heavily-cited reviews always won. A real search returned a median
    paper year of 2013, with 2 of 20 papers from 2020 or later. That skews an
    article towards broad old reviews, which carry fewer specific findings than
    recent trials and make the prose vaguer.

    Recency is now on the same scale as the citation term and decays linearly
    to zero over RECENCY_HALF_LIFE years. Citations still matter — this ranks
    a well-cited recent paper top, not merely the newest thing indexed.
    """
    import datetime
    import math

    now = now or datetime.date.today().year
    overlap = _keyword_overlap(paper, terms)
    citation_weight = math.log10(paper.citation_count + 1)
    age = max(0, now - paper.year) if paper.year else RECENCY_HALF_LIFE
    recency = RECENCY_WEIGHT * max(0.0, 1.0 - age / RECENCY_HALF_LIFE)
    return (overlap, citation_weight + recency)


def clear_search_cache() -> None:
    """Forget every cached search. For tests, and for forcing a fresh look."""
    with _cache_lock:
        _search_cache.clear()
        _fulltext_cache.clear()
        _pmcid_cache.clear()


# ---------------------------------------------------------------- full text

EUROPE_PMC_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"

# Back-matter sections that cost tokens and ground nothing. Matched against the
# lowercased section title; anything else is kept in document order.
_FULLTEXT_SKIP_TITLES = re.compile(
    r"acknowledg|funding|reference|supplementar|abbreviation|author contribution"
    r"|conflict|competing|availability|ethics|consent|orcid|appendix"
)

# pmcid -> (expiry, text). Same lifecycle as the search cache: full text does
# not change hour to hour, and each fetch is a real request against the one
# scholarly API that reliably answers — do not spend it twice.
_fulltext_cache: dict[str, tuple[float, str]] = {}

# doi -> (expiry, pmcid, is_open_access). See `resolve_pmcid`.
_pmcid_cache: dict[str, tuple[float, str, bool]] = {}


def _unpaywall_email() -> str:
    """The contact Unpaywall requires. Never a made-up address — it blocks those."""
    return os.environ.get(
        "OPENALEX_MAILTO", "https://github.com/bartholomewtj/article-generator")


def probe_unpaywall(doi: str = "10.1371/journal.pone.0000308") -> dict:
    """Can this host reach Unpaywall right now?

    The full-text path grew a fourth keyless external dependency (#103) and it
    fails soft: if Unpaywall rate-limits, blocks the contact address or changes
    its response shape, every article silently drops to abstracts-only. Soft
    failure is right for the reader and useless for the operator, so it has to
    be visible from outside — the same reason `/api/diag` exists at all.

    The default DOI is a PLOS ONE paper that has been open access since 2007;
    an answer that says otherwise means the response shape changed, which is
    exactly one of the failures worth catching.
    """
    result = {"source": "unpaywall", "doi": doi, "email_set":
              bool(os.environ.get("OPENALEX_MAILTO")), "error": ""}
    try:
        resp = _get_with_retry(UNPAYWALL_URL.format(doi=doi),
                               params={"email": _unpaywall_email()}, headers={})
        data = resp.json()
    except SearchFailure as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    if not isinstance(data, dict) or "is_oa" not in data:
        result["error"] = "unexpected response shape (no is_oa field)"
        return result
    result["is_oa"] = bool(data.get("is_oa"))
    result["has_oa_location"] = bool(data.get("best_oa_location"))
    if not result["is_oa"]:
        result["error"] = "answered, but reports this known open-access DOI as closed"
    return result


def resolve_pmcid(paper: Paper, use_cache: bool = True, log=lambda msg: None) -> bool:
    """Look a paper's DOI up in Europe PMC to fill in `pmcid` / `is_open_access`.

    Only the Europe PMC *search* returns those two fields, so before this
    existed a paper's full text was reachable only if that search happened to
    be the one that found it. Everything from OpenAlex arrived with an empty
    pmcid and was therefore treated as abstract-only — including wholly
    open-access journals (Frontiers, MDPI, and the like) whose full text
    Europe PMC serves perfectly well. Measured on one real run, that cost 9 of
    11 available full texts: 2 were fetched where 11 could have been.

    If Europe PMC does not yield an open-access PMCID copy, a secondary lookup
    against Unpaywall is performed.

    Returns True when the paper now has a fetchable open-access full text. One
    HTTP call per unseen DOI, so callers must bound how many they make.
    """
    doi = (paper.doi or "").removeprefix("https://doi.org/").strip()
    if (paper.pmcid and paper.is_open_access) or not doi:
        return bool(paper.pmcid and paper.is_open_access)

    now = time.time()
    if use_cache and _CACHE_TTL > 0:
        with _cache_lock:
            entry = _pmcid_cache.get(doi)
        if entry and entry[0] > now:
            paper.pmcid, paper.is_open_access = entry[1], entry[2]
            return bool(entry[1] and entry[2])

    pmcid, open_access = "", False
    try:
        resp = _get_with_retry(
            EUROPE_PMC_URL,
            # The DOI field is exact-match, so this returns the one record or none.
            params={"query": f'DOI:"{doi}"', "format": "json",
                    "resultType": "core", "pageSize": 1},
            headers={},
        )
        results = (resp.json().get("resultList") or {}).get("result") or []
        if results:
            item = results[0]
            pmcid = item.get("pmcid") or ""
            # Both flags, for the same reason as in `search_europe_pmc`:
            # isOpenAccess without inEPMC means the copy is somewhere else.
            open_access = item.get("isOpenAccess") == "Y" and item.get("inEPMC") == "Y"
    except SearchFailure as exc:
        # A refused lookup is cached briefly, like a refused search, so a
        # throttled Europe PMC is not asked the same question twice a run.
        # Soft-failing is right for the reader; failing *silently* left the
        # operator with halved full-text coverage and nothing to look at (#104).
        log(f"  europe_pmc DOI lookup failed for {doi}: {exc}")

    if not (pmcid and open_access):
        try:
            unpaywall_resp = _get_with_retry(
                UNPAYWALL_URL.format(doi=doi),
                # Unpaywall requires a real contact and blocks addresses that
                # bounce, so never send a made-up one. It accepts a project URL
                # when no address is configured.
                params={"email": _unpaywall_email()},
                headers={},
            )
            data = unpaywall_resp.json()
            if isinstance(data, dict) and data.get("is_oa") is True and data.get("best_oa_location"):
                best_oa = data.get("best_oa_location") or {}
                extracted_pmcid = best_oa.get("pmcid") or data.get("pmcid")
                if not extracted_pmcid:
                    pmc_match = re.search(
                        r"PMC\d+",
                        str(best_oa.get("url") or "")
                        + " "
                        + str(best_oa.get("url_for_pdf") or "")
                        + " "
                        + str(best_oa.get("pmh_id") or ""),
                    )
                    if pmc_match:
                        extracted_pmcid = pmc_match.group(0)
                if extracted_pmcid:
                    extracted_pmcid = str(extracted_pmcid).strip()
                    if extracted_pmcid and not extracted_pmcid.startswith("PMC") and extracted_pmcid.isdigit():
                        extracted_pmcid = f"PMC{extracted_pmcid}"
                    pmcid = extracted_pmcid
                open_access = True
        except SearchFailure as exc:
            # Same reasoning as above, and this is the one the issue was
            # actually about: a blocked contact address here halves full-text
            # coverage across every article and looks like nothing at all.
            log(f"  unpaywall lookup failed for {doi}: {exc}")

    if _CACHE_TTL > 0:
        ttl = _CACHE_TTL if (pmcid or open_access) else _CACHE_FAILURE_TTL
        with _cache_lock:
            _pmcid_cache[doi] = (now + ttl, pmcid, open_access)

    paper.pmcid, paper.is_open_access = pmcid, open_access
    return bool(pmcid and open_access)


def _jats_text(node) -> str:
    return re.sub(r"\s+", " ", " ".join(node.itertext())).strip()


def _parse_fulltext_xml(xml_text: str) -> str:
    """JATS XML -> plain text of the body, section by section.

    Titles are kept ("Methods. ...") so the writer can attribute what it reads,
    and back matter is dropped. Falls back to the whole body text when the
    article has no <sec> structure. Markup is flattened for the same reason
    `_strip_markup` exists: verification is a substring check over this text.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    body = root.find(".//body")
    if body is None:
        return ""

    chunks: list[str] = []
    for sec in body.findall("sec"):
        title_node = sec.find("title")
        title = _jats_text(title_node) if title_node is not None else ""
        if title and _FULLTEXT_SKIP_TITLES.search(title.lower()):
            continue
        text = _jats_text(sec)
        if text:
            chunks.append(text)
    text = "\n\n".join(chunks) if chunks else _jats_text(body)
    # The paper's own bracketed citation numbers ("[ 1 ]", "[2, 5]", "[3-7]")
    # collide with the pipeline's [N] SOURCE-index scheme: a writer reading
    # "improves outcomes [ 4 ]" mid-paragraph may echo that number as if it
    # were one of OUR sources. Strip them; the prose keeps its meaning.
    return re.sub(r"\[\s*\d+(?:\s*[,–—-]\s*\d+)*\s*\]", "", text)


# Prompt policy for full text, and simultaneously the verification contract:
# the writer is shown exactly the excerpts this function yields, and verify.py
# checks statistics against exactly the same excerpts. Both sides derive them
# from this one deterministic function so nothing has to be recorded per run —
# and so verification never searches text the writer was not shown, which
# would let a remembered figure pass as grounded.
FULLTEXT_PER_PAPER_CHARS = 12000
FULLTEXT_TOTAL_CHARS = 60000


def full_text_excerpts(papers: list[Paper]) -> dict[int, str]:
    """{1-based index: the full-text excerpt shown to the writer}.

    Papers arrive ranked, so when the total budget runs out it is the least
    relevant full texts that are left as abstract-only.
    """
    out: dict[int, str] = {}
    used = 0
    for i, p in enumerate(papers, start=1):
        if not p.full_text:
            continue
        room = FULLTEXT_TOTAL_CHARS - used
        if room <= 0:
            break
        excerpt = p.full_text[:min(FULLTEXT_PER_PAPER_CHARS, room)]
        out[i] = excerpt
        used += len(excerpt)
    return out


def fetch_full_text(paper: Paper, use_cache: bool = True) -> str:
    """The paper's open-access full text as plain text, or "" when unavailable.

    Only papers Europe PMC can actually serve (a PMCID plus both OA flags) are
    fetchable; everything else returns "" and stays abstract-only. Failures are
    cached briefly, like search refusals, so one dead fetch is not retried
    across a run.
    """
    if not (paper.pmcid and paper.is_open_access):
        return ""
    now = time.time()
    if use_cache and _CACHE_TTL > 0:
        with _cache_lock:
            entry = _fulltext_cache.get(paper.pmcid)
            if entry and entry[0] > now:
                return entry[1]
    try:
        resp = _get_with_retry(
            EUROPE_PMC_FULLTEXT_URL.format(pmcid=paper.pmcid), params={}, headers={})
        text = _parse_fulltext_xml(resp.text)
    except SearchFailure:
        text = ""
    if _CACHE_TTL > 0:
        ttl = _CACHE_TTL if text else _CACHE_FAILURE_TTL
        with _cache_lock:
            _fulltext_cache[paper.pmcid] = (now + ttl, text)
    return text


def _cache_get(key: tuple[str, str, int]) -> tuple[list[Paper], str] | None:
    """The cached (papers, error) for this key, or None if absent or stale."""
    if _CACHE_TTL <= 0:
        return None
    now = time.time()
    with _cache_lock:
        entry = _search_cache.get(key)
        if entry is None:
            return None
        expires_at, papers, error = entry
        if expires_at <= now:
            del _search_cache[key]
            return None
    # Hand back a copy of the list: callers collect into their own lists and a
    # shared one would accumulate across runs.
    return list(papers), error


def _cache_put(key: tuple[str, str, int], papers: list[Paper], error: str) -> None:
    if _CACHE_TTL <= 0:
        return
    ttl = _CACHE_FAILURE_TTL if error else _CACHE_TTL
    with _cache_lock:
        _search_cache[key] = (time.time() + ttl, list(papers), error)
        if len(_search_cache) <= _CACHE_MAX_ENTRIES:
            return
        now = time.time()
        for stale in [k for k, (exp, _, _) in _search_cache.items() if exp <= now]:
            del _search_cache[stale]
        while len(_search_cache) > _CACHE_MAX_ENTRIES:
            soonest = min(_search_cache, key=lambda k: _search_cache[k][0])
            del _search_cache[soonest]


def _search_once(name: str, search, query: str, limit: int) -> tuple[list[Paper], str, bool]:
    """One source, one query, live. Returns (papers, error, cached=False).

    Failures are returned rather than raised so the caller can record them
    alongside successes; a source failing is survivable as long as another
    answers. The result is written to the cache either way.
    """
    key = (name, query, limit)
    try:
        papers, error = search(query, limit=limit), ""
    except SearchFailure as exc:
        papers, error = [], str(exc)
    except Exception as exc:  # malformed payload, etc.
        papers, error = [], f"{type(exc).__name__}: {exc}"

    _cache_put(key, papers, error)
    return papers, error, False


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
    use_cache: bool = True,
) -> list[Paper]:
    """Run every query against every source, dedupe, and return the best candidates,
    ranked by a blend of topic relevance, citations, and recency.

    One source failing is survivable — another may still answer — so failures
    are recorded rather than raised. `outcomes` collects them so the caller can
    tell "this topic has no literature" from "every API refused us", which look
    identical from the returned list alone. Each outcome carries `cached`, so a
    caller can see whether a result reflects the sources' behaviour just now.

    `use_cache=False` forces a live probe of every source. Only the diagnostic
    endpoint wants this — it exists to answer "can this host reach its sources
    *right now*", which a cached answer cannot. Drafting always leaves it on.
    """
    global _recency_query_refused
    _recency_query_refused = False
    seen: set[str] = set()
    _first_by_title: dict[str, Paper] = {}
    collected: list[Paper] = []
    # A source that has already refused once in this run will almost certainly
    # refuse again — the limits are per-minute and the run takes seconds. Each
    # attempt costs three tries with backoff, about ten seconds, so retrying a
    # dead source across every query wasted a third of the gather time.
    # Semantic Scholar's keyless tier currently 429s on every call.
    exhausted: set[str] = set()

    for query in queries:
        # Keys are explicit rather than derived from `search.__name__`: the name
        # is not a stable identity (a replaced function reports whatever it is
        # called, and two lambdas are both `<lambda>`), and these keys index
        # DATABASE_NAMES and the outcome records. The tuple is rebuilt each call
        # so the module-level names are looked up fresh.
        #
        # arXiv goes last, and the order is load-bearing: dedupe is first-seen-
        # wins on the normalised title, and a preprint usually shares its title
        # with the published version. Querying arXiv last means the peer-
        # reviewed record is the one kept, with the preprint discarded as its
        # duplicate — the wrong way round would cite preprints for work that
        # has since appeared in a journal.
        for name, search in (("semantic_scholar", search_semantic_scholar),
                             ("openalex", search_openalex),
                             ("europe_pmc", search_europe_pmc),
                             ("arxiv", search_arxiv)):
            # The cache is consulted before the exhausted set, not after: a hit
            # costs nothing and carries no risk of deepening a throttle, so a
            # source that has already refused this run can still contribute
            # results an earlier run stored for a different query.
            hit = _cache_get((name, query, per_query)) if use_cache else None
            if hit is None and name in exhausted:
                if outcomes is not None:
                    outcomes.append({"source": name, "query": query, "count": 0,
                                     "error": "skipped (already failed this run)",
                                     "cached": False})
                log(f"  {name}({query!r}) -> skipped, already failed this run")
                continue

            if hit is not None:
                results, error, cached = hit[0], hit[1], True
            else:
                results, error, cached = _search_once(name, search, query, per_query)
                if error:
                    exhausted.add(name)

            if outcomes is not None:
                outcomes.append({
                    "source": name, "query": query,
                    "count": len(results), "error": error, "cached": cached,
                })
            suffix = " (cached)" if cached else ""
            log(f"  {name}({query!r}) -> "
                + (f"{len(results)} papers{suffix}" if not error
                   else f"FAILED ({error}){suffix}"))

            for paper in results:
                key = _normalize_title(paper.title)
                if not key:
                    continue
                if key in seen:
                    # First-seen wins, but a duplicate from Europe PMC may know
                    # something the kept copy does not: the PMCID that makes
                    # full text fetchable. Merge that instead of discarding it.
                    if paper.pmcid:
                        kept = _first_by_title.get(key)
                        if kept is not None and not kept.pmcid:
                            kept.pmcid = paper.pmcid
                            kept.is_open_access = paper.is_open_access
                    continue
                seen.add(key)
                _first_by_title[key] = paper
                collected.append(paper)

    # Build a keyword set from the topic + core entity for a relevance signal.
    raw = f"{topic} {core_entity}".lower()
    terms = {w for w in re.split(r"[^a-z0-9]+", raw) if len(w) > 3}
    collected.sort(key=lambda p: _rank_score(p, terms), reverse=True)
    return collected[:max_papers]

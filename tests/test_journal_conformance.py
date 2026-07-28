"""Conformance check: does a rendered draft actually follow journal conventions?

`docs/journal-style.md` lists the conventions we copied from Nature, Science, the
Nature Reviews titles and JAMA. This file turns that list into assertions and runs
them over several fixture articles, including the awkward ones a live run produces:
an article with no directly relevant sources, one with sparse source metadata, and
one whose sources span forty years.

Run with:  python tests/test_journal_conformance.py   (exits non-zero on failure)
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from articlegen.render import render_article, render_markdown  # noqa: E402
from articlegen.sources import Paper  # noqa: E402

FAILURES: list[str] = []


# --------------------------------------------------------------------------
# the conventions, as predicates over the rendered page
# --------------------------------------------------------------------------

def _has_all(html: str, *needles: str) -> bool:
    return all(n in html for n in needles)


CONVENTIONS = [
    ("article-type label in the masthead",
     lambda h, a: "Evidence Review" in h),
    ("title is not a question or clickbait",
     lambda h, a: not a["title"].rstrip().endswith("?")),
    ("abstract is one unstructured paragraph",
     lambda h, a: 'class="run-in-head">Abstract' in h
     and h.count('<div class="abstract">') == 1),
    ("abstract carries no citation markers",
     lambda h, a: not re.search(r"\[\d", a.get("abstract", ""))),
    ("index terms are printed",
     lambda h, a: 'class="keywords"' in h or not a.get("keywords")),
    ("key points box sits above the body",
     lambda h, a: h.index("Key points") < h.index("Introduction")),
    ("first section is the Introduction",
     lambda h, a: a["sections"][0]["heading"] == "Introduction"),
    ("last section is the Conclusions",
     lambda h, a: a["sections"][-1]["heading"].startswith("Conclusions")),
    ("citations are superscript, not bracketed",
     lambda h, a: '<sup class="cite">' in h and not re.search(r">\[\d+\]<", h)),
    ("citations sit after the punctuation",
     lambda h, a: not re.search(r'<sup class="cite">[^<]*(?:<[^>]+>[^<]*)*</sup>\s*\.', h)),
    ("every inline marker resolves to a reference",
     lambda h, a: _markers_resolve(h)),
    ("references are numbered and titled",
     lambda h, a: '<section class="refs">' in h and 'id="ref-1"' in h),
    # Records with no authorship data at all exist in OpenAlex; "Unknown authors" is
    # the honest rendering, so it satisfies the convention too.
    ("reference authors are in surname-initial form",
     lambda h, a: all(
         re.match(r"[^<]+, [A-Z]\.", author) or author == "Unknown authors"
         for author in re.findall(r'class="ref-authors">([^<]+)<', h)
     )),
    ("Methods reports the search strategy",
     lambda h, a: _has_all(h, "Methods", "Search strategy.", "OpenAlex")),
    ("Methods states the abstracts-only constraint",
     lambda h, a: "full texts were not retrieved" in h),
    ("evidence assessment carries a Limitations paragraph",
     lambda h, a: _has_all(h, "Evidence assessment", "Limitations.")),
    ("back matter is complete",
     lambda h, a: _has_all(h, "Data availability", "Competing interests",
                           "Author contributions", "Peer review")),
    ("no magazine furniture",
     lambda h, a: not _has_all(h, "kicker") and "pull" not in h
     and "standfirst" not in h and "opener" not in h),
    ("no emoji warnings",
     lambda h, a: not any(c in h for c in "⚠🔬📊✅❌")),
    ("no fabricated journal apparatus",
     lambda h, a: not re.search(r"\b(Volume|Issue|Received|Accepted|ORCID)\b", h)),
    ("page is self-contained",
     lambda h, a: "http-equiv" not in h and not re.search(r'src="https?://', h)),
]


def _markers_resolve(html: str) -> bool:
    """Every #ref-N linked from the body must exist as a list item id."""
    linked = {int(n) for n in re.findall(r'href="#ref-(\d+)"', html)}
    defined = {int(n) for n in re.findall(r'id="ref-(\d+)"', html)}
    return bool(defined) and linked <= defined


# --------------------------------------------------------------------------
# fixtures — the shapes a live run actually produces
# --------------------------------------------------------------------------

def _article(title, sections, **overrides):
    base = {
        "title": title,
        "abstract": "A single unstructured paragraph summarising the evidence and its limits.",
        "keywords": ["alpha", "beta"],
        "evidence_note": "The direct evidence is thin.",
        "featured_study": {"source_index": 1, "why": "Most relevant.",
                           "method": "Cohort study.", "results": "A positive association."},
        "sections": sections,
        "key_points": ["First point [1].", "Second point [2]."],
        "glossary": [{"term": "Term", "definition": "A definition."}],
        "references": [1, 2],
    }
    base.update(overrides)
    return base


_SECTIONS = [
    {"heading": "Introduction", "paragraphs": ["Scope and rationale [1]."]},
    {"heading": "Mechanisms", "paragraphs": ["A mechanistic account [2].", "More detail [1, 2]."]},
    {"heading": "Clinical evidence", "paragraphs": ["Trial evidence remains limited [2]."]},
    {"heading": "Conclusions and outlook", "paragraphs": ["What would settle it [1]."]},
]


def _papers(n, **kw):
    return [
        Paper(
            title=f"Study {i}", abstract=f"abstract {i}",
            year=kw.get("years", [2000 + i] * n)[i - 1],
            authors=[f"Given{i} Sur{i}"],
            venue=kw.get("venue", f"Journal {i}"),
            citation_count=10 * i,
            doi=f"10.1000/{i}",
        )
        for i in range(1, n + 1)
    ]


def fixtures():
    """(name, article, papers, curation, verification, provenance, topic)."""
    from articlegen import demo

    provenance = {"queries": ["query one", "query two"], "model": "test-model"}

    # 1. The happy path.
    yield ("demo sample", demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, demo.SAMPLE_CURATION,
           None, demo.SAMPLE_PROVENANCE, "the functions of sleep in the brain")

    # 2. Nothing directly on topic — the extrapolation path.
    papers = _papers(4)
    yield ("no direct sources",
           _article("Gravity batteries for grid storage", _SECTIONS),
           papers,
           {"relevance": {1: "related", 2: "related", 3: "tangential", 4: "tangential"},
            "most_relevant_index": 1,
            "counts": {"direct": 0, "related": 2, "tangential": 2}},
           {"unverified": ["0.42"], "total": 3}, provenance, "gravity batteries")

    # 3. Sparse metadata: no years, no venues, no DOIs — Fig. 1 must bow out cleanly.
    bare = [Paper(title=f"Untitled {i}", abstract="a", authors=[]) for i in range(1, 4)]
    yield ("sparse source metadata",
           _article("A topic with poorly indexed sources", _SECTIONS),
           bare,
           {"relevance": {1: "direct", 2: "related", 3: "tangential"},
            "most_relevant_index": 1, "counts": {"direct": 1, "related": 1, "tangential": 1}},
           None, provenance, "poorly indexed topic")

    # 4. Forty years of sources — Fig. 1 must switch to 5-year bins.
    wide_years = [1984, 1989, 1993, 1997, 2001, 2004, 2008, 2011, 2015, 2018, 2021, 2024]
    wide = _papers(12, years=wide_years)
    yield ("wide year range",
           _article("A long-running literature", _SECTIONS,
                    references=list(range(1, 13)),
                    key_points=[f"Point {i} [{i}]." for i in range(1, 6)]),
           wide,
           {"relevance": {i: ("direct" if i % 3 == 0 else "related" if i % 3 == 1 else "tangential")
                          for i in range(1, 13)},
            "most_relevant_index": 3,
            "counts": {"direct": 4, "related": 4, "tangential": 4}},
           None, provenance, "a long-running literature")

    # 5. Many authors and a clinical topic — reference truncation + disclaimer.
    crowded = _papers(3)
    crowded[0].authors = [f"Given{i} Sur{i}" for i in range(1, 12)]
    yield ("many authors, clinical topic",
           _article("Treatment response in a patient population", _SECTIONS,
                    references=[1, 2, 3]),
           crowded,
           {"relevance": {1: "direct", 2: "direct", 3: "related"},
            "most_relevant_index": 1, "counts": {"direct": 2, "related": 1, "tangential": 0}},
           {"unverified": ["-0.90", "4.91", "12.5"], "total": 8}, provenance,
           "treatment response in patients")


def main() -> int:
    for name, article, papers, curation, verification, provenance, topic in fixtures():
        print(f"\n# {name}")
        html = render_article(article, papers, topic, curation, verification, provenance)
        render_markdown(article, papers, topic, curation, verification, provenance)
        for convention, predicate in CONVENTIONS:
            try:
                ok = bool(predicate(html, article))
            except Exception as exc:  # a convention that blows up is a failure
                ok, convention = False, f"{convention} (raised {exc!r})"
            print(("OK   " if ok else "FAIL ") + convention)
            if not ok:
                FAILURES.append(f"{name}: {convention}")

    print(f"\n{'FAILED: ' + '; '.join(FAILURES) if FAILURES else 'ALL CONVENTIONS MET'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

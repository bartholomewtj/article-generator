"""Deterministic grounding check for the statistics in a generated article.

The writer sees abstracts, plus — for open-access sources — the same full-text
excerpts that `sources.full_text_excerpts` yields. It is prone to stating
precise figures (effect sizes, confidence intervals, risk ratios) it was never
shown. This pass extracts the decimal/percentage figures the article asserts
and checks whether each appears in that same material. Anything missing is
surfaced to the reader as "verify against the full text" rather than trusted.

The haystack is exactly what the writer was shown, not the whole retrieved
paper: searching text the writer never saw would let a figure recalled from
training pass as grounded. `full_text_excerpts` is deterministic over the
papers, so both sides derive the same excerpts without anything recorded.

It is intentionally deterministic — an LLM verifier can hallucinate agreement;
substring presence in the real source text cannot.
"""

from __future__ import annotations

import re

from .sources import Paper, full_text_excerpts

# Decimals (0.90, -0.38, 4.91) and percentages (12%, 3.5%) — the figures most at
# risk of being reconstructed from memory. Plain integers (years, counts) are
# excluded to avoid noise.
_FIGURE_RE = re.compile(r"-?\d+\.\d+%?|\b\d{1,3}%")


def _normalize(token: str) -> str:
    return token.lstrip("+-").rstrip("%")


def _article_text(article: dict) -> str:
    # `standfirst` / `key_takeaways` are the pre-journal-format field names; they are
    # still read so drafts written against the old schema keep being checked.
    parts = [
        article.get("abstract", "") or article.get("standfirst", ""),
        article.get("evidence_note", ""),
    ]
    fs = article.get("featured_study") or {}
    parts += [fs.get("method", ""), fs.get("results", "")]
    for section in article.get("sections", []):
        parts.extend(section.get("paragraphs", []))
        if section.get("pull_quote"):
            parts.append(section["pull_quote"])
    parts.extend(article.get("key_points") or article.get("key_takeaways") or [])
    return "\n".join(parts)


def check_statistics(article: dict, papers: list[Paper]) -> dict:
    """Return {'unverified': [figures not found in the shown material], 'total': n}."""
    shown = full_text_excerpts(papers)
    haystack = " ".join(p.abstract or "" for p in papers)
    if shown:
        haystack += " " + " ".join(shown.values())
    haystack_norm = haystack.replace(" ", "")

    seen: set[str] = set()
    unverified: list[str] = []
    total = 0
    for match in _FIGURE_RE.findall(_article_text(article)):
        norm = _normalize(match)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        total += 1
        # present verbatim, or with the percent sign, or without spaces
        if norm in haystack or f"{norm}%" in haystack or norm in haystack_norm:
            continue
        unverified.append(match)
    return {"unverified": unverified, "total": total}

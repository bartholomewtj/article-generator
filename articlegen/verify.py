"""Deterministic grounding check for the statistics in a generated article.

The writer only ever sees abstracts, yet is prone to stating precise figures
(effect sizes, confidence intervals, risk ratios) that live in full-text tables.
This pass extracts the decimal/percentage figures the article asserts and checks
whether each actually appears in the fetched abstracts. Anything missing is
surfaced to the reader as "verify against the full text" rather than trusted.

It is intentionally deterministic — an LLM verifier can hallucinate agreement;
substring presence in the real abstract text cannot.
"""

from __future__ import annotations

import re

from .sources import Paper

# Decimals (0.90, -0.38, 4.91) and percentages (12%, 3.5%) — the figures most at
# risk of being reconstructed from memory. Plain integers (years, counts) are
# excluded to avoid noise.
_FIGURE_RE = re.compile(r"-?\d+\.\d+%?|\b\d{1,3}%")


def _normalize(token: str) -> str:
    return token.lstrip("+-").rstrip("%")


def _article_text(article: dict) -> str:
    parts = [article.get("standfirst", ""), article.get("evidence_note", "")]
    fs = article.get("featured_study") or {}
    parts += [fs.get("method", ""), fs.get("results", "")]
    for section in article.get("sections", []):
        parts.extend(section.get("paragraphs", []))
        if section.get("pull_quote"):
            parts.append(section["pull_quote"])
    parts.extend(article.get("key_takeaways", []))
    return "\n".join(parts)


def check_statistics(article: dict, papers: list[Paper]) -> dict:
    """Return {'unverified': [figures not found in any abstract], 'total': n}."""
    haystack = " ".join(p.abstract or "" for p in papers)
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

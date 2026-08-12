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

# Decimals (0.90, -0.38, 4.91), percentages (12%, 3.5%), clinical counts (n=60, 25-mg),
# and effect metrics (d=-1.70, CI: 1.2-3.4). Plain years (2020-2026) are excluded.
_FIGURE_RE = re.compile(
    r"-?\d+\.\d+%?"
    r"|\b\d{1,3}%"
    r"|\b(?:n\s*=\s*\d+|\d+-(?:mg|week|month|year|arm|day|patient|participant|subject)s?)\b"
    r"|\b(?:CI|p|d|OR|RR|HR)\s*=\s*-?\d+(?:\.\d+)?\b",
    re.IGNORECASE,
)

# Common publication years to skip during standalone integer extraction
_YEAR_RE = re.compile(r"\b(?:19\d\d|20[0-2]\d)\b")


def _normalize(token: str) -> str:
    return re.sub(r"^[+\-\s]+|[+\-\s%]+$", "", token)


def _article_sentences(article: dict) -> list[tuple[str, list[int]]]:
    """Yields (sentence_text, list_of_cited_source_indices)."""
    text = _article_text(article)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result = []
    for s in sentences:
        cites = [int(n) for n in re.findall(r"\[(\d+)\]", s)]
        result.append((s, cites))
    return result


def _paper_haystack(paper: Paper, full_texts: dict[int, str], idx: int) -> str:
    parts = [paper.abstract or ""]
    if idx in full_texts:
        parts.append(full_texts[idx])
    return " ".join(parts)


def _article_text(article: dict) -> str:
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
    paper_map = {i: _paper_haystack(p, shown, i) for i, p in enumerate(papers, start=1)}
    global_haystack = " ".join(paper_map.values())
    global_haystack_norm = global_haystack.replace(" ", "")

    seen: set[str] = set()
    unverified: list[str] = []
    total = 0

    sentences = _article_sentences(article)
    for sentence, cites in sentences:
        # Build local haystack for cited sources in this sentence, or fall back to global
        if cites:
            local_haystack = " ".join(paper_map[i] for i in cites if i in paper_map)
        else:
            local_haystack = global_haystack

        local_norm = local_haystack.replace(" ", "")

        for match in _FIGURE_RE.findall(sentence):
            if _YEAR_RE.fullmatch(match.strip()):
                continue
            norm = _normalize(match)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            total += 1

            # Match against local scoped haystack, falling back to global
            found = (
                norm in local_haystack
                or f"{norm}%" in local_haystack
                or norm in local_norm
                or norm in global_haystack
                or norm in global_haystack_norm
            )
            if found:
                continue
            unverified.append(match)

    return {"unverified": unverified, "total": total}

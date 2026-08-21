"""Deterministic grounding check for the statistics in a generated article.

The writer sees abstracts, plus — for open-access sources — the same full-text
excerpts that `sources.full_text_excerpts` yields. It is prone to stating
precise figures (effect sizes, confidence intervals, risk ratios) it was never
shown. This pass extracts the figures the article asserts and checks whether
each appears in that same material. Anything missing is surfaced to the reader
as "verify against the full text" rather than trusted.

The haystack is exactly what the writer was shown, not the whole retrieved
paper: searching text the writer never saw would let a figure recalled from
training pass as grounded. `full_text_excerpts` is deterministic over the
papers, so both sides derive the same excerpts without anything recorded.

**A cited sentence is checked against its own sources only.** Searching every
source and passing on any hit is what this used to do, and it hid the failure
that most changes clinical meaning: a real number lifted from paper 12 and
credited in the prose to paper 3 passed silently as verified. That case is now
reported separately as `misattributed` — the figure is real, the attribution is
not. A sentence citing nothing has no attribution to break, so it is still
checked against everything.

It is intentionally deterministic — an LLM verifier can hallucinate agreement;
substring presence in the real source text cannot. The corollary is that the
check is deliberately generous about *form*: it asks whether the number is
there at all, not whether the surrounding words match. A missed figure is a
warning the reader never sees; a false flag is a wrong warning printed in the
article.
"""

from __future__ import annotations

import re

from .sources import Paper, full_text_excerpts

# Units that make a bare integer a clinical quantity rather than a year, a
# citation marker or ordinary prose. An integer without one is not extracted:
# checking every loose number produces noise, not grounding. Longer forms come
# first so the alternation does not clip them (`ng` before `ng/mL` would).
# Single letters (g, L, h) are left out — under IGNORECASE they match far too
# much for what they would buy.
_CLINICAL_UNITS = (
    r"ng/m[lL]|[mµn]mol/[lL]|mcg|µg|mg|kg|ng|mL|IU|lux|"
    r"minute|min|hour|day|week|month|year|"
    r"participant|patient|subject|children|child|adult|case|women|men|"
    r"session|episode|admission|arm"
)

# Decimals (0.90, -0.38, 4.91), percentages (12%, 3.5%), sample sizes (n=60),
# effect metrics (d=-1.70, CI: 1.2-3.4), and integers carrying a clinical unit
# (7,000 lux, 15 minutes, 50 ng/mL, 441 participants, 25-mg). Plain years
# (2020-2026) are excluded.
_FIGURE_RE = re.compile(
    r"-?\d+\.\d+%?"
    r"|\b\d{1,3}%"
    r"|\bn\s*=\s*\d+\b"
    r"|\b(?:CI|p|d|OR|RR|HR)\s*=\s*-?\d+(?:\.\d+)?\b"
    r"|\b(?P<quantity>\d[\d,]*\s*-?\s*(?:" + _CLINICAL_UNITS + r")s?)\b",
    re.IGNORECASE,
)

# Common publication years to skip during standalone integer extraction
_YEAR_RE = re.compile(r"\b(?:19\d\d|20[0-2]\d)\b")

# The number a quantity leads with, which is the part that has to be real.
_LEADING_NUMBER_RE = re.compile(r"^\d[\d,]*")


def _normalize(token: str) -> str:
    return re.sub(r"^[+\-\s]+|[+\-\s%]+$", "", token)


def _variants(text: str) -> tuple[str, str, str]:
    """(raw, spaces stripped, commas stripped) forms of a haystack.

    One quantity gets written all three ways: `n = 60` against `n=60`, `7,000`
    against `7000`. Stripping on the haystack side is cheaper than enumerating
    the spellings on the figure side.
    """
    return text, text.replace(" ", ""), text.replace(",", "")


def _found(figure: str, haystack: tuple[str, str, str], quantity: bool) -> bool:
    """Is this figure present in this haystack?"""
    raw, nospace, nocomma = haystack
    norm = _normalize(figure)
    if not norm:
        return False
    if norm in raw or f"{norm}%" in raw or norm.replace(" ", "") in nospace:
        return True
    if not quantity:
        return False
    # A quantity verifies on its number alone. The source may write the same
    # amount with a different unit form ("50 ng/mL" against "50 ng per mL", "15
    # minutes" against "15-min"), and demanding the words match would flag
    # figures that are in fact grounded. Digit boundaries stop 50 matching
    # inside 1950 or 0.50.
    number = _LEADING_NUMBER_RE.match(norm)
    if not number:
        return False
    digits = number.group(0).replace(",", "")
    return re.search(rf"(?<![\d.,]){re.escape(digits)}(?![\d,])", nocomma) is not None


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
        article.get("question", ""),
        article.get("answer", "") or article.get("abstract", "") or article.get("standfirst", ""),
        article.get("evidence_note", ""),
    ]
    fs = article.get("featured_study") or {}
    parts += [fs.get("method", ""), fs.get("results", "")]
    parts.extend(article.get("findings") or [])
    parts.extend(article.get("unknowns") or [])
    for section in article.get("sections", []):
        parts.extend(section.get("paragraphs", []))
        if section.get("pull_quote"):
            parts.append(section["pull_quote"])
    parts.extend(article.get("key_points") or article.get("key_takeaways") or [])
    return "\n".join(parts)


def check_statistics(article: dict, papers: list[Paper]) -> dict:
    """Check every figure the article asserts against the sources it credits.

    Returns three keys:

    - `unverified` — figures found in none of the material the writer was shown.
    - `misattributed` — figures that are real, but appear only in a source other
      than the one their sentence cites.
    - `total` — figures checked. A figure credited to two different sources is
      two claims and counts twice.
    """
    shown = full_text_excerpts(papers)
    paper_map = {i: _paper_haystack(p, shown, i) for i, p in enumerate(papers, start=1)}
    everything = _variants(" ".join(paper_map.values()))

    # Sentences citing the same sources share a haystack; most articles cite the
    # same handful of papers repeatedly.
    local_cache: dict[tuple[int, ...], tuple[str, str, str]] = {}

    seen: set[tuple[str, tuple[int, ...]]] = set()
    unverified: list[str] = []
    misattributed: list[str] = []
    total = 0

    for sentence, cites in _article_sentences(article):
        cited = tuple(sorted({i for i in cites if i in paper_map}))
        if cited:
            if cited not in local_cache:
                local_cache[cited] = _variants(" ".join(paper_map[i] for i in cited))
            local = local_cache[cited]
        else:
            # Nothing cited — no attribution to break, so the whole evidence
            # base is the right haystack.
            local = everything

        for match in _FIGURE_RE.finditer(sentence):
            text = match.group(0)
            if _YEAR_RE.fullmatch(text.strip()):
                continue
            norm = _normalize(text)
            if not norm:
                continue
            # Keyed on the attribution as well as the figure: the same number
            # credited to two different sources is two claims, and the second
            # one is exactly the case worth catching.
            if (norm, cited) in seen:
                continue
            seen.add((norm, cited))
            total += 1

            quantity = match.group("quantity") is not None
            if _found(text, local, quantity):
                continue
            if cited and _found(text, everything, quantity):
                misattributed.append(text)
            else:
                unverified.append(text)

    return {"unverified": unverified, "misattributed": misattributed, "total": total}

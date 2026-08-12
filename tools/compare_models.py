#!/usr/bin/env python
"""Run one topic through two models and put the results side by side.

The OpenRouter default is `anthropic/claude-opus-5` ($5/$25 per Mtok).
`anthropic/claude-sonnet-5` is $2/$10 — **2.5x cheaper** — and is the model the
#63 test actually validated on this pipeline. Since then the pipeline gained
full-text grounding, the layout rearrange and truthful provenance, and Sonnet
has never been run through it (#85).

    python tools/compare_models.py "bright light therapy for schizophrenia"
    python tools/compare_models.py "..." --models anthropic/claude-opus-5 anthropic/claude-sonnet-5

Both runs use the same topic on the same day, and `sources.py` caches searches
for 24h, so the second run sees the same evidence base as the first. Each
article is written to `drafts/` so the part that matters can be read.

## What this can and cannot tell you

It measures what is countable: style-gate failures by rule, unverified and
misattributed figures, section and word counts, hedging density, how much of
the evidence base each draft actually cited, and token cost from the provider's
own accounting.

It **cannot** tell you whether a draft *adjudicates* its evidence base — whether
it notices that a meta-analysis and two register studies disagree, and says why.
That is the behaviour the whole thing exists for, and reading two articles is
the only way to judge it. The contrast-marker count below is a hint about where
to look, not a score: a draft can hedge its way to a high count while
adjudicating nothing.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from articlegen.pipeline import generate_draft  # noqa: E402
from articlegen.style import errors as style_errors  # noqa: E402

# OpenRouter list prices, $ per million tokens (input, output). Used only for
# an estimate — the OpenRouter activity log is the authority, and these go
# stale. Unknown models are reported in tokens with no dollar figure rather
# than with a wrong one.
PRICES = {
    "anthropic/claude-opus-5": (5.0, 25.0),
    "anthropic/claude-sonnet-5": (2.0, 10.0),
    "anthropic/claude-fable-5": (5.0, 25.0),
}

DEFAULT_MODELS = ["anthropic/claude-opus-5", "anthropic/claude-sonnet-5"]

# Where a review adjudicates rather than summarises, these tend to appear. A
# hint about where to read, never a score.
CONTRAST = ("however", "in contrast", "by contrast", "whereas", "conversely",
            "disagree", "disagreement", "conflict", "inconsistent",
            "at odds", "does not replicate", "failed to replicate",
            "unlike", "although", "nevertheless")

_USAGE = re.compile(r"\[articlegen\] openrouter \S+ in=(\d+) cached=(\d+) out=(\d+)")


def _article_text(article: dict) -> str:
    parts = [article.get("abstract", "")]
    for section in article.get("sections", []):
        parts.extend(section.get("paragraphs", []))
    parts.extend(article.get("key_points") or [])
    return "\n".join(parts)


def run(topic: str, model: str) -> dict:
    print(f"\n=== {model} ===", flush=True)
    captured = io.StringIO()
    real_stderr = sys.stderr
    try:
        # The provider logs its own token counts to stderr; tee them so the run
        # stays watchable and the numbers are still collectable.
        class Tee:
            def write(self, s):
                real_stderr.write(s)
                captured.write(s)

            def flush(self):
                real_stderr.flush()

        sys.stderr = Tee()
        draft = generate_draft(topic, model=model, max_papers=20,
                               log=lambda m: print("  " + m, flush=True))
    finally:
        sys.stderr = real_stderr

    tokens_in = tokens_out = 0
    for m in _USAGE.finditer(captured.getvalue()):
        tokens_in += int(m.group(1))
        tokens_out += int(m.group(3))

    text = _article_text(draft.article)
    sentences = max(1, text.count(". "))
    cited = draft.cited_refs
    return {
        "model": model,
        "draft": draft,
        "sections": len(draft.article.get("sections", [])),
        "words": len(re.findall(r"[A-Za-z][\w'-]*", text)),
        "cited": len(cited),
        "papers": len(draft.papers),
        "counts": (draft.curation or {}).get("counts") or {},
        "style_errors": [i["rule"] for i in style_errors(draft.style_report)],
        "unverified": len(draft.verification.get("unverified") or []),
        "misattributed": len(draft.verification.get("misattributed") or []),
        "figures": draft.verification.get("total", 0),
        "contrast": sum(text.lower().count(c) for c in CONTRAST),
        "contrast_per_sentence": round(
            sum(text.lower().count(c) for c in CONTRAST) / sentences, 3),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def cost(model: str, tokens_in: int, tokens_out: int) -> str:
    if model not in PRICES or not (tokens_in or tokens_out):
        return "n/a"
    pin, pout = PRICES[model]
    return f"${(tokens_in * pin + tokens_out * pout) / 1_000_000:.3f}"


def report(results: list[dict]) -> None:
    rows = [
        ("sources cited / fetched", lambda r: f"{r['cited']}/{r['papers']}"),
        ("direct / related / tangential",
         lambda r: "/".join(str(r["counts"].get(k, 0))
                            for k in ("direct", "related", "tangential"))),
        ("sections", lambda r: r["sections"]),
        ("body words", lambda r: r["words"]),
        ("figures checked", lambda r: r["figures"]),
        ("unverified figures", lambda r: r["unverified"]),
        ("misattributed figures", lambda r: r["misattributed"]),
        ("style errors", lambda r: len(r["style_errors"]) or "none"),
        ("  which rules", lambda r: ", ".join(sorted(set(r["style_errors"]))) or "-"),
        ("contrast markers (hint only)", lambda r: r["contrast"]),
        ("  per sentence", lambda r: r["contrast_per_sentence"]),
        ("input tokens", lambda r: r["tokens_in"] or "?"),
        ("output tokens", lambda r: r["tokens_out"] or "?"),
        ("estimated cost",
         lambda r: cost(r["model"], r["tokens_in"], r["tokens_out"])),
    ]
    width = max(len(label) for label, _ in rows) + 2
    print("\n" + "=" * 78)
    print("METRIC".ljust(width) + "".join(r["model"][-22:].ljust(26) for r in results))
    print("-" * 78)
    for label, fn in rows:
        print(label.ljust(width) + "".join(str(fn(r)).ljust(26) for r in results))
    print("=" * 78)
    print(
        "\nThe countable half is above. The half that decides it is not:\n"
        "  * Does the draft ADJUDICATE its evidence base — notice that studies\n"
        "    disagree and say why — or does it summarise them one after another?\n"
        "  * Are effect estimates given with confidence intervals and a sense of\n"
        "    certainty, or are they bare claims?\n"
        "Read both drafts in drafts/ before deciding. Contrast markers point at\n"
        "paragraphs worth reading; they are not a score, and a draft can hedge\n"
        "its way to a high count while adjudicating nothing.\n"
        "\nCost estimates use list prices in this file and go stale. The\n"
        "OpenRouter activity log is the authority."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("topic")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = ap.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("Set OPENROUTER_API_KEY — both models are OpenRouter slugs.")
        return 2

    results = []
    for model in args.models:
        try:
            results.append(run(args.topic, model))
        except Exception as exc:
            print(f"  {model} failed: {type(exc).__name__}: {exc}")
    if len(results) < 2:
        print("\nNeed two successful runs to compare.")
        return 1
    report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

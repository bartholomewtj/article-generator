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

## Replay mode (`--replay`)

    python tools/compare_models.py --replay tests/replays/2026-09-05-night-shift-health-risk.json
    python tools/compare_models.py --replay <manifest> --models anthropic/claude-opus-5 anthropic/claude-sonnet-5

Reruns the writer on a saved run manifest instead of searching, so both models
see the identical pool, relevance labels and full-text excerpts — the only
variable is the model. It does not re-search, re-curate or refetch full text
(that would let the two runs see different evidence). It does not run the
style/statistics revision passes — the numbers describe raw writer output, not
a shipped article, because a revision pass is an extra model call and would be
comparing post-repair prose rather than the writer itself.

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
import copy
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from articlegen.pipeline import Draft, generate_draft  # noqa: E402
from articlegen.render import render_article, render_markdown  # noqa: E402
from articlegen.sources import full_text_excerpts  # noqa: E402
from articlegen.style import check_style  # noqa: E402
from articlegen.style import errors as style_errors  # noqa: E402
from articlegen.verify import check_statistics
# `_article_text` is private to `articlegen.verify`, but it is the one place
# that already covers a briefing's `answer` / `findings` / `unknowns` as well
# as a review's `sections` and both `key_points` spellings. The local copy
# below only ever read the review fields, which is why replay mode on the
# repo's one real manifest (a briefing) used to score every draft as 0 words.
from articlegen.verify import _article_text  # noqa: E402
from articlegen.writer import is_briefing, write_article, write_briefing  # noqa: E402

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


def _section_count(article: dict) -> int:
    """Sections for a review, findings for a briefing — a briefing has no
    `sections` key, so counting that alone always read 0 for it."""
    if is_briefing(article):
        return len(article.get("findings") or [])
    return len(article.get("sections") or [])


def _tee_tokens(fn):
    """Run `fn()` with stderr teed, so token-usage lines are both watchable and
    collectable, and return `(fn()'s result, tokens_in, tokens_out)`."""
    captured = io.StringIO()
    real_stderr = sys.stderr
    try:
        class Tee:
            def write(self, s):
                real_stderr.write(s)
                captured.write(s)

            def flush(self):
                real_stderr.flush()

        sys.stderr = Tee()
        result = fn()
    finally:
        sys.stderr = real_stderr

    tokens_in = tokens_out = 0
    for m in _USAGE.finditer(captured.getvalue()):
        tokens_in += int(m.group(1))
        tokens_out += int(m.group(3))
    return result, tokens_in, tokens_out


def run(topic: str, model: str) -> dict:
    print(f"\n=== {model} ===", flush=True)
    draft, tokens_in, tokens_out = _tee_tokens(lambda: generate_draft(
        topic, model=model, max_papers=20,
        log=lambda m: print("  " + m, flush=True)))

    text = _article_text(draft.article)
    sentences = max(1, text.count(". "))
    cited = draft.cited_refs
    return {
        "model": model,
        "draft": draft,
        "sections": _section_count(draft.article),
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


def run_replay(draft: Draft, model: str, manifest_stem: str) -> dict:
    """Rerun the writer on `draft`'s saved pool, labels and excerpts.

    A sibling of `run()`, not a branch inside it: `run()` calls
    `generate_draft`, which re-searches, curates and fetches full text —
    exactly the variance replay mode exists to remove. This calls only the
    writer.

    No network beyond the model call. Deliberately does not call
    `generate_draft`, `rerun_draft`, `gather_evidence`, `curate_sources` or
    `_retrieve_full_texts` — `rerun_draft` in particular refetches full text,
    which would defeat "identical inputs" by letting one model's run see a
    different excerpt than another's. The manifest's papers already carry
    `full_text`, so `_writer_context` (via `write_briefing`/`write_article`)
    rebuilds the exact prompt the accepted run used.

    Scores only the raw writer output: `check_style` and `check_statistics`,
    with no `enforce_style` / `enforce_statistics` revision pass. A revision
    pass is an extra model call, and it would compare post-repair prose
    instead of what the model actually wrote.
    """
    print(f"\n=== {model} (replay) ===", flush=True)
    # Deep-copy the papers per model so one model's run cannot mutate the pool
    # (e.g. `is_retracted` flags, cache fields) the next model sees.
    papers = copy.deepcopy(draft.papers)
    counts = (draft.curation or {}).get("counts") or {}
    briefing = is_briefing(draft.article)
    writer_fn = write_briefing if briefing else write_article

    def _write():
        return writer_fn(draft.topic, papers, model=model, style_note="",
                          curation=draft.curation, api_key=None)

    article, tokens_in, tokens_out = _tee_tokens(_write)

    text = _article_text(article)
    sentences = max(1, text.count(". "))
    style_report = check_style(article, direct_sources=counts.get("direct"))
    verification = check_statistics(article, papers)

    new_excerpts = full_text_excerpts(papers)
    provenance = dict(draft.provenance)
    provenance["model"] = model
    result_draft = Draft(
        topic=draft.topic, article=article, papers=papers,
        curation=draft.curation, verification=verification,
        provenance=provenance, style_report=style_report,
        excerpts=new_excerpts,
    )
    render_args = (result_draft.article, result_draft.papers, result_draft.topic,
                   result_draft.curation, result_draft.verification,
                   result_draft.provenance, result_draft.style_report)
    slug = model.replace("/", "-")
    stem = f"{manifest_stem}-replay-{slug}"
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "drafts")
    os.makedirs(out_dir, exist_ok=True)
    html_path = os.path.join(out_dir, f"{stem}.html")
    md_path = os.path.join(out_dir, f"{stem}.md")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_article(*render_args))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(*render_args))
    print(f"  HTML:     {html_path}")
    print(f"  Markdown: {md_path}")

    cited = result_draft.cited_refs
    return {
        "model": model,
        "draft": result_draft,
        "sections": _section_count(article),
        "words": len(re.findall(r"[A-Za-z][\w'-]*", text)),
        "cited": len(cited),
        "papers": len(papers),
        "counts": counts,
        "style_errors": [i["rule"] for i in style_errors(style_report)],
        "unverified": len(verification.get("unverified") or []),
        "misattributed": len(verification.get("misattributed") or []),
        "figures": verification.get("total", 0),
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
        ("sections / findings", lambda r: r["sections"]),
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


def _print_replay_header(manifest_path: str, draft: Draft) -> None:
    counts = (draft.curation or {}).get("counts") or {}
    n_full_text = sum(1 for p in draft.papers if p.full_text)
    print(f"Manifest: {manifest_path}")
    print(f"Topic:    {draft.topic}")
    print(f"Pool:     {len(draft.papers)} papers "
          f"(direct {counts.get('direct', 0)}, related {counts.get('related', 0)}, "
          f"tangential {counts.get('tangential', 0)}); "
          f"{n_full_text} carry full text")
    print("Replay mode: raw writer output only, no revision pass — see the "
          "module docstring.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("topic", nargs="?",
                     help="Topic to search and write from scratch.")
    ap.add_argument("--replay", metavar="PATH",
                     help="Rerun the writer on a saved run manifest instead of searching.")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = ap.parse_args()

    if bool(args.topic) == bool(args.replay):
        print("Give exactly one of `topic` or `--replay <manifest>`, not both/neither.")
        return 2

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("Set OPENROUTER_API_KEY — both models are OpenRouter slugs.")
        return 2

    results = []
    if args.replay:
        with open(args.replay, encoding="utf-8") as f:
            raw_manifest = json.load(f)
        manifest_stem = os.path.splitext(os.path.basename(args.replay))[0]
        base_draft = Draft.from_dict(raw_manifest)
        _print_replay_header(args.replay, base_draft)
        for model in args.models:
            try:
                # Rebuild the Draft per model so one model's run cannot mutate
                # the pool (e.g. retraction flags) the next one sees.
                model_draft = Draft.from_dict(raw_manifest)
                results.append(run_replay(model_draft, model, manifest_stem))
            except Exception as exc:
                print(f"  {model} failed: {type(exc).__name__}: {exc}")
    else:
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

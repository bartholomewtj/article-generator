#!/usr/bin/env python
"""Does curating on truncated abstracts still label sources the same way?

`curate_sources` sends every candidate's full abstract — ~39,000 input tokens
for 20 papers. Relevance labelling plausibly turns on the title, the topic and
the population, which live in the first few hundred characters, so truncating
would take the call to roughly 15,000 (#117).

**That is a hypothesis about the relevance gate, and the gate is load-bearing.**
`style._required_sections` scales the section floor with the `direct` count, so
under-calling `direct` lets a thinner article pass. `write_article` omits
`tangential` sources from the prompt, so under-calling `tangential` puts
background abstracts back in front of the writer. And the failure mode is not
theoretical: running curation at a cheaper reasoning tier agreed with the full
tier on only 14 of 20 labels, with every disagreement collapsing toward
"related".

So this script measures it rather than assuming.

    python tools/compare_curation.py --chars 400
    python tools/compare_curation.py --chars 400 --topics "light therapy" "peer support"

It fetches each topic's papers **once** and runs curation twice over the same
list, so the only variable is the prompt length. Costs two curation calls per
topic plus one search each — real credit and real quota, which is why it is a
tool rather than a test.

## The acceptance rule

`direct` and `tangential` must both be stable. **Agreement on `related` alone is
not enough** — that is exactly where a degraded run parks everything, so a run
that collapsed every label to "related" would score well on overall agreement
while destroying the gate.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from articlegen.sources import gather_evidence  # noqa: E402
from articlegen.writer import curate_sources, plan_queries  # noqa: E402

DEFAULT_TOPICS = [
    "bright light therapy for schizophrenia",
    "peer support workers in acute mental health care",
    "ketamine for treatment-resistant depression",
    "shift work and cardiometabolic risk",
]

LABELS = ("direct", "related", "tangential")

# How far a label may move before the change is a downgrade of the gate rather
# than noise. One flip in twenty on a label that gates nothing is tolerable; one
# flip on `direct` or `tangential` is not, because both have a downstream
# consumer that reads the count.
CRITICAL = ("direct", "tangential")


def compare(topic: str, chars: int, model: str | None, max_papers: int) -> dict:
    print(f"\n=== {topic} ===", flush=True)
    queries, core = plan_queries(topic, model=model)
    papers = gather_evidence(queries, max_papers=max_papers, topic=topic,
                             core_entity=core, log=lambda m: None)
    if not papers:
        print("  no papers; skipping")
        return {}
    print(f"  {len(papers)} papers")

    full = curate_sources(topic, papers, model=model)
    short = curate_sources(topic, papers, model=model, abstract_chars=chars)
    if not full.get("relevance") or not short.get("relevance"):
        print("  curation returned no labels; skipping")
        return {}

    rows = []
    for i in range(1, len(papers) + 1):
        a, b = full["relevance"].get(i), short["relevance"].get(i)
        if a and b:
            rows.append((i, a, b, papers[i - 1].title[:54]))

    agree = sum(1 for _, a, b, _ in rows if a == b)
    print(f"  agreement: {agree}/{len(rows)}")
    for i, a, b, title in rows:
        if a != b:
            flag = "  <-- CRITICAL" if a in CRITICAL or b in CRITICAL else ""
            print(f"    [{i:2}] {a:>10} -> {b:<10} {title}{flag}")

    print(f"  counts full : {full.get('counts')}")
    print(f"  counts short: {short.get('counts')}")
    return {"topic": topic, "rows": rows,
            "full": full.get("counts", {}), "short": short.get("counts", {})}


def verdict(results: list[dict]) -> bool:
    rows = [r for res in results for r in res.get("rows", [])]
    if not rows:
        print("\nNo comparable labels. Nothing is settled.")
        return False

    agree = sum(1 for _, a, b, _ in rows if a == b)
    print(f"\n{'=' * 60}\nOverall: {agree}/{len(rows)} labels agree")

    # Per-label recall against the full-abstract run, which is the reference.
    ok = True
    for label in LABELS:
        held = [(a, b) for _, a, b, _ in rows if a == label]
        if not held:
            continue
        kept = sum(1 for a, b in held if b == label)
        marker = ""
        if label in CRITICAL and kept < len(held):
            marker = "   <-- gate degraded"
            ok = False
        print(f"  {label:>10}: {kept}/{len(held)} retained{marker}")

    # The specific failure seen before: everything collapsing toward "related".
    drifted = sum(1 for _, a, b, _ in rows if a != b and b == "related")
    if drifted:
        print(f"\n  {drifted} label(s) moved TO 'related' — the collapse seen "
              "when curation ran at a cheaper tier.")

    print()
    if ok:
        print("PASS: direct and tangential were both stable. Truncation is "
              "safe to adopt — set writer.CURATION_ABSTRACT_CHARS.")
    else:
        print("FAIL: a gating label moved. Do not truncate. Agreement on "
              "'related' alone is not enough.")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chars", type=int, default=400,
                    help="abstract characters to keep (default 400)")
    ap.add_argument("--topics", nargs="*", default=DEFAULT_TOPICS)
    ap.add_argument("--model", default=None)
    ap.add_argument("--max-papers", type=int, default=20)
    args = ap.parse_args()

    if not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            or args.model):
        print("Set OPENROUTER_API_KEY / ANTHROPIC_API_KEY, or pass --model cli:opus.")
        return 2

    print(f"Comparing full abstracts against {args.chars}-character abstracts "
          f"over {len(args.topics)} topic(s).")
    results = [r for t in args.topics
               if (r := compare(t, args.chars, args.model, args.max_papers))]
    return 0 if verdict(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

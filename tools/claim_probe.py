#!/usr/bin/env python
"""Probe: does a cheap second model catch non-numeric overreach in a claim?

    python tools/claim_probe.py --worksheet          # build the by-hand reading file
    python tools/claim_probe.py --show all           # print every pair for reading
    python tools/claim_probe.py --show 3             # print one pair
    python tools/claim_probe.py --run                # call the model, write results
    python tools/claim_probe.py --score              # print the agreement report

All modes default to the one replay fixture
`tests/replays/2026-09-05-night-shift-health-risk.json`. Pass a different
manifest as the first positional argument.

## What this is (and is not)

`articlegen/verify.py`'s `check_statistics` is deterministic: it checks that
every *number* an article states appears in the material the writer was
shown. It cannot see non-numeric overreach — a sentence that turns an
association into a cause, widens the population, drops a qualifier, or
reports an outcome the source never measured.

This script measures whether a cheap second model, shown one sentence and
the exact excerpt it cites, catches that kind of overreach — and whether it
agrees with a reading done by hand. It is a **probe**, not a product:

- It is not imported by `articlegen/` anywhere, and nothing in the pipeline's
  draft-generation entry point calls it.
- It never revises an article. It only produces verdicts and a report.
- The deterministic verifier in `verify.py` remains the only thing that ever
  flags an article. This script cannot change that on its own; a warning
  driven by this probe, if one is ever added, is separate work.

## Method

The 12 sentences in the one replay fixture that carry a citation, each
paired with the exact haystack (title + abstract + full-text excerpt)
`check_statistics` already judges them against — so the probe is a second
opinion on the same units the verifier uses, not on a different split of the
text. `--worksheet` writes the pairs to a labels file for reading by hand
*before* the model runs (see `tools/claim_probe_labels.json`); `--run` then
calls the model; `--score` compares the two, offline.
"""

from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from articlegen.llm import generate_json  # noqa: E402
from articlegen.pipeline import Draft  # noqa: E402
from articlegen.sources import full_text_excerpts  # noqa: E402

# `_article_sentences` and `_paper_haystack` are private to `articlegen.verify`.
# Imported anyway: this probe is a second opinion on exactly the units the
# deterministic verifier already judges — the same sentence split and the
# same haystack (title + abstract + the full-text excerpt the writer was
# shown). Rebuilding either by hand would make the probe an opinion about
# different text, and any disagreement would be about the split rather than
# the claim. `tools/compare_models.py` imports `verify._article_text` for the
# same reason.
from articlegen.verify import _article_sentences, _paper_haystack  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST = os.path.join(REPO_ROOT, "tests", "replays",
                                 "2026-09-05-night-shift-health-risk.json")
LABELS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "claim_probe_labels.json")
RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "claim_probe_results.json")

DEFAULT_MAX_CHARS = 14000

# Cheap, and a different model family from the writer's default
# anthropic/claude-opus-5 — the point is a second, independent opinion.
PROBE_MODEL = "openai/gpt-5.6-luna"

_PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["supported", "overreach", "unclear"]},
        "quote": {
            "type": "string",
            "description": "≤25 words copied verbatim from the excerpt, or empty if nothing fits.",
        },
        "note": {"type": "string", "description": "≤25 words on why."},
    },
    "required": ["verdict", "quote", "note"],
    "additionalProperties": False,
}

_PROBE_SYSTEM = """\
You judge whether ONE sentence from a health article is supported by the \
excerpt it cites. Use only three labels:

- "supported" -- the excerpt states the claim or plainly entails it. \
Different wording is fine if the meaning holds.
- "overreach" -- the sentence goes further than the excerpt: an association \
stated as a cause, a wider population than the excerpt studied, a dropped \
qualifier or hedge, a certainty the excerpt does not carry, or an outcome \
the excerpt never reports.
- "unclear" -- the excerpt does not settle it either way.

Judge only this sentence against only this excerpt. Use no outside \
knowledge of the topic. Numbers are already checked by a separate \
deterministic pass -- judge the claim, not the arithmetic. Quote directly \
from the excerpt, or leave `quote` empty rather than paraphrasing.\
"""

# Mirrors `tools/compare_models.py`'s `_tee_tokens`: run a callable with
# stderr teed so the `[articlegen] openrouter ... in=... out=` lines stay
# watchable AND collectable. A local copy, not an import, per house style for
# tool scripts (compare_models.py does the same for its own helpers).
_USAGE = re.compile(r"\[articlegen\] openrouter \S+ in=(\d+) cached=(\d+) out=(\d+)")


def _tee_tokens(fn):
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


def _load_manifest(path: str) -> tuple[dict, Draft]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return raw, Draft.from_dict(raw)


def pairs(draft: Draft, max_chars: int = DEFAULT_MAX_CHARS) -> list[dict]:
    """One record per cited sentence: the sentence and the excerpt it cites.

    Pure: same manifest and max_chars in, identical list out. No I/O, no
    model call.
    """
    shown = full_text_excerpts(draft.papers)
    n_papers = len(draft.papers)
    out: list[dict] = []
    next_id = 1
    for sentence, cites in _article_sentences(draft.article):
        cited = sorted({i for i in cites if 1 <= i <= n_papers})
        if not cited:
            continue
        sources = []
        excerpt_parts = []
        for i in cited:
            paper = draft.papers[i - 1]
            title = paper.title or ""
            sources.append({
                "index": i,
                "title": title,
                "year": paper.year,
                "has_full_text": i in shown,
            })
            haystack = _paper_haystack(paper, shown, i)
            excerpt_parts.append(f"SOURCE [{i}] {title}\n{haystack}")
        excerpt = "\n\n".join(excerpt_parts)
        excerpt_chars = len(excerpt)
        truncated = excerpt_chars > max_chars
        if truncated:
            excerpt = excerpt[:max_chars]
        out.append({
            "id": next_id,
            "sentence": sentence,
            "cited": cited,
            "sources": sources,
            "excerpt": excerpt,
            "excerpt_chars": excerpt_chars,
            "truncated": truncated,
        })
        next_id += 1
    return out


def _prompt(topic: str, record: dict) -> str:
    cited = ", ".join(f"[{i}]" for i in record["cited"])
    return (
        f"Topic: {topic}\n"
        f"Cited source(s): {cited}\n\n"
        f"SENTENCE:\n{record['sentence']}\n\n"
        f"--- EXCERPT ---\n{record['excerpt']}\n--- END EXCERPT ---\n"
    )


def run_probe(records: list[dict], model: str, topic: str = "",
              generate=generate_json) -> list[dict]:
    """Call `generate` once per record. A seam for tests: pass a stub.

    One failed call must not lose the other pairs -- each call is wrapped in
    its own try/except and recorded as `verdict: "error"` on failure.
    """
    results = []
    for record in records:
        prompt = _prompt(topic, record)
        try:
            reply = generate(prompt, _PROBE_SCHEMA, system=_PROBE_SYSTEM, model=model)
            results.append({
                "id": record["id"],
                "verdict": reply.get("verdict"),
                "quote": reply.get("quote", ""),
                "note": reply.get("note", ""),
                "truncated": record["truncated"],
                "excerpt_chars": record["excerpt_chars"],
            })
        except Exception as exc:
            results.append({
                "id": record["id"],
                "verdict": "error",
                "error": f"{type(exc).__name__}: {exc}"[:200],
                "truncated": record["truncated"],
                "excerpt_chars": record["excerpt_chars"],
            })
    return results


def score(labels: list[dict], results: list[dict]) -> dict:
    """Pure comparison of a by-hand reading against the model's verdicts.

    No I/O. Takes and returns plain data so a test can call it on
    hand-made input.
    """
    results_by_id = {r["id"]: r for r in results}
    dropped_no_human: list[int] = []
    dropped_error: list[int] = []
    compared: list[dict] = []

    for label in labels:
        pid = label["id"]
        human = label.get("human")
        result = results_by_id.get(pid)
        if human is None:
            dropped_no_human.append(pid)
            continue
        if result is None or result.get("verdict") == "error":
            dropped_error.append(pid)
            continue
        compared.append({
            "id": pid,
            "sentence": label.get("sentence", ""),
            "human": human,
            "human_reason": label.get("reason", ""),
            "model": result.get("verdict"),
            "model_note": result.get("note", ""),
            "model_quote": result.get("quote", ""),
        })

    def collapse(v: str) -> str:
        return "supported" if v == "supported" else "not supported"

    exact = sum(1 for c in compared if c["human"] == c["model"])
    collapsed = sum(1 for c in compared if collapse(c["human"]) == collapse(c["model"]))
    confusion: dict[str, dict[str, int]] = {}
    for c in compared:
        confusion.setdefault(c["human"], {}).setdefault(c["model"], 0)
        confusion[c["human"]][c["model"]] += 1
    disagreements = [c for c in compared if c["human"] != c["model"]]

    return {
        "n": len(compared),
        "dropped_no_human": dropped_no_human,
        "dropped_error": dropped_error,
        "exact": exact,
        "collapsed": collapsed,
        "confusion": confusion,
        "disagreements": disagreements,
    }


def _print_pair(record: dict) -> None:
    print(f"\n=== pair {record['id']} ===")
    print(f"cited: {record['cited']}")
    for s in record["sources"]:
        print(f"  [{s['index']}] {s['title']} ({s['year']}) "
              f"full_text={'yes' if s['has_full_text'] else 'no'}")
    print(f"\nsentence:\n{record['sentence']}")
    print(f"\nexcerpt ({record['excerpt_chars']} chars"
          f"{', TRUNCATED' if record['truncated'] else ''}):")
    print(record["excerpt"])


def _cmd_worksheet(draft: Draft, max_chars: int, force: bool) -> int:
    if os.path.exists(LABELS_PATH) and not force:
        print(f"{LABELS_PATH} already exists -- refusing to overwrite. "
              "Pass --force to regenerate it (this destroys any reading already done).")
        return 2
    recs = pairs(draft, max_chars)
    entries = [
        {
            "id": r["id"],
            "sentence": r["sentence"],
            "cited": r["cited"],
            "human": None,
            "reason": "",
        }
        for r in recs
    ]
    doc = {
        "manifest": DEFAULT_MANIFEST,
        "manifest_stem": os.path.splitext(os.path.basename(DEFAULT_MANIFEST))[0],
        "read_by": None,
        "read_on": None,
        "note": ("This is a reading done by hand against the excerpt "
                 "`--show all` prints for each pair, before the model ever "
                 "ran. The operator may overwrite any `human` label and "
                 "re-run `--score`; the excerpt itself is not stored here, "
                 "it is rebuilt from the manifest."),
        "entries": entries,
    }
    with open(LABELS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    print(f"Wrote {len(entries)} entries to {LABELS_PATH}. "
          "Read each with --show, fill `human` and `reason`, then --run.")
    return 0


def _load_labels() -> dict:
    with open(LABELS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _cmd_run(draft: Draft, model: str, max_chars: int, limit: int | None,
             allow_unlabelled: bool) -> int:
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("Set OPENROUTER_API_KEY -- the probe calls an OpenRouter slug.")
        return 2
    if not os.path.exists(LABELS_PATH):
        print(f"{LABELS_PATH} does not exist -- run --worksheet first, then "
              "read every pair by hand before --run.")
        return 2
    labels = _load_labels()
    unlabelled = [e["id"] for e in labels["entries"] if e.get("human") is None]
    if unlabelled and not allow_unlabelled:
        print(f"{len(unlabelled)} pair(s) still have human=null "
              f"({unlabelled}). Reading the sentences after seeing the "
              "model's answers anchors the human reading and would make the "
              "agreement number meaningless. Read them first, or pass "
              "--allow-unlabelled to override.")
        return 2

    recs = pairs(draft, max_chars)
    if limit:
        recs = recs[:limit]
    truncated_ids = [r["id"] for r in recs if r["truncated"]]
    if truncated_ids:
        print(f"Truncated excerpt(s) for pair(s) {truncated_ids} at "
              f"--max-chars={max_chars} -- the model sees less than the writer did.")

    results, tokens_in, tokens_out = _tee_tokens(
        lambda: run_probe(recs, model, topic=draft.topic))

    doc = {
        "model": model,
        "date": datetime.date.today().isoformat(),
        "manifest": DEFAULT_MANIFEST,
        "max_chars": max_chars,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "results": results,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    n_errors = sum(1 for r in results if r["verdict"] == "error")
    print(f"\nWrote {len(results)} verdicts to {RESULTS_PATH} "
          f"({n_errors} error(s)). tokens_in={tokens_in} tokens_out={tokens_out}")
    return 0


def _cmd_score() -> int:
    if not os.path.exists(LABELS_PATH):
        print(f"{LABELS_PATH} does not exist -- run --worksheet first.")
        return 2
    if not os.path.exists(RESULTS_PATH):
        print(f"{RESULTS_PATH} does not exist -- run --run first.")
        return 2
    labels_doc = _load_labels()
    with open(RESULTS_PATH, encoding="utf-8") as f:
        results_doc = json.load(f)

    report = score(labels_doc["entries"], results_doc["results"])
    n = report["n"]
    print(f"model: {results_doc.get('model')}   date: {results_doc.get('date')}")
    if report["dropped_no_human"]:
        print(f"dropped (no human label): {report['dropped_no_human']}")
    if report["dropped_error"]:
        print(f"dropped (model error): {report['dropped_error']}")
    print(f"\nexact agreement:     {report['exact']} of {n}")
    print(f"collapsed agreement: {report['collapsed']} of {n} "
          "(supported vs not-supported; overreach+unclear merged)")

    print("\nconfusion (human x model):")
    labels_seen = sorted({*report["confusion"].keys(),
                          *(k for v in report["confusion"].values() for k in v)})
    header = "human\\model".ljust(14) + "".join(l.ljust(14) for l in labels_seen)
    print(header)
    for h in labels_seen:
        row = h.ljust(14)
        for m in labels_seen:
            row += str(report["confusion"].get(h, {}).get(m, 0)).ljust(14)
        print(row)

    if report["disagreements"]:
        print("\ndisagreements:")
        for d in report["disagreements"]:
            print(f"\n  [{d['id']}] {d['sentence']}")
            print(f"    human: {d['human']} -- {d['human_reason']}")
            print(f"    model: {d['model']} -- {d['model_note']}"
                  + (f" (quote: {d['model_quote']!r})" if d["model_quote"] else ""))

    print(f"\nn = {n} is too small for a percentage to mean much -- the "
          "disagreements above are the finding, not the rate.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", nargs="?", default=DEFAULT_MANIFEST,
                     help="Replay manifest to draw pairs from.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--worksheet", action="store_true",
                       help="Write the by-hand labels worksheet.")
    mode.add_argument("--show", metavar="ID_OR_all",
                       help="Print one pair (by id) or all pairs, offline.")
    mode.add_argument("--run", action="store_true",
                       help="Call the model for every pair and write results.")
    mode.add_argument("--score", action="store_true",
                       help="Compare labels and results and print the report.")
    ap.add_argument("--model", default=PROBE_MODEL)
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ap.add_argument("--limit", type=int, default=None,
                     help="First N pairs only, for a cheap trial run.")
    ap.add_argument("--force", action="store_true",
                     help="Allow --worksheet to overwrite an existing labels file.")
    ap.add_argument("--allow-unlabelled", action="store_true",
                     help="Allow --run even if some human labels are still null.")
    args = ap.parse_args()

    if args.score:
        return _cmd_score()

    _, draft = _load_manifest(args.manifest)

    if args.worksheet:
        return _cmd_worksheet(draft, args.max_chars, args.force)

    if args.show is not None:
        recs = pairs(draft, args.max_chars)
        if args.show == "all":
            for r in recs:
                _print_pair(r)
            return 0
        try:
            wanted = int(args.show)
        except ValueError:
            print("--show wants an integer id or 'all'.")
            return 2
        match = next((r for r in recs if r["id"] == wanted), None)
        if not match:
            print(f"No pair with id {wanted} (there are {len(recs)}).")
            return 2
        _print_pair(match)
        return 0

    if args.run:
        return _cmd_run(draft, args.model, args.max_chars, args.limit,
                         args.allow_unlabelled)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

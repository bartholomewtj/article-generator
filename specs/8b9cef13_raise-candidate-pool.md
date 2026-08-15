# Plan — Raise the candidate pool from 20 to 40 (issue #141)

## What this fixes

Three mental-health runs on 2026-08-15 each collected **exactly 20** candidate
papers and cited 16–19 of them. That is near-total inclusion, not curation: the
direct/related/tangential gate had nothing to discard. The concrete cost is in
the issue — the seclusion run's own planned query was "Safewards trial conflict
containment acute mental health wards", yet the Bowers Safewards cluster RCT
never made the pool. A 20-slot pool ranked with a recency weight fills with
recent reviews and crowds out landmark primary trials.

The `--max-papers` flag and its plumbing already exist. This change is only
about **the default every run gets**, and about making that default live in one
place instead of four.

**The trade-off is accepted, not dodged.** Curation cost scales with pool size
(~13,000 input tokens at 20 papers today, so roughly ~26,000 at 40).
`writer.CURATION_ABSTRACT_CHARS` **stays `None`** — issue #117 measured
truncation at 400 chars and it destabilised the gate (`direct` retained 27/30,
`tangential` 12/17, every topic moved at least one gating label). Do **not**
truncate abstracts to pay for the bigger pool. The bigger pool is paid for in
tokens.

## Current state (verified)

The number 20 is written in four places, so "the default" is really four
defaults that can drift apart:

| File | Line | Today |
|---|---|---|
| `articlegen/sources.py` | 1090 | `max_papers: int = 20` on `gather_evidence` |
| `articlegen/pipeline.py` | 289 | `max_papers: int = 20` on `generate_draft` |
| `articlegen/cli.py` | 198 | `--max-papers … default=20`, help text says 20 |
| `articlegen/web.py` | 398 | `generate_draft(..., max_papers=20, ...)` — **hardcoded**, not a default |

`web.py` is the trap: change only the pipeline default and the deployed web app
silently keeps a pool of 20 forever.

## The change

### 1. One constant, in `articlegen/sources.py`

`sources.py` owns the candidate pool (it is the module that collects, dedupes,
ranks and slices it), so the constant lives there next to the other pool
constants.

Add immediately above `def gather_evidence(` (currently line 1088), keeping the
existing comment about `per_query` where it is:

```python
# The pool the relevance gate gets to work on. At 20 it barely worked: three
# measured runs collected exactly 20 candidates and cited 16-19 of them, and a
# landmark cluster RCT named by a run's own planned query never made the pool
# (#141). Curation cost scales with this number and that is the accepted price
# — the alternative, truncating the abstracts sent to curation, was measured in
# #117 and destabilises the gate, so CURATION_ABSTRACT_CHARS stays None.
DEFAULT_MAX_PAPERS = 40
```

Then change the signature (line 1090):

```python
    max_papers: int = DEFAULT_MAX_PAPERS,
```

### 2. Every entry point reads that constant

- **`articlegen/pipeline.py`** — add `DEFAULT_MAX_PAPERS` to the existing
  `from .sources import (...)` block (lines 24–25, alphabetical: after
  `DATABASE_NAMES`), and change line 289 to
  `max_papers: int = DEFAULT_MAX_PAPERS,`.

- **`articlegen/cli.py`** — add a new import line after
  `from .render import ...` (line 23):
  `from .sources import DEFAULT_MAX_PAPERS`
  and change line 198 to:

  ```python
      p_draft.add_argument("--max-papers", type=int, default=DEFAULT_MAX_PAPERS,
                           help=f"Max candidate papers (default: {DEFAULT_MAX_PAPERS})")
  ```

  The help string is built from the constant so it cannot go stale.

- **`articlegen/web.py`** — add `DEFAULT_MAX_PAPERS` to the existing
  `from .sources import gather_evidence, probe_unpaywall` (line 43) and change
  line 398 to `max_papers=DEFAULT_MAX_PAPERS,`.

After this edit the literal `20` as a candidate cap must not appear in
`articlegen/` at all. The test below pins that.

### 3. Two stale comments that now name the wrong number

- **`articlegen/llm.py` line 696–697** — the comment above the shallow
  `max_tokens=16000` branch reads "The curation call in particular grades
  twenty sources at once." Change "twenty sources" to "the whole candidate
  pool — forty sources by default". **Do not change any ceiling.** The default
  route (`anthropic/*` on OpenRouter) uses the reasoning pair, so a shallow
  curation call gets `OPENROUTER_REASONING_OUTPUT = 16000` and the direct
  Anthropic path gets 16000; 40 assessments of ≤12 words each is ~1,500 reply
  tokens. Ceilings have their own settled history (#77) — leave them.

- **`tests/test_offline.py` line 4721** — the docstring of
  `test_curation_truncation_is_off_until_measured` says the saving was measured
  "for 20 papers". Make it read "for 20 papers (the default pool then; it is
  now `DEFAULT_MAX_PAPERS`)". The measurement stays true; the sentence just
  stops implying that is today's pool size.

## Do not change

Named explicitly because each one looks adjacent and is not in scope:

- **`writer.CURATION_ABSTRACT_CHARS` stays `None`** (#117, settled). No
  truncation anywhere to pay for the bigger pool.
- **`sources.gather_evidence`'s `per_query = 25`.** Untouched. On a thin topic
  the pool may still come back under 40 — that is the literature, not a bug.
- **`pipeline.MAX_FULLTEXT_REQUESTS` (18) and `pipeline.FULLTEXT_TARGET` (5).**
  Both are sized against the excerpt budget, and `specs/5a83f646_full-text-fetch-order.md`
  says outright not to move them. Leave them.
- **`tools/compare_models.py` line 91** passes `max_papers=20` explicitly. It is
  a fixed-pool comparison harness; leaving it pinned keeps old runs comparable.
- **`render._assessment_paragraphs`.** See "Known follow-up" below — real, but a
  separate issue.
- Anything in `drafts/`, `adws/`, `.github/`.

## Expected knock-on effects (correct behaviour, not regressions)

The builder should not "fix" these:

1. **Methods' screened count roughly doubles.** `render.py:1307` passes
   `len(papers)`, so Methods will read "leaving 40 for screening". Derived and
   truthful.
2. **The full-text stop reason changes character.** Five full texts are still
   fetched (`FULLTEXT_TARGET`), but the eligible list doubles while
   `MAX_FULLTEXT_REQUESTS` stays 18, so "request cap of 18 reached" and its
   NOTE will fire more often instead of "ran out of eligible sources". That NOTE
   exists to tell the operator exactly this — it is the mechanism working.
3. **The read-subset skew line's `abstract-only n=` roughly doubles.**
4. **Fig. 1 will bin by 5 years more often** (`render._year_buckets` switches
   above ten distinct years). Bar width is already adaptive.
5. **`style._required_sections` cannot break.** It is
   `max(MIN_SECTIONS_FLOOR, min(MIN_SECTIONS, direct_sources))` — clamped at 5,
   so more `direct` labels can never raise the floor past 5. No new
   `too-few-sections` failures.

## Test

Add to `tests/test_offline.py`, next to `test_curation_truncation_is_off_until_measured`
(~line 4718), and **register it in the tuple in `main()`** (~line 4934) — a test
not in that tuple never runs. Put it directly after
`test_curation_truncation_is_off_until_measured,` in the list.

```python
def test_the_candidate_pool_is_big_enough_to_curate() -> None:
    """The pool default is one constant, and 20 was too small to be curated.

    Three runs on 2026-08-15 collected exactly 20 candidates and cited 16-19 of
    them — the relevance gate discarding almost nothing — and a landmark cluster
    RCT named by a run's own planned query never made the pool (issue #141).

    The number lived in four places, and one of them was a hardcoded argument in
    the web handler rather than a default. Raising the pipeline default alone
    would have left the deployed web app on 20 with nothing to show for it.
    """
    import inspect

    from articlegen import cli, pipeline, sources, web, writer

    check("the pool default is 40", sources.DEFAULT_MAX_PAPERS == 40)

    for mod, fn in ((sources, sources.gather_evidence),
                    (pipeline, pipeline.generate_draft)):
        default = inspect.signature(fn).parameters["max_papers"].default
        check(f"{fn.__name__} defaults to the constant",
              default == sources.DEFAULT_MAX_PAPERS)

    parser = cli.build_parser()
    args = parser.parse_args(["draft", "a topic"])
    check("the CLI flag defaults to the constant",
          args.max_papers == sources.DEFAULT_MAX_PAPERS)

    handler = inspect.getsource(web.ArticleGenHandler._handle_draft)
    check("the web handler reads the constant rather than its own number",
          "max_papers=DEFAULT_MAX_PAPERS" in handler)

    # The whole point of one constant: no caller may carry a second copy of the
    # number. A stale literal here is how the web path would sit on the old pool
    # while everything else moved.
    for mod in (cli, pipeline, sources, web):
        check(f"{mod.__name__} hardcodes no candidate cap of its own",
              "max_papers=20" not in inspect.getsource(mod)
              and "max_papers: int = 20" not in inspect.getsource(mod))

    # The bigger pool is paid for in curation tokens, never in truncation.
    # Truncating at 400 chars was measured in #117 and destabilised the gate.
    check("a bigger pool did not buy itself truncated abstracts",
          writer.CURATION_ABSTRACT_CHARS is None)
```

Note `cli.build_parser()` exists (`articlegen/cli.py:165`) and
`web.ArticleGenHandler._handle_draft` is already inspected this way elsewhere in
the suite (e.g. lines 654, 2606), so both patterns are house style.

## Docs

### `CLAUDE.md`

Two edits, both required — the `docs-current` CI gate fails a PR that touches
`articlegen/**` without touching this file, and
`test_claude_md_still_describes_this_code` checks that every backticked file,
test name and CONSTANT named here still exists.

**a. Invariants table** (the "Pinned by a test" table, ~line 80–102). Add a row:

```
| The candidate-pool default lives in one constant | `test_the_candidate_pool_is_big_enough_to_curate` |
```

**b. "Sources and grounding" section** (~line 215). Add as the **first** bullet
of that section, above "Abstracts plus open-access full text":

```markdown
- **The candidate pool is `DEFAULT_MAX_PAPERS` (40), defined in `sources.py` and
  read by every entry point** — the CLI flag's default, `generate_draft`, and
  the web handler. At 20 the relevance gate barely discarded anything: three
  measured runs collected exactly 20 candidates and cited 16-19 of them, and a
  landmark cluster RCT named by a run's own planned query never made the pool
  (#141). A bigger pool is paid for in curation tokens, **never in truncated
  abstracts** — `CURATION_ABSTRACT_CHARS` stays `None` (#117). Two knock-ons
  are expected rather than bugs: the Methods "screened" count roughly doubles,
  and `MAX_FULLTEXT_REQUESTS` (18) now binds before `FULLTEXT_TARGET` more
  often, so the stop-reason NOTE fires routinely.
```

### `README.md`

Line 213 — the options table. `ideas` already states its default inline
("`-n` (how many, default 6)"), so match it:

```
| `draft <title>` | `--open`, `--style "<audience/tone>"`, `--max-papers N` (default 40), `--name <stem>` |
```

No other README line states a candidate count (checked).

### `docs/decisions.md`

Add at the end of the "Grounding and provenance" section, after the `#143`
entry and before the `---` that precedes "## Web app and deployment"
(~line 401):

```markdown
### `#141` — a pool of 20 was inclusion, not curation

Three mental-health runs on 2026-08-15 each collected **exactly 20** candidates
and cited 16-19 of them. Hitting the cap every time is the tell: the pool was
capped, not exhausted, so the direct/related/tangential gate was choosing from a
list that had already been cut for it.

The cost was specific. The seclusion run planned the query "Safewards trial
conflict containment acute mental health wards" and the Bowers Safewards cluster
RCT still never made the pool — it reached the article only second-hand, quoted
inside an integrative review. Twenty slots ranked with a recency weight fill
with recent reviews, and the landmark primary trial they all cite is what gets
squeezed out.

The default is now `DEFAULT_MAX_PAPERS = 40`, defined once in `sources.py` and
read by `gather_evidence`, `generate_draft`, the `--max-papers` flag and the web
handler. It was previously written out four times, and the web handler's copy
was a hardcoded argument rather than a default — raising the pipeline default
alone would have left the deployed app on 20.

**Paid for in tokens, not in truncation.** Curation grades every candidate on a
full abstract, so the curation call roughly doubles (~13,000 input tokens
measured at 20). That is the accepted price. Truncating those abstracts is the
one thing that must not be traded here: `#117` measured it and it destabilises
the gate, so `CURATION_ABSTRACT_CHARS` stays `None`.

What to watch on the next few real runs:

- **Does the gate now discard?** Cited-of-collected should fall well below the
  16-19 of 20 that prompted this. If runs still cite nearly everything, the
  problem is the gate's labelling, not the pool size.
- **`per_query` is still 25 and was not raised.** A topic that comes back with
  fewer than 40 candidates is a thin literature, not a bug — but if that is the
  common case, the cap is not the binding constraint and this change is inert.
- **The full-text stop reason.** The eligible list doubles while
  `MAX_FULLTEXT_REQUESTS` stays 18, so "request cap reached" should become the
  usual exit and its NOTE should fire routinely. That is the log doing its job.
  Whether 18 is still the right number is a separate question with its own
  measurement.
```

## Known follow-up — do not fix here

`render._assessment_paragraphs` (render.py:907–925) prints the curation `counts`
(computed over **all** candidates) against `n = len(cited)`, which can now read
like "Of the 9 sources cited, 22 address the review question directly". The
mismatch exists today; a 40-paper pool makes it common. It is the same class of
self-contradiction issue #54 fixed elsewhere. **Out of scope for #141** — report
it in the envelope notes so it can be filed as its own issue.

## Verify

Run both suites from the repo root; judge by exit status, not by scanning output
for the word "error":

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. The conformance suite is unaffected by this change (no fixture
or render logic moves), but it is cheap and the render layer is downstream of
the pool.

Sanity check on the plumbing, no network or key needed:

```
python -c "from articlegen import cli; print(cli.build_parser().parse_args(['draft','x']).max_papers)"
```

Expect `40`.

Do **not** run a live draft as part of this change — it spends credit and the
behaviour it would show (a bigger pool, a different stop reason) is exactly what
the "what to watch" list is for on the owner's next real run.

## Git

Stay on the current branch (`fix/quality-sweep-139-148`). Do not run any
state-changing git command. The workflow commits after the tests pass.

**Commit message:**

```
Raise the default candidate pool from 20 to 40 so the relevance gate has something to discard

Fixes #141
```

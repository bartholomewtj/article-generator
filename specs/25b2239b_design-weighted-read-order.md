# Plan — send the five deep reads to reviews and trials first (issue #166)

## What this changes, in one line

`full_text_order` currently ranks eligible sources **relevance → recency → search
rank**. Add a **study-design weight between relevance and recency**, so a direct
systematic review or trial is read in full ahead of a newer direct primary study.
Nothing else about the fetch changes: same eligible set, same target, same caps,
tangential still never fetched.

## Why

#143 fixed "the deep reads went to old, heavily-cited work" by sorting on recency
inside a relevance tier. That created the opposite skew. In the seclusion draft,
Gaynes 2017 — the only systematic appraisal of adult acute settings — was
abstract-only, while a 2024 pilot study and a child/adolescent review were read in
full. The load-bearing paper lost for being nine years old.

Order wanted (issue #166):

1. direct systematic review / meta-analysis / Cochrane
2. direct trial
3. other direct
4. related, same design preference inside it
5. recency, then search rank, as tie-breakers

Relevance still outranks design: a direct primary study beats a related review.

## Out of scope (from the issue — do not do these)

- Do not raise `FULLTEXT_TARGET`. The excerpt budget is already full at
  5 × 12,000 (`FULLTEXT_PER_PAPER_CHARS` × `FULLTEXT_TARGET` =
  `FULLTEXT_TOTAL_CHARS`).
- No quality-appraisal score. Design weight is "which study is worth 12,000
  characters of reading", not "which study is good".
- No extra LLM call to label design. Deterministic, from metadata already held.
- No paywalled full text.
- No change to `--long`, to the web UI, or to `drafts/`.

## Files to touch

| File | Change |
|---|---|
| `articlegen/sources.py` | new `publication_types` field on `Paper`, capture it in three parsers, enrich it in `_merge_duplicate`, new `DESIGN_ORDER` + `paper_design()`, new sort key in `full_text_order` |
| `tests/test_offline.py` | rewrite + rename the order test, add design detection checks incl. negative controls, one parser check |
| `CLAUDE.md` | invariant-table row rename, rewrite the "fetch order" bullet |
| `docs/decisions.md` | new `#166` entry recording the reversal and its reasoning |

`articlegen/pipeline.py` needs **no logic change**, only a comment refresh (two
comment blocks describe the old order — lines ~496–500 and ~518–521). The
read-subset skew log line stays exactly as it is.

## Step 1 — carry the type metadata that already arrives

`Paper` holds title, venue and abstract but throws away every API's document-type
field except for the preprint flag. Add one field and fill it at the three parse
sites that have something to put in it.

In `articlegen/sources.py`, on the `Paper` dataclass, after `is_preprint`:

```python
    # Document type as the API reported it, lowercased, e.g. ("journal article",
    # "randomized controlled trial"). Fed to `paper_design` for the full-text
    # order and nothing else — it is never printed, so a source that reports
    # nothing costs nothing. Empty for arXiv, which has no such field.
    publication_types: tuple[str, ...] = ()
```

It must go **last** among the fields, with a default, so no existing positional
construction breaks.

Fill it:

- **Semantic Scholar** (`search_semantic_scholar`): add `publicationTypes` to
  `_SS_FIELDS` (line 110) and pass
  `publication_types=_clean_types(item.get("publicationTypes"))`.
  Note: `_SS_FIELDS` is a live-API seam — see the testing section.
- **OpenAlex** (`_parse_openalex`, ~line 395): `publication_types=_clean_types(item.get("type"))`.
  OpenAlex's `type` is coarse (`article`, `review`, `preprint`), which is why
  bare `review` deliberately does **not** reach the synthesis tier in step 2.
- **Europe PMC** (`search_europe_pmc`, ~line 520): `publication_types=_clean_types(item.get("pubType"))`.
  Europe PMC returns a single string that is often a semicolon- or comma-separated
  list (`"research-article; Journal Article"`), so `_clean_types` must split it.
- **arXiv**: nothing to add.

Add the small helper next to `_looks_like_preprint`:

```python
def _clean_types(raw) -> tuple[str, ...]:
    """API document-type metadata as a tuple of lowercase strings.

    The three sources disagree on shape: Semantic Scholar sends a list, OpenAlex
    a single string, Europe PMC one string holding a delimited list. Normalising
    here keeps `paper_design` from knowing which API a paper came from.
    """
```

Accept `None`, `str` and `list`; split strings on `;` and `,`; strip; drop empties.

In `_merge_duplicate`, enrich only when the kept copy has none — the same rule
as `venue` and `authors`, and for the same reason (identity is never swapped,
only filled in):

```python
    if dup.publication_types and not kept.publication_types:
        kept.publication_types = dup.publication_types
```

## Step 2 — deterministic design detection

Add to `articlegen/sources.py`, immediately above `full_text_order`:

```python
# Which study designs earn one of the five deep reads, best first. Not a quality
# score — nothing here appraises a study. It answers a narrower question: which
# paper repays 12,000 characters of reading? A systematic review carries the
# appraised evidence base, a trial carries the primary result, and a cross-
# sectional survey mostly restates its own abstract (#166).
DESIGN_ORDER = ("synthesis", "trial", "other")
```

Then `paper_design(paper: Paper) -> str`, returning one of those three, matched
against `f"{title} {venue}"` lowercased plus `publication_types`. Never the
abstract: an abstract that says "a systematic review is needed" would promote a
paper that is not one.

Detection order matters — check the exclusions first:

1. **Exclusions → `"other"`**, whatever else matched: `study protocol`,
   `trial protocol`, `protocol for a`, `: a protocol`, `statistical analysis
   plan`, `rationale and design`, `narrative review`, `scoping review` (unless
   the string also says `systematic`). A protocol describes a study that has not
   reported yet, so reading it in full buys nothing.
2. **`"synthesis"`**: `systematic review`, `meta-analys` (covers analysis /
   analyses), `metaanalys`, `meta-analytic`, `umbrella review`, `evidence
   synthesis`, `cochrane review`; venue containing `cochrane database of
   systematic reviews` or `systematic reviews`; a publication type containing
   `systematic review`, `meta-analysis` or `metaanalysis`.
   Bare `review` (title, venue or type) is **not** enough — most narrative
   reviews and every OpenAlex `type: review` would land here otherwise.
3. **`"trial"`**: `randomis`/`randomiz` (both spellings), `\brct\b`,
   `controlled trial`, `clinical trial`, `stepped[- ]wedge`, `cluster[ -]random`,
   `pragmatic trial`, `feasibility trial`; a publication type containing
   `randomized controlled trial`, `clinical trial` or `controlled clinical
   trial`. Bare `trial` on its own is **not** a match — it appears in ordinary
   prose titles.
4. Otherwise `"other"`.

Use module-level compiled regexes (`_SYNTHESIS_RE`, `_TRIAL_RE`,
`_DESIGN_EXCLUDE_RE`) in the style of `_PREPRINT_DOI_RES`, with `\b` boundaries
where a term could appear inside a longer word.

Docstring must say what a caller needs to know: it is ordering-only, it reads
title/venue/type and never the abstract, and preprints are untouched by it
(CLAUDE.md: preprints are marked, never excluded or down-ranked — a preprint of a
trial still ranks as a trial).

## Step 3 — the new sort key

In `full_text_order`, add the design tier between relevance and recency:

```python
    tier = {label: n for n, label in enumerate(FULLTEXT_RELEVANCE_ORDER)}
    design = {label: n for n, label in enumerate(DESIGN_ORDER)}
    ranked = []
    for index, paper in enumerate(papers, start=1):
        label = relevance.get(index)
        if label in tier:
            ranked.append((tier[label], design[paper_design(paper)],
                           -(paper.year or 0), index))
    return [index for _, _, _, index in sorted(ranked)]
```

Update the docstring and the comment block above `FULLTEXT_RELEVANCE_ORDER` to
describe the current rule and why it moved: #143's recency-first fix inside a
tier is what stranded Gaynes 2017, so relevance → design → recency → rank, with
the eligible set unchanged.

Keep `FULLTEXT_RELEVANCE_ORDER` as it is. Tangential and unlabelled sources are
still absent from the result.

## Step 4 — the two knock-ons, both expected

- **`_named_source_pass` also calls `full_text_order`** (`pipeline.py` ~line 350)
  to choose which abstracts to scan for named papers. It now scans reviews and
  trials first. That is an improvement, not a regression — reviews are exactly
  the abstracts that name landmark trials — but say so in one line of the
  comment there so the next reader does not think it is accidental.
- **The read-subset skew line may now report an older read subset than the
  abstract-only rest.** That is the change working, if the older papers are the
  reviews and trials. Do not "fix" it. Leave `_read_subset_skew` alone.

## Step 5 — tests

All in `tests/test_offline.py`.

**Rename** `test_full_text_order_favours_direct_and_recent` →
`test_full_text_order_favours_reviews_and_trials`. Grep for the old name and
update every hit: the runner list near the bottom of the file (~line 6079) and
the invariant row in `CLAUDE.md`. `test_claude_md_still_describes_this_code`
fails on a doc that cites a test name that no longer exists, so both must move
together.

Rewrite the test body to pin the new rule. Cover, with `check()` lines:

1. **Full ordering** over a hand-built pool that separates design from recency —
   e.g. a 2016 direct systematic review, a 2024 direct primary study, a 2019
   direct RCT, a 2025 related meta-analysis, a 2025 tangential review, an
   unlabelled paper. Expect the direct review first, direct trial second, direct
   primary third, related review after all directs.
2. **Relevance still outranks design**: a direct `"other"` sorts ahead of a
   related `"synthesis"`.
3. **Recency inside a design tier**: two direct trials, newer first — the #143
   behaviour survives where design ties.
4. **Ties fall back to incoming rank**: same tier, same design, same year keeps
   `[1, 2, 3, 4]`.
5. **Tangential and unlabelled are never offered**, and `full_text_order(x, {})`
   is `[]` — carry these two checks over unchanged.
6. **`paper_design` directly**, positives and negative controls:
   - synthesis: `"... : a systematic review and meta-analysis"`; venue
     `"Cochrane Database of Systematic Reviews"`; type
     `("systematic review",)`.
   - trial: `"... : a randomised controlled trial"`, `"...: a cluster-randomized
     trial"`, type `("Randomized Controlled Trial",)`, `\bRCT\b` in a title.
   - **other** (the controls that matter): `"Protocol for a randomised
     controlled trial of ..."`, `"Seclusion in acute wards: a narrative
     review"`, OpenAlex bare `type: ("review",)` with an ordinary title, `"The
     trials of implementing a new model of care"`, a plain cohort study.
   The docstring should say that these negative controls are the specification —
   the same framing `clinical-directive` uses.
7. **A preprint of a trial still ranks as a trial** — one line, guarding the
   standing "never down-rank a preprint" rule.

Then **one parser check**, in `test_europe_pmc_parsing`: add `"pubType":
"research-article; Randomized Controlled Trial"` to the full-featured fixture
record and assert `papers[0].publication_types` contains
`"randomized controlled trial"` — that pins the split-and-lowercase behaviour of
`_clean_types` on the shape a real record has.

Run both suites; both must be green:

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Judge them by exit status, not by scanning the output.

`tests/test_offline.py --live` touches `sources.py` and a field list, so it is
worth running **if** an OpenRouter or Semantic Scholar key is present — the one
real risk in this change is `publicationTypes` being rejected by the Semantic
Scholar `fields` parameter. If no key is available, say so in the PR body rather
than claiming it passed. (It is a documented S2 field; the fallback if it 400s is
to drop it from `_SS_FIELDS` and rely on OpenAlex, Europe PMC and the title
regexes, which is the majority of the signal anyway.)

## Step 6 — docs

**`CLAUDE.md`** (the CI gate fails a PR that touches `articlegen/**` without
touching this file):

- Invariant table row: replace
  `| Deep reads go to direct and recent sources first | test_full_text_order_favours_direct_and_recent |`
  with
  `| Deep reads go to direct reviews and trials first | test_full_text_order_favours_reviews_and_trials |`
- Rewrite the bullet that starts **"The fetch order is relevance then recency,
  not rank"** in the Sources and grounding section. It should now read: relevance
  tier, then design weight (`DESIGN_ORDER`, from `paper_design`), then recency,
  then search rank. Keep the #143 measurement — it is why citation weight is not
  in the key at all — and add the #166 case in one sentence: recency-first inside
  `direct` stranded the only systematic appraisal of adult acute settings because
  it was nine years old. Say the eligible set is unchanged and tangential is
  still never fetched. Say explicitly that the read-subset skew line may now show
  an *older* read subset and that this is the change working.
- Any backticked ALL-CAPS name added here must exist in code —
  `test_claude_md_still_describes_this_code` sweeps for that. `DESIGN_ORDER`
  qualifies and will exist.

**`docs/decisions.md`**: add a `### `#166` — recency-first sent the deep reads to
the wrong papers` entry, placed next to the `#143` entry it revises. Record: the
Gaynes 2017 case, that #143's fix was right about citation weight and wrong about
what replaced it, the three-tier design ladder and why bare "review" and bare
"trial" are excluded from it, that design is read from title/venue/type and never
from the abstract, and that `FULLTEXT_TARGET` was deliberately not raised. Add
one line to the end of the existing `#143` entry pointing forward to `#166` so a
reader arriving at #143 does not act on a superseded rule.

## Verification checklist

- [ ] `python tests/test_offline.py` exits 0
- [ ] `python tests/test_journal_conformance.py` exits 0
- [ ] `grep -rn "test_full_text_order_favours_direct_and_recent" .` returns
      nothing outside `docs/decisions.md` history prose
- [ ] `full_text_order` has no new call into the network, no LLM call, no
      `os.environ` read
- [ ] `FULLTEXT_TARGET`, `MAX_FULLTEXT_REQUESTS`, `FULLTEXT_PER_PAPER_CHARS`
      unchanged
- [ ] `_read_subset_skew` unchanged and still logged
- [ ] no file in `drafts/` changed

## Git

Branch, push, PR — this touches four files.

```
git checkout -b design-weighted-full-text-order
```

PR body must include a `Docs:` line or a CLAUDE.md edit (it has one), and should
say `Closes #166` plus `Refs #143` and `Refs #84`. **Never write "does not close
#NNN"** — GitHub's parser ignores the negation and closes the issue on merge.

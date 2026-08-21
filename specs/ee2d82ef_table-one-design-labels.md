# Plan — Table 1 Design: print `Other`, and label the designs we currently throw away (#192)

## What's wrong now

Table 1's Design column was a dash on 7–9 of 12 rows in every Grok 4.6 briefing
(21 Aug 2026). Three separate causes, all in `articlegen/sources.py` and
`articlegen/render.py`:

1. **`other` renders as `—`.** `render._table_rows` line 510:
   `design_str = sources.DESIGN_LABELS[d_label] if d_label != "other" else "—"`.
   `DESIGN_LABELS["other"]` already says `"Other"`; the dash is a deliberate
   override. A dash reads as "no data"; the honest word is "Other".

2. **Whole design families have nowhere to go.** Scoping reviews are *forced* to
   `other` by an explicit branch, narrative reviews are swept into
   `_DESIGN_EXCLUDE_RE` (an ordering exclusion reused as a classifier), and
   consensus statements have no rule at all. Case reports and case series are
   silently folded into `Observational`.

3. **Europe PMC's design metadata is discarded at the parse site — this is the
   Blackman bug.** `_parse_epmc` reads `item.get("pubType")`. Verified live
   against the real API on 21 Aug 2026: that flat field is **`None` on every
   record**. The types live one level down, in `pubTypeList.pubType`, as a list.
   Measured, live:

   ```
   Blackman 2023 (10.1001/jamapsychiatry.2023.2225)
     pubType     = None
     pubTypeList = {'pubType': ['Meta-Analysis', 'research-article',
                                'Systematic Review', 'Journal Article']}
   a scoping review          -> ['Scoping Review', 'Journal Article']
   a clozapine case report   -> ['Journal Article', 'Case Reports']
   ```

   So `Paper.publication_types` is empty for **every** Europe PMC record today,
   and the MEDLINE vocabulary — the one source that names Meta-Analysis,
   Systematic Review, Randomized Controlled Trial, Case Reports by name — has
   never reached `classify_design`. Blackman's title omits "meta-analysis"; its
   metadata does not. Fix the parse and the issue's headline case labels itself.

   Note the existing test faked a field shape the API does not send:
   `test_europe_pmc_parsing` (tests/test_offline.py:1679) feeds
   `"pubType": "research-article; Randomized Controlled Trial"`. That is why the
   gap survived. Keep the flat field as a fallback, add the list.

`classify_design` already reads `publication_types` (they are concatenated into
`combined`), so once the parse is fixed, "if publication_types names a design the
title omits, use it" needs no new machinery for the exact tokens — only
hyphen tolerance and the new categories.

## What to change

### 1. `articlegen/sources.py` — Europe PMC parse (the root cause)

In the Europe PMC result loop (around line 560–578):

```python
raw_types = (item.get("pubTypeList") or {}).get("pubType") or item.get("pubType")
...
    is_preprint=(src == "PPR" or "preprint" in " ".join(_clean_types(raw_types))),
    publication_types=_clean_types(raw_types),
```

`_clean_types` already accepts either a list or a delimited string, so no change
there. Keep the flat `pubType` as a fallback — some endpoints do send it, and
the existing test fixture uses it.

Comment it: the flat field is documented but null in practice, measured live
against the search endpoint on 21 Aug 2026.

**Expected knock-on, and it is wanted:** `paper_design` reads
`classify_design`, so records that only ever said "Randomized Controlled Trial"
in their index metadata now sort as `trial` in `full_text_order` instead of
`other`. That is the #166 ordering working with better data, not a regression.
`test_full_text_order_favours_reviews_and_trials` builds synthetic `Paper`s and
stays green.

### 2. `articlegen/sources.py` — new design categories

Add four categories. Keep `DESIGN_ORDER` (`synthesis`, `trial`, `other`)
**exactly as it is** — every new label falls through `paper_design`'s
`label if label in DESIGN_ORDER else "other"`, so the deep-read fetch order is
untouched. Say so in the docstring.

```python
DESIGN_DISPLAY_ORDER = ("synthesis", "trial", "observational", "qualitative",
                        "case", "scoping", "narrative", "consensus", "other")
DESIGN_LABELS = {
    "synthesis": "Reviews",
    "trial": "Trials",
    "observational": "Observational",
    "qualitative": "Qualitative",
    "case": "Case reports",
    "scoping": "Scoping",
    "narrative": "Narrative",
    "consensus": "Consensus",
    "other": "Other",
}
```

`other` stays last (Fig. 1 draws buckets in this order). Labels are kept short
because they are also Fig. 1's x-axis tick labels — see §4.

New regexes, beside the existing ones:

```python
_SCOPING_RE     = re.compile(r"\bscoping\s+reviews?\b", re.IGNORECASE)   # exists, keep
_NARRATIVE_RE   = re.compile(r"\b(?:narrative|literature|integrative|critical)\s+reviews?\b"
                             r"|\breview\s+of\s+the\s+literature\b", re.IGNORECASE)
_CONSENSUS_RE   = re.compile(r"\b(?:consensus\s+(?:statement|document|guidance|recommendations?|"
                             r"development\s+conference)|expert\s+consensus|delphi)\b", re.IGNORECASE)
_CASE_RE        = re.compile(r"\bcase[\s-]reports?\b|\bcase[\s-]series\b", re.IGNORECASE)
```

`_CASE_RE` must not fire on `case-control` — that is an observational design and
there is an existing negative control to keep. `\bcase[\s-]reports?\b` cannot
match "case-control"; add the negative control to the test anyway.

Edits to existing patterns:

- `_DESIGN_EXCLUDE_RE`: **remove** the `narrative\s+reviews?` alternative. That
  regex is now only the protocol/plan exclusion it was named for. Narrative
  reviews still end at `paper_design == "other"`, so the existing check
  "paper_design demotes narrative review to other" (test_offline.py:6320)
  stays green — verify it does before moving on.
- `_OBSERVATIONAL_RE`: **remove** `case\s+series|case\s+report` — the new `case`
  branch owns them and runs first.
- Keep `_SYSTEMATIC_RE`; it is still the guard that lets "systematic scoping
  review" reach `synthesis`.

### 3. `articlegen/sources.py` — `classify_design` branch order

```python
text = f"{paper.title} {paper.venue}"
types_text = " ".join(paper.publication_types)
# Index vocabularies hyphenate ("systematic-review", "case-report"); match both
# spellings rather than loosening every regex.
combined = f"{text} {types_text} {types_text.replace('-', ' ')}"

if _DESIGN_EXCLUDE_RE.search(combined):        return "other"      # protocols, analysis plans
if _SYNTHESIS_RE.search(combined):             return "synthesis"  # systematic / meta / umbrella / Cochrane
if _SCOPING_RE.search(combined):               return "scoping"
if _NARRATIVE_RE.search(combined):             return "narrative"
if _CONSENSUS_RE.search(combined):             return "consensus"
if _TRIAL_RE.search(combined):                 return "trial"
if _CASE_RE.search(combined):                  return "case"
if _QUALITATIVE_RE.search(combined):           return "qualitative"
if _OBSERVATIONAL_RE.search(combined):         return "observational"
return "other"
```

Two things this ordering preserves, deliberately:

- Synthesis now runs *before* scoping, replacing the old
  `_SCOPING_RE and not _SYSTEMATIC_RE` guard. Same outcome: "a systematic
  scoping review" matches `systematic\s+(?:\w+\s+)?reviews?` and returns
  `synthesis`, exactly as today; a plain "scoping review" now returns `scoping`
  instead of `other`.
- Case before observational, so "a case series of ten patients" is
  `Case reports`, not `Observational`.

**Do not** map a bare `review` publication type (OpenAlex `type: review`,
Europe PMC `Review`) to `narrative`. OpenAlex tags systematic reviews as
`review` too, so that mapping would print "Narrative" on a systematic review —
a false claim in a table that a reader forwards. Bare `review` stays `Other`.
Write that reasoning into a comment; it is the kind of thing that gets
"improved" back in.

**Invariant to hold:** every value `classify_design` can return must be a key of
both `DESIGN_LABELS` and `DESIGN_DISPLAY_ORDER`. A missing key makes
`_table_rows` raise `KeyError` and makes `_figure_series` silently drop a
bucket, so Fig. 1's segment counts no longer sum to the number of cited sources.
Pin it with an assertion in the test (§5).

### 4. `articlegen/render.py`

**Table 1 cell** (line ~509):

```python
design_str = sources.DESIGN_LABELS[sources.classify_design(paper)]
```

The `!= "other"` special case goes. No `KeyError` risk given §3's invariant.

**Table 1 caption** (line ~668) currently says design "is left blank where it
could not be inferred" — no longer true. Replace with: "...and reads Other where
no design could be inferred; no quality appraisal was performed." Do not touch
the rest of the caption or the Box 1 / Fig. 1 quality-appraisal disclaimers
(#102, #171).

**Fig. 1 width** (in `_figure_html`, line ~728). Nine categories instead of five
makes design mode fire more often *and* draw more bars. At the current
`width = 660` a nine-bucket figure gives `slot = 67.6px` while "Observational"
at 11px is ~78px wide — the tick labels collide. The viewBox scales to its
container, so widening it shrinks the text proportionally and buys the room:

```python
FIGURE_WIDE_BUCKETS = 6      # above this many bars, the x tick labels stop fitting at 660
...
width = 660.0 if len(buckets) <= FIGURE_WIDE_BUCKETS else 860.0
```

Everything downstream (`plot_w`, `slot`, `bar_w`, tick positions) already derives
from `width`. Nothing else in the figure changes.

**Do not touch** `DESIGN_FIGURE_MIN_SHARE`, the `labelled_share > 0.5` test, the
`distinct_categories >= 2` test, or the year fallback (#171, explicitly out of
scope). Design mode will fire on more drafts than before because more papers now
carry a label — that is the fix working, not a rule change.

### 5. `tests/test_offline.py`

**Extend `test_europe_pmc_parsing`** (line ~1655): add a second record to the
fake payload carrying `"pubTypeList": {"pubType": ["Meta-Analysis",
"research-article", "Systematic Review", "Journal Article"]}` and no flat
`pubType`, and check:

- `"meta-analysis" in paper.publication_types`
- the existing flat-`pubType` record still parses (fallback intact)
- `sources.classify_design(that_paper) == "synthesis"` even though its title
  says neither "systematic review" nor "meta-analysis" — this is the Blackman
  case, end to end from the API payload.

**Extend `test_figure_one_counts_study_designs`** (line ~4377). Keep every
existing check; the year-fallback sub-checks (4 and 5) must stay green
unmodified. Add:

- Label/order invariant:
  `set(sources.DESIGN_LABELS) == set(sources.DESIGN_DISPLAY_ORDER)`, and for
  every fixture paper `classify_design(p) in sources.DESIGN_LABELS`.
- Positives from the title: scoping review → `scoping`; "a narrative review
  of…" → `narrative`; "consensus statement on…" → `consensus`;
  "…: a case report" → `case`; "…: a case series" → `case`.
- Positives from `publication_types` alone, plain titles:
  `("meta-analysis",)` → `synthesis`; `("systematic review",)` → `synthesis`;
  `("scoping review",)` → `scoping`; `("case reports",)` → `case`;
  `("randomized controlled trial",)` → `trial`. Add the hyphenated spellings
  `("case-report",)` and `("systematic-review",)` to pin the de-hyphenated pass.
- Negative controls (these are the specification):
  "a case-control study of…" → `observational`;
  "a systematic scoping review of…" → `synthesis`;
  "a systematic literature review of…" → `synthesis`;
  "Protocol for a narrative review…" → `other`;
  `("review",)` with a plain title → `other` (bare review type is not narrative);
  "General overview of clinical services" → `other` (already present).
- Fetch order unchanged: `paper_design(p) == "other"` for the scoping,
  narrative, consensus and case fixtures, and `paper_design(p) in DESIGN_ORDER`
  for all of them.
- Table 1 prints the word: build rows with
  `render._table_rows([unclassifiable_paper], {1: "direct"})` and check
  `rows[0]["design"] == "Other"`; check `"—"` does not appear in any Design cell
  for a mixed set; check `"<td>Other</td>"` is in `render._table_html(...)`.
- Fig. 1 width: nine distinct-design papers give a `viewBox` starting
  `0 0 860`; the existing five-design set still gives `0 0 660`.

Keep every new check inside the existing test function — CLAUDE.md names it as
the guard for this behaviour and the invariant table points at it.

### 6. `tests/test_journal_conformance.py`

Fixture 7, "design-labelled sources" (line ~341): add two titles so the
rendered fixtures actually exercise the new labels and the `Other` cell —
e.g. `"Coercive practice in acute care: a scoping review"` and
`"Trends in mental health service use"` (unclassifiable), and bump
`_papers(5, ...)` and the `references` / `relevance` / `counts` entries to
match. Run the suite and read the failure list: the relevance counts,
key-point citations and `_markers_resolve` all key off the paper count.

Add one global convention check beside the existing Table 1 ones (line ~112):

```python
("Table 1 never leaves Design empty",
 lambda h, a: "Table 1 |" not in h or "<td></td>" not in h),
```

and, if the fixture set makes it safe, that `Other` appears where a design could
not be inferred. Do not add a check that forbids `—` anywhere in the table — the
Source column legitimately prints a dash for a preprint with no journal.

### 7. `CLAUDE.md`

- In the full-text-order bullet (line ~355–365): `classify_design` now returns
  nine labels, `DESIGN_ORDER` is unchanged and `paper_design` still collapses
  everything outside it to `other`, so the #166 read order is unaffected.
- Add to the "Sources and grounding" section, as its own bullet:
  **Europe PMC's document types live in `pubTypeList.pubType`, never in the flat
  `pubType`** — measured live; the flat field is null on every record, so every
  Europe PMC paper reached `classify_design` with no index metadata at all and a
  JAMA meta-analysis printed as a dash (#192). Any label `classify_design`
  returns must be a key of both `DESIGN_LABELS` and `DESIGN_DISPLAY_ORDER`, and
  a bare `review` type is deliberately not treated as a narrative review.
- Invariant table: keep the two existing rows pointing at
  `test_figure_one_counts_study_designs`; add
  `| Table 1 prints a design word, never a dash | test_figure_one_counts_study_designs |`.
- The docs CI gate (`.github/workflows/docs-current.yml`) fails a PR touching
  `articlegen/**` that does not touch this file, and
  `test_claude_md_still_describes_this_code` checks that every backticked file,
  test name and constant named here still exists. Name only things you actually
  created: `DESIGN_LABELS`, `DESIGN_DISPLAY_ORDER`, `FIGURE_WIDE_BUCKETS`.

### 8. `docs/decisions.md`

Append a `### #192 — Table 1 Design was a dash` entry under the #171 section:
the three causes above, the live measurement of `pubTypeList`, why bare `review`
is not narrative, and why `DESIGN_ORDER` was left alone. Keep it to the story;
the invariants live in CLAUDE.md.

## Out of scope (from the issue, do not drift into these)

- No LLM design labelling — `classify_design` stays deterministic and never
  reads an abstract.
- No quality-appraisal column in Table 1.
- No change to Fig. 1's fallback-to-years rule (#171).
- No change to the default model (#85), no `--long` on the web UI, and do not
  regenerate the public demo Reviews in `drafts/` (existing HTML keeps its
  dashes; that is a record of what shipped).
- Do not add `practice guideline` to the consensus bucket — a guideline is not a
  consensus statement and the issue did not ask for it.

## Verify

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0 — judge them by exit status, not by scanning the output for the
word "error". Then eyeball the change on real data without spending credit:

```
articlegen demo                 # renders the built-in sample; no API, no network
```

Open the generated HTML and confirm Table 1's Design column shows words on every
row and Fig. 1 still draws. If you want a live check of the Blackman case
specifically, `python tests/test_offline.py --live` spends real quota — not
required for this change; the parse fix is pinned offline by the payload fixture.

## Ship

Branch, commit, push, `gh pr create`. PR body: refs #192, refs #185, refs #171
(**never** write "does not close #NNN" — GitHub's parser matches `close #NNN`
and ignores the negation). The docs gate is satisfied because CLAUDE.md is
edited.

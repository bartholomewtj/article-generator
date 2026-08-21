# Plan — Fig. 1 counts study designs; Table 1 drops "Cited by" (issue #171)

## What this changes, in one paragraph

Fig. 1 (Review / `--long` path only) currently plots cited sources by publication
year, stacked by relevance. It becomes a count **by study design** — reviews,
trials, observational, qualitative, other — still stacked by relevance, using
design labels derived from title / venue / `publication_types` metadata already
on `Paper`. When design cannot be worked out for most of the cited rows, or when
everything lands in one category, Fig. 1 falls back to today's year chart
unchanged. Table 1 loses its **Cited by** column on both paths (briefing and
Review) and gains a **Design** column. Citation counts stay on the reference
list, where they are bibliographic rather than a quality score.

No LLM labelling. No quality-appraisal column. The briefing still has no Fig. 1.

## Files to touch

| File | Why |
|---|---|
| `articlegen/sources.py` | 5-way design classifier + display labels; `paper_design` becomes a wrapper |
| `articlegen/render.py` | Fig. 1 design mode + fallback; Table 1 columns; captions |
| `tests/test_offline.py` | new guard test, update the display-items test, register in `main()` |
| `tests/test_journal_conformance.py` | two new conventions + one design-labelled fixture |
| `CLAUDE.md` | invariant rows, display-item description, Box 1 rationale sentence |
| `docs/journal-style.md` | §6 display-item bullets |
| `docs/decisions.md` | the story behind #171 |
| `demo.html` | regenerate so the committed demo page is not stale |

Do **not** touch `drafts/`, `index.html`, `web.py`, or `full_text_order`'s
behaviour.

---

## 1. `articlegen/sources.py` — one classifier, two views

Today `paper_design(paper)` returns `"synthesis" | "trial" | "other"` and exists
only to order full-text fetches (#166). That ordering is pinned by
`test_full_text_order_favours_reviews_and_trials` and **must not change**.

Refactor so there is one place that reads title / venue / `publication_types`,
and two views onto it:

1. Add regexes next to the existing `_SYNTHESIS_RE` / `_TRIAL_RE`:

   ```python
   _QUALITATIVE_RE = re.compile(
       r"\b(?:qualitative(?:\s+\w+)?\s+(?:study|studies|analysis|research|interviews?|evaluation)"
       r"|qualitative\s+study|focus\s+groups?|thematic\s+analysis|grounded\s+theory"
       r"|semi-?structured\s+interviews?|phenomenolog\w+|ethnograph\w+"
       r"|interpretative\s+phenomenological)\b",
       re.IGNORECASE,
   )
   _OBSERVATIONAL_RE = re.compile(
       r"\b(?:cohort\s+stud\w+|prospective\s+cohort|retrospective\s+cohort"
       r"|case[-\s]control|cross[-\s]sectional|longitudinal\s+stud\w+"
       r"|observational\s+stud\w+|registry\s+stud\w+|case\s+series|case\s+report"
       r"|population[-\s]based\s+stud\w+|national\s+survey)\b",
       re.IGNORECASE,
   )
   ```

   Mixed-methods work is deliberately left unclassified — calling it qualitative
   would be a claim the metadata does not support. Say so in a comment.

2. Add the display vocabulary, as module constants:

   ```python
   DESIGN_DISPLAY_ORDER = ("synthesis", "trial", "observational", "qualitative", "other")
   DESIGN_LABELS = {
       "synthesis": "Reviews",
       "trial": "Trials",
       "observational": "Observational",
       "qualitative": "Qualitative",
       "other": "Other",
   }
   ```

3. Add `classify_design(paper) -> str`, returning one of `DESIGN_DISPLAY_ORDER`.
   Move the body of the current `paper_design` into it, with the check order:

   `_DESIGN_EXCLUDE_RE` (protocols, narrative reviews) → scoping-without-
   systematic → `_SYNTHESIS_RE` → `_TRIAL_RE` → `_QUALITATIVE_RE` →
   `_OBSERVATIONAL_RE` → `"other"`.

   Qualitative is tested before observational on purpose: "a qualitative
   interview study nested in a cohort" is qualitative.

4. `paper_design(paper)` becomes a two-line wrapper:

   ```python
   def paper_design(paper: Paper) -> str:
       """Fetch-ordering view of classify_design: synthesis / trial / other."""
       label = classify_design(paper)
       return label if label in DESIGN_ORDER else "other"
   ```

   Keep its existing docstring content (it explains the ordering rationale) and
   add a line saying the classification itself now lives in `classify_design`.
   `DESIGN_ORDER` and `full_text_order` are untouched.

Because synthesis and trial are still tested first and everything new maps back
to `"other"` for ordering, the existing full-text-order test stays green without
edits. Verify that, don't assume it.

---

## 2. `articlegen/render.py` — Fig. 1

### 2a. Make bucket membership uniform

`_figure_series` currently returns `buckets` as `[(label, set_of_years)]` and the
tally loop matches papers by year. Change membership to **1-based cited index
sets** so both modes share one counting loop:

```python
buckets = [(label, {n, ...}), ...]     # n is the cited-source number
```

In year mode, build those index sets from `_year_buckets` (keep `_year_buckets`
as it is — it still takes and returns years; convert its year sets to index sets
in `_figure_series`).

### 2b. Design mode and when it is allowed

Add near the other render constants:

```python
# Fig. 1 counts study designs only when the metadata actually supports it.
# `classify_design` reads titles, venues and index metadata, never an abstract,
# so a pool of terse or badly indexed titles collapses into "other" — and a bar
# chart that is 80% "Other" says less than the year histogram it replaced.
DESIGN_FIGURE_MIN_SHARE = 0.5
```

`_figure_series(cited, labels)` logic:

1. Need at least 2 cited sources (as now) or return `None`.
2. Compute `designs = {n: sources.classify_design(p) for n, p in enumerate(cited, 1)}`.
3. Design mode is used when **both**:
   - labelled share `> DESIGN_FIGURE_MIN_SHARE` — i.e.
     `sum(1 for d in designs.values() if d != "other") / len(cited) > 0.5`;
   - at least **2** distinct categories are non-empty (a single-bar chart is
     less informative than the year chart).
4. Otherwise fall back to the existing year path exactly as today — including
   returning `None` when fewer than two sources carry a year.
5. Design-mode buckets are ordered by `DESIGN_DISPLAY_ORDER`, skipping empty
   categories, labelled with `DESIGN_LABELS`. `"other"` keeps its bar so the bars
   sum to the number of cited sources.
6. Relevance segmentation is unchanged and applies to both modes (all-or-nothing
   `segmented` flag, `series` of `direct` / `related` / `tangential`, else
   `["cited"]`). No new CSS or swatch classes are needed.
7. Add `"mode": "design" | "year"` to the returned dict.

### 2c. `_figure_html`

- x-axis title: `Study design` in design mode, `Year of publication` in year mode.
- `aria-label`: "Cited sources by study design, segmented by relevance" / the
  existing year wording.
- Caption: `Composition of the evidence base. Cited sources by study design`
  (+ `, segmented by how directly each addresses the review question.` when
  segmented) + `Design is inferred from each record's title, journal and index
  metadata; it is not a quality appraisal. Bar labels give the number of sources
  in each category; the underlying records are listed in Table 1.`
  Year mode keeps today's caption verbatim.
- Everything else (SVG geometry, ticks, rounded top segment, legend) is unchanged.
  Bar `<title>` tooltips read e.g. `Trials: 3 direct`.

### 2d. `_figure_markdown`

Same split: heading sentence follows the mode, bullets stay
`- {label}: {total} ({n direct, n related, …})`. The offline display-items test
iterates buckets generically, so this shape must be preserved.

---

## 3. `articlegen/render.py` — Table 1

One table shape for both paths (briefing and `--long`); do not add a
conditional variant.

- `_table_rows`: **remove** the `"cited_by"` key, **add**
  `"design": sources.DESIGN_LABELS[label] if label != "other" else "—"` using
  `classify_design`. Nothing else in the row dict changes.
- `_table_html`: header becomes
  `Ref. | Study | Year | Source | Design | Relevance | Read`
  (Design before Relevance, so the two curation-ish columns sit together and
  the first three columns still identify the paper). Drop the `Cited by` cell
  and its `<th>`.
- Caption: drop `citation counts are as reported by the indexing database` and
  add: `Design is inferred from each record's title, journal and index metadata
  and is left blank where it could not be inferred; no quality appraisal was
  performed.` Keep the existing Relevance and Read sentences.
- `_table_markdown`: same column change —
  `| Ref. | Study | Year | Source | Design | Relevance | Read |`.
- **Leave both reference lists alone**: the HTML `<span class="ref-cites">Cited
  by N</span>` and the Markdown `Cited by N.` stay.

### Comment maintenance in `render.py`

The block above `_BOX_SELECTION_NOTE` (around line 552) argues that Table 1's
"Cited by" is the only quality-looking number on the page. That is now history —
rewrite it in the past tense and name #171 as the change that removed the
column. The `_BOX_SELECTION_NOTE` text itself stays exactly as it is.

---

## 4. Tests

### `tests/test_offline.py`

Add `test_figure_one_counts_study_designs()` (place it near the other render
tests) and **register it in the `main()` tuple** — a test that is not in that
list never runs.

It must check, using locally built `Paper` fixtures (no network, no keys):

1. **Design mode fires.** Six cited papers with unmistakable titles — a
   systematic review, a meta-analysis, an RCT, a cluster-randomised trial, a
   prospective cohort study, a qualitative interview study — give
   `_figure_series(...)["mode"] == "design"`; bucket labels are drawn from
   `DESIGN_LABELS`; the per-bucket totals sum to the number of cited sources.
2. **The HTML says which axis it is.** `_figure_html` contains `Study design`
   and not `Year of publication`; the caption says design is not a quality
   appraisal.
3. **Markdown agrees with HTML.** `_figure_markdown` names the same buckets with
   the same totals.
4. **Fallback: mostly unlabelled.** Papers titled `Study 1..6` with years (the
   `demo.SAMPLE_PAPERS` shape) give `mode == "year"` and HTML containing
   `Year of publication` — proving a wrong stack is never drawn.
5. **Fallback: one category.** Six papers that are *all* randomised trials fall
   back to year mode.
6. **Table 1 demotes citation counts.** `_table_html` / `_table_markdown` over
   any of the fixtures contain no `Cited by`, do contain a `Design` header, and
   `render_article(...)` still prints `Cited by` in the reference list. Assert
   both, in one place — the point is the number moved, not that it vanished.
7. **`classify_design` negative controls**, in the same spirit as the existing
   `paper_design` controls: a study *protocol* for a cohort study is `other`;
   "Survey of national policy" (no design words) is `other`; "A randomised
   controlled trial" stays `trial` even though it also says "controlled"; and
   `paper_design` still returns only `synthesis` / `trial` / `other` for every
   input `classify_design` can produce.

Update `test_display_items_are_selected_once_for_both_formats`: the loop over
shared row values reads `row["cited_by"]` — change it to `row["design"]`
(skipping `"—"`, which the loop already does for em dashes). Everything else in
that test stays.

Also re-run and, if needed, adjust `test_claude_md_still_describes_this_code`
expectations by making CLAUDE.md correct — not by loosening the test.

### `tests/test_journal_conformance.py`

- Extend `_papers(n, **kw)` with a `titles` kwarg (default: today's
  `f"Study {i}"`), so a fixture can supply design-bearing titles.
- Add a fixture, **"design-labelled sources"**: five or six papers whose titles
  name their designs (systematic review, meta-analysis, RCT, cohort study,
  qualitative interview study), full relevance labels, the standard `_SECTIONS`
  article, so Fig. 1 renders in design mode through the real `render_article`
  path. Keep the reference/key-point discipline the other fixtures follow
  (every key point names a study the body discusses).
- Add two conventions to `CONVENTIONS`:
  - `("Table 1 carries no citation count", lambda h, a: "<th>Cited by</th>" not in h)`
  - `("Table 1 reports study design", lambda h, a: "<th>Design</th>" in h)`
- Add one Fig. 1 convention:
  - `("Fig. 1 names the axis it actually plotted", lambda h, a: "Fig. 1 |" not in h or ("Study design" in h) != ("Year of publication" in h))`
    — i.e. exactly one of the two, never both, never neither.

The existing sparse-metadata fixture (`Untitled N`, no years) must still produce
no Fig. 1, and the wide-year fixture (`Study N`, 1984–2024) must still produce
5-year bins. Both titles classify as `other`, so both fall back — confirm by
running the suite, not by reasoning about it.

---

## 5. Docs

### `CLAUDE.md`

- Invariants table — add two rows (same guard test is fine):
  - `| Fig. 1 counts study designs, and falls back to years when it cannot | test_figure_one_counts_study_designs |`
  - `| Table 1 prints no citation count | test_figure_one_counts_study_designs |`
- "Three display items are built deterministically in `render.py`" bullet:
  Fig. 1 is now "counts of cited sources by study design, with the year chart as
  the fallback below `DESIGN_FIGURE_MIN_SHARE`"; add that Table 1 carries
  Design, not Cited by, and that citation counts live on the reference list.
- The Box 1 sentence that says Table 1's "Cited by" is the only quality-looking
  number: rewrite as history ("was the only quality-looking number on the page;
  removed in #171"), because the guard test loads this file as current fact.
- Sources section: one line saying `classify_design` is the single classifier
  (title / venue / `publication_types`, never the abstract), `DESIGN_DISPLAY_ORDER`
  and `DESIGN_LABELS` are the display view, and `paper_design` stays the
  three-value fetch-ordering wrapper so #166's read order is unaffected.
- Any constant you name in backticks must exist in code — the guard test checks
  `DESIGN_DISPLAY_ORDER`, `DESIGN_LABELS`, `DESIGN_FIGURE_MIN_SHARE` by name.

### `docs/journal-style.md`

§6 bullets: rewrite the `Fig. 1` bullet (designs, with the year fallback stated)
and the `Table 1` bullet (columns: number, authors, year, venue, design,
relevance, read — no citation count). Fix the trailing sentence in the Box 1
bullet that leans on "Cited by" being present.

### `docs/decisions.md`

Add a short #171 entry: what Fig. 1 showed before, why a clinician reading it
wants the design mix instead, why the fallback exists (design comes from titles
and index metadata only, so a badly indexed pool would otherwise be drawn as a
mostly-"Other" bar chart), and why the citation count moved to the reference
list rather than being deleted (bibliographic there, authority-looking in a
characteristics table — same argument as #102).

---

## 6. Regenerate the committed demo page

`demo.html` at the repo root is a checked-in render of `articlegen demo` and
still shows the old Table 1 header. Regenerate it:

```
articlegen demo -o demo.html
```

No key or network needed. The generated date line will change — that is expected
diff noise. `drafts/` is **not** regenerated.

---

## 7. Verify

Run, in this order, and judge by exit status:

```
python tests/test_offline.py
python tests/test_journal_conformance.py
articlegen demo -o demo.html
```

Then eyeball the new figure once:

```
python -c "from articlegen import demo, render; print(render._figure_series(*(lambda c: (c[0], render._display_relevance(c[1], demo.SAMPLE_CURATION)))(render._citation_map(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS)))['mode'])"
```

Expect `year` for the demo sample (its titles carry no design words — that is the
fallback working), and `design` for the new offline fixture.

Open `demo.html` in a browser and confirm Table 1 has a Design column, no Cited
by column, and that the reference list still shows "Cited by N".

## 8. Ship

Branch, commit, PR — this is a multi-file change:

```
git checkout -b fig1-study-designs
git add -A && git commit
gh pr create
```

PR body: what changed, why, `Closes #171`, and a line noting the CLAUDE.md
docs gate is satisfied by real edits. **Never write "does not close #NNN"** —
GitHub's parser ignores the negation.

## Out of scope

- LLM design labelling of any kind.
- A quality-appraisal column or score anywhere.
- Putting `--long` on the web UI.
- Regenerating anything in `drafts/`.
- Changing `full_text_order`, `DESIGN_ORDER`, or the read-order behaviour
  from #166.

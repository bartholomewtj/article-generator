# Table 1 Study Design Labels and Europe PMC Metadata Parse

## What changed and why it matters

In previous versions, Table 1's **Design** column rendered as an em-dash (`—`) for 7–9 of 12 citations in many generated briefings. This made it look as though metadata was missing or unpopulated, even when papers had clear designs or explicit index metadata.

Three issues caused this:
1. `articlegen/render.py` explicitly converted the `"other"` classification label into `"—"` rather than displaying `"Other"`.
2. Several common study designs (scoping reviews, narrative reviews, consensus statements, and case reports/series) had no dedicated display labels in `DESIGN_LABELS` and were either forced into `"other"`, treated as protocols, or collapsed into observational studies.
3. Europe PMC search API responses store document types in nested list structure `pubTypeList.pubType`, while the flat `pubType` field returned by search queries is `None` in practice. As a result, Europe PMC records arrived with empty `publication_types`, causing papers like Blackman 2023 (a JAMA meta-analysis whose title omitted the words "meta-analysis") to classify as `"other"` and display as a dash.

This change:
- Parses `pubTypeList.pubType` (with fallback to flat `pubType`) in Europe PMC search results so publication types reach the classifier.
- Expands `DESIGN_DISPLAY_ORDER` and `DESIGN_LABELS` from 5 to 9 categories (`synthesis`, `trial`, `observational`, `qualitative`, `case`, `scoping`, `narrative`, `consensus`, `other`).
- Adds deterministic regex matching for narrative reviews, scoping reviews, consensus statements, and case reports/series in `classify_design`, matching both bare and hyphenated `publication_types` strings.
- Renders `Other` instead of `—` in Table 1 rows and updates Table 1's caption accordingly.
- Widens Fig. 1's SVG viewBox to 860px (`FIGURE_WIDE_BUCKETS = 6`) when more than 6 design buckets are plotted, preventing x-axis tick label collisions.
- Leaves `DESIGN_ORDER` (`synthesis`, `trial`, `other`) and `paper_design` untouched so full-text deep-read fetching prioritisation is preserved.

## Where the changes live

- `articlegen/sources.py`:
  - `search_europe_pmc`: Extracts `raw_types` from `(item.get("pubTypeList") or {}).get("pubType") or item.get("pubType")` and cleans them into `Paper.publication_types`.
  - `DESIGN_DISPLAY_ORDER` and `DESIGN_LABELS`: Added `case` ("Case reports"), `scoping` ("Scoping"), `narrative` ("Narrative"), and `consensus` ("Consensus").
  - `_NARRATIVE_RE`, `_CONSENSUS_RE`, `_CASE_RE`: New regular expressions for detecting these design families.
  - `_DESIGN_EXCLUDE_RE` and `_OBSERVATIONAL_RE`: Removed narrative reviews and case reports/series so they route to their dedicated categories instead of exclusion/observational.
  - `classify_design`: Evaluates synthesis before scoping, adds checks for narrative, consensus, trial, case, qualitative, and observational, and handles hyphenated index strings. Bare `review` publication types intentionally remain `other` to avoid mislabelling systematic reviews.
- `articlegen/render.py`:
  - `_table_rows`: Direct dictionary lookup `sources.DESIGN_LABELS[d_label]` without dashing `"other"`.
  - `_table_html`: Caption updated to note that design reads "Other" where no design could be inferred.
  - `_figure_html` and `FIGURE_WIDE_BUCKETS`: Sets SVG width to 860.0 when category count exceeds 6 buckets.
- `tests/test_offline.py`:
  - `test_europe_pmc_parsing`: Added list-form `pubTypeList` fixture and verified `classify_design` identifies syntheses from Europe PMC index metadata alone.
  - `test_figure_one_counts_study_designs`: Added test assertions for design label invariants, title matching, `publication_types` matching (including hyphenated strings), negative controls (e.g. case-control vs case report, bare review), fetch order invariance, Table 1 HTML output, and Fig. 1 viewBox width scaling.
- `tests/test_journal_conformance.py`:
  - Added `"Table 1 never leaves Design empty"` rule and updated fixture 7 with scoping and unclassifiable records.
- `CLAUDE.md` and `docs/decisions.md`:
  - Updated invariant table (`Table 1 prints a design word, never a dash`) and added context documentation for issue #192.
- `specs/ee2d82ef_table-one-design-labels.md`: Implementation specification.

## Verification

Run the test suites:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Inspect the demo output to check Table 1 and Fig. 1 layout:
```bash
articlegen demo
```
Verify that Table 1 contains no empty or dashed Design cells, displaying explicit design labels or `"Other"`.

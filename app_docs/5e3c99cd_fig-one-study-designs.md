# Study Design Counts in Fig. 1 and Citation Demotion in Table 1 (#171)

## Summary

Issue #171 updates the deterministic display items in the Review renderer and evidence tables:

1. **Fig. 1 (Composition of the Evidence Base)**: Previously plotted cited sources as a publication-year histogram stacked by relevance. It now counts sources by **study design** (Reviews, Trials, Observational, Qualitative, Other) stacked by relevance tier (`direct`, `related`, `tangential`). Classification is performed deterministically from title, venue, and `publication_types` metadata via `sources.classify_design`. If study design cannot be inferred for more than half of the cited papers (controlled by `DESIGN_FIGURE_MIN_SHARE = 0.5`) or if only a single design category is present, Fig. 1 cleanly falls back to the year histogram.
2. **Table 1 (Characteristics of Cited Evidence)**: Replaced the **"Cited by"** column with an inferred **"Design"** column across both HTML and Markdown renders. The table caption explicitly clarifies that design is inferred from bibliographic metadata and does not represent a study quality appraisal.
3. **Reference Lists**: Citation counts remain preserved on the full reference list (e.g. "Cited by N"), where they function bibliographically rather than being misread as quality scores.

## Changes by File

- **`articlegen/sources.py`**:
  - Added regex patterns `_QUALITATIVE_RE` and `_OBSERVATIONAL_RE` to detect qualitative and observational research without false positives from mixed methods.
  - Added `DESIGN_DISPLAY_ORDER = ("synthesis", "trial", "observational", "qualitative", "other")` and `DESIGN_LABELS` mapping categories to display names ("Reviews", "Trials", "Observational", "Qualitative", "Other").
  - Implemented `classify_design(paper: Paper) -> str` evaluating exclusion rules (protocols, narrative reviews) followed by systematic syntheses, trials, qualitative studies, and observational cohorts.
  - Refactored `paper_design(paper: Paper) -> str` to act as a 3-way fetch-ordering wrapper over `classify_design` preserving the existing `synthesis` / `trial` / `other` ladder for `full_text_order` (#166).

- **`articlegen/render.py`**:
  - Added `DESIGN_FIGURE_MIN_SHARE = 0.5` threshold constant.
  - Refactored `_figure_series` to unify bucket representations using 1-based index sets, evaluate design labelled share, and switch between `"design"` and `"year"` mode.
  - Updated `_figure_html` and `_figure_markdown` to dynamically render axis labels (`Study design` vs `Year of publication`), aria labels, and mode-specific captions stating that design classification is not a quality appraisal.
  - Updated `_table_rows`, `_table_html`, and `_table_markdown` to drop `"cited_by"` and add `"design"` column (`sources.DESIGN_LABELS[d_label]` or em dash for other). Updated caption text.

- **`tests/test_offline.py`**:
  - Added `test_figure_one_counts_study_designs` verifying design mode activation, axis and caption text, Markdown/HTML consistency, unlabelled and single-category fallbacks to year mode, Table 1 column layout, reference list citation counts, and `classify_design` negative controls.
  - Updated `test_display_items_are_selected_once_for_both_formats` to assert on `row["design"]` instead of `row["cited_by"]`.
  - Registered `test_figure_one_counts_study_designs` in `main()`.

- **`tests/test_journal_conformance.py`**:
  - Added journal style conventions asserting that Table 1 carries no `"Cited by"` header, includes `"Design"`, and Fig. 1 names the active axis.
  - Added `titles` kwarg support to `_papers()` helper and introduced a `"design-labelled sources"` fixture.

- **`CLAUDE.md`**:
  - Added invariant entries for `test_figure_one_counts_study_designs` and Table 1 citation omission.
  - Updated render rules and sources documentation for `classify_design`, `DESIGN_DISPLAY_ORDER`, `DESIGN_LABELS`, and `DESIGN_FIGURE_MIN_SHARE`.

- **`docs/journal-style.md`**:
  - Updated §6 display-item guidelines for Fig. 1 study designs (with year fallback) and Table 1 columns.

- **`docs/decisions.md`**:
  - Added Architecture Decision Record for `#171` detailing clinical rationale, deterministic design inference, fallback mechanisms, and citation count relocation.

- **`specs/5e3c99cd_fig-one-study-designs.md`**:
  - Implementation specification for issue #171.

## How to Verify

Run both offline test suites:

```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both test suites should pass all checks with exit code 0.

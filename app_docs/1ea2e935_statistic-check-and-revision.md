# Statistic Check Grounding Improvements and Statistics Revision Pass

## Summary

This change resolves false statistic flags in the deterministic verification check and adds an automated single-pass prose revision step when unverified or misattributed figures remain in a generated draft (GitHub issue #189).

Specifically:
1. **Titles in verification haystack**: Paper titles are now included in the search text alongside abstracts and retrieved full-text excerpts.
2. **Hyphenated range parsing**: Decimal ranges (such as `4.4-5.2` or `-0.38--0.12`) are matched as single composite quantities rather than splitting across hyphens into false negative numbers.
3. **Deterministic statistic enforcement**: `pipeline.enforce_statistics` runs at most one revision pass (`MAX_STATISTIC_PASSES = 1`) when flagged figures exist, strictly requiring revisions to be intact, reduce flags, and introduce no new numbers. A clean first draft (0 flagged figures) incurs zero revision calls.

---

## Changed Files & Implementation Details

### 1. `articlegen/verify.py`
- **`_paper_haystack(paper, full_texts, idx)`**: Prefixes `paper.title or ""` before `paper.abstract` and any full-text excerpt. Since `writer._format_sources` supplies titles to the writer, figures appearing solely in paper titles (e.g., headline effect sizes) now verify as grounded.
- **`_RANGE_RE_SRC` & `_FIGURE_RE`**: Placed range regex matching (`(?P<range>-?\d+\.\d+%?\s*[-–—]\s*-?\d+\.\d+%?)`) first in `_FIGURE_RE` alternation. Scanning ranges like `4.4-5.2` no longer matches `4.4` followed by `-5.2` (a phantom negative figure).
- **`_found(figure, haystack, quantity, is_range)`**: When `is_range=True`, splits the range on the inner delimiter (`_RANGE_PARTS_RE`) and verifies both endpoints against the haystack, allowing source variations such as `"from 4.4 to 5.2"`.
- **`check_statistics(article, papers)`**: Returns an additive `details` key containing structured records (`figure`, `kind`, `sentence`, `cited`) for each flagged item while preserving existing return keys (`unverified`, `misattributed`, `total`).
- **`revision_brief(verification)`**: Deterministically constructs instructions for the writer specifying the flagged figures, their sentences, and three permitted actions: (1) delete the figure and keep the claim in words, (2) restate qualitatively, or (3) move citation to the reporting source if misattributed. Forbids introducing new numbers or external sources.

### 2. `articlegen/writer.py`
- **`_REVISE_FIGURES_PATCH_SYSTEM` & `_REVISE_BRIEFING_FIGURES_PATCH_SYSTEM`**: System prompts for Review and Briefing formats instructing the LLM to patch only flagged blocks without introducing new numbers or sources.
- **`revise_statistics(article, brief, model, api_key)`**: LLM revision helper that sends the revision brief and current draft JSON to `generate_json` using `_REVISION_SCHEMA`, applying edits via `apply_revisions`.

### 3. `articlegen/pipeline.py`
- **`MAX_STATISTIC_PASSES = 1`**: Caps statistic revisions at one pass.
- **`enforce_statistics(article, papers, model, api_key, log, style_report, direct_sources)`**:
  - Checks statistics on the initial draft. If `len(unverified) + len(misattributed) == 0`, immediately returns without calling LLM.
  - If flags exist, invokes `revise_statistics`.
  - Validates that the revised article is intact (retains reference and section/finding counts), reduces total flags, and does not increase `total` figure count (`no_new_numbers`).
  - On acceptance, re-runs `check_style` so `style_report` accurately reflects the revised prose.
- **`generate_draft`**: Replaces direct `check_statistics` call with `enforce_statistics`.

### 4. `tests/test_offline.py`
- **`test_statistic_verification`**: Added test cases for title-only figures, grounded hyphenated/en-dash ranges, negative ranges, single figure count for ranges, and absent ranges.
- **`test_flagged_figures_buy_one_revision`**: Verifies that 0/0 drafts bypass revision, flagged drafts trigger exactly 1 revision pass, revisions introducing new numbers are rejected, successful revisions recompute style reports, and revision brief contains required constraints.

### 5. `CLAUDE.md` & `docs/decisions.md`
- Added invariants, table entries, and design decision documentation for `#189`.

---

## Verification

Run offline and journal conformance test suites:

```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```

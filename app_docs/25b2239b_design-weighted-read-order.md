# Design-Weighted Full-Text Read Order (#166)

## Summary

Previously, issue #143 replaced citation-weight ordering with recency-first sorting within relevance tiers (`direct` before `related`) to prevent full-text retrieval from favoring old, highly-cited papers. However, sorting strictly by recency inside `direct` created an opposite skew: landmark systematic reviews and clinical trials (such as Gaynes 2017 in acute psychiatric settings) were left as abstract-only simply because they were published several years ago, while recent small pilots were read in full.

Issue #166 introduces a deterministic study-design weight between relevance tier and recency in `full_text_order`. Eligible open-access papers are now ranked by:

1. **Relevance tier** (`FULLTEXT_RELEVANCE_ORDER`: `direct` before `related`; `tangential` and unlabelled papers are never fetched).
2. **Study design ladder** (`DESIGN_ORDER`: `synthesis` → `trial` → `other`).
3. **Recency** (`-year`, newest first).
4. **Search rank** (incoming candidate order as tie-breaker).

Relevance continues to outrank design: a direct primary study is prioritized ahead of a related systematic review. Design detection is performed deterministically by `paper_design()` using paper `title`, `venue`, and `publication_types` metadata, never inspecting abstracts (avoiding false positives from abstracts mentioning future review needs).

## Changes by File

- **`articlegen/sources.py`**:
  - Added `publication_types: tuple[str, ...] = ()` to the `Paper` dataclass.
  - Implemented `_clean_types(raw)` to normalize diverse API document-type formats (lists, delimited strings) into a tuple of lowercase strings.
  - Updated `_SS_FIELDS` to request `publicationTypes` from Semantic Scholar, and captured `publication_types` in `search_semantic_scholar`, `_openalex_page`, and `search_europe_pmc`.
  - Preserved `publication_types` during duplicate merging in `_merge_duplicate`.
  - Added `DESIGN_ORDER = ("synthesis", "trial", "other")` and regexes (`_DESIGN_EXCLUDE_RE`, `_SCOPING_RE`, `_SYSTEMATIC_RE`, `_SYNTHESIS_RE`, `_TRIAL_RE`).
  - Implemented `paper_design(paper: Paper) -> str` classifying papers into `synthesis`, `trial`, or `other` while enforcing negative controls (excluding protocols, narrative reviews, bare "review" metadata, and bare "trial" wording).
  - Updated `full_text_order(papers, relevance)` to sort by `(tier[label], design[paper_design(paper)], -(paper.year or 0), index)`.

- **`articlegen/pipeline.py`**:
  - Updated comments in `_named_source_pass` documenting that scanning candidates via `full_text_order` naturally inspects reviews and trials first.
  - Updated comments in `generate_draft()` describing the revised relevance → design → recency hierarchy for full-text grounding.

- **`CLAUDE.md`**:
  - Renamed invariant table entry `test_full_text_order_favours_direct_and_recent` to `test_full_text_order_favours_reviews_and_trials`.
  - Updated the fetch order description in the Sources and grounding section to specify relevance tier, design weight (`DESIGN_ORDER`), recency, and search rank.

- **`docs/decisions.md`**:
  - Added architecture decision record `### #166 — recency-first sent the deep reads to the wrong papers` capturing context, rationale, sort key order, design detection rules, negative controls, and budget constraints.
  - Added forward pointer to `#166` under the `#143` decision entry.

- **`specs/25b2239b_design-weighted-read-order.md`**:
  - Added implementation specification and verification plan for issue #166.

- **`tests/test_offline.py`**:
  - Updated `test_europe_pmc_parsing` to verify extraction of `publication_types` from `pubType`.
  - Renamed and expanded `test_full_text_order_favours_direct_and_recent` to `test_full_text_order_favours_reviews_and_trials`, testing the complete ordering ladder, relevance dominance over design, recency within design tiers, search rank tie-breaking, `paper_design` classification, negative control exclusions, and preprint preservation.
  - Updated test runner list in `main()`.

## How to Verify

Run both test suites:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```
Both test suites should pass cleanly with exit code 0.

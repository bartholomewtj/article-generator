# Skip Generic Named Lookups & Require Distinct Extra Query on Paraphrased Terms

## What Changed and Why

This change addresses two search-efficiency defects identified in issue #190:

1. **Generic named-source extraction and lookups**:
   - The named-source pass previously extracted pseudo-names from structured abstract headers (e.g., `RESULTS Twelve studies` -> `Twelve study`), descriptive compounds (`English-language trial`, `population-based cohort`), or setting acronyms (`ED intervention`, `US trial`).
   - These generic terms matched large portions of the literature (e.g. 15 of 16 returned records), pulling irrelevant papers into the pool and displacing candidate studies.
   - **Fix**:
     - Expanded `_NAMED_STOPLIST` in `articlegen/sources.py` with structured abstract headers (`background`, `methods`, `results`, `conclusion`, etc.), number words (`zero` through `twenty`, `thirty`..`ninety`, `hundred`, `thousand`), quantifiers (`several`, `many`, `multiple`, etc.), and place/unit acronyms (`us`, `eu`, `ed`, `er`, `icu`, `gp`).
     - Added `_GENERIC_NAME_SUFFIXES` and `_is_generic_name_token` to reject hyphenated descriptors (`-language`, `-based`, `-led`, `-wide`, `-arm`, etc.) and 2-letter uppercase tokens.
     - Added `filter_named_matches()` with `NAMED_MATCH_RATE_MAX = 0.5` and `NAMED_MATCH_MIN_MATCHES = 5` to drop any name query that matches more than 50% of returned records when returning 5+ matches. DOIs are never dropped.
     - Cleaned up duplicate named-source code block in `articlegen/sources.py`.
     - `articlegen/pipeline.py` now uses `filter_named_matches()` in `_named_source_pass()` and logs dropped generic queries.

2. **Paraphrased search terms and query planning**:
   - When topics or supplied search terms re-worded the same phrase across multiple queries, the search only explored a single route.
   - **Fix**:
     - Added token normalisation (`_query_tokens`), pairwise overlap scoring (`queries_are_near_duplicates` with `NEAR_DUPLICATE_OVERLAP = 0.6`), and route clustering (`query_routes`) in `articlegen/writer.py`.
     - In `plan_queries()`:
       - If supplied search terms have `query_routes <= 1`, the prompt instructs the model that terms share one route and requires exactly ONE additional distinct indexing term.
       - If the model returns a near-duplicate, it is rejected and retried once with feedback. If the retry fails, the supplied terms are retained unchanged.
       - If search terms were not supplied and planned queries have `query_routes <= 1`, a single follow-up `generate_json` call requests one distinct query. If at `MAX_PLANNED_QUERIES` (4), the last near-duplicate is pruned to accommodate the new query.
       - Added optional `log` callback to `plan_queries()`, plumbed from `pipeline.generate_draft()`.

## Files Changed

- `articlegen/sources.py`: Removed duplicate block; added `_GENERIC_NAME_SUFFIXES`, expanded `_NAMED_STOPLIST`, added `_is_generic_name_token`, and added `filter_named_matches()` with `NAMED_MATCH_RATE_MAX` / `NAMED_MATCH_MIN_MATCHES`.
- `articlegen/writer.py`: Added `NEAR_DUPLICATE_OVERLAP`, `_QUERY_STOP_WORDS`, `_query_tokens()`, `queries_are_near_duplicates()`, `query_routes()`, near-duplicate detection and retry/follow-up logic in `plan_queries()`.
- `articlegen/pipeline.py`: Imported and integrated `filter_named_matches()` into `_named_source_pass()`; passed `log=log` to `plan_queries()`.
- `CLAUDE.md`: Added invariant table entries and updated documentation for named sources and query planning.
- `tests/test_offline.py`: Added `test_generic_named_lookups_are_skipped` and `test_paraphrase_terms_buy_a_distinct_query`.

## Verification

Run the test suites:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```

# Citing a Working Set of Sources (#167)

## Summary

When the candidate pool default was increased to 40 (`sources.DEFAULT_MAX_PAPERS`), the goal was to provide the relevance gate sufficient candidate material to discard. However, generated drafts continued to cite nearly all screened sources (e.g. 20/20 and 17/20), turning curation into inclusion and overloading single-page evidence briefings.

This change instructs the writer (both evidence briefings and `--long` Review articles) to cite a working set of approximately 12 sources (`TARGET_CITED_SOURCES = 12`), prioritizing direct evidence and citing related sources only when they establish a distinct mechanism, population, or contrast. It updates `Draft.summary()` to report screened vs. cited counts, adapts Methods rendering to maintain consistency with Table 1's Read column when full-text sources are screened but uncited, and adds test coverage pinning these behaviors.

## Changes by File

- **`articlegen/writer.py`**:
  - Defined `TARGET_CITED_SOURCES = 12` constant.
  - Created `_WORKING_SET_RULE` shared prompt instruction used verbatim in both `_BRIEFING_SYSTEM` and `_WRITER_SYSTEM`, replacing previous inclusion instructions.
  - Removed misleading prompt directions in `_WRITER_SYSTEM` that instructed citing tangential sources which had already been omitted from the context.
  - Updated `_writer_context()` to append a run-specific `WORKING SET` header reporting actual screened vs. shown paper counts, instructing the model to cite ~12 sources (or only relevant sources when shown <= 12).

- **`articlegen/pipeline.py`**:
  - Updated `Draft.summary()` to report `"{len(cited)} of {len(self.papers)} screened sources cited"`, making the screened-to-cited ratio visible and measurable in CLI output and web responses.

- **`articlegen/render.py`**:
  - Updated `_methods_paragraphs()`, `_methods_html()`, and `_methods_markdown()` with optional `n_full_cited` parameter (computed via `_full_text_count(cited)` in `render_article` and `render_markdown`).
  - When full-text papers are retrieved but not all are cited, Methods now renders `({n_full_cited} of which are cited here and marked in Table 1)` so Methods remains accurate and consistent with Table 1's Read column count.

- **`tests/test_offline.py`**:
  - Updated assertions in `test_draft_summary` to match the new `"{cited} of {screened} screened sources cited"` format.
  - Added `test_the_writer_cites_a_working_set` and registered it in `main()`: asserts candidate pool remains 40, `TARGET_CITED_SOURCES` is 12, `_WORKING_SET_RULE` is present in system and full-text prompts, run-specific counts reach the model for standard and thin pools, Methods reflects screened vs. cited counts, and partial full-text citations match Table 1 wording.

- **`CLAUDE.md`**:
  - Added pinned invariant row for `test_the_writer_cites_a_working_set`.
  - Documented that `DEFAULT_MAX_PAPERS` is the screened count while `TARGET_CITED_SOURCES` is the cited count, explaining the working set rule and Methods / Table 1 Read column alignment.

- **`docs/decisions.md`**:
  - Added architectural decision record `### #167 — the pool was curated, the reference list was not` under `## Grounding and provenance`.

- **`specs/6cd2fac0_cite-a-working-set.md`**:
  - Added implementation plan and specification for issue #167.

- **`adws/adw_data/limit_events.jsonl`**:
  - Added session telemetry record.

## How to Verify

Run the offline and journal conformance test suites:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```
Both test suites exit with code 0.

To verify rendering without network:
```bash
articlegen demo
```

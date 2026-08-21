# Target Landmark Papers Named in Top Curated Abstracts (#165)

## Summary

Search in ArticleGen was previously one-shot: the model planned 2–4 queries, gathered evidence once, curated, and wrote. When top abstracts cited landmark trials (e.g., the Safewards trial) by name or DOI that the initial search queries did not specifically retrieve, those trials never entered the candidate pool as first-hand sources, causing key evidence and statistics to arrive quoted second-hand inside other papers (#141, #142).

After initial curation, the pipeline now deterministically extracts DOIs and trial names from the top `NAMED_SOURCE_SCAN` (3) abstracts, queries scholarly APIs via `gather_evidence` for up to `NAMED_SOURCE_LIMIT` (8) candidates, verifies matches with `named_matches`, and appends them to the candidate pool via `merge_candidates` without re-ranking existing records. The newly added records are curated separately and merged into relevance mappings before full-text retrieval, and Methods documents the targeted search pass.

## Changes by File

- **`articlegen/sources.py`**:
  - Added constants: `NAMED_SOURCE_SCAN = 3`, `NAMED_SOURCE_LIMIT = 8`, `NAMED_SOURCE_PER_QUERY = 5`.
  - Defined `_NAMED_STOPLIST` and regexes (`_DOI_EXTRACT_RE`, `_NAME_THEN_NOUN_RE`, `_NOUN_THEN_ACRONYM_RE`) to reject sentence-initial words and apparatus acronyms (e.g., PRISMA, RCT, CONSORT).
  - Implemented `named_references(text)`: Deterministically extracts DOIs and study names from abstracts in order, capped at `NAMED_SOURCE_LIMIT`.
  - Implemented `named_matches(paper, request)`: Validates that returned search results match the requested DOI or study name.
  - Implemented `merge_candidates(pool, extra, limit)`: Merges new records using existing DOI/title deduplication, enriching existing entries in-place while appending up to `limit` new records without reordering existing indices.
  - Updated `gather_evidence`: Added `exhausted: set[str] | None = None` parameter to share source failure state across gather invocations.

- **`articlegen/pipeline.py`**:
  - Implemented `_named_source_pass`: Scans the top abstracts (selected via `most_relevant_index` and `full_text_order`), queries APIs with `patient=False` and the shared `exhausted` set, filters with `named_matches`, merges candidates, and runs `curate_sources` on new records, shifting their relevance indices by the existing pool size.
  - Integrated `_named_source_pass` into `generate_draft()` between initial curation and the full-text fetch loop so new landmark papers can qualify for full-text retrieval.
  - Added `provenance["named_sources"]` tracking requested queries and count of added records.

- **`articlegen/render.py`**:
  - Updated `_methods_paragraphs` to append a sentence to Methods describing the targeted search and number of added records when `provenance["named_sources"]` is present.

- **`articlegen/writer.py`**:
  - Updated `curate_sources` docstring noting that it is called a second time for named sources and must maintain 1-based indexing relative to the subset passed.

- **`docs/decisions.md`**:
  - Added decision record `### #165 — the search was one-shot` detailing background, implementation mechanics, resource caps, and observability.
  - Updated `#142` section regarding nested reference chasing.

- **`CLAUDE.md`**:
  - Updated the pipeline sequence to reflect the named-source pass between `curate_sources` and full-text fetch.
  - Added invariant table rows for `test_named_papers_in_abstracts_are_looked_up` and `test_named_sources_merge_without_renumbering`.
  - Documented named source rules in the **Sources and grounding** section.

- **`tests/test_offline.py`**:
  - Added `test_named_papers_in_abstracts_are_looked_up`: End-to-end unit test checking the second gather invocation, scanning limits, shared `exhausted` set, index stability, separate curation, and provenance reporting.
  - Added `test_named_references_reads_names_not_noise`: Tests positive/negative extraction controls and sweeps `tests/real_abstracts.json`.
  - Added `test_named_sources_merge_without_renumbering`: Verifies duplicate enrichment, limit capping, and `named_matches` filtering.
  - Added `test_methods_names_the_named_source_pass`: Verifies HTML and Markdown rendering of the Methods description with escaping.
  - Registered all four tests in `main()`.

- **`specs/1a1b8156_named-source-pass.md`**:
  - Added implementation plan and specification for tracking and reference.

## How to Verify

Run both the offline test suite and journal conformance tests:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```
Both test suites should pass cleanly with exit code 0.

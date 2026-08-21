# Stop the Pipeline Run on Empty Source Curation (#168)

## Summary

When source relevance labelling (`curate_sources`) failed or returned no usable assessments, `curate_sources` previously caught the exception and returned an empty relevance dictionary, while `generate_draft` merely logged a warning and continued. Because nothing was labelled `tangential`, no papers were filtered out, but because no papers were labelled `direct` or `related`, `full_text_order` returned empty—causing the model to write an ungrounded, abstracts-only briefing with no topic-drift protection in silence (#168).

The pipeline now treats an empty curation result on a non-empty candidate pool as a fatal error. `generate_draft` raises `CurationFailed` (a direct subclass of `NoPapersFound`) before invoking `_named_source_pass` or the writer functions (`write_briefing` / `write_article`), avoiding unneeded LLM write charges. Existing CLI and web callers catch `CurationFailed` without code modifications. Additionally, `curate_sources` reports the failure cause via an `error` key.

## Changes by File

- **`articlegen/writer.py`**:
  - Updated `curate_sources` to include an `"error"` key in the returned dictionary on failure: captures truncated exception details `f"{type(exc).__name__}: {exc}"[:200]` when an exception occurs, or `"the model returned no usable relevance labels"` when the response contains no usable assessments.
  - Updated docstring documenting that an empty result carries an `error` key and is expected to be treated as fatal by the caller.

- **`articlegen/pipeline.py`**:
  - Added exception class `CurationFailed(NoPapersFound)` to inherit existing `NoPapersFound` exception handling across CLI and web endpoints.
  - In `generate_draft`, added a check under `if papers and not curation.get("relevance"):` that logs the existing warning and immediately raises `CurationFailed` with the reported failure reason before the named-source pass and writer stages.

- **`tests/test_offline.py`**:
  - Refactored `test_pipeline_fetches_full_text` to verify that `full_text_order(papers, {}) == []` directly rather than invoking `generate_draft` with empty curation.
  - Added `test_unlabelled_sources_stop_the_run` testing:
    - `CurationFailed` is raised on empty relevance and subclasses `NoPapersFound` with `sources_failed=False`.
    - Raised message describes the failure cause and states the write was not charged.
    - Writer passes (`write_briefing`, `write_article`, `enforce_style`) and `_named_source_pass` are not invoked.
    - Warning log is preserved.
    - `curate_sources` soft-fails with populated `error` key on provider exception and empty assessments.
    - Soft degradation in `_named_source_pass` remains intact.
  - Registered `test_unlabelled_sources_stop_the_run` in `main()`.

- **`CLAUDE.md`**:
  - Added invariant table row: `| Unlabelled sources stop the run before the writer | test_unlabelled_sources_stop_the_run |`.
  - Updated `generate_draft()` pipeline sequence notes.
  - Added rule under **Sources and grounding** explaining that empty relevance results are fatal.

- **`docs/decisions.md`**:
  - Added decision record `### #168 — empty curation produced an ungrounded draft in silence` detailing problem context, rationale for subclassing `NoPapersFound`, error reporting, and rejected alternatives (no retry loops, no fallback to all-direct).

- **`specs/ffce9489_stop-on-empty-curation.md`**:
  - Added specification and implementation plan for issue #168.

## How to Verify

Run both the offline test suite and journal conformance tests:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```
Both test suites should pass cleanly with exit code 0.
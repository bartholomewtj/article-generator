# `--long` Titles Describe the Question, Not the Result (#170)

## Summary

Updated the `--long` Review writer path to require descriptive, question-focused titles rather than outcome-claiming titles. Previously, `_ARTICLE_SCHEMA` requested "the subject and the finding", which caused models to generate causal claims in article titles (e.g. asserting that an intervention reduces an outcome) that were never caught downstream because statistic and style checks do not validate titles.

The Review schema and prompt now share the same title rule previously used only by the briefing path, requiring titles to specify the population, intervention or exposure, and outcome in sentence case without claiming a finding or result.

## Changes by File

- **`articlegen/writer.py`**:
  - Defined a single shared `_TITLE_RULE` constant requiring descriptive titles (`population + intervention/exposure + outcome`, sentence case, no result claimed).
  - Updated `_ARTICLE_SCHEMA["properties"]["title"]["description"]` to reference `_TITLE_RULE` instead of the old `"the subject and the finding"` description.
  - Updated `_BRIEFING_SCHEMA["properties"]["title"]["description"]` to reference `_TITLE_RULE` (keeping the exact byte-identical wording).
  - Added `TITLE: descriptive. Names the question. Does not claim the result.` to `_WRITER_SYSTEM` prior to the `REGISTER` block, which is automatically inherited by derived prompts (`_REVISE_SYSTEM`, `_REVISE_PATCH_SYSTEM`, and `_WRITER_SYSTEM_FULLTEXT`).

- **`tests/test_offline.py`**:
  - Added `test_titles_describe_the_question()` to verify that:
    - Both `_ARTICLE_SCHEMA` and `_BRIEFING_SCHEMA` share `_TITLE_RULE`.
    - The rule forbids claiming results and specifies population, intervention/exposure, and outcome.
    - The old phrasing is completely removed.
    - `_WRITER_SYSTEM`, `_BRIEFING_SYSTEM`, and all derived revise/fulltext prompts contain the title instruction line.
  - Registered `test_titles_describe_the_question` in `main()`.

- **`CLAUDE.md`**:
  - Added invariant table row pinning `test_titles_describe_the_question`:
    `| A title names the question, in both paths, from one string | test_titles_describe_the_question |`.

- **`docs/decisions.md`**:
  - Added section `### #170 — --long titles describe the question, not the result` recording the observed causal title, explaining why title validation is prompt-driven, and documenting why a crude regex ban in `style.py` was deliberately avoided.

- **`specs/1654193e_long-title-describes-question.md` & `requests/issue-170-long-titles.md`**:
  - Added the plan specification and request context for issue #170.

## How to Verify

Run the offline and journal conformance test suites from the repository root:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```
Both test suites exit with status 0.

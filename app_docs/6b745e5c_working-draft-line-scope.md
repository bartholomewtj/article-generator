# Working Draft Limitations Line Scoping (#169)

## Summary

Previously, any surviving style issue with severity `error` caused `render._style_failure_sentence` to append:
> "A revision was attempted and did not resolve this, so the text below should be read as a working draft rather than a finished review."

Four of five shipped drafts in `drafts/` printed this disclaimer due to benign prose nits like `recycled-phrasing` (reused phrases across sections) or `repeated-opener`. A reader forwarding the briefing into an email copied a claim that the analysis was unfinished, even on strong drafts.

Issue #169 scopes the "working draft" branding sentence so it prints only for defects that change whether the page can be sent:
1. `clinical-directive` errors that survived the revision pass.
2. Substance rules that survived the revision pass, **excluding** `recycled-phrasing` and `repeated-opener` (and `under-length`, which is a warning).
3. Residual unverified (`unverified`) or misattributed (`misattributed`) figures from the statistical grounding check.

The exempt prose rules (`recycled-phrasing`, `repeated-opener`) continue to fire, continue to trigger revision passes, and continue to appear in CLI logs and `style_report` / `draft.summary()`. They simply no longer brand the rendered HTML or Markdown page.

## Changes by File

- **`articlegen/render.py`**:
  - Imported `SUBSTANCE_RULES` from `.style`.
  - Defined `SENDABLE_BLOCKING_RULES = frozenset({"clinical-directive"}) | (SUBSTANCE_RULES - {"recycled-phrasing", "repeated-opener", "under-length"})`. This resolves to `clinical-directive`, `too-few-sections`, `hedge-monotony`, `echoed-abstract`, and `bundled-citations`.
  - Updated `_style_failure_sentence` to filter issues by `SENDABLE_BLOCKING_RULES` and removed the trailing working draft clause.
  - Added `_working_draft_sentence(style_report, verification)` to emit `"The text below should therefore be read as a working draft rather than a finished review."` only when blocking style errors or unverified/misattributed figures are present.
  - Updated `_assessment_paragraphs` to append `_working_draft_sentence` to the limitations list.

- **`tests/test_offline.py`**:
  - Added `test_only_sendable_defects_brand_the_page` asserting that nits do not brand the page, clinical directives and surviving substance errors brand the page, mixed reports isolate blocking faults, unverified/misattributed figures brand independently, clean drafts produce no branding, `under-length` warnings stay out, and style rules remain active in `style.revision_brief`.
  - Updated docstring in `test_a_second_style_pass_runs_only_after_progress`.
  - Registered `test_only_sendable_defects_brand_the_page` in `main()`.

- **`tests/test_journal_conformance.py`**:
  - Added `_check_sendable_branding()` validating rendered article HTML across nits, clinical directives, and unverified figures.
  - Added `_check_sendable_branding()` call to `main()`.

- **`CLAUDE.md`**:
  - Added invariant table row: `| Only sendable-blocking defects brand the page a working draft | test_only_sendable_defects_brand_the_page |`.
  - Added "A leftover nit is not a \"working draft\"" bullet under "Prose style (enforced, not prompted)" documenting `SENDABLE_BLOCKING_RULES` and rationale.
  - Scoped residual error note to blocking rules.

- **`specs/6b745e5c_working-draft-line-scope.md`**:
  - Added implementation specification and test plan for issue #169.

## How to Verify

Run both test suites:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```
Both test suites exit with code 0.

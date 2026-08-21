Stop branding leftover style nits as a working draft, per GitHub issue #169 (below, verbatim).
Where: articlegen/render.py (_style_failure_sentence), tests/test_offline.py, tests/test_journal_conformance.py, CLAUDE.md
Done means: the "working draft rather than a finished review" Limitations line prints only for errors that change whether the page can be sent — clinical-directive, residual unverified/misattributed figures after the check, or a substance rule that a revision did not clear; recycled-phrasing and repeated-opener stay in the CLI log and style_report and still try to get fixed, but they do not brand the page; under-length stays a warning and stays out; both suites green.
Out of scope: deleting those style rules; promoting them to skip the revision pass; regenerating drafts/; putting --long on the web UI.

--- Issue #169 as written ---
Stop branding leftover style nits as "a working draft rather than a finished review".

Four of five shipped drafts print that sentence because of recycled phrasing or a repeated sentence opener. The safety-planning piece is the strongest of the set and still wears it. A reader copying the briefing into an email copies a claim that the prose is unfinished.

The sentence is right for a failed substance revision, unverified figures, or a clinical-directive the model could not remove. It is wrong for a leftover six-word n-gram.

## What to change

`render` / Limitations: only print the "working draft" line for errors that change whether the page can be sent — `clinical-directive`, residual unverified/misattributed figures after the check, or a substance rule that a revision did not clear (`under-length` is a warning and stays out). `recycled-phrasing` and `repeated-opener` stay in the CLI log and in `style_report`. They do not brand the page.

## What not to do

- Do not delete those style rules.
- Do not promote them to skip the revision pass. Keep trying to fix them; just stop putting the failure in the sendable page.

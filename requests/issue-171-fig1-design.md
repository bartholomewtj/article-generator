Fig. 1 should show study designs; demote Table 1 Cited by, per GitHub issue #171 (below, verbatim).
Where: articlegen/render.py (Fig. 1, Table 1, briefing compact table), articlegen/sources.py (Paper metadata used for design), tests/test_offline.py, tests/test_journal_conformance.py, CLAUDE.md
Done means: Fig. 1 on the Review path counts by design type not year, with design from title/venue/type metadata already on Paper, falling back to the current year chart if design cannot be labelled for most rows; Table 1 drops Cited by from the default briefing table; on --long, Cited by is dropped or moved out of the first scan and a design column is preferred; citation counts can stay on the reference list; both suites green.
Out of scope: LLM design labelling; a quality-appraisal column in Table 1; putting --long on the web UI; regenerating drafts/.

--- Issue #171 as written ---
Fig. 1 should show study designs. Demote Table 1 "Cited by".

Fig. 1 is cited papers by year, stacked by relevance. A clinician reading a briefing (or a `--long` Review) cares whether the evidence is trials, reviews, observational, or qualitative — not the histogram. Table 1's "Cited by" column is the only quality-looking number on the page, and nothing appraises quality (#102 already had to rename Box 1 for that reason).

## What to change

- Fig. 1 (Review path): counts by design type, not year. Design from title/venue/type metadata already on `Paper`. If design cannot be labelled for most rows, fall back to the current year chart rather than a wrong stack.
- Table 1: drop "Cited by" from the default briefing table. On `--long`, either drop it or move it out of the first scan — a design column is more useful.
- Citation counts can stay on the reference list, where they are bibliographic.

## What not to do

- Do not add LLM design labelling.
- Do not put a quality-appraisal column in Table 1.

Applies to the Review renderer and to whatever compact table the briefing uses.

Refs #102, stays open until this lands if still open; otherwise this is new.

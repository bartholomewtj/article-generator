Print Other instead of a dash in Table 1 Design, and label narrative reviews, scoping reviews, consensus statements, and case reports, per GitHub issue #192 (below, verbatim).
Where: articlegen/sources.py (classify_design, DESIGN_LABELS, _SCOPING_RE and related), articlegen/render.py (design_str currently `---` for other), tests/test_offline.py, tests/test_journal_conformance.py, CLAUDE.md
Done means: `other` prints as `Other` not `---`; scoping / narrative / consensus / case report (or case series) show as those labels rather than Other when the title, venue, or publication_types name them; a meta-analysis whose title omits the words still labels if publication_types says so; Fig. 1 fallback-to-years is unchanged; both suites green.
Out of scope: LLM design labelling; a quality-appraisal column in Table 1; changing Fig. 1’s fallback-to-years rule (#171); changing the default model (#85); putting --long on the web UI; regenerating the public demo Reviews in drafts/.

--- Issue #192 as written ---
Table 1 Design was a dash on 7–9 of 12 rows in every Grok 4.6 briefing (21 Aug 2026). `other` renders as a dash. Scoping is forced to other. Blackman 2023 (a JAMA meta-analysis) dashed because the title does not say “meta-analysis”.

## What to change

- Print `Other` instead of a dash when classify_design returns other.
- Detect narrative review, scoping review, consensus, case report / case series as display labels.
- If publication_types already names a design the title omits, use it.

Refs #185, #171, stays open until this lands.

Cap cites at min(12, n_direct+2), pin question and title to the user’s topic, and prefer already-fetched full texts, per GitHub issue #188 (below, verbatim).
Where: articlegen/writer.py (_WORKING_SET_RULE, briefing/article prompts for question and title, per-run WORKING SET line), articlegen/pipeline.py if the working-set line is built there, tests/test_offline.py, CLAUDE.md
Done means: when n_direct is 7 the writer is told to cite at most 9, not about 12; when n_direct is 21 it still caps at 12 but is told to prefer full-text sources already fetched and not pad with case reports; question/title must stay on the user’s topic (polish wording, no new clause, no narrowed population); both suites green.
Out of scope: banning related citations; dropping DEFAULT_MAX_PAPERS back to 20; changing the default model (#85); putting --long on the web UI; regenerating the public demo Reviews in drafts/.

--- Issue #188 as written ---
Cap the working set at the evidence that is actually direct, and keep the question on the topic the user typed.

Four Grok 4.6 briefings (21 Aug 2026) met the bar on #185. Thin-direct runs padded to 12. All four widened or narrowed the question. Organic fetched 5 full texts and cited 4, padding the rest with case reports.

## What to change

- Cap cites at `min(12, n_direct + 2)` in `_WORKING_SET_RULE` and the per-run WORKING SET line. Direct first; at most two related, and only for a contrast no direct source makes. Do not pad.
- Pin `question` (and title) to the user’s topic. The model may polish wording. It may not add a clause or narrow the population.
- Prefer sources the pipeline already fetched in full. Do not spend a deep read then leave that paper uncited while citing abstract-only case reports.

Refs #185, #167, stays open until this lands.

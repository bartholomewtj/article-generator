Skip generic named-source lookups, and require a distinct extra planner query when search terms are paraphrases, per GitHub issue #190 (below, verbatim).
Where: articlegen/sources.py (named_references / named_matches), articlegen/writer.py (plan_queries), articlegen/pipeline.py (_named_source_pass skip/high-match-rate), tests/test_offline.py, CLAUDE.md
Done means: lookups like `Twelve study`, `English-language trial`, and `ED intervention` are not issued; DOIs and real names (`Safewards trial`) still are; when the planned or supplied terms are near-duplicates the planner must add one extra distinct scholarly index term and must not replace the supplied terms; both suites green.
Out of scope: hardcoding clinical synonyms; undoing #172; chasing nested citations in full text; adding a fifth search API; changing the default model (#85); putting --long on the web UI; regenerating the public demo Reviews in drafts/.

--- Issue #190 as written ---
Skip generic named-source lookups; require a distinct extra query when terms paraphrase.

Four Grok 4.6 briefings (21 Aug 2026) met the bar on #187. Generic names: `Twelve study` (16 returned, 15 matched, 8 new, all tangential) and the earlier `English-language trial` / `ED intervention`. Paraphrase queries on the one-phrase topics; distinct routes when the topic named more than one thing.

## What to change

- When planned or supplied terms are near-duplicates, the extra planner query is required and must be a distinct scholarly index term, not a paraphrase. Do not replace the supplied terms (#172).
- Named-source: skip a lookup if the “name” tokens are generic or if almost every returned record matches. Keep DOIs and real names.

Refs #187, #165, #172, stays open until this lands.

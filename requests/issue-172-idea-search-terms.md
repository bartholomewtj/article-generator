Use the search terms from the idea cards when drafting, per GitHub issue #172 (below, verbatim).
Where: articlegen/ideas.py (search_terms on each card), articlegen/writer.py (plan_queries), articlegen/cli.py (draft), articlegen/web.py (/api/draft), articlegen/pipeline.py (generate_draft), index.html (selectDraft), tests/test_offline.py, CLAUDE.md
Done means: when search_terms are supplied, plan_queries uses them as the starting set and may add at most one more specific query, not replace them; the web selectDraft sends search_terms with /api/draft; CLI draft can take optional --queries; if no terms were supplied, today's plan_queries behaviour stays; both suites green.
Out of scope: making the ideas stage mandatory; putting --long on the web UI; regenerating drafts/.

--- Issue #172 as written ---
Use the search terms from the idea cards when drafting.

`ideas.py` already returns `search_terms` on each card. `plan_queries` ignores them and invents a new set from the title. The only search thinking that happened before the paid draft is thrown away.

## What to change

- CLI: `articlegen draft "<title>"` can take optional `--queries` / keep `plan_queries`, but if the ideas markdown is in hand, pass those terms in.
- Web: `selectDraft` already has the card; send `search_terms` with `/api/draft`. `plan_queries` uses them as the starting set and may add at most one more specific query, not replace them.
- If no terms were supplied, today's `plan_queries` behaviour stays.

## What not to do

- Do not make the ideas stage mandatory. Direct `draft "topic"` with no prior ideas must still work.

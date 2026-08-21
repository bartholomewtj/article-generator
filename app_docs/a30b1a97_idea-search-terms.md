# Retain Idea Card Search Terms in Draft Planning (#172)

## What changed and why

When generating a briefing from an idea card, `ideas.py` generates specific scholarly `search_terms` for each concept. Previously, `plan_queries` ignored these terms and generated a completely new set of search queries from the title alone, discarding the search strategy already established during the ideas phase.

Now:
- When search terms are supplied from idea cards or the CLI, `plan_queries` retains them as the base query set and queries the LLM only to provide at most one additional specific query and the `core_entity`.
- The planner prompt instructs the LLM not to rewrite, reorder, or replace the supplied queries.
- In code, the supplied queries are prepended in order and capped at `MAX_SUPPLIED_QUERIES` (3), with any new query deduplicated and the total queries capped at `MAX_PLANNED_QUERIES` (4).
- When no search terms are provided (e.g. direct drafting without the ideas stage), the previous behavior of generating 2–4 queries is preserved unchanged.

## Key files and changes

- **`articlegen/writer.py`**:
  - Defined constants `MAX_PLANNED_QUERIES = 4` and `MAX_SUPPLIED_QUERIES = 3`.
  - Added `clean_search_terms(terms)` to strip whitespace, deduplicate case-insensitively, drop non-strings/empty strings, cap term length at 120 chars, and limit to 3 terms.
  - Updated `plan_queries(topic, model=None, api_key=None, *, search_terms=None)` to accept optional `search_terms`. When supplied, it formats the terms into the prompt, instructs the LLM to provide at most one additional query plus `core_entity`, and prepends the supplied terms before LLM additions.
- **`articlegen/pipeline.py`**:
  - Added optional `search_terms: list[str] | None = None` to `generate_draft()`. Cleans terms, logs their usage, and passes them to `plan_queries`.
- **`articlegen/cli.py`**:
  - Added `--queries` argument to `articlegen draft`, parsing comma-separated search terms and forwarding them to `generate_draft`.
- **`articlegen/web.py`**:
  - In `_handle_draft`, extracts optional `search_terms` from request JSON, validates type, cleans terms, and passes them to `generate_draft`.
- **`index.html`**:
  - Updated `renderDraftCards` to pass `idea.search_terms` into `selectDraft`.
  - Updated `selectDraft(title, searchTerms)` to include `search_terms` in the `POST /api/draft` payload and in the retry handler (`lastAction`).
- **`tests/test_offline.py`**:
  - Added `test_idea_search_terms_reach_the_draft` to verify term cleaning, prompt generation, deduplication, capping, pipeline forwarding, CLI args, web handling, and front-end wiring.
- **`CLAUDE.md`**:
  - Documented the invariant that supplied search terms start the plan and are never replaced.

## How to use and verify

### CLI
Pass comma-separated queries via `--queries`:
```bash
articlegen draft "Effectiveness of post-discharge suicide prevention interventions" --queries "suicide prevention discharge follow-up, caring contacts brief intervention"
```

### Web
1. Run `articlegen ideas "topic"` in the web interface.
2. Clicking **Generate Full Article →** on any idea card now automatically sends the card's `search_terms` with the draft request.

### Verification
Run the offline test suite and journal conformance tests:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```

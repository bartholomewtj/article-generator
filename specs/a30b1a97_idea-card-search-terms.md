# Plan — use the idea card's search terms when drafting (issue #172)

## What this is

`ideas.py` already returns `search_terms` on every card. `plan_queries` ignores
them and invents a fresh set from the title, so the only search thinking that
happened *before* the paid draft is thrown away.

After this change, when search terms are supplied they become the starting set
of scholarly queries. The model may add **at most one** more specific query. It
may never replace or drop a supplied term. When nothing is supplied, today's
behaviour is unchanged.

The ideas stage stays optional. `articlegen draft "topic"` with no prior ideas
must keep working exactly as it does now.

## Files to touch

| File | Change |
|---|---|
| `articlegen/writer.py` | `plan_queries(..., search_terms=None)` + two constants |
| `articlegen/pipeline.py` | `generate_draft(..., search_terms=None)`, pass through, log it |
| `articlegen/cli.py` | `--queries` flag on `draft`, forward to `generate_draft` |
| `articlegen/web.py` | read + validate `search_terms` from the `/api/draft` payload |
| `index.html` | `renderDraftCards` hands the card's terms to `selectDraft`; `selectDraft` posts them |
| `tests/test_offline.py` | new `test_idea_search_terms_reach_the_draft`, registered in `main()` |
| `CLAUDE.md` | one invariant row + one bullet (also satisfies the docs-current CI gate) |

Do **not** touch `articlegen/ideas.py` — `search_terms` is already on the card
and already rendered on the web card. The issue lists it as a *where* only
because that is where the field comes from.

## 1. `articlegen/writer.py`

Add near `_QUERY_SCHEMA`:

```python
# The search plan is at most four queries, whoever wrote them. When the ideas
# stage supplied terms they are the start of that set and the model may add one
# more specific query — the card's search thinking is the thing being kept, so
# it is never overwritten by the planner's own wording (#172).
MAX_PLANNED_QUERIES = 4
MAX_SUPPLIED_QUERIES = 3
```

New signature (keyword-only for the new argument, so the existing positional
callers and the test fakes that take `(topic, **kw)` keep working):

```python
def plan_queries(
    topic: str,
    model: str | None = None,
    api_key: str | None = None,
    *,
    search_terms: list[str] | None = None,
) -> tuple[list[str], str]:
```

Behaviour:

1. Normalise the supplied terms first, in a small module-level helper so the
   web handler and the test can reuse it:

   ```python
   def clean_search_terms(terms) -> list[str]:
       """Strip, drop blanks, drop case-insensitive duplicates, keep order,
       cap the count and each term's length."""
   ```
   - accept any iterable; ignore non-string entries
   - `strip()`, drop empties
   - dedupe case-insensitively, first spelling wins
   - cap each term at 120 characters
   - cap the list at `MAX_SUPPLIED_QUERIES`
   - return `[]` for `None` or anything that is not a list/tuple

2. If the cleaned list is **empty**: run exactly today's prompt and today's
   `return result["queries"][:MAX_PLANNED_QUERIES], result.get("core_entity", "").strip()`.
   Replacing the literal `4` with the constant is the only change on this path.

3. If the cleaned list is **non-empty**: one LLM call, same `_QUERY_SCHEMA`,
   different prompt. Something like:

   ```
   I want journal articles to support an evidence briefing about: {topic!r}

   These scholarly search terms were already chosen for this question and will
   be searched as they stand:
     1. <term>
     2. <term>
   Do not rewrite them, reorder them or propose alternatives to them.

   Return `queries`: at most ONE additional short keyword query, and only if it
   finds work the terms above would miss — make it specific enough to name the
   exact subject (the most specific entity/population by name). Return an empty
   list if the terms above already cover the question. Also return
   `core_entity`: the specific subject a source must be about to count as
   directly on-topic.
   ```

   Then build the result **in code, not from the model's list**:

   ```python
   queries = list(supplied)
   for q in result.get("queries") or []:
       q = (q or "").strip()
       if q and q.lower() not in {s.lower() for s in queries}:
           queries.append(q)
           break                      # at most one addition, whatever it returned
   queries = queries[:MAX_PLANNED_QUERIES]
   ```

   The cap-in-code is the point: a model that returns four replacements cannot
   displace the card's terms, because the supplied list is copied first and only
   one further entry is ever appended.

4. `core_entity` is still taken from the same call, so nothing downstream
   (`gather_evidence`, the relevance gate) loses its input.

Failure handling does not change: if the call raises, it propagates, exactly as
today. Do not add a "fall back to the supplied terms" branch — a silent fallback
would hide a broken provider, and `core_entity` would be missing anyway.

## 2. `articlegen/pipeline.py`

`generate_draft` gains a keyword-only argument and passes it straight through:

```python
def generate_draft(
    topic: str,
    *,
    style_note: str = "",
    max_papers: int = DEFAULT_MAX_PAPERS,
    model: str | None = None,
    api_key: str | None = None,
    log: Logger = _silent,
    long: bool = False,
    search_terms: list[str] | None = None,
) -> Draft:
```

At the planning step (currently around line 451):

```python
supplied = clean_search_terms(search_terms)          # imported from .writer
if supplied:
    log(f"Using {len(supplied)} search term(s) from the idea card: "
        + "; ".join(supplied) + " (the planner may add one more)")
log(f"Planning search queries for: {topic}")
queries, core_entity = plan_queries(
    topic, model=model, api_key=api_key, search_terms=supplied
)
```

Import `clean_search_terms` alongside `plan_queries` in the existing
`from .writer import (...)` line.

Provenance needs no change. `provenance["queries"]` is already the list that was
actually searched, and Methods prints it — so the card's terms appear in the
Methods section for free, and the derived-never-hardcoded rule still holds.

Order matters: `_preflight_sources` must still run before `plan_queries`
(`test_dead_sources_fail_before_the_caller_is_billed` asserts the source
positions). Put the new `log`/`clean_search_terms` lines *after* the pre-flight
call.

## 3. `articlegen/cli.py`

Parser (`p_draft`):

```python
p_draft.add_argument(
    "--queries", default="",
    help="Comma-separated search terms from the idea card. They are searched as "
         "given; the planner may add one more specific query.",
)
```

`cmd_draft` forwards them:

```python
draft = generate_draft(
    args.topic,
    style_note=args.style,
    max_papers=args.max_papers,
    model=args.model,
    log=_log,
    long=getattr(args, "long", False),
    search_terms=[t.strip() for t in (getattr(args, "queries", "") or "").split(",") if t.strip()],
)
```

Comma-separated single string rather than a repeatable flag — a search term with
a comma in it is not a thing, and one flag is one less moving part.

Also update the `ideas_to_markdown` hint? **No** — out of scope, leave
`ideas.py` alone. `cmd_ideas`'s console hint line stays as it is.

`test_pipeline_is_shared` checks `cmd_draft` does not contain `plan_queries(` —
this change adds no such string, so it stays green.

## 4. `articlegen/web.py`

In `_handle_draft`, after the topic/style/key reads:

```python
raw_terms = payload.get("search_terms")
if raw_terms is not None and not isinstance(raw_terms, (list, tuple)):
    self._send_json({"error": "search_terms must be a list of strings."}, status=400)
    return
search_terms = clean_search_terms(raw_terms)
```

Import `clean_search_terms` from `.writer` at the top of `web.py` (it is a pure
function, no LLM call, so importing it here does not put a stage in the handler).

Pass it into the existing `generate_draft(...)` call:

```python
draft = generate_draft(
    topic, style_note=style[:500], max_papers=DEFAULT_MAX_PAPERS, api_key=api_key,
    model=_requested_model(payload), log=self._log_stage,
    search_terms=search_terms,
)
```

Validation notes:
- `clean_search_terms` already caps count (3) and per-term length (120), so a
  hostile payload cannot inflate the prompt. The existing 64 KB body cap is the
  outer bound.
- Reject a non-list explicitly rather than ignoring it. A silently dropped field
  is the quiet failure this project keeps paying for.
- Validation happens **before** anything paid, and after the existing
  `_missing_key` / `_over_rate_limit` guards stay where they are (quota is
  charged after validation — do not move those).
- The handler must still contain no pipeline stage names
  (`test_pipeline_is_shared`); `clean_search_terms(` is not one of them.

## 5. `index.html`

Two edits, both inside the script block.

**a. `renderDraftCards`** — stop building the button's handler as an inline
`onclick` string with hand-rolled quote escaping, and bind it in JS so the terms
array travels as a real value:

```js
ideas.forEach((idea, idx) => {
  const card = document.createElement('div');
  card.className = 'draft-card';
  const terms = (idea.search_terms || []).filter(t => typeof t === 'string');
  const termsHtml = terms.map(t => `<span class="draft-term">${escapeHtml(t)}</span>`).join(' ');

  card.innerHTML = `
    <span class="draft-num">Idea #${idx + 1}</span>
    <h3 class="draft-title">${escapeHtml(idea.title)}</h3>
    <p class="draft-angle">${escapeHtml(idea.angle)}</p>
    <div class="draft-terms">${termsHtml}</div>
    <button class="btn-select">Generate Full Article →</button>
  `;
  card.querySelector('.btn-select').onclick = function () {
    selectDraft(idea.title, terms);
  };
  container.appendChild(card);
});
```

(`escapeHtml` on the terms is a fix that rides along here: the terms are model
output interpolated into `innerHTML` and were not escaped.)

**b. `selectDraft`** — take the terms, keep them on the retry path, and send
them:

```js
async function selectDraft(title, searchTerms) {
  ...
  const terms = Array.isArray(searchTerms) ? searchTerms : [];
  lastAction = function () { selectDraft(title, terms); };
  ...
  body: JSON.stringify({
    topic: title,
    style: styleGuidance(style),
    key,
    model: activeModel(),
    search_terms: terms
  })
```

`selectDraft` called with one argument still works (`terms` becomes `[]`), so
any other entry point into it is unaffected.

## 6. `tests/test_offline.py`

Add `test_idea_search_terms_reach_the_draft` and register it in `main()`'s tuple
(put it next to `test_pipeline_is_shared`). Use the existing `check(name, cond)`
helper. Assertions:

**writer**
1. `clean_search_terms` normalises: `["  a ", "", "A", "b", "c", "d", None, 7]`
   → `["a", "b", "c"]` (blank dropped, case-insensitive dup dropped, non-strings
   dropped, capped at `MAX_SUPPLIED_QUERIES`), and `clean_search_terms(None) == []`,
   `clean_search_terms("not a list") == []`.
2. With terms supplied and a fake `writer.generate_json` returning
   `{"queries": ["totally different one", "and another"], "core_entity": "x"}`:
   the result is `["term one", "term two", "totally different one"]` — supplied
   first, in order, exactly one addition, nothing replaced. `core_entity == "x"`.
3. The prompt the fake received contains every supplied term and instructs
   against rewriting them (assert on the captured prompt string, e.g. each term
   appears and `"at most one"`/`"ONE additional"` is present — pick whichever
   literal you actually wrote and assert that one).
4. A model that returns a query duplicating a supplied term (differing only in
   case) adds nothing: result length stays 2.
5. `len(result) <= MAX_PLANNED_QUERIES` when 3 terms are supplied and the model
   returns 4.
6. **No terms supplied → today's behaviour**: fake returns six queries; result is
   the model's first `MAX_PLANNED_QUERIES` in order, and the prompt does **not**
   contain the supplied-terms preamble.

   Restore `writer.generate_json` in a `finally`, following the pattern at
   `test_revision_replaces_blocks_rather_than_the_article`.

**pipeline**
7. Swap `pipeline.plan_queries` for a capturing fake
   (`lambda topic, **kw: (captured.update(kw) or (["q"], "core"))`), run
   `generate_draft("topic", search_terms=["a", "b"])` with the usual fakes for
   `gather_evidence` / `curate_sources` / `write_article` / `fetch_full_text` /
   `enforce_style` (copy the harness at `test_pipeline_fetches_full_text`,
   around line 5146), and check `captured["search_terms"] == ["a", "b"]`.
   Restore everything in a `finally`.

**cli**
8. Build the parser (`cli.build_parser()` or whatever the existing factory is —
   check the bottom of `cli.py`) and confirm
   `parser.parse_args(["draft", "t", "--queries", "a, b"]).queries == "a, b"`.
9. `inspect.getsource(cli.cmd_draft)` contains `search_terms=`.

**web**
10. `inspect.getsource(web.ArticleGenHandler._handle_draft)` contains
    `payload.get("search_terms")` and `search_terms=search_terms`, and still
    contains none of the stage names (that part is already covered by
    `test_pipeline_is_shared`; do not duplicate it).

**front end** (read `index.html` as text, like
`test_front_end_models_match_the_allowlist` does)
11. The `/api/draft` fetch body contains `search_terms`.
12. `selectDraft(` is called with the terms in `renderDraftCards`
    (`selectDraft(idea.title, terms)` present).

Then run both suites:

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. Judge by exit status, not by scanning output text.

## 7. `CLAUDE.md`

Two edits (this also satisfies `.github/workflows/docs-current.yml`, which fails
a PR touching `articlegen/**` without touching this file):

- Add a row to the invariants table:

  `| Supplied search terms start the plan and are never replaced | test_idea_search_terms_reach_the_draft |`

- Add a bullet under **Sources and grounding**:

  > **The idea card's `search_terms` start the search plan when they are
  > supplied.** `ideas.py` already returns them and the web card already shows
  > them; `plan_queries` used to throw them away and invent a new set from the
  > title, so the only search thinking done before the paid draft was discarded
  > (#172). Supplied terms are copied into the query list **in code** and the
  > model may append **at most one** more specific query — a planner that
  > returns four replacements cannot displace them. `MAX_PLANNED_QUERIES` (4)
  > and `MAX_SUPPLIED_QUERIES` (3) bound both ends. With no terms supplied the
  > old one-shot prompt runs unchanged: the ideas stage is not mandatory and
  > `draft "topic"` on its own must keep working.

Every backticked filename, `test_*` name and `SHOUTY_CONSTANT` written into
CLAUDE.md is checked by `test_claude_md_still_describes_this_code`, so the test
name and both constants above must exist exactly as spelled.

## Out of scope

- Making the ideas stage mandatory.
- Putting `--long` on the web UI.
- Regenerating anything in `drafts/`.
- Changing `ideas.py`, the ideas prompt, or the number of terms a card returns.
- Recording the supplied terms separately in provenance or in Methods —
  `provenance["queries"]` is already the honest record of what was searched.

## Verify

1. `python tests/test_offline.py` → exit 0.
2. `python tests/test_journal_conformance.py` → exit 0.
3. `python -c "from articlegen.cli import main; main(['draft','--help'])"` shows
   `--queries` (or just run `articlegen draft --help`).
4. Optional, spends credit — do not run unless asked:
   `articlegen draft "<a question>" --queries "term one, term two"` and check the
   log line names the supplied terms and the finished Methods section prints
   them among the search strings.

## Git

Branch, then PR — this touches six files. Put "Refs #172" in the PR body if you
want it linked; write "Closes #172" only if the owner asks. Never write "does
not close #NNN" anywhere in a commit message or PR body.

# Plan — the named-source pass (issue #165)

## What this does

Today the search is one shot: the model plans 2–4 queries, we gather once, we
curate, we write. A landmark trial that every top abstract names but no query
happens to hit never reaches the pool, so its numbers arrive quoted inside
another paper (#141, #142).

After curation, read the two or three most relevant abstracts, pull out the
papers they name — DOI where the abstract prints one, study name otherwise —
run **one extra gather** for those names, merge the new records into the
candidate pool through the existing DOI/title dedupe, label **only the new
records**, then write. Methods says the pass ran and what it added.

Hard caps so a chatty review abstract cannot explode the pool: at most 8 named
lookups, at most 8 new records kept.

## Where the pass sits, and why there

`pipeline.generate_draft`, between `curate_sources` and the full-text loop.

That order matters. A named landmark trial is exactly the paper that should get
a deep read, and the full-text loop is what does the deep reading — so the new
records must be in the pool *before* it runs. The consequence is that nothing
has full text yet at extraction time, so **extraction reads abstracts only**.
The issue's "and any full text already fetched" is not implementable at this
point in the pipeline without either fetching twice or denying the new papers a
deep read; say so in the code comment rather than adding an inert `full_text`
branch to the extractor.

Nothing else moves: `FULLTEXT_TARGET`, `MAX_FULLTEXT_REQUESTS`, the open-access
constraint, `DEFAULT_MAX_PAPERS`, the four search sources, the writer prompt
shape.

## Design decisions taken (do not re-open while building)

1. **No new API and no new endpoint.** The named pass is a second
   `gather_evidence(...)` call with the DOIs/names as query strings. A DOI as
   free text is a weak query on OpenAlex and a decent one on Europe PMC and
   Semantic Scholar; a study name ("Safewards trial") is a strong query
   everywhere, and that is the common case in an abstract. Hit rate is
   unmeasured — the run must log it (below) so the next session can decide
   whether a targeted DOI lookup is worth a follow-up issue.
2. **New records are accepted only when they match what was asked for.** A
   free-text DOI query can return unrelated noise, and noise in the pool is
   worse than a miss. Keep a returned paper only if it passes the acceptance
   rule in `named_matches()` below.
3. **Extraction is deterministic, not an LLM call.** Same argument as
   `style.py` and `verify.py`: a model asked "which papers does this abstract
   name?" answers differently each time, and this rule needs negative controls
   in a test to be trustworthy. It also keeps the pass free.
4. **New papers are appended to the end of the pool and the pool is never
   re-sorted.** The 1-based index into `papers` *is* the citation scheme and
   the key of `curation["relevance"]`. Re-ranking after the merge would silently
   re-point every existing label. Appending keeps indices 1..N stable and gives
   the new records N+1..M.
5. **Only the new records are curated.** One extra `curate_sources` call over
   the new papers alone, its 1..k labels shifted by N and merged in. The first
   pass's `most_relevant_index` is kept as is.
6. **The named pass shares the run's source state.** See "The two globals" —
   this is the easiest thing to get wrong.

## The two globals (read this before touching `gather_evidence`)

`gather_evidence` treats each call as a run boundary. A second call in the same
draft would, as the code stands:

- reset `_s2_patient_round_spent`, buying a **second** 30-second Semantic
  Scholar wait in one draft — breaking the invariant that the first refusal of
  a run buys *one* patient round (`test_first_semantic_scholar_refusal_buys_one_patient_round`); and
- reset the local `exhausted` set, so every source that already refused during
  the main gather gets retried — three tries with backoff each, per named query.
  Eight named queries against a dead Semantic Scholar is over a minute of dead
  time with a user watching a progress bar.

Fix both by letting the caller carry the state across the two calls:

- add `exhausted: set[str] | None = None` to `gather_evidence`; when passed, use
  that set instead of a fresh one (`exhausted = set() if exhausted is None else exhausted`);
- call the named pass with `patient=False` (the existing parameter already means
  "start with the patient round spent");
- `generate_draft` creates one `exhausted: set[str] = set()` and passes it to
  both gathers.

## Changes, file by file

### `articlegen/sources.py`

**Constants** (one place, read by the pipeline — same rule as
`DEFAULT_MAX_PAPERS`):

```python
NAMED_SOURCE_SCAN = 3        # abstracts read for names
NAMED_SOURCE_LIMIT = 8       # lookups requested, and new records kept
NAMED_SOURCE_PER_QUERY = 5   # page size for a lookup; we want one exact record
```

**`named_references(text: str) -> list[str]`** — the extractor. Deterministic,
ordered, deduped, truncated to `NAMED_SOURCE_LIMIT`, DOIs first (they are
precise), then study names.

- DOIs: `10\.\d{4,9}/[^\s"'<>,;)\]]+`, trailing punctuation stripped, run
  through `_normalize_doi` and dropped if that returns `""`.
- Study names, two patterns over the raw (case-preserving) abstract:
  - name-then-noun: a capitalised or ALL-CAPS name of 1–3 tokens immediately
    before `trial|study|programme|program|cohort|RCT|intervention`, e.g.
    "Safewards trial", "RAISE-ETP study";
  - noun-then-parenthesised acronym: `... trial (SAFEWARDS)`.
  The returned query is the name plus its noun ("Safewards trial") — that is
  what searches well.
- Precision rules, because a false name costs four API requests and can drag
  noise into the pool:
  - accept a token as a name only if it is ALL-CAPS (≥3 characters, at least
    one letter) **or** a capitalised word that is not sentence-initial and not
    in the stoplist;
  - stoplist of capitalised non-names and apparatus acronyms: `This`, `The`,
    `Our`, `A`, `An`, `Recent`, `Previous`, `Current`, `Prior`, `One`, `Two`,
    `We`, plus `RCT`, `PRISMA`, `CONSORT`, `GRADE`, `PROSPERO`, `WHO`, `NICE`,
    `NHS`, `NIH`, `USA`, `UK`, `COVID`, `PICO`, `MEDLINE`, `EMBASE`, `CINAHL`.
  Keep the stoplist and the regexes together with a comment saying the negative
  controls in the test are the specification (same convention as
  `style._IMPERATIVE_RE`).

**`named_matches(paper: Paper, request: str) -> bool`** — the acceptance rule.

- If `request` normalises to a DOI: keep only when
  `_normalize_doi(paper.doi) == _normalize_doi(request)`.
- Otherwise: keep only when the name part of the request (the request minus its
  trailing study noun), normalised with `_normalize_title`, appears in
  `_normalize_title(paper.title)`.

**`merge_candidates(pool: list[Paper], extra: list[Paper], limit: int) -> list[Paper]`**
— the merge, using the dedupe rules already in `gather_evidence`.

- Build `by_doi` / `by_title` from `pool` (DOI first, title second, via
  `_normalize_doi` / `_normalize_title`).
- For each `extra` paper: if it matches an existing record, `_merge_duplicate`
  into the kept copy (existing wins — first-seen identity is never swapped) and
  register the duplicate's keys against it; otherwise append, up to `limit` new
  records.
- Return the list of newly appended papers (the caller needs their indices).
  The pool is mutated in place and **never re-sorted**.
- Refactor `gather_evidence`'s inner dedupe block to share this helper if it
  falls out cleanly; if the shapes fight, leave `gather_evidence` alone and keep
  `merge_candidates` a sibling with a comment pointing at it. Do not risk the
  dedupe behaviour pinned by `test_candidate_papers_dedupe_by_doi`.

**`gather_evidence`**: add the `exhausted` parameter described above. No other
behaviour change.

`Paper` needs no new field.

### `articlegen/pipeline.py`

After the curation block and its warning, before the full-text loop:

```python
named = _named_source_pass(topic, papers, curation, exhausted, model, api_key, log)
```

A module-level helper (not inline in `generate_draft` — it needs to be readable
and the function is already long) that:

1. Picks the abstracts to scan: `most_relevant_index` if it carries a
   direct/related label, then `full_text_order(papers, relevance)`, deduped and
   truncated to `NAMED_SOURCE_SCAN`. Reusing `full_text_order` is deliberate —
   direct before related, newest first, is already the "most relevant" order and
   is already tested.
2. Runs `named_references` over each scanned abstract, concatenating in order,
   deduping, truncating to `NAMED_SOURCE_LIMIT`. Returns early (empty result) if
   nothing was named.
3. Logs what it will ask for: `Following up N paper(s) named in the top M abstract(s): ...`
4. Calls
   `gather_evidence(requests, max_papers=NAMED_SOURCE_LIMIT * 2, per_query=NAMED_SOURCE_PER_QUERY, topic=topic, core_entity=core_entity, log=log, outcomes=outcomes, exhausted=exhausted, patient=False)`.
   Passing the same `outcomes` list matters: a database that only answered here
   still belongs in Methods' `databases`.
5. Filters the results with `named_matches` against the request that could have
   produced them (a result is kept if it matches **any** request).
6. `merge_candidates(papers, accepted, limit=NAMED_SOURCE_LIMIT)` → the new
   papers, appended.
7. If new papers exist, `curate_sources(topic, new_papers, model=..., api_key=...)`,
   shift its `relevance` keys by the old pool length, merge into
   `curation["relevance"]`, recompute `curation["counts"]` from the merged
   relevance. Leave `most_relevant_index` alone. If that curation comes back
   empty, log the same style of warning the main curation has (the new records
   will be unlabelled, so they will never be deep-read — say so).
8. Returns `{"queries": requests, "added": len(new_papers)}` for provenance.

Logging (this pass is unmeasured, so the log is how the next session learns
whether it works — follow the `#84` precedent of naming the exit, not just the
count):

```
Following up 5 paper(s) named in the top 3 abstract(s): 'Safewards trial'; '10.1001/...'
  named-source pass: 5 requested, 7 records returned, 3 matched, 2 new after dedupe
  relevance (new records): 1 direct / 1 related / 0 tangential
```

Provenance gains one key, derived and only when the pass actually ran:

```python
if named["queries"]:
    provenance["named_sources"] = {"queries": named["queries"], "added": named["added"]}
```

No key when nothing was named — the same no-fallback rule as `databases`.

### `articlegen/writer.py`

`curate_sources` already works on any list of papers and returns 1-based labels,
so **no signature change is needed**. Add two sentences to its docstring saying
it is called a second time for the records the named-source pass added, that the
caller shifts the indices, and that it must therefore keep returning indices
relative to the list it was handed.

If (and only if) the isolated second call misbehaves in review — e.g. it labels
4 landmark trials `tangential` because it cannot see the rest of the pool —
note it in the PR body as a measurement to take; do not add a "context" argument
speculatively.

### `articlegen/render.py`

One derived sentence in the **search-strategy** paragraph of
`_methods_paragraphs`, after the curation sentence, only when provenance
records the pass:

```python
named = (provenance.get("named_sources") or {}) if provenance else {}
named_queries = [q for q in (named.get("queries") or []) if q]
if named_queries:
    added = int(named.get("added") or 0)
    search += (
        f" A second, targeted search then looked up {len(named_queries)} "
        f"work{'s' if len(named_queries) != 1 else ''} named in the most "
        f"relevant abstracts ("
        + "; ".join(f"‘{esc(q)}’" for q in named_queries) + "), which added "
        + (f"{added} further record{'s' if added != 1 else ''} to the pool."
           if added else "no further records to the pool.")
    )
```

Both renderers already go through `_methods_paragraphs`, so Markdown gets it for
free. Escaping goes through `esc` like every other outside value. A draft
without the key renders exactly as it does today — old drafts and the
conformance fixtures must not change.

### `tests/test_offline.py`

Four new tests, each added to the tuple in `main()`:

1. **`test_named_papers_in_abstracts_are_looked_up`** — the pinning test. Build
   it on the `test_pipeline_fetches_full_text` harness (monkeypatch
   `pipeline.plan_queries` / `gather_evidence` / `curate_sources` /
   `write_briefing` / `fetch_full_text` / `enforce_style`, restore in `finally`).
   Assert:
   - the second `gather_evidence` call happens, and its query list contains the
     DOI printed in the curated abstract **and** the trial name;
   - only the top `NAMED_SOURCE_SCAN` abstracts were scanned (a DOI in a
     fourth-ranked abstract is not requested);
   - the second call gets `patient=False` and the *same* `exhausted` set object
     as the first;
   - the returned paper is appended at index N+1 and indices 1..N are unchanged
     (check `draft.papers[0] is papers[0]` and the existing relevance labels);
   - `curate_sources`'s second call receives exactly the new papers, and the
     merged `curation["relevance"]` holds a label at N+1 with `counts`
     recomputed;
   - `provenance["named_sources"]` records the queries and the added count;
   - the cap: an abstract naming 20 DOIs produces at most `NAMED_SOURCE_LIMIT`
     requests, and returning 20 matching records adds at most
     `NAMED_SOURCE_LIMIT` new papers;
   - nothing named → no second gather and no `named_sources` key.
2. **`test_named_references_reads_names_not_noise`** — the extractor, with the
   negative controls as the specification. Positive: "the Safewards cluster
   randomised controlled trial", "(doi: 10.1001/jama.2015.1234)", "the RAISE-ETP
   study", "a stepped-wedge trial (STAR)". Negative: "This study found…",
   "Recent trials suggest…", "a randomised controlled trial (RCT)", "reported
   using PRISMA", "The trial was registered". Then sweep all 14 abstracts in
   `tests/real_abstracts.json` and assert every extraction is within the cap and
   contains no stoplisted token — a chatty abstract must not explode the pool.
3. **`test_named_sources_merge_without_renumbering`** — `merge_candidates`
   directly: a duplicate by DOI spelled three ways and by title merges into the
   existing record (existing identity kept, metadata enriched), a genuine new
   record appends at the end, the `limit` binds, existing indices never move.
   Include `named_matches` here: a DOI request rejects a paper with a different
   DOI; a name request rejects a paper whose title does not contain the name.
4. **`test_methods_names_the_named_source_pass`** — render with and without
   `provenance["named_sources"]`; the sentence appears in HTML and Markdown when
   the key is there, names the count and the added count, is absent when the key
   is absent, and the query text is HTML-escaped in the HTML path.

Also check `test_the_candidate_pool_is_big_enough_to_curate`'s "no module
hardcodes a cap of its own" sweep still passes — do not write a literal `8` in
`pipeline.py`; read `NAMED_SOURCE_LIMIT` from `sources`.

### `CLAUDE.md`

- Two rows in the invariants table:
  - `| Papers named in the top abstracts are looked up once, capped | test_named_papers_in_abstracts_are_looked_up |`
  - `| A merged record never renumbers the pool | test_named_sources_merge_without_renumbering |`
- One bullet in **Sources and grounding**, in the house voice: the search is no
  longer one-shot; after curation the top `NAMED_SOURCE_SCAN` abstracts are
  scanned for DOIs and study names, one extra gather runs for up to
  `NAMED_SOURCE_LIMIT` of them, matched records merge through the existing
  DOI/title dedupe and are **appended, never re-ranked**, because the index is
  the citation scheme; only the new records are re-curated; the pass shares the
  run's `exhausted` set and runs with `patient=False`, so it cannot buy a second
  30-second Semantic Scholar wait.
- One line under the pipeline description noting the new stage between
  `curate_sources` and the full-text fetch.
- Every constant and test name you write in backticks must exist —
  `test_claude_md_still_describes_this_code` checks it.

### `docs/decisions.md`

- New `### \`#165\` — the search was one-shot` under the sources section: what
  it cost (the Safewards trial, #141/#142), what was built, the caps and why,
  the two globals that made a second `gather_evidence` call dangerous, and what
  to measure on the first real runs (how many names extracted, how many matched,
  whether a DOI-as-free-text query ever hits — if it never does, a targeted DOI
  lookup on the same four APIs is the follow-up).
- Amend the `#142` paragraph that says chasing nested references "was left out
  of scope" so it points at #165 for the narrow version that landed. Keep the
  retrospective wording — the audit test reads those markers.

## Verify

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. The conformance fixtures carry no `named_sources` key, so
their Methods output must be byte-identical to before — if a fixture changes,
the sentence is not properly gated.

Optional live check (spends credit and quota, only if the operator asks):
`articlegen draft "seclusion and restraint reduction in acute mental health wards"`
and read the log for the named-source lines and the Methods sentence.

## Branch, commit, PR

Already on `feat/165-snowball-named-papers`. Commit, push, and open the PR with
`gh pr create`. The PR body must:

- say what changed in plain language and name the caps;
- carry `Closes #165` and `Refs #141, #142`;
- **never** contain the words "does not close" next to an issue number —
  GitHub's parser ignores the negation and closes the issue anyway;
- satisfy the docs gate by touching `CLAUDE.md` (it does).

## Out of scope

A fifth search API. Chasing every nested citation inside full text. Weakening
the open-access constraint. `--long` on the web UI. Regenerating `drafts/`.
Raising `FULLTEXT_TARGET`, `MAX_FULLTEXT_REQUESTS` or `DEFAULT_MAX_PAPERS`.

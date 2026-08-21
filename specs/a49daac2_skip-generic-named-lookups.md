# Plan — skip generic named-source lookups, demand a distinct extra query when terms paraphrase (#190)

## What this fixes

Two separate leaks measured on four Grok 4.6 briefings (21 Aug 2026):

1. **The named-source pass spends lookups on things that are not names.**
   `named_references` pulled `Twelve study` out of a structured abstract
   (16 records returned, 15 matched, 8 new, all tangential), and earlier runs
   produced `English-language trial` and `ED intervention`. A generic "name"
   matches almost anything, so the follow-up gather buys a pile of off-topic
   records and pushes real candidates out of the pool.

2. **The planner writes paraphrases when the topic is one phrase.** With supplied
   search terms (#172) or with its own 2–4 planned queries, the planner
   frequently returns terms that all search the same route. The extra query is
   then either absent or a re-wording, so a run with three queries really has one.

Reproduced today, current `main`:

```
'RESULTS Twelve studies were included in the review.' -> ['RESULTS Twelve study']
'We included Twelve studies of seclusion.'            -> ['Twelve study']
'We searched for English-language trials …'           -> ['English-language trial']
'The ED intervention reduced restraint use.'          -> ['ED intervention']
'Data from the US trial and UK trials …'              -> ['US trial']
'the Safewards cluster randomised controlled trial'   -> ['Safewards trial']   # keep
```

**Done means:** the first five return `[]`, the last one and DOIs still return
what they return, a name that matches almost every returned record is dropped
before it reaches the pool, near-duplicate query sets force one extra *distinct*
scholarly index term without touching the supplied terms, and both suites are
green.

## Step 0 — delete the duplicated block in `articlegen/sources.py` first

`articlegen/sources.py` currently holds the whole named-source block **twice,
byte-identical**: lines 1305–1489 and 1490–1674 (`NAMED_SOURCE_SCAN`,
`_NAMED_STOPLIST`, `_DOI_EXTRACT_RE`, `_NAME_THEN_NOUN_RE`,
`_NOUN_THEN_ACRONYM_RE`, `_STUDY_NOUN_CANONICAL`, `_is_sentence_initial`,
`_is_valid_name_token`, `named_references`, `_STUDY_NOUNS_RE`, `named_matches`,
`merge_candidates`). Python keeps the **second** copy. Editing only one is the
obvious way to spend an hour on a change that does nothing.

Do this before any other edit, as its own commit:

```
sed -n '1305,1489p' articlegen/sources.py > /tmp/a.txt
sed -n '1490,1674p' articlegen/sources.py > /tmp/b.txt
diff /tmp/a.txt /tmp/b.txt          # must be empty — confirm before deleting
```

Delete the **first** copy (1305–1489, the dead one), keep the second. Verify:

```
grep -c "^def named_references" articlegen/sources.py     # must print 1
grep -c "^NAMED_SOURCE_SCAN"    articlegen/sources.py     # must print 1
python tests/test_offline.py                              # green before moving on
```

If the diff is not empty, stop and report — the two copies drifted and that is a
different bug.

## Change 1 — `articlegen/sources.py`: a generic "name" is not a name

All edits go in the surviving block.

### 1a. Widen `_NAMED_STOPLIST`

Add, keeping the existing entries:

- **Structured-abstract section headers** (they arrive ALL-CAPS and the
  ALL-CAPS branch of `_is_valid_name_token` waves them through, which is how
  `RESULTS Twelve study` happened): `background objective objectives aim aims
  method methods result results findings conclusion conclusions discussion
  introduction design setting participants outcomes limitations registration
  funding data evidence eligibility`.
- **Number words**: `zero one two three four five six seven eight nine ten
  eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen
  twenty thirty forty fifty sixty seventy eighty ninety hundred thousand`
  (`one two` are already there — keep the list deduped, it is a frozenset).
- **Quantifiers and filler determiners**: `several many most some few both all
  other another further additional remaining various multiple numerous each
  every no included eligible`.
- **Setting / geography acronyms that name a place or a ward, never a study**:
  `us eu ed er icu gp` (`usa uk who nhs nih` are already there).

Keep the existing comment pointing at the test as the specification, and extend
it: the specification for these is the negative-control list in the new test.

### 1b. Reject two-letter acronyms in `_is_valid_name_token`

Today the ALL-CAPS branch requires `len(t) >= 3`, but a two-letter uppercase
token then falls through to the "capitalised word" branch and is accepted —
that is `ED intervention` and `US trial`. Fix: before the capitalised-word
branch, reject a token whose alphabetic characters are all uppercase and whose
length is under 3. Two letters carry no distinguishing content; a real study
acronym has three or more (`RAISE-ETP`, `STAR`, `SAFEWARDS`).

### 1c. Reject hyphenated descriptive compounds

Add a module-level frozenset `_GENERIC_NAME_SUFFIXES` holding the tails of
compounds that *describe* a study rather than name one:

```
language based related led level wide term arm site centre center
country year month week day group controlled blind blinded specific
adjusted matched only
```

In `_is_valid_name_token`, reject a token containing `-` whose portion after the
last `-`, lowercased and stripped of punctuation, is in that set. This kills
`English-language`, `population-based`, `nurse-led`, `single-centre`,
`hospital-wide`, `long-term`, `two-arm`. It leaves `RAISE-ETP` and `STAR*D`
alone because their tails are not in the set.

Put these three checks in one small helper, `_is_generic_name_token(token) ->
bool`, called from `_is_valid_name_token`, so the reasoning has one home and the
test has one thing to exercise.

`named_references` itself needs no structural change: its existing loop pops
invalid leading tokens and rejects a name with any invalid trailing token, so
`Twelve studies`, `RESULTS Twelve studies`, `English-language trials` and
`ED intervention` all fall out to `[]` once the token rules tighten.

### 1d. Backstop: a name that matches almost everything is not a name

Some generic names will still get through the token rules. Their signature is
behavioural — a real name matches one or two of the records that come back, a
generic one matches nearly all of them.

Add next to the other named-source constants, each with a one-line comment:

```python
NAMED_MATCH_RATE_MAX = 0.5    # share of returned records one name may match
NAMED_MATCH_MIN_MATCHES = 5   # below this, a high share means a small return
```

Add a pure function (importable and testable without the pipeline):

```python
def filter_named_matches(records: list[Paper], requests: list[str]) -> tuple[list[Paper], list[str]]:
    """Keep the records a request genuinely asked for; drop requests that behave generically.

    Returns (kept records, requests dropped). A DOI request is never dropped —
    it identifies exactly one work. A name request is dropped when it matches
    at least NAMED_MATCH_MIN_MATCHES records AND more than NAMED_MATCH_RATE_MAX
    of everything returned: a name that matches most of the pool is describing
    the literature, not naming a paper.
    """
```

Rules, in full, so the builder does not have to guess:

- Empty `records` or empty `requests` → `([], [])`.
- A request is a DOI when `_normalize_doi(request)` is truthy → always kept.
- For each name request, `count = sum(1 for p in records if named_matches(p, req))`.
  Drop it when `count >= NAMED_MATCH_MIN_MATCHES and count / len(records) > NAMED_MATCH_RATE_MAX`.
- A record is kept when it matches at least one **surviving** request.
- Order of kept records follows `records`; order of dropped requests follows
  `requests`.

The `NAMED_MATCH_MIN_MATCHES` floor is the part that protects a real name: a
lookup that returns 3 records and matches 2 of them scores 0.67 but is below the
floor, so it survives. The cost of the rule being wrong is a handful of extra
records the pool of 40 did not need; the cost of not having it is eight
tangential records displacing real candidates.

## Change 2 — `articlegen/pipeline.py`: use the filter and say what was skipped

In `_named_source_pass`:

- Import `filter_named_matches` (and the two new constants if you log them)
  from `.sources` alongside the existing named-source imports.
- Replace `matched = [p for p in extra_records if any(named_matches(p, req) for req in requests)]`
  with `matched, dropped = filter_named_matches(extra_records, requests)`.
- Extend the existing summary log line so a run says what happened:

  ```
  named-source pass: 3 requested, 16 records returned, 15 matched, 1 new after dedupe
  ```

  becomes, when something was dropped:

  ```
  named-source pass: 3 requested, 16 records returned, 1 matched, 1 new after dedupe
    dropped as generic (matched most of what came back): 'Twelve study'
  ```

  Only print the second line when `dropped` is non-empty. This is the same rule
  as the full-text stop reason: a count with no reason is not an answer.
- `named_references` returning nothing after the tightened rules already means
  `requests` is empty and the second gather never runs — leave that branch alone.
- **Provenance is unchanged.** `provenance["named_sources"]["queries"]` must keep
  listing the queries that were **actually issued**, because
  `render._methods_html` prints "looked up N works named in the most relevant
  abstracts" from it and Methods must describe what ran. A request that was
  issued and then dropped by the rate rule was still looked up, so it stays in
  `queries`; a name never extracted was never issued, so it was never in there.
  Do not add a `skipped` key — nothing renders it, and every provenance key is
  something a future reader will assume is printed somewhere.

## Change 3 — `articlegen/writer.py`: near-duplicate terms buy one distinct query

### 3a. Deterministic near-duplicate test

Near the other query constants (`MAX_PLANNED_QUERIES`, `MAX_SUPPLIED_QUERIES`):

```python
NEAR_DUPLICATE_OVERLAP = 0.6   # overlap coefficient above which two queries search the same route
```

Helpers, all pure and all tested:

- `_query_tokens(q: str) -> set[str]` — lowercase, split on non-alphanumerics,
  drop tokens in a small function/filler-word set (`the a an of in on for and or
  to with among between using versus vs effect effects impact study studies
  trial trials review reviews systematic randomised randomized controlled` plus
  the number words), drop tokens shorter than 3 characters, strip a trailing `s`
  from what is left so `interventions`/`intervention` agree.
- `queries_are_near_duplicates(a: str, b: str) -> bool` — overlap coefficient
  `len(ta & tb) / min(len(ta), len(tb))` `>= NEAR_DUPLICATE_OVERLAP`. **If either
  side normalises to an empty set, return `False`** — an unjudgeable pair is not
  a duplicate, and this is what keeps the existing `test_idea_search_terms_reach_the_draft`
  cases (`"term one"`, `"other"`) behaving as they do today.
  Use the overlap coefficient, not Jaccard: a paraphrase that adds three words
  ("reducing seclusion in psychiatric inpatient units" vs "seclusion reduction
  psychiatric inpatient") scores 0.75 on overlap and only 0.50 on Jaccard.
- `query_routes(queries: list[str]) -> int` — greedy single-link clustering
  under `queries_are_near_duplicates`; returns the number of distinct clusters.
  A list of one term returns 1.

"The terms are near-duplicates" means `query_routes(terms) <= 1` — every term
searches one route. A single supplied term counts, deliberately: one term is one
route, and the point of the extra query is to add a second.

### 3b. Supplied-terms path (must not undo #172)

The supplied terms are known **before** the call, so harden the prompt up front
rather than paying for a retry by default.

- When `query_routes(supplied) > 1` — the terms already take distinct routes —
  send today's prompt unchanged and keep today's behaviour (at most one addition).
- When `query_routes(supplied) <= 1`, send a variant that says the terms all
  search the same route and that **exactly one** additional query is required.
  Wording to use, following the existing prompt's voice:

  > These terms all search the same route — they re-word one another. Return
  > `queries`: exactly ONE additional short keyword query that a scholarly index
  > would match to a *different* set of records — a different intervention,
  > population, outcome measure, setting, or the standard indexing term for the
  > subject. It must not be a re-wording, synonym, reordering or narrowing of
  > the terms above. An empty list is not an acceptable answer here.

  Keep the existing "Do not rewrite them, reorder them or propose alternatives
  to them" line above it: the supplied terms are still copied into the query
  list in code and are never replaced or reordered (#172).
- Accept the first returned query that is neither a case-insensitive duplicate
  **nor** a near-duplicate (`queries_are_near_duplicates`) of any query already
  in the list. When nothing survives and the terms were near-duplicates, retry
  **once** with the same prompt plus one line quoting the rejected suggestion:
  "`<q>` was a re-wording of the terms above — it searches the same records.
  Return a different indexing term." Accept from the retry under the same rule.
- If the retry also fails: log it (see 3d) and return the supplied terms
  unchanged. **Never raise, never block the draft** — a weak query plan is worse
  than a paraphrase but neither is worth failing a paid run over.
- Only apply the near-duplicate rejection when the supplied set was
  near-duplicate. When the terms already took distinct routes, today's
  first-non-duplicate rule stands, so runs that are already fine cost nothing new.
- Cap unchanged: `MAX_PLANNED_QUERIES` (4) still trims the result. With
  `MAX_SUPPLIED_QUERIES` = 3 there is always room for the extra.

### 3c. No-supplied path

The planner returns 2–4 queries in one call; near-duplication is only knowable
afterwards.

- Take `queries = (result.get("queries") or [])[:MAX_PLANNED_QUERIES]` as today.
- If `queries` is non-empty and `query_routes(queries) <= 1`, make **one**
  follow-up `generate_json` call asking for a single distinct query, quoting the
  queries already planned and reusing the same "different set of records / not a
  re-wording" wording as 3b. One call, never a loop.
- Accept the first returned query that is not a case-insensitive or
  near-duplicate of one already held. If the list is already at
  `MAX_PLANNED_QUERIES`, make room by dropping the **last** query that is a
  near-duplicate of an earlier one — a paraphrase is the redundant member, so it
  is the one to give up. If somehow nothing is droppable, keep the list as it is
  and skip the addition.
- `core_entity` still comes from the first call; the follow-up must not change it.

### 3d. Visibility

Give `plan_queries` an optional `log` keyword (`log=lambda msg: None`, matching
`Logger` usage elsewhere) and pass `log=log` from `pipeline.generate_draft`'s
call. Log one line each for: the terms being near-duplicates and an extra query
being required, a rejected paraphrase and its text, and the final failure to get
a distinct query. Silence here is how a paraphrase plan looks identical to a good
one in the CLI output.

## Change 4 — `tests/test_offline.py`

Two new tests, both registered in the tuple inside `main()` (put them next to
`test_named_papers_in_abstracts_are_looked_up` and
`test_idea_search_terms_reach_the_draft` respectively). Use the existing
`check(name, cond)` style; assert on behaviour, not on wording.

### `test_generic_named_lookups_are_skipped`

Negative controls (each must return `[]`) — these are the specification, so
write them as a list with the failing string beside the assertion:

- `"RESULTS Twelve studies were included in the review."`
- `"We included Twelve studies of seclusion."`
- `"We searched for English-language trials of seclusion reduction."`
- `"The ED intervention reduced restraint use."`
- `"Three ED interventions were compared."`
- `"Data from the US trial and UK trials were combined."`
- `"A population-based cohort study followed adults."`
- `"BACKGROUND Several trials have examined restraint."`

Positive controls (must still be extracted):

- `"the Safewards cluster randomised controlled trial"` → `["Safewards trial"]`
- `"In the RAISE-ETP study, comprehensive care improved outcomes."` → `["RAISE-ETP study"]`
- `"(doi: 10.1001/jama.2015.1234)"` → the DOI
- `"a stepped-wedge trial (STAR)"` → `["STAR trial"]`
- a sentence carrying both a DOI and a real name → DOI first, then the name.

Then `filter_named_matches`, built from `Paper` objects with plain titles:

- 16 records, a name request matching 15 of them → request dropped, none of its
  records kept.
- The same 16 records, a name request matching 2 → kept.
- A DOI request matching every record → never dropped (state why in the check
  name: a DOI identifies one work).
- 3 records, a name matching 2 (0.67 rate, below `NAMED_MATCH_MIN_MATCHES`) → kept.
- A record matching one dropped and one surviving request → kept.
- Empty `records` and empty `requests` → `([], [])`.

Also assert the pipeline wiring end-to-end with the fakes already used by
`test_named_papers_in_abstracts_are_looked_up`: a second gather that returns
records all matching one generic-behaving name adds **no** new papers to
`draft.papers`.

### `test_paraphrase_terms_buy_a_distinct_query`

With `writer.generate_json` swapped for a fake that records prompts (restore it
in a `finally`, as the existing test does):

- `queries_are_near_duplicates` unit checks: a paraphrase pair is True, an
  unrelated pair is False, a pair where one side normalises to nothing is False.
- `query_routes(["seclusion reduction acute mental health",
  "reducing seclusion in acute mental health wards"]) == 1`; a pair naming two
  different things returns 2.
- Supplied near-duplicate terms → the prompt contains the "exactly ONE" demand
  **and** still contains "Do not rewrite them"; a distinct reply is appended
  after the supplied terms, in order.
- Supplied near-duplicate terms + a paraphrase reply → the paraphrase is
  rejected, exactly **two** `generate_json` calls happen (one retry, no more),
  and if the retry also paraphrases the result is the supplied terms unchanged.
- Supplied terms that already take distinct routes → one call only, prompt does
  **not** carry the "exactly ONE" demand, behaviour matches today.
- No-supplied path, planner returns three paraphrases → exactly one follow-up
  call, the distinct query is appended, `core_entity` still comes from the first
  call.
- No-supplied path, planner returns four paraphrases (at the cap) → the last
  near-duplicate is dropped to make room and the result is still
  `<= MAX_PLANNED_QUERIES`.
- No-supplied path, planner returns distinct queries → no follow-up call.
- Supplied terms are never reordered or replaced in any of the above (#172).

### Existing tests that must stay green as written

Do not edit them; if one goes red, the new rules are wrong, not the test.

- `test_idea_search_terms_reach_the_draft` — its fakes use `"term one"`,
  `"term two"`, `"other"`, `"s1".."s3"`, `"q1".."q6"`. Under the token rules
  above, `"term one"`/`"term two"` normalise to `{"term"}` and count as
  near-duplicates, so the required-extra path fires: the fake's
  `"totally different one"` is still accepted and the expected result is
  unchanged. The case that returns only `"TERM ONE"` will now cost a second
  `generate_json` call and still end at length 2 — that is correct, and it is
  why the retry must be capped at one.
- `test_named_papers_in_abstracts_are_looked_up` — `Safewards trial`,
  `RAISE-ETP study` and the DOI must all still be issued; its small returns sit
  under the `NAMED_MATCH_MIN_MATCHES` floor so nothing is dropped.
- `test_named_references_reads_names_not_noise`,
  `test_named_sources_merge_without_renumbering`,
  `test_methods_names_the_named_source_pass`,
  `test_claude_md_still_describes_this_code`.

## Change 5 — `CLAUDE.md`

The docs CI gate fails a PR touching `articlegen/**` that leaves this file
alone, and `test_claude_md_still_describes_this_code` checks that every file,
test and constant named here still exists — so name the new things exactly.

- Add two rows to the invariants table:
  - `| A generic "name" is never looked up | test_generic_named_lookups_are_skipped |`
  - `| Paraphrased terms buy one distinct extra query | test_paraphrase_terms_buy_a_distinct_query |`
- In **Sources and grounding**, extend the named-source bullet (the one starting
  "The search is no longer one-shot") with two sentences: the extraction skips
  generic tokens — number words, structured-abstract headers, two-letter
  acronyms and hyphenated descriptors — and a name that matches more than
  `NAMED_MATCH_RATE_MAX` of what came back, over a floor of
  `NAMED_MATCH_MIN_MATCHES`, is dropped after the lookup because it is
  describing the literature rather than naming a paper. Keep it short; the tests
  are the specification.
- Extend the `search_terms` bullet (#172) with the new rule: when the supplied
  or planned terms all search one route (`query_routes` <= 1 under
  `NEAR_DUPLICATE_OVERLAP`), one additional **distinct** query is required and a
  paraphrase is rejected once and re-asked; the supplied terms are still copied
  in code and never replaced.
- Optional but in keeping with the repo's convention: a short entry in
  `docs/decisions.md` with the measured numbers from #190 (16 returned / 15
  matched / 8 new, all tangential for `Twelve study`) and the thresholds chosen.
  If you add it, every backticked file, test and constant in it is checked by
  the same guard test.

## Verification

```
python tests/test_offline.py              # exit 0
python tests/test_journal_conformance.py  # exit 0
```

Judge both by exit status, not by scanning output text.

Then a real behavioural check, no network needed:

```
python -c "
from articlegen.sources import named_references as n, filter_named_matches, Paper
for t in ['RESULTS Twelve studies were included.','We included Twelve studies of seclusion.',
          'We searched for English-language trials.','The ED intervention reduced restraint use.',
          'the Safewards cluster randomised controlled trial','(doi: 10.1001/jama.2015.1234)']:
    print(repr(t), '->', n(t))
"
```

First four must print `[]`; last two must print the name and the DOI.

If a key is available, one live run is the real proof — `articlegen draft
"reducing seclusion in acute adult mental health units"` and read the log for
the named-source line and the planned queries. That spends credit, so ask
before running it.

## Out of scope

No clinical synonym tables. Do not undo #172 (supplied terms stay first and
unreplaced). No chasing nested citations inside full text, no fifth search API,
no change to the default model (#85), no `--long` on the web UI, and do not
regenerate the public demo Reviews in `drafts/`.

## Branch, commits and PR

Branch off `main`, e.g. `fix/190-generic-named-lookups`. Suggested commits:

1. `Remove the duplicated named-source block in sources.py`
2. `Skip generic named-source lookups and drop names that match everything (#190)`
3. `Require one distinct extra query when the terms paraphrase (#190)`
4. `Document the generic-name skip and the distinct-query rule (#190)`

PR body: say what changed, quote the before/after extraction output, and use
`Closes #190`. **Never write "does not close #NNN"** anywhere in a commit or PR
body — GitHub's parser ignores the negation and closes the issue. Refs #187,
#165, #172.

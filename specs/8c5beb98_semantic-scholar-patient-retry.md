# Plan — issue #148: keyless Semantic Scholar 429s for a whole session

## The problem, in one paragraph

Measured over four runs spanning more than an hour: the **first** Semantic
Scholar query of every run failed `HTTP 429 after 3 attempts`, and
`gather_evidence`'s `exhausted` set then — correctly, by design — skipped the
source for the rest of that run. Net effect: Semantic Scholar contributed
nothing all session, and every draft was written on the databases that were
left.

Two things are **not** the fix and must not be touched:

- The `exhausted` set (`articlegen/sources.py`, `gather_evidence`). It exists
  because re-attempting a dead source on every query cost ~10s each time.
- `_MAX_BACKOFF = 30.0` and `_retry_delay`'s rule that a server-requested
  cool-off *longer* than the cap means give up now. A user is watching a
  progress bar.

The real fix is the free `SEMANTIC_SCHOLAR_API_KEY`, which is an ops job and
stays open. This change does two narrow things: says that plainly in the docs,
and buys back the case where the limit clears within half a minute.

## Scope

Files to touch, and nothing else:

- `articlegen/sources.py` — the patient round
- `articlegen/pipeline.py` — one call site opts out (one line)
- `tests/test_offline.py` — new test + registration
- `README.md`, `CLAUDE.md` — the docs half
- `docs/decisions.md` — the story (repo convention)
- `deploy/README.md` — one line, so it stops contradicting README.md

Do **not** touch `drafts/`, `adws/`, `.github/`, `web.py`, `index.html`.

---

## Part 1 — Code

### 1a. `articlegen/sources.py` — mark which failures are worth waiting on

`_get_with_retry` (around line 249) raises `SearchFailure` from three places.
Two of them are *not* worth a patient wait, and telling them apart is what keeps
the `_MAX_BACKOFF` invariant intact. Set an attribute on the exception at each
raise site — this does **not** change the function's signature, which matters
because ~10 existing tests monkeypatch `_get_with_retry` with a
`lambda url, params, headers: ...`:

- non-retryable status (`resp.status_code not in (429, 500, 502, 503)`) →
  `retry_later = False`
- `"cool-off longer than {_MAX_BACKOFF}s"` → `retry_later = False`
  (the server told us it will not answer inside our budget; waiting 30s anyway
  would be exactly the behaviour `_MAX_BACKOFF` exists to prevent)
- the final `"{last} after {tries} attempts"` → `retry_later = True`

Shape:

```python
exc = SearchFailure(last)
exc.retry_later = False
raise exc
```

Keep the messages byte-identical — other tests assert on their text.

### 1b. `articlegen/sources.py` — the patient round itself

Add next to `_MAX_BACKOFF` (so the two constants are read together):

```python
# One extra, patient attempt for the FIRST Semantic Scholar call of a run.
# Measured over four runs spanning more than an hour (#148): every first
# keyless Semantic Scholar query returned HTTP 429 after its three tries, the
# `exhausted` set then skipped the source for the rest of that run, and every
# draft that session was written without it.
#
# The wait sits AT _MAX_BACKOFF, never above it: 30s is the most this codebase
# is willing to make a caller with a progress bar wait. Semantic Scholar only,
# once per run, and once it has failed the source is exhausted exactly as
# before. This does not replace SEMANTIC_SCHOLAR_API_KEY — it only buys back
# the case where the limit clears inside half a minute.
_S2_PATIENT_WAIT = _MAX_BACKOFF

# Spent per run. Reset by gather_evidence, which is the run boundary — the same
# pattern as _recency_query_refused.
_s2_patient_round_spent = False
```

Rewrite `search_semantic_scholar` (line ~275) to wrap its one `_get_with_retry`
call. The parsing loop below is unchanged:

```python
def search_semantic_scholar(query: str, limit: int = 15) -> list[Paper]:
    global _s2_patient_round_spent
    headers = {}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    params = {"query": query, "limit": limit, "fields": _SS_FIELDS}
    try:
        resp = _get_with_retry(SEMANTIC_SCHOLAR_URL, params=params, headers=headers)
    except SearchFailure as exc:
        # `retry_later` defaults True: an unlabelled failure costs one wait,
        # which is cheaper than missing the case this exists for.
        if _s2_patient_round_spent or not getattr(exc, "retry_later", True):
            raise
        _s2_patient_round_spent = True   # set BEFORE the wait: spent is spent,
        time.sleep(_S2_PATIENT_WAIT)     # whether or not this round succeeds
        resp = _get_with_retry(SEMANTIC_SCHOLAR_URL, params=params, headers=headers)
    ...unchanged parsing...
```

A second failure propagates as before → `_search_once` records the error →
`gather_evidence` adds `semantic_scholar` to `exhausted`. **Nothing downstream
changes.**

Add a docstring to `search_semantic_scholar` saying it is the one source with a
patient round and why.

### 1c. `articlegen/sources.py` — reset the flag at the run boundary

`gather_evidence` already does `global _recency_query_refused` /
`_recency_query_refused = False` (lines ~1125-1126). Add the new flag to the
same `global` line and reset it there, plus a new keyword argument:

```python
def gather_evidence(..., use_cache: bool = True, patient: bool = True) -> list[Paper]:
    global _recency_query_refused, _s2_patient_round_spent
    _recency_query_refused = False
    # patient=False starts the run with the round already spent. The pre-flight
    # probe uses it: it exists to fail FAST before the caller is billed, so it
    # must never add 30s to a run that is about to work.
    _s2_patient_round_spent = not patient
```

Document `patient` in the docstring in one sentence.

### 1d. `articlegen/pipeline.py` — the probe opts out

In `_preflight_sources` (line ~95), change the call to:

```python
    papers = gather_evidence([topic], max_papers=1, per_query=1, topic=topic,
                             log=_silent, outcomes=outcomes, patient=False)
```

Leave every other `gather_evidence` caller alone (`generate_draft`, `/api/diag`,
the live smoke test). Without this line a keyless run pays the 30s wait twice —
once in the probe, once in the real gather.

### Why here and not in `_get_with_retry`

Two reasons, both load-bearing:

1. Existing tests replace `sources.search_semantic_scholar` wholesale (lines
   1079, 1172, 1540, 1893, 4481). Putting the logic inside that function means
   those fakes bypass it — no surprise 30-second sleeps in the offline suite.
2. Existing tests replace `sources._get_with_retry` with three-positional-arg
   lambdas. Adding a parameter there would break them.

---

## Part 2 — Test

Add `test_first_semantic_scholar_refusal_buys_one_patient_round` to
`tests/test_offline.py` (put it next to `test_search_cache` /
`test_polite_pool_identification`, which is where the retry behaviour already
lives), and register it in the list inside `main()` near `test_search_cache`.

Follow the file's conventions: `check("...", <bool>)`, a docstring that says why
the behaviour matters, and every global restored in a `finally`.

What it must pin:

1. **The wait stays inside the cap** —
   `sources._S2_PATIENT_WAIT <= sources._MAX_BACKOFF`.
2. **First refusal buys a second round.** Fake `sources._get_with_retry` with a
   counter keyed on the URL that raises
   `sources.SearchFailure("HTTP 429 after 3 attempts")`; fake
   `sources.time.sleep` to record waits (never sleep for real); replace
   `search_europe_pmc` and `search_arxiv` with `lambda q, limit=15: []`; leave
   `search_openalex` real so it goes through the same faked transport. Run
   `sources.gather_evidence(["q one", "q two"], outcomes=outs)` and assert:
   - the Semantic Scholar URL was called **twice**
   - exactly one wait was recorded, equal to `sources._S2_PATIENT_WAIT`
3. **Scoped to Semantic Scholar.** In the same run, the OpenAlex URL was called
   once — no patient round for any other source.
4. **The second refusal still exhausts the source.** In that same run the
   `"q two"` outcome for `semantic_scholar` carries
   `"skipped (already failed this run)"`, and the Semantic Scholar call count is
   still 2 — the patient round is once per run, not once per query.
5. **A non-retryable failure gets no wait.** Fresh run, fake raises a
   `SearchFailure` carrying `retry_later = False` (build it the way
   `_get_with_retry` does): one call, no sleep. This is the `_MAX_BACKOFF`
   invariant staying intact.
6. **The pre-flight probe does not buy the round.**
   `gather_evidence([...], patient=False)` with the always-429 fake: one
   Semantic Scholar call, no sleep.

Setup/teardown notes for whoever writes it:

- `sources.clear_search_cache()` at the top **and** in `finally` — a failure is
  cached for 120s and would otherwise answer for the second sub-case.
- Use a **different query string** per sub-case for the same reason.
- Restore `sources._get_with_retry`, `sources.time.sleep`, the three replaced
  search functions, and set `sources._s2_patient_round_spent = False` in
  `finally`.

---

## Part 3 — Docs

Plain language, no hedging. State the measurement, then the fix.

### `README.md`

1. Lines ~108-109 ("Optional extras: a `SEMANTIC_SCHOLAR_API_KEY` secret and an
   `OPENALEX_MAILTO` environment variable raise the scholarly APIs' rate
   limits."). Replace with something that says the key is not really optional —
   e.g.:

   > Set a free `SEMANTIC_SCHOLAR_API_KEY`. Without it, Semantic Scholar's
   > shared keyless limit refuses effectively every call: measured over four
   > runs spanning an hour, the first query of every run came back HTTP 429 and
   > the source was then skipped for the rest of that run, so those drafts were
   > written on the other databases alone. `OPENALEX_MAILTO` is genuinely
   > optional — it puts OpenAlex requests in its "polite pool".

2. Lines ~179-184 (the Install block, "The scholarly APIs need no key, but you
   can raise their rate limits"). Reword so the S2 key reads as the recommended
   step and the mailto as the optional one. Keep the code block, drop the
   `# optional` comment from the S2 line, and link the free key page:
   `https://www.semanticscholar.org/product/api`. Say in one line that a run
   without it still works — it just runs on fewer databases, and the Methods
   section will say so.

### `CLAUDE.md`

1. **Invariant table** (the "Pinned by a test" table). Add one row near the
   other source rows:

   `| The first Semantic Scholar refusal of a run buys one patient retry | test_first_semantic_scholar_refusal_buys_one_patient_round |`

2. **Sources and grounding section**, immediately *before* the existing
   "**A source that refuses once is skipped for the rest of the run**" bullet
   (lines ~354-361), add a new bullet. Leave that existing bullet untouched —
   it is still true. Content:

   - Keyless Semantic Scholar is effectively dead under the shared rate limit —
     measured, four runs over more than an hour (#148): every *first* Semantic
     Scholar query returned HTTP 429 after its three tries, `exhausted` then
     skipped it for the rest of the run, and the drafts that session were
     written without it.
   - **Setting the free `SEMANTIC_SCHOLAR_API_KEY` is the fix worth doing on
     any machine that runs drafts.** No code change recovers this.
   - The one code-side concession: `_S2_PATIENT_WAIT`, a single extra attempt
     after one wait at the `_MAX_BACKOFF` ceiling, on the first Semantic Scholar
     call of a run only. Semantic Scholar only, once per run, and the source is
     exhausted after it exactly as before. A failure marked `retry_later =
     False` (non-retryable status, or a cool-off past the cap) is **not** waited
     on — that is `_MAX_BACKOFF` doing its job.
   - `_preflight_sources` passes `patient=False`: it exists to fail fast before
     the caller is billed, so the probe must not add 30s to a run that is about
     to work.

3. **Setup / testing section**, line ~541: `Optional: `SEMANTIC_SCHOLAR_API_KEY`,
   `OPENALEX_MAILTO`.` → make the S2 key recommended (free; without it Semantic
   Scholar 429s on effectively every call, #148) and leave `OPENALEX_MAILTO`
   optional.

### `docs/decisions.md`

Add one entry at the end of the **"Grounding and provenance"** section (before
`## Web app and deployment`), matching the existing heading style:

`### `#148` — keyless Semantic Scholar 429'd for a whole session`

Say what was measured (four runs, more than an hour, first query of each run
429 after 3 attempts, exhausted-set then skipped it), what was rejected
(weakening the `exhausted` set; raising `_MAX_BACKOFF`; waiting out a cool-off
the server said was longer than the cap), what was done (one patient round,
Semantic Scholar only, first call of a run only, at the existing ceiling), and
what is still open (getting and setting the key — the ops half of the issue).

### `deploy/README.md`

Line ~64: the env-var table calls `SEMANTIC_SCHOLAR_API_KEY` "Optional; raises
Semantic Scholar's rate limit." Change the wording to recommended — without it
the source refuses nearly every call (#148). Still a *secret*. One line.

---

## Verify

Both suites must pass, judged on exit status:

```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Specific things to watch:

- The offline suite must not take 30 seconds longer than it used to. If it
  does, a real `time.sleep` is being reached — the new test is not patching
  `sources.time.sleep`, or a fake is not replacing the right thing.
- `test_search_cache`, `test_source_failures_are_distinguishable`,
  `test_methods_names_only_sources_that_answered` and
  `test_dead_sources_fail_before_the_caller_is_billed` all make Semantic Scholar
  fail. They replace `sources.search_semantic_scholar` itself, so they should be
  untouched by this change — if any of them changes behaviour, the patient
  round has been put in the wrong place.
- `test_claude_md_still_describes_this_code` checks that every backticked
  file, `test_*` name and SHOUTY constant in `CLAUDE.md` + `docs/decisions.md`
  actually exists. The new test name and `_S2_PATIENT_WAIT` must match the code
  exactly.
- `test_pipeline_is_shared` and
  `test_dead_sources_fail_before_the_caller_is_billed` cover the
  `_preflight_sources` edit.

## Commit message

One sentence, plain language, ending with the reference. The ops half of the
issue stays open, so it must end:

```
Refs #148, stays open
```

Never write the phrase "does not close" anywhere — GitHub's parser reads the
`close #NNN` inside it and closes the issue on merge.

## Out of scope

- Obtaining or setting the actual API key (the ops half — that is what stays
  open).
- Any change to `web.py`, `/api/diag`, `index.html`, or the rate limiter.
- Any change to the `exhausted` set, `_MAX_BACKOFF`, `_retry_delay`'s cap rule,
  or the cache TTLs.

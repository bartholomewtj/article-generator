# Plan — stop the run when source labelling returns nothing (#168)

## The problem in one paragraph

`writer.curate_sources` catches every exception and returns
`{"relevance": {}, "most_relevant_index": None, "counts": {}}`.
`pipeline.generate_draft` logs a WARNING and carries on. From that point the
relevance gate is off (nothing is labelled `tangential`, so nothing is
withheld from the writer), `full_text_order` returns `[]` so no full text is
fetched, and the model writes a briefing anyway. The reader gets an
abstracts-only draft with no topic-drift protection and nothing on the page
says so. Make it a hard stop instead.

## Done means

- Papers exist but `curation["relevance"]` is empty → `generate_draft` raises,
  in the same exception family as `NoPapersFound`, so the existing CLI and web
  handlers catch it with no change to either file.
- The raise happens **before** the named-source pass and **before**
  `write_briefing` / `write_article` — no further paid call.
- The message tells the caller labelling failed, names why if the reason is
  known, and says the write was not charged (the curation call was).
- The existing WARNING log line stays exactly where it is.
- `python tests/test_offline.py` and `python tests/test_journal_conformance.py`
  both exit 0.

## Out of scope

Retrying curation in a loop. Falling back to labelling every source `direct`.
Putting `--long` on the web UI. Regenerating anything in `drafts/`.
Changing `cli.py` or `web.py` (the subclass below is what makes that
unnecessary — do not edit them).

---

## Change 1 — `articlegen/writer.py`: say *why* curation came back empty

`curate_sources` (line ~865) currently returns the same empty dict for two
different events: the provider call blew up, or the call worked and the model
returned no usable assessments. The pipeline can only report a useful message
if it knows which.

Keep the function's contract (it still returns a dict, it still never raises)
— the named-source pass calls it a second time and must keep degrading soft
there. Add one optional key.

1. Leave the `if not papers:` early return as it is (no `error` key — nothing
   failed).
2. In the `except Exception` branch (around line 892), capture the reason:

   ```python
   except Exception as exc:
       return {"relevance": {}, "most_relevant_index": None, "counts": {},
               "error": f"{type(exc).__name__}: {exc}"[:200]}
   ```

   Truncate to 200 characters. Do not put the prompt or any request payload in
   that string: it is surfaced to a web visitor through the raised exception,
   and provider errors sometimes echo request context back. No API key is in
   an exception's text today, and the cap keeps a future verbose provider
   error from becoming a wall of text on someone's phone.
3. At the end of the function, when the call succeeded but nothing usable came
   back, mark that too:

   ```python
   if not relevance:
       return {"relevance": {}, "most_relevant_index": None, "counts": {},
               "error": "the model returned no usable relevance labels"}
   ```

   Put this **before** the `most_relevant_index` fallback block, so the empty
   case returns early and `mri` never has to default to `1` on a pool nobody
   labelled.
4. Update the docstring. It currently says "Degrades to empty on failure."
   Say instead that an empty result carries an `error` key naming the reason,
   and that the caller is expected to treat empty as fatal.

Nothing reads `curation` by iterating its keys — `render.py`, `verify.py` and
`writer._writer_context` all use `.get()` — so the extra key is inert on the
happy path. It is inert in `_named_source_pass` too, which reads only
`relevance` and `counts` from its second curation result.

## Change 2 — `articlegen/pipeline.py`: a new exception and the raise

### 2a. The exception (next to `NoPapersFound`, lines ~156-169)

```python
class CurationFailed(NoPapersFound):
    """Source labelling came back empty, so the run stops before the write.

    A subclass of `NoPapersFound` on purpose: every caller already has an
    `except NoPapersFound` branch that prints the message and stops, and this
    failure wants exactly that handling. A sibling class would mean two more
    edits in two more files and a third way for a caller to forget.
    """
```

No new attributes. `sources_failed` stays `False` (the default), which is
correct — the scholarly APIs answered; the LLM labelling step is what failed.
`web.py` therefore returns 422 with this message as the detail, and
`index.html` prints the detail verbatim (its 422 branch is
`detail || <fallback>`), so the visitor sees the real sentence. Do not widen
the 503 condition.

### 2b. The raise (immediately after the existing WARNING, lines 484-488)

Keep the comment block and the `log(...)` call. Inside the same
`if papers and not curation.get("relevance"):` body, straight after the log
call, add:

```python
        reason = curation.get("error") or "no reason was reported"
        raise CurationFailed(
            f"Source relevance labelling failed ({reason}), so the run stopped "
            f"before writing. {len(papers)} papers were found, but none could be "
            "labelled, and without labels the relevance gate cannot keep "
            "off-topic evidence out of the briefing and no full text is "
            "fetched. Nothing was charged for the writing step. Try again, or "
            "draft on a different model."
        )
```

Amend the comment above it so it describes what the code now does — it ends
"Say so." and explains a warning. It should end by saying the run stops here,
and why stopping beats writing: an unlabelled pool means the gate that
prevents topic drift is off, and the failure is invisible on the finished page
(#168). Keep the existing reasoning about the two indistinguishable cases; it
is still why the check exists.

The raise sits before `_named_source_pass`, which spends a second `gather` and
a second `curate_sources` call — so the failure costs the caller
`plan_queries` plus the one curation call and nothing more.

Leave `_named_source_pass`'s own "curation of named sources returned no usable
labels" warning (line ~413) alone. That one is genuinely soft: the base pool
is labelled, only the newly merged records are not, and they are simply not
fetched in full text. Do not raise there.

---

## Change 3 — `tests/test_offline.py`

### 3a. Fix the one existing fixture that now contradicts the change

`test_pipeline_fetches_full_text` (starts line 5034) has a second half at
roughly lines 5079-5089 that sets `pipeline.curate_sources` to return an empty
result and then asserts `generate_draft` produced a draft with
`full_text_sources == []`. That call now raises, so the test would fail.

Replace that sub-block. The behaviour it protected — unlabelled sources are
never fetched — still matters and is cheaper to assert one level down, with no
pipeline run at all:

```python
        # Unlabelled sources are never fetched. Reaching this through
        # generate_draft is no longer possible — an empty curation is a hard
        # stop (#168) — but the ordering function is where the rule lives, so
        # it is asserted here directly.
        from articlegen.sources import full_text_order
        check("no relevance labels means nothing is eligible for full text",
              full_text_order(papers, {}) == [])
```

Delete the `for p in papers: p.full_text = ""` reset, the
`fetched_pmcids.clear()`, the empty `pipeline.curate_sources` reassignment and
the second `generate_draft` call that went with them. Leave the first half of
the test untouched.

Every other fake `curate_sources` in the suite returns a non-empty `relevance`
(lines ~5234, ~5461, ~5611/5662, ~5727, ~5739, ~6005/6026), so line 5084 is
the only fixture needing a change. Confirm afterwards with
`grep -n '"relevance": {}' tests/test_offline.py` — it should only hit the new
test below.

### 3b. New guard test

Add `test_unlabelled_sources_stop_the_run` after
`test_pipeline_fetches_full_text` and before
`test_full_text_comes_from_the_papers_cli_when_it_is_there`, and register it
in the tuple inside `main()` (line ~6377) directly after
`test_pipeline_fetches_full_text`.

House pattern: save the pipeline attributes you monkeypatch into a tuple,
restore them in a `finally`, report with `check(name, cond)` — never `assert`.

Docstring: state the failure it guards. Curation swallows every exception and
returns empty labels; the pipeline used to log a warning and write anyway,
which turned a failed relevance gate into a normal-looking briefing with no
topic-drift protection and no full text (#168).

The checks:

1. **It raises, and in the right family.** Fake `plan_queries`,
   `gather_evidence` (return 3-4 `Paper`s with abstracts and append a
   successful outcome dict to `kw["outcomes"]`, exactly as the neighbouring
   tests do), and `curate_sources` returning
   `{"relevance": {}, "most_relevant_index": None, "counts": {},
   "error": "RuntimeError: provider exploded"}`. Call
   `pipeline.generate_draft("topic", log=collect)` in
   `try/except pipeline.CurationFailed`.
   - `check("empty labelling stops the run", raised is not None)`
   - `check("and is caught by every existing NoPapersFound handler",
     isinstance(raised, pipeline.NoPapersFound))`
   - `check("and is not blamed on the scholarly APIs",
     raised.sources_failed is False)`
   - the message names the reason: `"provider exploded" in str(raised)`
   - the message says the write was not charged:
     `"charged" in str(raised).lower()`

2. **The writer is never called.** Set
   `pipeline.write_briefing = pipeline.write_article = _boom`, where `_boom`
   raises `AssertionError("the writer must not run")`, and check the run still
   ended in `CurationFailed` rather than that AssertionError. Do the same for
   `pipeline.enforce_style`.

3. **The named-source pass is never reached.** Point
   `pipeline._named_source_pass` at a counter (or at `_boom`) and check it was
   not called — that is the second paid call the early raise saves.

4. **The WARNING log line survives.** Pass a `log` that appends to a list and
   check `any("no usable labels" in line for line in logged)`. The issue asks
   for this explicitly: the log is no longer the only signal, but it is still
   a signal.

5. **`curate_sources` still degrades soft and now says why.** With
   `writer.generate_json` monkeypatched to raise `RuntimeError("nope")`
   (restore it in the `finally`):
   - the call returns a dict rather than raising
   - `result["relevance"] == {}`
   - `"nope" in result["error"]`

   And with `generate_json` returning `{"assessments": []}`: `result["error"]`
   is a non-empty string and `result["relevance"] == {}`. `curate_sources`
   calls `generate_json` as a module-level name in `writer`, so patch
   `writer.generate_json`, not `llm.generate_json`.

6. **The soft path for the named-source pass is preserved.** A cheap
   source-level check rather than a second full run:
   `check("the named-source pass still degrades soft",
   "CurationFailed" not in inspect.getsource(pipeline._named_source_pass))`.

The empty-papers case needs no test change: the guard is
`if papers and not curation.get("relevance")`, and a genuinely empty pool
still raises the existing `NoPapersFound` earlier.

---

## Change 4 — docs

### `CLAUDE.md`

1. Add a row to the invariants table (the "Pinned by a test" one), beside the
   other pipeline rows:

   | Unlabelled sources stop the run before the writer | `test_unlabelled_sources_stop_the_run` |

2. In **Architecture**, the `pipeline.generate_draft()` stage list: after
   `curate_sources`, note that an empty labelling result stops the run. One
   clause, not a paragraph.

3. In **Sources and grounding**, add a bullet next to the relevance-gate
   bullet:

   > **An empty relevance result is fatal, not a warning.** `curate_sources`
   > returns empty on any failure, so a failed labelling call is
   > indistinguishable from a pool where everything was labelled tangential:
   > "0 direct / 0 related / 0 tangential", logged and passed over. The gate
   > is then off, no full text is fetched, and the model writes anyway — the
   > quietest way this pipeline can go wrong (#168). `generate_draft` now
   > raises `CurationFailed`, a subclass of `NoPapersFound`, so every existing
   > caller stops on it unchanged, and the empty result carries an `error` key
   > naming the reason. Do not retry curation in a loop and do not fall back
   > to labelling everything `direct`.

Watch `test_claude_md_still_describes_this_code`: every backticked `test_*`
name in CLAUDE.md must exist in a suite, and every backticked ALL_CAPS name
must exist in the code. `CurationFailed` is mixed case so it is not swept, but
do not misspell the test name.

### `docs/decisions.md`

Repo convention: the invariant goes in `CLAUDE.md`, the story goes here. Add a
short entry under `## Grounding and provenance` — what the old behaviour was,
why a warning was not enough (nothing on the finished page said the gate was
off, so an abstracts-only draft with no drift protection looked exactly like a
good one), and why the fix is a subclass rather than a new exception type
(zero caller edits, one fewer way to forget). Record the deliberate
non-choices: no retry loop, no `direct` fallback.

---

## Verify

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. Judge on exit status, not by scanning output — this suite
prints `FAIL` inside check names and the word `error` inside test prose.

Manual sanity check, no key and no network needed:

```
python -c "
from articlegen import pipeline
from articlegen.sources import Paper
p=[Paper(title='t',abstract='a')]
pipeline.plan_queries=lambda t,**k:(['q'],'c')
def g(q,**k):
    k.get('outcomes',[]).append({'source':'europe_pmc','query':'q','count':1,'error':'','cached':False}); return p
pipeline.gather_evidence=g
pipeline.curate_sources=lambda t,pp,**k:{'relevance':{},'most_relevant_index':None,'counts':{},'error':'boom'}
try:
    pipeline.generate_draft('x', log=print)
except pipeline.CurationFailed as e:
    print('RAISED:', e)
"
```

Expect the WARNING line, then `RAISED:` with `boom` in it.

## Git

Branch off `main`, one commit, push, `gh pr create`. The PR body must mention
that `CLAUDE.md` was updated — `.github/workflows/docs-current.yml` fails a PR
that touches `articlegen/**` without touching it. Reference the issue as
"Closes #168". Never write "does not close #NNN" anywhere in a PR body or
commit message.

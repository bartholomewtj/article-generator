# Plan — issue #146: a second style-revision pass, gated on progress

## What we're changing and why

`pipeline.enforce_style` revises the prose exactly once. Two of three recent
runs finished with **one** residual style error after a revision that had
already worked (3 → 1 and 2 → 1). That single leftover is enough for
`render.py` to print the Limitations sentence branding the article "a working
draft rather than a finished review" — a real quality cost for what is probably
one more targeted edit.

Change: allow a **second** `revise_prose` pass, but only when the previous pass
was accepted (i.e. it strictly reduced the error count). Hard cap of two passes
total. A stuck error therefore never loops — no progress, no second pass.

Everything else about the pass stays as it is: the same acceptance rule (keep
the revision only if it reduces errors **and** leaves citations and sections
intact), the same `SUBSTANCE_RULES` source-carrying split, the same
`rewrite_whole` rule for `too-few-sections`.

## Files to touch

| File | Change |
|---|---|
| `articlegen/pipeline.py` | `MAX_STYLE_PASSES = 2`; turn the one-shot body of `enforce_style` into a progress-gated loop |
| `tests/test_offline.py` | new `test_a_second_style_pass_runs_only_after_progress`, registered in `main()` |
| `CLAUDE.md` | the two lines that say the revision happens "once" |
| `docs/decisions.md` | short entry under `## Prose style` recording why two and not three |

Do **not** touch `drafts/`, `adws/`, `.github/`, `articlegen/style.py`,
`articlegen/writer.py` or `articlegen/render.py`.

## Step 1 — `articlegen/pipeline.py`

### 1a. Add the cap constant

Put it at module level, near the other pipeline constants (above
`enforce_style` is fine):

```python
# How many times `enforce_style` may send the prose back to the model. The
# second pass is gated on the first having *worked*: a pass only repeats after
# a revision that was accepted, and acceptance means strictly fewer errors. So
# an error the model cannot fix costs one call, not two, and nothing loops.
# Two, not three: the runs that motivated this ended at 3 -> 1 and 2 -> 1, a
# residual of one, which is what a second pass is sized for (#146).
MAX_STYLE_PASSES = 2
```

The name must stay `MAX_STYLE_PASSES` — CLAUDE.md will cite it and
`test_claude_md_still_describes_this_code` checks that every backticked
constant in the docs exists in a module.

### 1b. Rewrite the body of `enforce_style` as a loop

Current body (lines ~231–282) is: check → early return if clean → compute
`rewrite_whole` / `needs_sources` → one `revise_prose` → accept-or-discard.
Wrap the middle in a `for` loop over the passes and keep everything inside it
derived from the **current** report each time round.

Replacement body, from the `direct_sources` line to the end of the function:

```python
    # The section floor scales with how much directly on-topic evidence there is;
    # demanding five sections from three usable abstracts invites padding.
    direct_sources = ((curation or {}).get("counts") or {}).get("direct")
    report = check_style(article, direct_sources=direct_sources)
    problems = style_errors(report)
    if not problems:
        log("Prose style: clean.")
        log(format_style(report))
        return article, report

    for attempt in range(1, MAX_STYLE_PASSES + 1):
        log(
            f"Prose style: {len(problems)} issue(s) against journal conventions; "
            f"revising (pass {attempt} of {MAX_STYLE_PASSES})..."
        )
        # Both of these are recomputed from the *current* report: a second pass
        # is fixing whatever the first one left behind, which need not be the
        # kind of failure the first one was fixing.
        #
        # The revision replaces named blocks, which is far cheaper than
        # regenerating the article — but a block can only be replaced if it
        # exists. `too-few-sections` is the one failure whose fix is a section
        # that is not there yet, so it is also the one that still pays for a
        # whole rewrite.
        rewrite_whole = any(i["rule"] == "too-few-sections" for i in problems)

        # The sources go along only when the draft failed for thinness or
        # repetition. `revision_brief` already splits the two cases: a substance
        # failure is told to pull specific findings out of the sources, and a
        # register failure is told to reword and add nothing. Sending 20
        # abstracts and 60,000 characters of full text to fix a contraction is
        # ~30,000 input tokens the model is explicitly forbidden to use — and
        # material it cannot use is material it can still be distracted by.
        needs_sources = any(i["rule"] in SUBSTANCE_RULES for i in problems)
        if papers and not needs_sources:
            log("  (register-only fixes; revising against the draft alone)")

        try:
            revised = revise_prose(
                article, revision_brief(report), model=model, api_key=api_key,
                papers=papers if needs_sources else None,
                curation=curation, rewrite_whole=rewrite_whole,
            )
        except Exception as exc:
            log(f"  revision failed ({exc}); keeping the draft as it stands.")
            break

        # Intactness is measured against the draft in hand, not the draft this
        # function was handed: after an accepted pass, that is the revision.
        intact = (
            len(revised.get("references") or []) >= len(article.get("references") or [])
            and len(revised.get("sections") or []) == len(article.get("sections") or [])
        )
        revised_report = check_style(revised, direct_sources=direct_sources)
        revised_problems = style_errors(revised_report)
        if not intact or len(revised_problems) >= len(problems):
            reason = (
                "revision dropped citations or sections" if not intact
                else "revision did not improve"
            )
            log(f"  {reason}; keeping the draft as it stands.")
            break

        log(f"  revised: {len(problems)} -> {len(revised_problems)} issue(s).")
        article, report, problems = revised, revised_report, revised_problems
        if not problems:
            log("  prose style now clean.")
            break

    log(format_style(report))
    return article, report
```

Notes on why this shape:

- **The progress gate is the loop itself.** The only way round the loop a
  second time is through the accept branch, and that branch requires
  `len(revised_problems) < len(problems)`. A refused or unhelpful revision
  `break`s. A raised exception `break`s.
- `article`/`report`/`problems` are rebound on acceptance, so pass 2 briefs the
  model on what is *left*, not on what was already fixed.
- `needs_sources` and `rewrite_whole` are inside the loop, so the
  `SUBSTANCE_RULES` split works identically on pass 2 — if the residual error is
  a substance rule, the sources travel with the second call too.
- Update the docstring: change "revise once" to say up to `MAX_STYLE_PASSES`
  passes, with the second only after an accepted first one.
- Keep the literal strings `i["rule"] == "too-few-sections"` and
  `rewrite_whole=rewrite_whole` in the source —
  `test_revision_replaces_blocks_rather_than_the_article` greps
  `inspect.getsource(pipeline.enforce_style)` for both.

### Out of scope

`render.py`'s "A revision was attempted and did not resolve this" sentence stays
as it is. It is still true after two passes and it is derived from the final
style report, not from a pass count. Do not touch it.

## Step 2 — tests (`tests/test_offline.py`)

Add one test next to `test_warnings_ride_along_on_a_revision` (after it is
fine), and register it in the `for fn in (...)` tuple inside `main()` — the
suite has no auto-discovery, so an unregistered test never runs.

```python
def test_a_second_style_pass_runs_only_after_progress() -> None:
    """A second revision pass is allowed, and only after the first one worked.

    Two of three measured runs ended with exactly one residual style error after
    a productive revision (3 -> 1 and 2 -> 1), which is enough to print the
    "working draft rather than a finished review" line in Limitations. So
    `enforce_style` may go round twice — but the second pass is gated on the
    first having been accepted, and acceptance means strictly fewer errors. An
    error the model cannot fix costs one call, never a loop (#146).
    """
    from articlegen import pipeline

    stats = {"sentences": 20, "mean_sentence_words": 22.0, "hedges_per_sentence": 0.3,
             "passive_ratio": 0.2}

    def report_with(n_errors, rule="contraction"):
        return {"issues": [{"rule": rule, "severity": "error", "where": "whole article",
                            "detail": "d", "excerpt": ""} for _ in range(n_errors)],
                "stats": stats}

    article = {"sections": [{"heading": "Introduction", "paragraphs": ["Prose."]}],
               "references": []}

    def run(error_counts):
        """Drive enforce_style with a scripted sequence of error counts.

        `error_counts[0]` is the initial check; each later entry is the check on
        the revision produced by that pass. Returns (passes_run, final_report).
        """
        seq = list(error_counts)
        calls = {"check": 0, "revise": 0, "sources": []}

        def fake_check(a, **kw):
            i = min(calls["check"], len(seq) - 1)
            calls["check"] += 1
            return report_with(seq[i])

        def fake_revise(a, brief, **kwargs):
            calls["revise"] += 1
            calls["sources"].append(kwargs.get("papers"))
            return dict(a)

        saved = pipeline.revise_prose, pipeline.check_style
        try:
            pipeline.revise_prose = fake_revise
            pipeline.check_style = fake_check
            out_article, out_report = pipeline.enforce_style(article)
        finally:
            pipeline.revise_prose, pipeline.check_style = saved
        return calls, out_report

    # 1. Improves, then clears: two passes run and the draft comes back clean.
    calls, report = run([3, 1, 0])
    check("a productive first pass buys a second", calls["revise"] == 2)
    check("and a cleared draft is what comes back",
          not [i for i in report["issues"] if i["severity"] == "error"])

    # 2. Improves, then stalls: the cap stops it at two.
    calls, report = run([3, 1, 1])
    check("progress then a stall stops at the two-pass cap", calls["revise"] == 2)
    check("and the better of the two drafts is kept",
          len([i for i in report["issues"] if i["severity"] == "error"]) == 1)

    # 3. No improvement on the first pass: no second pass at all.
    calls, _ = run([2, 2])
    check("a pass that did not improve buys no second pass", calls["revise"] == 1)

    # 4. A revision that gets worse is discarded and stops the loop.
    calls, report = run([2, 3])
    check("a worse revision buys no second pass", calls["revise"] == 1)
    check("and the original draft is kept",
          len([i for i in report["issues"] if i["severity"] == "error"]) == 2)

    # 5. The cap is two, stated once.
    check("the pass cap is a named constant set to two",
          pipeline.MAX_STYLE_PASSES == 2)

    # 6. The substance split still applies on the second pass: if what is left
    #    is a thinness failure, the sources travel with that call too.
    seq = [("recycled-phrasing", 3), ("recycled-phrasing", 1), ("recycled-phrasing", 0)]
    calls = {"check": 0, "revise": 0, "sources": []}

    def fake_check(a, **kw):
        rule, n = seq[min(calls["check"], len(seq) - 1)]
        calls["check"] += 1
        return report_with(n, rule=rule)

    def fake_revise(a, brief, **kwargs):
        calls["revise"] += 1
        calls["sources"].append(kwargs.get("papers"))
        return dict(a)

    papers = ["paper-stand-in"]
    saved = pipeline.revise_prose, pipeline.check_style
    try:
        pipeline.revise_prose = fake_revise
        pipeline.check_style = fake_check
        pipeline.enforce_style(article, papers=papers)
    finally:
        pipeline.revise_prose, pipeline.check_style = saved
    check("the sources travel on both passes of a substance failure",
          calls["sources"] == [papers, papers])
```

Two things the builder must get right in this test:

- `report_with(0)` must produce a report with **no** issues, so
  `style_errors()` returns empty and the loop's clean-break fires.
- `fake_check` clamps its index, so a script that runs out of entries keeps
  returning the last report rather than raising — that is what makes case 3
  ("no improvement") terminate naturally.

Adjust the assertion details to whatever the real `check_style`/`style_errors`
shapes require; the assertions above are the contract, not the exact code.

## Step 3 — `CLAUDE.md`

Two lines say "once". Both must change.

**Line ~67**, in the pipeline description:

> `write_article` → `enforce_style` (one `revise_prose` pass if `check_style`
> finds errors) → `check_statistics` → …

becomes

> `write_article` → `enforce_style` (up to `MAX_STYLE_PASSES` `revise_prose`
> passes if `check_style` finds errors) → `check_statistics` → …

**Line ~169**, opening the "Prose style (enforced, not prompted)" section:

> `enforce_style` sends `revision_brief()` back through `revise_prose` **once**,
> and keeps the revision only if it reduces the error count *and* leaves
> citations and sections intact.

becomes

> `enforce_style` sends `revision_brief()` back through `revise_prose`, and
> keeps each revision only if it reduces the error count *and* leaves citations
> and sections intact.

Then add a bullet to the same section's list (next to "The revision is a patch,
not a new article"):

> - **A second pass is allowed, and only after the first one worked.**
>   `MAX_STYLE_PASSES` is 2, and the loop repeats only through the accept
>   branch — which requires strictly fewer errors — so a stuck error costs one
>   call rather than looping. Two runs on record ended at 3 → 1 and 2 → 1
>   errors, and a single residual is enough to print the "working draft rather
>   than a finished review" line in Limitations (#146). Each pass recomputes
>   `rewrite_whole` and `needs_sources` from the *current* report, so the
>   `SUBSTANCE_RULES` split applies on pass 2 exactly as on pass 1. →
>   `test_a_second_style_pass_runs_only_after_progress`

Also add a row to the invariants table:

> | A second style pass runs only after the first reduced the errors | `test_a_second_style_pass_runs_only_after_progress` |

Check the `RIDE_ALONG_WARNINGS` bullet just below while you are there — it says
"the early return, `needs_sources` and the acceptance rule all stay keyed on
errors", which is still true and needs no edit.

## Step 4 — `docs/decisions.md`

Append a short entry to the end of the `## Prose style` section (before the
next `## ` heading):

```markdown
### `#146` — a second revision pass, gated on progress

Two of three runs finished with exactly one residual style error after a
revision that had already worked: 3 → 1 and 2 → 1. One error is enough for
Limitations to brand the article "a working draft rather than a finished
review", so the last error was costing the article's framing for want of one
more targeted edit.

The gate is progress, not a retry count. `enforce_style` loops only through the
accept branch, and acceptance already required strictly fewer errors, so an
error the model cannot fix still costs exactly one call. `MAX_STYLE_PASSES` is
2 rather than 3 because the residual being paid for is one error; nothing on
record suggests a third pass has anything to do.
```

## How to verify

Run both suites; judge by exit status, not by reading the output for the word
"error":

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Expect green from both. Nothing in the render path changed, so the conformance
suite should be untouched — if it moves, something was changed that should not
have been.

Watch specifically that these existing tests still pass:

- `test_revision_replaces_blocks_rather_than_the_article` — greps the source of
  `enforce_style` for `i["rule"] == "too-few-sections"` and
  `rewrite_whole=rewrite_whole`.
- `test_revision_carries_sources_only_when_they_can_be_used` — its fake
  `revise_prose` raises, which now hits the `break` in the exception branch.
- `test_warnings_ride_along_on_a_revision` — case 3 relies on the early return
  when there are no errors, which is unchanged.
- `test_claude_md_still_describes_this_code` — will fail if the new test name in
  CLAUDE.md is misspelled, or if `MAX_STYLE_PASSES` is named in the docs but
  does not exist in a module.

No live run and no API key is needed for this change.

## Commit message

```
Allow a second style-revision pass when the first one reduced the error count, so a lone residual error no longer brands the article a working draft.

Fixes #146
```

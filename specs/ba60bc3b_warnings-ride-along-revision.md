# Plan — #145: warning-level findings must ride along on a revision

## The problem

`style.check_style` records `long-sentence` as a **warning**. `style.revision_brief`
builds its list from `errors(report)`, so no warning ever reaches the model.
`pipeline.enforce_style` only revises when there are errors, so a draft with 12
long sentences and no errors is logged as "Prose style: clean" and shipped as is;
a draft that *is* revised gets its errors fixed and its long sentences left alone.

Measured across three recent runs: 21 long-sentence warnings (4, 5, 12 per draft),
mean sentence length 28–30 words, including a 61-word sentence in a Conclusions
section.

## What to change

Warnings ride along **only when a revision is already happening**. Errors still
decide whether the revision runs and whether it is kept. Nothing about the
acceptance rule, the sources split, or `check_style` itself changes.

### 1. `articlegen/style.py` — new constant

Add next to `SUBSTANCE_RULES` (just above `revision_brief`):

```python
# Warnings that ride along on a revision that is already happening. A warning
# never buys a revision on its own — `enforce_style` returns early when there
# are no errors — but once the model is being paid to rewrite prose anyway,
# a 61-word sentence is a fix nobody else is going to make (#145).
#
# `under-length` is deliberately absent. It is the one warning that is also a
# SUBSTANCE_RULE, and letting it into the brief would flip the brief into "go
# back to the SOURCES below" while `enforce_style` — which keys `needs_sources`
# on the *errors* — sent no sources with it. The brief would then name material
# that is not in the prompt.
RIDE_ALONG_WARNINGS = frozenset({"long-sentence", "wordiness", "passive-voice"})
```

Keep the name spelled in ALL CAPS and defined in `style.py`: `test_claude_md_still_describes_this_code`
resolves every backticked constant named in the docs against the modules.

### 2. `articlegen/style.py` — `revision_brief`

Current body:

```python
def revision_brief(report: dict) -> str:
    problems = errors(report) or report["issues"]
    needs_substance = any(i["rule"] in SUBSTANCE_RULES for i in problems)
    ...
```

Change to (structure, not literal — keep the existing docstring and the two
closing paragraphs exactly as they are worded):

```python
def revision_brief(report: dict) -> str:
    errs = errors(report)
    problems = errs or report["issues"]
    needs_substance = any(i["rule"] in SUBSTANCE_RULES for i in problems)

    # Warnings ride along only when errors already bought the revision. With no
    # errors there is no revision to attach them to, and appending them here
    # would let a warning-only report produce a brief that reads like a job.
    extras = [
        i for i in report["issues"]
        if i["severity"] != "error" and i["rule"] in RIDE_ALONG_WARNINGS
    ] if errs else []

    lines = ["The draft breaks these journal-prose conventions. Fix each one:"]
    for issue in problems:                      # unchanged loop
        ...

    if extras:
        lines.append(
            "Also fix these while you are in the same blocks, provided doing so "
            "disturbs nothing above:"
        )
        for issue in extras:
            lines.append(f"- [{issue['where']}] {issue['detail']}")
            if issue["excerpt"]:
                lines.append(f"  Offending text: {issue['excerpt']}")

    if needs_substance:
        ...                                      # both closing paragraphs unchanged
```

Rules the wording must respect:

- Errors are listed **first**, warnings second and labelled as secondary. The
  revision is only kept if it reduces the **error** count, so a model that spends
  its edit budget on sentence length and leaves an error in place gets the whole
  revision discarded — including the sentence fixes.
- The extras paragraph must **not** contain the strings `SOURCES below` or
  `go back to the SOURCES`. `test_revision_carries_sources_only_when_they_can_be_used`
  asserts a register-only brief contains neither.
- Do not touch the two closing paragraphs. Existing tests assert
  `"do not introduce new claims or numbers" in reg_brief` and
  `"SOURCES below" in substance`. Splitting a long sentence introduces no new
  claim or number, so the register paragraph is still true as written.
- `needs_substance` stays computed over `problems` (errors in every reachable
  path). Never compute it over `extras`.

### 3. Nothing changes in `articlegen/pipeline.py`

`enforce_style` already keys everything on errors: the early return
(`if not problems`), `rewrite_whole`, `needs_sources`, and the acceptance test
`len(style_errors(revised_report)) < len(problems)`. Leave all four alone. This
is what makes "warnings alone never trigger a revision" true, and what keeps the
acceptance rule keyed on errors.

### 4. `tests/test_offline.py` — new test

Add `def test_warnings_ride_along_on_a_revision() -> None:` immediately after
`test_revision_carries_sources_only_when_they_can_be_used`, and register it in the
`main()` tuple on the line after that test's entry (around line 5069). Use the
existing `check(label, condition)` helper; follow the house docstring style —
say what broke and what the test pins.

Cases to assert:

1. **Real prose, end to end.** Build an article with one register error and one
   genuinely long sentence (>45 words — `LONG_SENTENCE_WORDS`), run
   `check_style` then `revision_brief`, and assert the brief mentions the long
   sentence (e.g. `"word sentence; split it" in brief`). Confirm first that
   `check_style` on the fixture actually produced a `long-sentence` warning —
   if the fixture does not trip the rule the test proves nothing.
2. **Every long sentence rides along, not just the first.** A fixture with two
   over-length sentences puts two `long-sentence` items in the brief; count
   occurrences of `"word sentence"`.
3. **Warnings alone buy no revision.** Monkeypatch `pipeline.check_style` to
   return a warnings-only report (`long-sentence`, `severity: "warning"`) and
   `pipeline.revise_prose` to a function that sets a flag and raises. Call
   `pipeline.enforce_style({"sections": []})` and assert the flag is unset and
   the article comes back unchanged. Restore both in a `finally:` — several
   tests in this file mutate `pipeline` module attributes and the runner keeps
   going after a failure, so a leaked patch corrupts later tests.
4. **`under-length` does not ride along.** A report with a `contraction` error
   plus an `under-length` warning must produce a brief that still contains
   `"do not introduce new claims or numbers"` and does **not** contain
   `"SOURCES below"`. This is the pairing invariant: whenever the brief names the
   sources, `enforce_style` must actually have sent them.
5. **The curated sample is untouched.** `check_style(demo.SAMPLE_ARTICLE)` has
   zero errors and one `under-length` warning (verified). Assert
   `style.errors(check_style(SAMPLE_ARTICLE)) == []` so the sample still buys no
   revision at all.

Reuse the `report_with(rule, severity=...)` / `stats` fixture shape from
`test_revision_carries_sources_only_when_they_can_be_used` for the synthetic
reports — `format_report` reads `stats["sentences"]`, `mean_sentence_words`,
`hedges_per_sentence` and `passive_ratio`, so a stats dict missing those keys
raises.

### 5. `CLAUDE.md`

In the **Prose style (enforced, not prompted)** section, add one bullet after the
"The revision is a patch, not a new article" bullet:

> - **Warnings ride along on a revision; they never buy one.**
>   `RIDE_ALONG_WARNINGS` (long-sentence, wordiness, passive-voice) are appended
>   to `revision_brief()` only when errors already triggered the pass. The
>   early return, `needs_sources` and the acceptance rule all stay keyed on
>   errors. `under-length` is deliberately out: it is a substance rule, so
>   letting it in would make the brief ask for sources `enforce_style` did not
>   send. → `test_warnings_ride_along_on_a_revision`

Both the constant and the test name must exist in the code, or
`test_claude_md_still_describes_this_code` fails on the doc line.

### 6. `docs/decisions.md`

Add a short entry under `## Prose style`, matching the file's heading style:

```
### `#145` — long-sentence warnings survived every draft
```

Two or three short paragraphs: the measurement (three runs, 21 long-sentence
warnings at 4/5/12 per draft, mean sentence 28–30 words, a 61-word sentence in a
Conclusions section, one run logged "prose style clean" while printing 12
long-sentence lines); why warnings were excluded in the first place (a warning is
a matter of degree and must not be able to spend an LLM call on its own); and why
the fix is ride-along rather than promotion to error (promoting it would make
every long sentence buy a revision and would put length into the acceptance
count, which is calibrated on errors).

## Out of scope

- Do **not** promote `long-sentence` to an error, and do not change
  `LONG_SENTENCE_WORDS` (45).
- Do **not** change the `Draft.summary` "prose style clean" wording. It counts
  errors and that is a separate reporting question; leave it for its own issue.
- No new rules, no corpus changes (`tests/style_corpus.json`,
  `tests/real_abstracts.json` stay as they are — nothing here adds a rule, so the
  corpus-before-rule convention is not engaged).
- Do not touch `drafts/`, `adws/`, `.github/`.

## Verify

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must be green; judge by exit status, not by scanning output. No network,
no keys, no credit spent. A quick manual sanity check of the new brief:

```
python -c "
from articlegen import style
a = {'sections':[{'heading':'Introduction','paragraphs':[
 \"It's clear that \" + ' '.join(['word']*50) + ' here.']}]}
print(style.revision_brief(style.check_style(a)))
"
```

Expect the contraction listed first, then the long sentence under the
'Also fix these' line.

## Commit message

```
Include long-sentence and other warnings in the style revision brief when errors already triggered a revision, so they stop surviving every draft.

Fixes #145
```

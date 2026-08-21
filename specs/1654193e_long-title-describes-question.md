# Plan — `--long` titles describe the question, they do not claim the result (#170)

## What this fixes

The `--long` Review path asks the model for "the subject and the finding", so it
produced a title that asserts causation:

> Brief hospital admission by self-referral reduces involuntary care and self-harm
> without increasing total inpatient utilization in borderline personality disorder

Nothing checks titles — `verify.check_statistics` never looks at them, and
`style.py` has no title rule. The briefing path already asks for a descriptive
title. This makes the Review path ask for the same thing, in the same words, from
one shared string so the two cannot drift apart again.

Prompt-only fix. **No regex title-ban in `style.py`** — measure first, per the
issue.

## Files to touch

| File | Change |
|---|---|
| `articlegen/writer.py` | New `_TITLE_RULE` constant; both schemas use it; `_WRITER_SYSTEM` gains the TITLE line |
| `tests/test_offline.py` | New `test_titles_describe_the_question`, registered in `main()` |
| `CLAUDE.md` | One invariant row naming the new guard test (also satisfies the docs CI gate) |
| `docs/decisions.md` | Short entry recording the observed title and why the fix is prompt-only |

Out of scope, do not touch: `style.py`, `articlegen/demo.py`, `index.html`,
`drafts/`, `docs/journal-style.md`, the briefing prompt's own TITLE line.

---

## Step 1 — `articlegen/writer.py`: one shared title rule

`_ARTICLE_SCHEMA` starts at line ~70, well above `_WORKING_SET_RULE` (line ~270),
so the new constant has to be defined **before `_ARTICLE_SCHEMA`** — put it
immediately after `_CURATE_SCHEMA` ends (the `}` at line ~68) and before
`_ARTICLE_SCHEMA = {`.

The string is **verbatim the text `_BRIEFING_SCHEMA` already carries today**. Copy
it exactly; do not reword it. That is what makes this a no-op for the briefing.

```python
# One rule, used verbatim by both schemas, so the briefing and the `--long`
# Review cannot drift apart on what a title is for (#170). The Review path used
# to ask for "the subject and the finding", which is an instruction to assert a
# causal result in the one field nothing downstream checks.
_TITLE_RULE = (
    "A descriptive title: the population, the intervention or exposure, and "
    "the outcome. Sentence case. No puns, no questions, no colon-clickbait, "
    "and no result claimed — the title names the question, it does not answer "
    "it. Wrong: 'X reduces Y in Z'. Right: 'X for Y in Z'."
)
```

Then:

1. In `_ARTICLE_SCHEMA["properties"]["title"]` (line ~73-77), replace the whole
   `"description"` value — currently
   `"A declarative journal-style title: the subject and the finding, sentence case, no puns, no questions, no colon-clickbait."`
   — with `"description": _TITLE_RULE,`.
2. In `_BRIEFING_SCHEMA["properties"]["title"]` (line ~168-174), replace its
   description with `"description": _TITLE_RULE,` as well. The rendered string
   must be byte-identical to what is there now — verify with the check in Step 4
   before you consider this done.

Watch the em dash and the curly-quote-free apostrophes: the existing briefing text
uses `—` and straight single quotes around `'X reduces Y in Z'`. Keep both.

## Step 2 — `articlegen/writer.py`: the prompt line

`_WRITER_SYSTEM` has no TITLE line at all. `_BRIEFING_SYSTEM` has one at line 512:

```
TITLE: descriptive. Names the question. Does not claim the result.
```

Add **that exact sentence** to `_WRITER_SYSTEM`, in the same position the briefing
puts it: as its own paragraph immediately before the `REGISTER — this is checked
automatically after you write, so follow it exactly:` line (line ~385), separated
by a blank line either side. Leave the briefing's copy alone.

Nothing else needs doing for the derived prompts — `_REVISE_SYSTEM`,
`_REVISE_PATCH_SYSTEM` and `_WRITER_SYSTEM_FULLTEXT` are all built from
`_WRITER_SYSTEM`, so they inherit it. Confirm the fulltext variant still carries it:
`_FULLTEXT_SUBSTITUTIONS` only rewrites the abstracts-only framing and the
`FROM ITS ABSTRACT ONLY` phrase, neither of which is near the new line.

Do **not** touch the second-hand-figure bullet that says "never build the `title`
… on a second-hand figure". It still applies and other tests read that block.

## Step 3 — `tests/test_offline.py`: the guard test

Add a new test next to `test_briefing_is_the_default_artefact` (line ~6384), using
the file's existing `check(label, condition)` helper.

```python
def test_titles_describe_the_question() -> None:
    """A `--long` title names the question. It does not answer it.

    The Review path asked for "the subject and the finding" and got
    "Brief hospital admission by self-referral reduces involuntary care and
    self-harm ... in borderline personality disorder" — a causal claim in the
    one field nothing downstream checks. `verify.check_statistics` never reads
    titles and `style.py` has no title rule, so the prompt is the only control
    there is (issue #170).

    The briefing schema already had the rule. This pins that both schemas now
    read it from one string, that the old wording is gone, and that both system
    prompts carry the prohibition. Deliberately no regex title-ban in style.py:
    "reduces" is a legitimate word in a descriptive title and a crude ban would
    fail good titles. Measure first, per the issue.
    """
    from articlegen.writer import (_ARTICLE_SCHEMA, _BRIEFING_SCHEMA, _TITLE_RULE,
                                   _BRIEFING_SYSTEM, _REVISE_PATCH_SYSTEM,
                                   _REVISE_SYSTEM, _WRITER_SYSTEM,
                                   _WRITER_SYSTEM_FULLTEXT)

    article_title = _ARTICLE_SCHEMA["properties"]["title"]["description"]
    briefing_title = _BRIEFING_SCHEMA["properties"]["title"]["description"]

    check("the Review and the briefing share one title rule",
          article_title == briefing_title == _TITLE_RULE)
    check("the rule forbids claiming the result", "no result claimed" in _TITLE_RULE)
    check("and shows what that means",
          "reduces" in _TITLE_RULE and "Right:" in _TITLE_RULE)
    check("the rule asks for population, intervention/exposure and outcome",
          all(word in _TITLE_RULE
              for word in ("population", "intervention or exposure", "outcome")))
    check("the old 'subject and the finding' wording is gone",
          "the subject and the finding" not in article_title)

    line = "TITLE: descriptive. Names the question. Does not claim the result."
    check("the Review prompt carries the title rule", line in _WRITER_SYSTEM)
    check("the briefing prompt still does", line in _BRIEFING_SYSTEM)
    for name, prompt in (("revise", _REVISE_SYSTEM),
                         ("revise-patch", _REVISE_PATCH_SYSTEM),
                         ("full-text", _WRITER_SYSTEM_FULLTEXT)):
        check(f"the {name} prompt inherits it", line in prompt)
```

Register it in the `main()` tuple (line ~6463 onward) directly after
`test_briefing_is_the_default_artefact`.

Leave `test_real_articles_still_match_the_schema` unchanged — a `description` is
not validated, so it keeps passing; just confirm it does.

## Step 4 — verify

Run from the repo root, and judge each by its exit status, not by reading output
for the word "error":

```bash
python - <<'PY'
# the briefing description must be byte-identical to what it was before
from articlegen.writer import _BRIEFING_SCHEMA
d = _BRIEFING_SCHEMA["properties"]["title"]["description"]
expected = ("A descriptive title: the population, the intervention or exposure, "
            "and the outcome. Sentence case. No puns, no questions, no "
            "colon-clickbait, and no result claimed — the title names the "
            "question, it does not answer it. Wrong: 'X reduces Y in Z'. "
            "Right: 'X for Y in Z'.")
assert d == expected, repr(d)
print("briefing title text unchanged")
PY

python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both suites must be green. No live run, no credit spent — nothing here calls a
provider.

## Step 5 — `CLAUDE.md`

The `docs-current.yml` workflow fails a PR that touches `articlegen/**` without
touching `CLAUDE.md`, and `test_claude_md_still_describes_this_code` checks that
every backticked test name and constant in it exists. Add one row to the
"Pinned by a test" table in **Invariants**, after the
`Default artefact is a briefing; the Review is --long` row:

```
| A title names the question, in both paths, from one string | `test_titles_describe_the_question` |
```

That is all that is needed — the row names a test that will exist and a rule the
code enforces. Do not add a second prose paragraph; the table row plus the
decisions entry is the whole record.

## Step 6 — `docs/decisions.md`

Add a short entry in whichever section covers the writer prompts (match the file's
existing heading style — read the nearest few headings before writing). Keep it to
one short paragraph:

- what shipped: a Review title asserting that brief self-referral admission
  *reduces* involuntary care and self-harm;
- why nothing caught it: `verify.check_statistics` reads sentences, not the title,
  and `style.py` has no title rule;
- what was done: `_TITLE_RULE`, one string in both schemas, plus the briefing's
  existing TITLE line added to `_WRITER_SYSTEM`;
- what was deliberately *not* done: a regex ban on `reduces|increases|improves` in
  `style.py` — those words are legitimate in a descriptive title, so a crude ban
  fails good titles. Revisit only if a later `--long` draft shows the prompt being
  ignored.

Only name files, tests and constants that exist — that doc is swept by the same
guard test.

## Step 7 — branch, PR

Per the repo's rules this is more than a single-file edit, so:

```bash
git checkout -b fix/170-long-titles-describe-the-question
git add articlegen/writer.py tests/test_offline.py CLAUDE.md docs/decisions.md
git commit
git push -u origin fix/170-long-titles-describe-the-question
gh pr create
```

PR body: say what changed and why in a couple of lines, and write `Closes #170`.
**Never write "does not close #NNN"** anywhere in the body or the commit — GitHub's
parser ignores the negation and closes the issue.

The CLAUDE.md edit satisfies the docs gate, so no `Docs: n/a` line is needed.

## Done when

- `_TITLE_RULE` exists once in `articlegen/writer.py` and both schemas read it.
- `_WRITER_SYSTEM` contains `TITLE: descriptive. Names the question. Does not claim the result.`
- The briefing's schema description and prompt line are byte-for-byte what they
  were before.
- `test_titles_describe_the_question` exists, is registered in `main()`, and passes.
- `test_real_articles_still_match_the_schema` still passes.
- `python tests/test_offline.py` and `python tests/test_journal_conformance.py`
  both exit 0.
- `style.py` is untouched; `drafts/` is untouched.

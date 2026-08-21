# Plan — cite a working set of ~12, keep screening 40 (#167)

## What this is

The candidate pool is 40 so the relevance gate has something to throw away
(#141). The shipped drafts then cited almost everything they screened —
safety-planning 20/20, seclusion 17/20. That is inclusion, not curation. A
briefing cannot carry 17 papers.

This change tells the writer — both the briefing and the `--long` Review — to
cite a **working set of about 12**, preferring direct sources, and makes the
screened-vs-cited gap visible in Methods and in the one-line run summary so the
next few real runs can be measured.

Nothing about the pool, the search, curation or full-text fetching changes. The
whole 40 is still screened, still curated, still eligible.

## Out of scope (from the issue — do not do these)

- Do not drop `DEFAULT_MAX_PAPERS` back to 20.
- Do not truncate curation abstracts. `CURATION_ABSTRACT_CHARS` stays `None`.
- Do not hide uncited candidates from Table 1. Table 1 is **cited records**; the
  screened count lives in Methods.
- Do not put `--long` on the web UI.
- Do not regenerate anything in `drafts/`.

## Why the current prompts produce inclusion

Read these two before editing:

- `articlegen/writer.py` `_BRIEFING_SYSTEM` already carries one weak line:
  *"Cite about a dozen sources, preferring direct ones. Related sources only
  when they earn a specific point."* It is buried mid-list under SUBSTANCE, it
  is not repeated in the run-specific context, and no number reaches the model
  from the actual run.
- `articlegen/writer.py` `_WRITER_SYSTEM` says the opposite outright:
  *"Lead with the strongest DIRECT evidence, and cite the related and tangential
  sources too …"* That is an instruction to include everything, and it is also
  **factually wrong about its own inputs**: `_writer_context` drops every
  tangential source from the prompt by number (`omit=`), so the model is told to
  cite sources it cannot see. CLAUDE.md's rule applies — a prompt that
  misdescribes its own inputs teaches the model to ignore it.

## Files to touch

| File | Why |
|---|---|
| `articlegen/writer.py` | the constant, the shared rule, both system prompts, the derived per-run line |
| `articlegen/pipeline.py` | `Draft.summary()` prints cited **of screened** so runs can be measured |
| `articlegen/render.py` | keep Methods' full-text count in agreement with Table 1's Read column once some read sources go uncited |
| `tests/test_offline.py` | new guard test + two updated assertions in `test_draft_summary` |
| `CLAUDE.md` | new invariant row + amend the candidate-pool bullet |
| `docs/decisions.md` | the story, under `## Grounding and provenance` |

---

## Step 1 — `articlegen/writer.py`: one constant, one rule string

Add both **above** `_WRITER_SYSTEM` (currently line 257), after `_CURATE_SCHEMA`
/ before the prompt strings.

```python
# The writer screens the whole candidate pool and cites a working set of about
# this many sources. The pool is deliberately larger — `sources.DEFAULT_MAX_PAPERS`
# is 40 — so the relevance gate has something to discard (#141). What it then
# discarded was almost nothing: the shipped drafts cited 20 of 20 and 17 of 20
# (#167). Screening that keeps everything is inclusion, not curation, and a
# one-page briefing cannot carry seventeen papers.
#
# Not a preference. The same argument as TONE_LABEL/LENGTH_LABEL: the shape of
# the artefact is fixed, and the reader does not choose it.
TARGET_CITED_SOURCES = 12

# One string, used verbatim in both system prompts, so the briefing and the
# `--long` Review cannot drift apart on the one rule they share.
_WORKING_SET_RULE = f"""\
- CITE A WORKING SET, NOT EVERYTHING YOU WERE SHOWN. The candidate list is \
deliberately longer than this piece needs, so that screening has something to \
discard, and sources labelled tangential have already been withheld from it. \
Cite about {TARGET_CITED_SOURCES} sources: the direct ones first, and a related \
source only when it earns a specific point no direct source makes — a mechanism, \
an adjacent population, a contrast. Report what a related source found under its \
own label, never as a direct finding, and label evidence carried over from \
another population as extrapolation. A source you have nothing specific to say \
about does not belong in the reference list."""
```

### 1a. `_WRITER_SYSTEM`

Delete the whole bullet beginning `- Lead with the strongest DIRECT evidence,`
(it runs to `— just don't let it masquerade as a direct finding.`) and splice
`_WORKING_SET_RULE` in its place by concatenation, e.g.

```python
_WRITER_SYSTEM = """\
… everything up to the bullet before it …
""" + _WORKING_SET_RULE + """
- featured_study: summarize the single most relevant study's method and results \
FROM ITS ABSTRACT ONLY. …
"""
```

Keep the surrounding blank lines and bullet spacing exactly as they are now.

### 1b. `_BRIEFING_SYSTEM`

Under `SUBSTANCE:`, delete the line
`- Cite about a dozen sources, preferring direct ones. Related sources only when they earn a specific point.`
and splice `_WORKING_SET_RULE` in its place the same way.

### Traps in this file — read before editing

- **`_FULLTEXT_SUBSTITUTIONS` (line ~674).** A test asserts each substitution
  target appears **exactly once** in `_WRITER_SYSTEM` and is present in
  `_BRIEFING_SYSTEM`. The four targets are:
  `"You are working from ABSTRACTS ONLY — never the full papers. This constrains you:"`,
  `"if that exact figure appears in the abstract you are citing"`,
  `"If the abstract doesn't give the number,"`, `"FROM ITS ABSTRACT ONLY"`.
  `_WORKING_SET_RULE` contains none of them — keep it that way. Do not delete or
  duplicate any of them while editing around them.
- **The revise prompts inherit these systems.** `_REVISE_SYSTEM`,
  `_REVISE_PATCH_SYSTEM`, `_REVISE_BRIEFING_SYSTEM` and
  `_REVISE_BRIEFING_PATCH_SYSTEM` are all `<system> + addendum`, and each
  addendum already says every `[N]` marker must survive unchanged and no source
  may be added or removed. That addendum comes **after** the working-set rule and
  must stay that way — a style pass must never start dropping citations. Do not
  add the working-set rule anywhere in the revise addenda.

## Step 2 — `articlegen/writer.py`: the derived per-run line in `_writer_context`

`_writer_context` (~line 900) is the shared payload builder for both
`write_briefing` and `write_article`, so the run's real numbers reach both from
one place. Insert this **after** the `omit` explanation paragraph and
**immediately before** `context += _format_sources(...)`, so the selection rule
is the last instruction the model reads before the data:

```python
    shown = len(papers) - len(omit)
    if shown > TARGET_CITED_SOURCES:
        context += (
            f"WORKING SET. {len(papers)} records were screened and {shown} are "
            f"reproduced below. Cite about {TARGET_CITED_SOURCES} of them — the "
            f"ones that carry the {kind}. Leaving a screened source uncited is "
            "the expected outcome of screening, not an omission; the counts the "
            "reader sees are computed from what you cite.\n\n"
        )
    else:
        context += (
            f"WORKING SET. {len(papers)} records were screened and {shown} are "
            f"reproduced below. Cite the ones that carry the {kind} and no more; "
            "a source you have nothing specific to say about does not belong in "
            "the reference list.\n\n"
        )
```

The branch matters: with a thin pool the prompt must not ask for 12 sources it
is not showing. Same no-fallback discipline as the provenance rules — the prompt
states what is actually in front of the model.

## Step 3 — `articlegen/pipeline.py`: make the ratio measurable

In `Draft.summary()` change the opening clause:

```python
parts = f"{len(cited)} of {len(self.papers)} screened sources cited"
```

`summary()` is printed by the CLI as `EVIDENCE_SUMMARY:` and returned by the web
API. Nothing parses it — checked: `cli.py:127` prints it, `web.py:429` passes it
through as a string, no workflow or front-end code reads its shape. This is the
free measurement the issue asks for: "cited-of-screened should fall well below
the 16–19 of 20".

## Step 4 — `articlegen/render.py`: Methods and Table 1 must not disagree

**Why this is needed even though render is not in the issue's file list.**
CLAUDE.md: *"Table 1's Read column must agree with Methods."* Methods counts full
texts **fetched** (`provenance["full_text_sources"]`); Table 1's Read column and
every other grounding phrase count full texts **fetched and cited**
(`render._full_text_count(cited)`). Today those agree only because nearly every
screened source gets cited. Once the writer cites 12 of 40, a paper can be read
in full and not cited — Methods would say "the open-access full texts of 5
sources were retrieved … (marked in Table 1)" while Table 1 marks 3. This change
creates that gap, so this change closes it.

In `_methods_paragraphs` (line ~797) add a keyword parameter and use it in the
full-text branch only:

```python
def _methods_paragraphs(
    provenance: dict | None, screened: int, n_cited: int, topic: str, esc=lambda s: s,
    n_full_cited: int | None = None,
) -> dict[str, str]:
```

In the `if n_full:` branch, replace the literal `(marked in Table 1)` with:

```python
        marked = (
            "(marked in Table 1)"
            if n_full_cited is None or n_full_cited == n_full
            else f"({n_full_cited} of which are cited here and marked in Table 1)"
        )
```

and interpolate `{marked}` where the literal was. Thread the same optional
parameter through `_methods_html` (line ~889) and `_methods_markdown`
(line ~2048), and pass it at both call sites — line ~1454
(`render_article`) and line ~1947 (`render_markdown`) — as
`n_full_cited=_full_text_count(cited)`.

Defaulting to `None` keeps the existing direct-call tests
(`tests/test_offline.py:5751` onward) and the `full-text mode` fixture in
`tests/test_journal_conformance.py` green: that fixture reads and cites the same
two papers, so the wording is unchanged there.

## Step 5 — tests

### 5a. Update `test_draft_summary` (line ~752)

Two assertions change wording only:

- line ~765: `clean.summary().startswith("3 of 5 screened sources cited")`
- line ~786: `out_of_range.summary().startswith("1 of 5 screened sources cited")`

### 5b. New test `test_the_writer_cites_a_working_set`

Add it near `test_tangential_sources_stay_out_of_the_writer_prompt` (it uses the
same prompt-capture pattern: swap `writer.generate_json` for a recorder in a
`try/finally`), and **register it in `main()`'s tuple** (~line 6264) — an
unregistered test never runs.

Docstring: state the numbers from #167 (20/20 and 17/20 cited-of-screened) and
that the pool stays 40 — the docstring is where the reasoning lives.

Assertions:

1. **The pool did not shrink.** `sources.DEFAULT_MAX_PAPERS == 40` and
   `writer.CURATION_ABSTRACT_CHARS is None` — the two things #167 forbids
   trading away for this.
2. **The constant exists and is 12.** `writer.TARGET_CITED_SOURCES == 12`.
3. **One rule string, in both prompts.**
   `writer._WORKING_SET_RULE in writer._BRIEFING_SYSTEM` and
   `writer._WORKING_SET_RULE in writer._WRITER_SYSTEM`, and the rule text
   contains `str(writer.TARGET_CITED_SOURCES)` (so the prose cannot drift from
   the constant).
4. **The inclusion instruction is gone.**
   `"cite the related and tangential sources too" not in writer._WRITER_SYSTEM`
   — and, because that sentence was also false about its own inputs, assert the
   Review prompt now says tangential sources were withheld.
5. **Full-text variants still carry the rule.**
   `writer._WORKING_SET_RULE in writer._WRITER_SYSTEM_FULLTEXT` and in
   `writer._BRIEFING_SYSTEM_FULLTEXT` (guards against a substitution eating it).
6. **The run's own numbers reach the model.** Build 40 `Paper`s, mark 4
   tangential in `relevance`, capture the prompt from `write_briefing` and again
   from `write_article`. In both: `"WORKING SET"` appears, `"40 records were
   screened"` appears, `"36 are reproduced below"` appears, and
   `f"about {writer.TARGET_CITED_SOURCES} of them"` appears.
7. **A thin pool is not asked for twelve.** Same capture with 6 papers, 1
   tangential: the prompt says `"5 are reproduced below"` and does **not**
   contain `"about 12"`.
8. **Methods prints screened and cited as two different numbers.**
   `render._methods_html(prov, screened=40, n_cited=12, topic="x")` contains
   `"leaving 40"` and `"12 were cited here"`; same for
   `render._methods_markdown`. (This is the issue's "two different numbers on a
   healthy run" — it already works; the test pins it so a future edit cannot
   collapse them.)
9. **Methods does not over-claim the Read column.** With
   `provenance["full_text_sources"] = [1, 2, 3, 4, 5]` and `n_full_cited=3`, the
   Methods HTML says `"3 of which are cited here and marked in Table 1"` and
   does **not** contain the bare `"(marked in Table 1)"`. With `n_full_cited=5`
   the wording is the unchanged one.

Use the existing `check(...)` helper for every assertion, one line each.

## Step 6 — docs

### `CLAUDE.md`

1. New row in the pinned-invariant table (Invariants section):
   `| The writer cites a working set, not everything screened | test_the_writer_cites_a_working_set |`
2. In **Sources and grounding**, extend the `DEFAULT_MAX_PAPERS` bullet — it
   currently explains why the pool is 40 and stops there. Add, in the same
   bullet or directly under it:
   *"The pool is what is **screened**; `writer.TARGET_CITED_SOURCES` (12) is what
   is **cited**. Those are two numbers and Methods prints both — raising the pool
   without a citing target just produced longer reference lists (20 of 20, 17 of
   20 cited, #167). The working-set rule lives in one string,
   `writer._WORKING_SET_RULE`, spliced into both `_BRIEFING_SYSTEM` and
   `_WRITER_SYSTEM`, with the run's own screened/shown counts added by
   `_writer_context`. Table 1 stays the list of **cited** records; the screened
   count lives in Methods."*
3. In the same area, note that Methods' full-text sentence now names how many
   read sources were cited when those two differ, because the Read column counts
   read-and-cited.

Do not restate the test's assertions in prose — name the test and stop, per the
file's own rule.

### `docs/decisions.md`

Short entry under `## Grounding and provenance`, headed
``### `#167` — the pool was curated, the reference list was not``. Record: the
pool went to 40 for #141; the next drafts cited 20/20 and 17/20; the briefing
prompt's one weak "about a dozen" line was already there and did nothing on its
own; `_WRITER_SYSTEM` was actively instructing the opposite *and* naming
tangential sources that `_writer_context` never showed it; the fix is a shared
rule string plus the run's real counts in the context; and the acceptance
measurement is the next few real runs' `EVIDENCE_SUMMARY` line, which now reads
"N of 40 screened sources cited".

Keep both docs' backticked file/test/constant names correct —
`test_claude_md_still_describes_this_code` fails on a name that does not exist.

## Verification

Run from the repo root. Judge by exit status, not by reading for the word
"error".

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. Then one no-network render to eyeball Methods:

```
articlegen demo
```

Expect: the demo draft still renders, Methods still reads sensibly, and the new
prompt text is not in the rendered page (it is prompt-side only).

Optional, if a key is available and the operator asks for it — **not required to
land this** — one real `articlegen draft "<topic>"` and read the
`EVIDENCE_SUMMARY:` line. Acceptance per the issue: cited-of-screened well below
the old 16–19 of 20. If it does not fall, the problem is the prompt, not the cap.

## Done means

- `sources.DEFAULT_MAX_PAPERS` is still 40 and `CURATION_ABSTRACT_CHARS` is still
  `None`.
- Both the briefing and the `--long` Review are instructed to cite a working set
  of about 12, direct first, related only when it earns a specific point.
- `_WRITER_SYSTEM` no longer tells the model to cite the tangential sources it
  was never shown.
- Methods shows screened and cited as two different numbers, and does not claim
  Table 1 marks more read sources than it does.
- `Draft.summary()` reports cited of screened.
- `test_the_writer_cites_a_working_set` exists, is registered in `main()`, and
  passes; both suites green.
- CLAUDE.md and `docs/decisions.md` updated.

## PR notes

- Branch, push, `gh pr create` — the user merges.
- The PR body must mention the CLAUDE.md edit or carry `Docs: n/a - <why>`;
  since CLAUDE.md is edited, nothing extra is needed.
- Reference the issue as **"Refs #167"** and **"Refs #141, stays open"**. Never
  write "does not close #NNN" — GitHub's parser closes it anyway.

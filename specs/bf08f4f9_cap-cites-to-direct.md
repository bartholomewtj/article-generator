# Plan — cap cites at the direct count, pin the question to the topic, prefer read papers (#188)

## What this is

Three prompt-side fixes to `articlegen/writer.py`, all measured on four Grok 4.6
briefings from 21 Aug 2026 (issue #188):

1. **Thin-direct runs padded to 12.** The writer is told "cite about 12" whenever
   more than 12 sources are shown, regardless of how many are actually *direct*.
   A run with 7 direct sources filled the remaining slots with related and
   weak-design papers. Cap the ask at `min(12, n_direct + 2)`.
2. **All four runs moved the question.** `question` and `title` widened or
   narrowed away from the topic the user typed — a different population, an
   added clause. Pin both to the user's topic; polish only.
3. **A deep read was wasted.** The organic run fetched 5 full texts, cited 4 of
   them, and padded the reference list with abstract-only case reports. Tell the
   writer which SOURCE numbers it was given full text for, and that leaving one
   uncited while citing an abstract-only source is the wrong trade.

Everything here is prompt text plus one small pure function. No pipeline stage
moves, no new LLM calls, no schema field added or removed.

## Files to touch

| File | What changes |
|---|---|
| `articlegen/writer.py` | new `MIN_CITED_SOURCES` + `cite_target()`; rewritten `_WORKING_SET_RULE`; new `_TOPIC_FIDELITY_RULE` spliced into both system prompts; `_TITLE_RULE` gains a topic-fidelity sentence; `_BRIEFING_SCHEMA["question"]` description gains one; `_writer_context()` builds the per-run WORKING SET line from `cite_target`, adds the topic-pinning line and the full-text-preference line |
| `articlegen/pipeline.py` | one log line only (the run's cite ceiling), so the operator can see it |
| `tests/test_offline.py` | update `test_the_writer_cites_a_working_set` for the new wording; add `test_the_cite_ceiling_scales_with_the_direct_count` |
| `CLAUDE.md` | two invariant rows; amend the pool/target bullet in "Sources and grounding" |
| `docs/decisions.md` | short `#188` entry under the existing per-issue heading style |

`pipeline.py` does **not** build the working-set line — `writer._writer_context`
owns it (verified). Do not move that logic into the pipeline.

## Step 1 — `cite_target()` in `articlegen/writer.py`

Put it directly under `TARGET_CITED_SOURCES = 12` (line ~280), keeping that
constant and its comment as they are.

```python
# A cite ceiling of 12 is the ceiling, not the target. It was being read as a
# target: four measured briefings (#188) with a thin direct pool cited 12
# anyway, filling the gap with related sources and weak-design primary studies.
# The ask now scales with the evidence that is actually on-topic — at most two
# sources beyond the direct count, and only for a contrast no direct source
# makes.
#
# The floor exists because the schema asks for 5-8 findings, each tied to a
# named study: a run with one direct source cannot be asked for a two-source
# briefing. Where the pool itself is smaller than the floor, the pool wins.
MIN_CITED_SOURCES = 5


def cite_target(n_direct: int | None, shown: int) -> int:
    """How many sources this run should be asked to cite.

    `min(TARGET_CITED_SOURCES, n_direct + 2)`, floored at MIN_CITED_SOURCES and
    never above the number of sources actually reproduced in the prompt. An
    unlabelled run (`n_direct is None`) gets the flat ceiling, because there is
    no direct count to scale by.
    """
    if n_direct is None:
        target = TARGET_CITED_SOURCES
    else:
        target = min(TARGET_CITED_SOURCES, int(n_direct) + 2)
    target = max(target, MIN_CITED_SOURCES)
    return min(target, shown) if shown else target
```

Required behaviour (these become test cases):

| `n_direct` | `shown` | result | why |
|---|---|---|---|
| 7 | 30 | 9 | the issue's worked example |
| 21 | 30 | 12 | the flat ceiling still binds |
| 0 | 30 | 5 | floor — a zero-direct run is still a briefing |
| `None` | 30 | 12 | unlabelled: nothing to scale by |
| 3 | 4 | 4 | never ask for more than are shown |

## Step 2 — rewrite `_WORKING_SET_RULE`

It is one string spliced verbatim into `_BRIEFING_SYSTEM` and `_WRITER_SYSTEM`,
so it cannot know this run's direct count. It states the *rule*; the per-run
line (step 4) states the number. Replace the body with something equivalent to:

```python
_WORKING_SET_RULE = f"""\
- CITE A WORKING SET, NOT EVERYTHING YOU WERE SHOWN. The candidate list is \
deliberately longer than this piece needs, so that screening has something to \
discard, and sources labelled tangential have already been withheld from it. \
Cite AT MOST {TARGET_CITED_SOURCES} sources, and never more than two beyond the \
number labelled direct. The WORKING SET note below gives this run's exact \
ceiling: it is a ceiling, not a quota. Citing fewer is the correct outcome of a \
thin evidence base — do NOT pad the reference list to reach the number. \
- Direct sources first. A related source earns a place only when it makes a \
specific point no direct source makes — a mechanism, an adjacent population, a \
contrast — and at most two do. Report what a related source found under its own \
label, never as a direct finding, and label evidence carried over from another \
population as extrapolation. A source you have nothing specific to say about \
does not belong in the reference list, and a case report cited to fill a slot \
is worse than a shorter list."""
```

Constraints on the wording:

- `str(TARGET_CITED_SOURCES)` must still appear in it (pinned by
  `test_the_writer_cites_a_working_set`).
- The phrase `sources labelled tangential have already been withheld` must
  survive verbatim — the same test checks it in `_WRITER_SYSTEM`.
- Do **not** ban related citations. The cap is two, not zero (out of scope).

## Step 3 — pin the question and the title to the user's topic

Three places, smallest first.

**3a. `_TITLE_RULE`** (line ~81). Append one sentence, leave everything else
byte-identical — `test_titles_describe_the_question` asserts the existing
substrings and that both schemas read this one string:

```
" The title names the topic the reader gave, in the same population and scope: "
"polish clumsy wording, but never add a clause, narrow the population, or "
"broaden to the area the sources happen to cover."
```

**3b. `_BRIEFING_SCHEMA["properties"]["question"]["description"]`** — append:

```
" It restates the reader's topic as asked, in the same population and scope. "
"Polished wording only: no added clause, no narrowed population."
```

**3c. A new shared rule string**, next to `_WORKING_SET_RULE`, spliced into both
`_BRIEFING_SYSTEM` and `_WRITER_SYSTEM` the same way (`""" + _TOPIC_FIDELITY_RULE + """`).
Put it immediately after the working-set splice in each prompt:

```python
# The question the reader typed is the product. All four measured briefings
# (#188) returned a `question` that had moved — a narrowed population, an added
# clause, or a widening to whatever the retrieved sources covered. Nothing
# downstream checks this: `verify.check_statistics` never reads the question or
# the title, and `style.py` has no rule for either, so the prompt is the only
# control (same reasoning as #170).
_TOPIC_FIDELITY_RULE = """\
- THE QUESTION IS THE READER'S, NOT YOURS. The topic at the top of the prompt is \
what was asked. `title` — and `question`, where the shape has one — must stay on \
it: same subject, same population, same scope. You may polish clumsy wording into \
a clean question. You may NOT add a qualifying clause, narrow the population to a \
subgroup, restrict the setting or the timeframe, or widen the topic to the area \
the sources happen to cover. When the evidence does not answer the topic as \
asked, that is what `answer` and `unknowns` — or, in a Review, the Introduction \
and Conclusions — are for. Never rewrite the question into one the sources \
answer better."""
```

Both `_WRITER_SYSTEM_FULLTEXT` / `_BRIEFING_SYSTEM_FULLTEXT` and the revise
prompts inherit this automatically, since they are built from the system prompts
by `_with_fulltext_framing` / concatenation. Check that none of the strings in
`_FULLTEXT_SUBSTITUTIONS` accidentally matches the new text (they will not — the
substitution keys are about abstracts and figures).

## Step 4 — `_writer_context()` (line ~1032)

Three edits inside this one function.

**4a. Topic line.** The context currently opens `f"Topic: {topic}\n\n"`. Extend
it so the model is told what that line is for. Keep it `kind`-aware — the Review
has no `question` field, so naming one would misdescribe the shape:

```python
context = f"Topic: {topic}\n\n"
if kind == "briefing":
    context += (
        "That line is the reader's question, as typed. `question` and `title` "
        "must stay on it — polish the wording if it is clumsy, but do not add a "
        "clause, narrow the population, or drift to whatever the sources below "
        "happen to cover.\n\n"
    )
else:
    context += (
        "That line is the reader's question, as typed. The `title` and the "
        "Introduction's statement of scope must stay on it — polish the wording "
        "if it is clumsy, but do not add a clause, narrow the population, or "
        "drift to whatever the sources below happen to cover.\n\n"
    )
```

**4b. The WORKING SET line.** Replace the existing `if shown > TARGET_CITED_SOURCES:`
branch with one keyed on `cite_target`:

```python
shown = len(papers) - len(omit)
target = cite_target(counts.get("direct") if counts else None, shown)
if shown > target:
    context += (
        f"WORKING SET. {len(papers)} records were screened and {shown} are "
        f"reproduced below, of which {counts.get('direct', 0)} are directly "
        f"on-topic. Cite AT MOST {target} of them — the ones that carry the "
        f"{kind}, direct sources first. That is a ceiling and not a quota: "
        "citing fewer is the correct outcome of a thin evidence base, and a "
        "source added to reach the number makes the piece worse. Leaving a "
        "screened source uncited is the expected outcome of screening, not an "
        "omission; the counts the reader sees are computed from what you cite.\n\n"
    )
else:
    ...  # existing "cite the ones that carry the {kind} and no more" branch, unchanged
```

Note `counts` may be `{}` (unlabelled run) — `counts.get("direct") if counts else None`
is what routes that to the flat ceiling. Guard the `{counts.get('direct', 0)} are
directly on-topic` clause so it is only emitted when `counts` is truthy; drop that
clause otherwise rather than printing "0 are directly on-topic" for a run that was
never labelled. **A prompt that misdescribes its own inputs teaches the model to
ignore it** — that rule is in `CLAUDE.md` and it applies here.

**4c. Full-text preference.** After `excerpts = full_text_excerpts(papers)` and
after the omit set is known, add a line naming the SOURCE numbers actually read,
emitted **only when there are any** (same reason as above — a run with no full
text must not be told to prefer full text):

```python
read = sorted(i for i in excerpts if i not in omit)
if read:
    context += (
        "DEEP READS. The open-access full text below was fetched for "
        f"SOURCE {', '.join(str(i) for i in read)} — the pipeline spent a "
        "retrieval on each because they were the most relevant reviews and "
        "trials it could read. Prefer them: a full-text source you leave "
        "uncited while citing an abstract-only case report is the wrong trade. "
        "Cite one only if the briefing genuinely has no use for it.\n\n"
    )
```

Place it before the `Here are the candidate sources...` paragraph, with the
`{kind}` word substituted where "briefing" appears if you prefer — either is
fine as long as the Review path does not read as if it were a briefing.

## Step 5 — one log line in `articlegen/pipeline.py`

The ceiling is now run-dependent, so make it visible. In `generate_draft`,
immediately before `compose = write_article if long else write_briefing`
(line ~695):

```python
_n_direct = ((curation or {}).get("counts") or {}).get("direct")
_shown = len(papers) - sum(
    1 for label in (curation.get("relevance") or {}).values() if label == "tangential"
)
log(f"  cite ceiling: {cite_target(_n_direct, _shown)} "
    f"({_n_direct if _n_direct is not None else 'unlabelled'} direct of {_shown} shown)")
```

Add `cite_target` to the existing `from .writer import (...)` at line ~35. No
test needed for the log line; do not let it raise if `curation` is `{}`.

## Step 6 — tests (`tests/test_offline.py`)

**6a. Update `test_the_writer_cites_a_working_set`** (line ~3700). It fails as
written, and that is expected, not a regression:

- Section 6 builds a 40-paper pool with `counts = {"direct": 16, ...}`. With
  `n_direct = 16`, `cite_target` returns 12, so the prompt now reads
  `at most 12 of them` — change the assertion from
  `f"about {writer.TARGET_CITED_SOURCES} of them"` to
  `f"at most {writer.TARGET_CITED_SOURCES} of them"`.
- Section 3's `str(TARGET_CITED_SOURCES) in _WORKING_SET_RULE` still holds.
- Section 7's `"about 12" not in thin_prompt` still holds; also assert
  `"at most 12" not in thin_prompt`.
- Leave sections 1, 2, 4, 5, 8, 9 alone.

**6b. Add `test_the_cite_ceiling_scales_with_the_direct_count`.** Follow the
house pattern: docstring naming issue #188 and what was measured, then `check(...)`
calls, then register it wherever the file registers its tests (copy how
`test_the_writer_cites_a_working_set` is wired in — check the bottom of the
file). Assert:

1. `cite_target` returns the five values in the step-1 table.
2. `MIN_CITED_SOURCES == 5` and `TARGET_CITED_SOURCES == 12` (the ceiling did
   not move).
3. Prompt level, via a fake `writer.generate_json` capturing the prompt (copy
   the `fake_generate` shape already in the file): a 30-paper pool with
   `counts = {"direct": 7, "related": 20, "tangential": 3}` produces a briefing
   prompt containing `at most 9` and **not** containing `at most 12` or
   `about 12`.
4. Same pool with `counts = {"direct": 21, ...}` produces `at most 12`.
5. The rule text: `_WORKING_SET_RULE` contains `AT MOST` (or `at most`) and the
   two-related cap; it no longer contains `Cite about`.
6. Full-text preference: papers 2 and 5 given a non-empty `full_text`, the rest
   empty → the prompt contains `DEEP READS` and names `SOURCE 2, 5`; with no
   `full_text` anywhere the prompt contains neither `DEEP READS` nor the
   preference sentence. (`sources.full_text_excerpts` keys off `Paper.full_text`
   — set it directly on the `Paper` objects.)
7. Topic fidelity: `_TOPIC_FIDELITY_RULE` appears in `_BRIEFING_SYSTEM`,
   `_WRITER_SYSTEM`, `_BRIEFING_SYSTEM_FULLTEXT` and `_WRITER_SYSTEM_FULLTEXT`;
   `narrow the population` appears in `_TITLE_RULE` and in the briefing schema's
   `question` description; the briefing prompt for a run on topic `"topic"`
   contains the "reader's question, as typed" line.
8. `_ARTICLE_SCHEMA["properties"]["title"]["description"] == _BRIEFING_SCHEMA["properties"]["title"]["description"] == _TITLE_RULE`
   still holds after 3a (one string, both schemas).

Nothing in this test may hit the network or need a key.

## Step 7 — docs

**`CLAUDE.md`** (the docs-current workflow fails a PR touching `articlegen/**`
that leaves this file alone, so it must be edited):

- Add two rows to the invariant table:
  - `| The cite ceiling scales with the direct count | test_the_cite_ceiling_scales_with_the_direct_count |`
  - `| The question and title stay on the reader's topic | test_the_cite_ceiling_scales_with_the_direct_count |`
    (or a second test name if you split them — the table must name a test that
    exists, which `test_claude_md_still_describes_this_code` checks).
- In "Sources and grounding", amend the paragraph that reads
  "`writer.TARGET_CITED_SOURCES` (12) is what is **cited**": say that 12 is now
  the ceiling, that the run's ask is `min(12, n_direct + 2)` floored at
  `MIN_CITED_SOURCES` (5) and never above the number shown, and that the ask
  lives in `writer.cite_target` and is printed in both the WORKING SET line and
  the CLI log.
- One bullet on the deep-read preference: full text was fetched at a cost, so
  the read SOURCE numbers are named in the prompt and leaving one uncited while
  citing an abstract-only source is the failure the line exists to stop.
- Name `MIN_CITED_SOURCES` and `cite_target` — the CLAUDE.md checker verifies
  that constants named there still exist, so spell them exactly.

**`docs/decisions.md`** — add a `### The cite ceiling scales with the direct
count (#188)` entry under the section the other writer/source decisions live in.
Record the measurement as it stands in the issue: four Grok 4.6 briefings,
21 Aug 2026; thin-direct runs padded to 12; all four moved the question; the
organic run fetched 5 full texts and cited 4. Say plainly that the fix is prompt
text plus one clamp, so the evidence that it worked has to come from the next
batch of drafts, not from a test.

## Verify

Both must exit 0. Judge by exit status, not by reading the output for the word
"error".

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Also `python -c "import articlegen.writer, articlegen.pipeline"` to catch an
import-order mistake in the new constants, and
`python -m articlegen.cli demo` (or `articlegen demo`) as a no-network smoke of
the render path.

Do **not** run `--live` and do not generate a real draft — this spends credit,
and nothing in the change can be verified by one sample anyway.

## Ship

Branch, push, PR (per the repo's working rules — never commit straight to
`main`):

```
git switch -c fix/188-cite-ceiling-and-topic-fidelity
```

PR body must include a docs line (or edit `CLAUDE.md`, which this plan does, so
the gate is satisfied either way) and:

```
Closes #188. Refs #185, #167.
```

Never write "does not close #NNN" anywhere in the body or a commit message —
GitHub's parser ignores the negation and closes the issue.

## Out of scope — do not do these

- Banning related citations outright. The cap is two, not zero.
- Dropping `DEFAULT_MAX_PAPERS` back to 20.
- Changing the default model (settled, #85).
- Putting `--long` on the web UI.
- Regenerating the public demo Reviews in `drafts/`.
- Adding an LLM pass to check the question against the topic. The check is
  prompt text; a model asked "did you drift?" agrees with itself.

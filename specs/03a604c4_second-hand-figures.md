# Plan — #142: stop load-bearing figures arriving second-hand

## What the issue is

A draft opened its Introduction with three numbers the writer never saw at
first hand — for example "A meta-analysis cited within a Canadian pilot study
estimated ... 14.4%". The number is real *in the quoting paper*. Whether it is
real in the paper that produced it, nobody checked.

`verify.check_statistics` searches the abstracts and full-text excerpts the
writer was shown. A quoted figure is present in that material, so it verifies.
The check can only ever confirm that the quoting paper printed the number — it
cannot confirm the number. If the quoting paper misquoted, the article repeats
the error carrying a citation that looks checked.

## What we are building — and what we are not

**Prompt-side only.** Do not build nested-reference fetching. No new network
calls, no DOI chasing, no changes to `sources.py`, `verify.py` or `style.py`.

The fix is one new rule in the writer's system prompt, in two halves:

- **(a) Avoidance.** A figure the source itself attributes to another work must
  not carry the `title`, the `abstract`, a `key_points` bullet, or the opening
  claim of the Introduction — whenever any supplied source reports a comparable
  figure at first hand.
- **(b) Honesty when it is unavoidable.** When a second-hand figure is the only
  one available, keep the existing "cited within"-style attribution so the
  reader can see it is second-hand, and cite the source that was actually read.

The house style already produces (b) — the issue says so explicitly. The
instruction must **preserve** that behaviour, not replace it.

**Style checks stay deterministic.** `style.py` is not touched. Nothing here
becomes an LLM judgement, and no rule is added that would need a model to
decide whether a figure is second-hand.

## Files to touch

| File | Change |
|---|---|
| `articlegen/writer.py` | New bullet(s) in `_WRITER_SYSTEM` |
| `tests/test_offline.py` | New test + registration in `main()` |
| `CLAUDE.md` | One row in the pinned-invariant table |
| `docs/decisions.md` | Short entry under "Grounding and provenance" |

Nothing else. No `drafts/`, no `adws/`, no `.github/`.

## 1. `articlegen/writer.py`

### Where the text goes, and why there

Put the new rule in **`_WRITER_SYSTEM`**, inside the existing constrained-by-
your-inputs bullet list — the block that opens `You are working from ABSTRACTS
ONLY ...`. Insert it **directly after** the bullet that begins `ONLY state a
specific number (effect size, %, ...)`, because that bullet already governs
where a figure may come from and this is the same subject one step finer.

Putting it in `_WRITER_SYSTEM` is what makes it reach everywhere for free.
`_REVISE_SYSTEM`, `_REVISE_PATCH_SYSTEM` and all three `*_FULLTEXT` variants
are derived from `_WRITER_SYSTEM` by concatenation or by
`_with_fulltext_framing`. Adding the rule in one place means every system
prompt the writer or the reviser can be handed carries it.

### What must NOT change

- **Do not touch `write_article`'s user prompt (`context`).** The sources block
  stays last. `llm.py`'s claude-cli path appends the format demand after the
  caller's prompt, and `test_claude_cli_provider` asserts the input ends with
  `no YAML.` — nothing may be added at the tail of the user prompt.
- **Do not edit any of the four `_FULLTEXT_SUBSTITUTIONS` targets.** The
  existing test in `test_full_text_grounding` (around line 4185) asserts each
  `old` string is still present in `_WRITER_SYSTEM` and gone from
  `_WRITER_SYSTEM_FULLTEXT`.
- **`_with_fulltext_framing` uses `str.replace`, which replaces every
  occurrence.** So the new text must not contain any of the four `old` strings
  verbatim — in particular not `if that exact figure appears in the abstract
  you are citing`, not `If the abstract doesn't give the number,`, and not
  `FROM ITS ABSTRACT ONLY`. A second copy would be silently rewritten in the
  full-text variants.
- **The new text must stay true under both framings.** Do not write "the
  abstract" as the description of what the writer was given — that sentence
  becomes a lie in `_WRITER_SYSTEM_FULLTEXT`, which is exactly the drift
  `_FULLTEXT_SUBSTITUTIONS` exists to prevent. Write framing-neutral phrasing:
  "the source material you were given for that source", "what you can see of
  that paper".
- **Do not add a substitution pair** unless the wording genuinely forces it.
  Framing-neutral phrasing is cheaper and cannot drift.
- **Do not add or change anything in `_ARTICLE_SCHEMA`.** No new field, no
  changed `description` on `abstract` or `key_points`.
  `test_real_articles_still_match_the_schema` replays recorded payloads against
  it and a new required property would fail every fixture. The rule is
  behavioural guidance, and guidance belongs in the system prompt.
- **Do not relax `_REVISE_PATCH_SYSTEM`'s "every number must be unchanged".**
  The revision pass is a style pass; it may not go hunting for better figures.
  A second-hand figure that reached a draft stays there — the rule works at
  write time.

### Suggested wording

Adjust the prose if you can say it shorter, but keep every element listed
under "Acceptance" below. Two bullets, matching the two halves:

```
- A FIGURE THE SOURCE ITSELF ATTRIBUTES TO ANOTHER WORK IS SECOND-HAND, and it
  may not carry the article. If a source quotes a number from a study or review
  it cites — rather than one it measured, pooled or reported itself — that
  number is only as good as the quotation. The automatic check downstream
  searches the material you were shown, so a quoted figure passes it while
  saying nothing about whether the original paper reported it. So: never build
  the `title`, the `abstract`, a `key_points` bullet, or the opening claim of
  the Introduction on a second-hand figure while any source you were given
  reports a comparable figure at first hand. Look for the first-hand figure
  before reaching for the quoted one, and prefer a source's own result over a
  larger number it is merely repeating.
- WHEN A SECOND-HAND FIGURE IS THE ONLY ONE THERE, use it and say so in the
  prose, as this house style already does: "a meta-analysis cited within a
  pilot study estimated…", "as summarised in [4]". Cite the source you actually
  read — the work it quotes is not in your source list and must never be given
  a SOURCE number of its own. In the body it may sit alongside first-hand
  evidence; it is the abstract, the key points and the opening claim it may not
  carry alone. Where no figure survives that test, give the direction and rough
  magnitude in words instead.
```

Two details worth keeping:

- The **reason** is stated ("the automatic check ... says nothing about whether
  the original paper reported it"). A model given the reason follows a rule
  further than a model given the rule.
- The rule names the **four slots** by their schema keys, so the constraint is
  checkable by eye and the writer knows exactly where it bites. Everywhere else
  in the article a labelled second-hand figure remains fine.

## 2. `tests/test_offline.py`

**A test does apply.** The instruction text is assembled by a function —
`_with_fulltext_framing` builds three of the six system prompts by substitution,
and `_REVISE_SYSTEM` / `_REVISE_PATCH_SYSTEM` build the other two by
concatenation. That derivation is a pure-logic seam and it can silently drop a
rule: someone rewriting a substitution target, or writing a future rule that
happens to contain one, changes what the writer is actually told without
touching the rule.

Add `test_second_hand_figures_are_a_last_resort` next to the other prompt
tests. Use the module's existing `check(label, condition)` helper — same shape
as `test_evidence_assessment_is_wholly_deterministic`, which already asserts on
substrings of `_WRITER_SYSTEM`.

Assert:

1. The rule is in `_WRITER_SYSTEM` — a short, load-bearing substring
   (e.g. `"SECOND-HAND"`), not a paragraph copied out of the prompt. A test
   that restates the whole prompt fails on every wording tweak and teaches
   people to update it without reading it.
2. It names the slots it protects: the block containing the rule mentions
   `abstract`, `key_points` and the Introduction.
3. **It survives every derivation** — the rule substring appears in all of
   `_WRITER_SYSTEM_FULLTEXT`, `_REVISE_SYSTEM`, `_REVISE_SYSTEM_FULLTEXT`,
   `_REVISE_PATCH_SYSTEM` and `_REVISE_PATCH_SYSTEM_FULLTEXT`. This is the
   assertion that actually earns the test.
4. **No substitution target appears twice in `_WRITER_SYSTEM`** —
   `for old, _ in writer._FULLTEXT_SUBSTITUTIONS: check(..., writer._WRITER_SYSTEM.count(old) == 1)`.
   `str.replace` rewrites every occurrence, so a second copy anywhere in the
   prompt is rewritten out of sight. Complements the existing loop in
   `test_full_text_grounding`, which only checks presence.
5. The second half survives: the "cited within"-style attribution is still
   asked for, so the fix cannot be read as "drop second-hand figures". Assert
   on the attribution phrasing the rule mandates (e.g. `"cited within"`).

Write a docstring in the file's house style: what broke (a draft opened on
three quoted figures), why the check could not catch it, what the test pins.

**Register the test** in the tuple inside `main()` — tests are listed
explicitly, so an unregistered test never runs. Put it near
`test_full_text_grounding`.

## 3. `CLAUDE.md`

`.github/workflows/docs-current.yml` fails a PR touching `articlegen/**`
without touching `CLAUDE.md`, and `test_claude_md_still_describes_this_code`
checks every backticked test name in it resolves to a real `def`.

Add one row to the **"Pinned by a test"** table in *Invariants*, after the
preprint row:

```
| A load-bearing figure is not quoted at second hand when a first-hand one exists | `test_second_hand_figures_are_a_last_resort` |
```

Nothing else. The file's own convention is that a pinned invariant names its
test and stops — the test is the specification. Do not add a prose bullet
restating the rule; that is what goes stale.

## 4. `docs/decisions.md`

Add a short entry under the existing **"Grounding and provenance"** heading,
matching the surrounding style (a `### ` heading, the observation, the
measurement or example, the decision, the issue number). Cover:

- The three figures from the drafts run of 2026-08-15 (14.4% / 15.8% / 25.6%
  restraint-seclusion prevalence; 25–47% PTSD; the Cochrane-within-a-realist-
  review case).
- Why `verify.check_statistics` cannot help: it searches the abstracts and
  excerpts the writer was shown, and the quoted figure is genuinely in there.
  Confirming a quotation is not confirming a number.
- Why the fix is prompt-side: chasing the nested reference means resolving a
  DOI mentioned inside a body of text and fetching it — a new fetch path, new
  failure modes, and no guarantee the nested work is open access. Deliberately
  out of scope; the issue lists it as the other option and it stays available.
- What was chosen: avoidance in the four load-bearing slots when a first-hand
  alternative exists, honest attribution everywhere else. Not exclusion — a
  labelled second-hand figure in the body is still useful evidence and the
  house style already labels it.
- Note that this is a prompt-side rule with no deterministic enforcement, so it
  is a tendency, not a guarantee. Say so plainly. Anyone reading a future draft
  that still opens on a quoted figure should know the fix was probabilistic.
- Refs #142.

## Verification

Run both suites from the repo root; judge them by exit status:

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must print `ALL PASS`. `test_journal_conformance.py` is expected to be
untouched by this change (no render or layout change) — run it anyway, it is
the ground rule.

Specifically confirm these do not regress:

- `test_full_text_grounding` — the substitution targets still resolve.
- `test_claude_cli_provider` — the argv ceiling and the format-demand-last
  assertion. `_WRITER_SYSTEM` grows by a few hundred characters; it travels on
  stdin, not argv, so the 2,000-char argv assertion is unaffected. Confirm it.
- `test_claude_md_still_describes_this_code` — the new test name in `CLAUDE.md`
  resolves.
- `test_evidence_assessment_is_wholly_deterministic` and
  `test_house_style_is_fixed_not_a_preference` — both assert on
  `_WRITER_SYSTEM` substrings that must survive the insertion.
- `test_real_articles_still_match_the_schema` — unchanged, because the schema
  is unchanged.

No live smoke run is needed: no model id, ceiling, routing or `sources.py`
change. The system prompt grows, which is a prompt-content change, not a seam
change.

## Acceptance

- [ ] `_WRITER_SYSTEM` states that a figure a source attributes to another work
      is second-hand.
- [ ] It bars a second-hand figure from `title`, `abstract`, `key_points` and
      the Introduction's opening claim **when a first-hand alternative exists in
      the supplied sources**.
- [ ] It preserves the "cited within"-style attribution for the cases where a
      second-hand figure is still used.
- [ ] It tells the model *why* — the downstream check confirms the quotation,
      not the number.
- [ ] The rule reads true in both the abstracts-only and full-text framings.
- [ ] No `_FULLTEXT_SUBSTITUTIONS` target is duplicated or altered.
- [ ] `write_article`'s user prompt is unchanged; the sources block is still
      last.
- [ ] `style.py`, `verify.py`, `sources.py`, `render.py` and `_ARTICLE_SCHEMA`
      are untouched.
- [ ] `test_second_hand_figures_are_a_last_resort` exists and is registered in
      `main()`.
- [ ] `CLAUDE.md` names it in the pinned-invariant table.
- [ ] `docs/decisions.md` carries the story.
- [ ] Both test suites exit 0.

## Commit message

```
Tell the writer not to build the abstract, key points or opening claim on a figure its source only quotes from another paper, so load-bearing numbers are ones we can actually check. Fixes #142
```

Never write the phrase "does not close" anywhere in the commit or PR body —
GitHub's parser ignores the negation and closes the issue.

## Git

Do not run any state-changing git command. No branch, checkout, commit, push,
merge, rebase, stash or reset. Leave the working tree; the workflow commits it
after the tests pass.

# Plan — statistics check: titles in the haystack, no split ranges, one revision pass (#189)

## What this is

Three changes to the deterministic statistics check and one new pipeline stage.

1. `verify._paper_haystack` also searches the paper's **title**. A figure that
   appears only in a title is grounded, and the writer *was* shown that title
   (`writer._format_sources` prints `Title:` above every abstract), so this does
   not weaken the "search exactly what the writer was shown" invariant.
2. `verify._FIGURE_RE` treats `4.4-5.2` as **one** figure. Today the alternation
   matches `4.4`, then restarts at the hyphen and matches `-5.2` as a negative
   number that no source contains, so a real confidence interval reliably prints
   a ‡ on its second half.
3. A new `pipeline.enforce_statistics` runs **one** revision pass when
   `unverified + misattributed > 0` after the first write. The model is asked to
   drop the figure, put it in words, or move/remove the citation. No new numbers,
   no new sources — and that is enforced deterministically, not just asked for.

Measured behaviour that motivates it (four Grok 4.6 briefings, 21 Aug 2026):
3 of 4 were branded "working draft" on a pile of ‡ marks, and the hyphenated
range split recurred. One briefing came back 0/0, which is the case that must
still cost zero extra calls.

## Out of scope — do not do these

- Ignoring `95%` inside `95% CI`. It did not recur this batch. Follow-up if it does.
- Asking the model to guess a new source or a replacement number.
- Raising `FULLTEXT_TARGET`, fetching paywalled full text.
- Changing the default model (#85), putting `--long` on the web UI, regenerating
  the public demo Reviews in `drafts/`.
- Changing the shape of `check_statistics`' existing return keys. `render.py`,
  `Draft.summary()` and the conformance fixtures all read `unverified`,
  `misattributed` and `total` as they are. Add keys, never rename them.

---

## Change 1 — `articlegen/verify.py`: titles in the haystack

`_paper_haystack` currently joins the abstract and (when present) the full-text
excerpt. Add the title first:

```python
def _paper_haystack(paper: Paper, full_texts: dict[int, str], idx: int) -> str:
    # The title is part of what the writer was shown -- `writer._format_sources`
    # prints it above every abstract -- and it is where a headline effect size
    # often lives ("...reduces seclusion by 37%: a cluster RCT"). Leaving it out
    # printed a dagger on a figure the source states in its own title (#189).
    parts = [paper.title or "", paper.abstract or ""]
    if idx in full_texts:
        parts.append(full_texts[idx])
    return " ".join(parts)
```

Also update the module docstring paragraph that says "The haystack is exactly
what the writer was shown" so it names title + abstract + excerpt. It is still
true; make it say so explicitly.

## Change 2 — `articlegen/verify.py`: a hyphenated range is one figure

### Why the split happens

`_FIGURE_RE`'s first alternative is `-?\d+\.\d+%?`. Scanning `4.4-5.2` matches
`4.4`, resumes at the `-`, and matches `-5.2`. The second token is not a
quantity the article asserts — it is the tail of a range with the range's own
hyphen glued to the front — and no source contains the string `-5.2`, so it is
flagged every time.

### The fix

Add a **range alternative, first in the alternation**, that swallows the whole
range in one match, and check it endpoint-by-endpoint.

```python
# A hyphenated range is ONE quantity. Scanning "4.4-5.2" with the plain decimal
# alternative alone matched "4.4" and then "-5.2" -- a negative number the
# article never asserted and no source contains, so a real confidence interval
# printed a flag on its own second half (#189). This alternative is first in the
# alternation so it wins at the position where the range starts; `_found` then
# requires BOTH endpoints, which keeps the check strict about presence while
# staying generous about form (a source writing "4.4 to 5.2" still verifies).
_RANGE_RE_SRC = r"(?P<range>-?\d+\.\d+%?\s*[-–—]\s*-?\d+\.\d+%?)"

_FIGURE_RE = re.compile(
    _RANGE_RE_SRC
    + r"|-?\d+\.\d+%?"
    + r"|\b\d{1,3}%"
    ...   # the rest unchanged, in the same order
    , re.IGNORECASE,
)
```

Then in `check_statistics`, pass the range flag through to `_found`, and in
`_found` handle it:

```python
def _range_parts(figure: str) -> list[str]:
    """The two endpoints of a hyphenated range, sign restored on each."""
    ...
```

Rules for `_found` when the match is a range:

- Split on the internal `-`/`–`/`—` **that separates the two decimals**, not on
  a leading minus sign. `-0.38--0.12` must split into `-0.38` and `-0.12`, not
  into `-0.38`, `` and `-0.12`. A regex-based split is safest, e.g. re-match the
  token with `^(?P<lo>-?\d+\.\d+%?)\s*[-–—]\s*(?P<hi>-?\d+\.\d+%?)$`.
- The range verifies only if **both** endpoints are found, each by the existing
  non-quantity path (`norm in raw` / `norm.replace(" ","") in nospace`).
- Verify each endpoint both with and without its sign is *not* needed — the
  existing `_normalize` already strips a leading `-`, so `-0.12` and `0.12`
  compare the same way they do today. Keep that behaviour, do not tighten it.

Consequences the builder must respect:

- The reported figure string is the **whole range** (`match.group(0)`), so it
  counts once in `total`, appears once in `unverified`/`misattributed`, and
  `render._flag_pattern` marks the whole range inline. `_flag_pattern` escapes
  its alternatives, so a token containing a hyphen needs no render change —
  confirm this by eye, do not change `render.py`.
- The misattribution branch is unchanged: a range not found in the cited
  sources but found across everything is `misattributed`.
- `12%-18%`, `12-18%`, `25-30 mg` and `2.5-fold` are all unaffected — the range
  alternative requires a decimal on both sides. Do not widen it to integers in
  this change; an integer range has no split bug because bare integers are not
  extracted at all.

## Change 3 — `articlegen/verify.py`: a brief the writer can act on

`check_statistics` returns lists of figure strings, which is not enough to write
a revision brief — the model needs the sentence each flag came from. Add an
**additive** key, leaving the three existing ones byte-identical:

```python
    return {
        "unverified": unverified,
        "misattributed": misattributed,
        "total": total,
        # Additive, for the revision pass only. Renderers and older drafts read
        # the three lists above and must keep working untouched.
        "details": details,   # [{"figure": str, "kind": "unverified"|"misattributed",
                              #   "sentence": str, "cited": [int, ...]}]
    }
```

And a deterministic brief builder next to it — the same division of labour as
`style.revision_brief` living in `style.py`:

```python
def revision_brief(verification: dict) -> str:
    """What to send back to the writer when figures did not check out.

    Deterministic string building, no LLM. Three fixes are allowed and they are
    named explicitly, because the fourth one -- inventing a source or a number
    that would make the sentence true -- is the failure this pass could
    otherwise cause.
    """
```

The brief must:

- List each flagged figure, its kind, and quote the sentence it appears in.
- State the three permitted fixes, in order: **delete the figure and keep the
  claim in words**; **restate the quantity qualitatively** ("a moderate
  reduction"); **for a misattributed figure, move the citation to the source
  that actually reports it, or drop the figure**.
- State the prohibitions outright: introduce no number that is not already in
  the draft, add no source, do not "correct" a figure to a value you believe is
  right, change no other block.
- Say nothing about style. This pass is not a style pass.

Name this function `revision_brief` in `verify.py` (same name as `style.py`'s —
they are imported into `pipeline.py` under distinct aliases; see below).

## Change 4 — `articlegen/writer.py`: `revise_statistics`

Mirror `revise_prose`, but simpler: **patch only, no whole-article rewrite, no
sources in the payload.** There is nothing to add, so sending 40 abstracts and
60,000 characters of full text would be input the model is forbidden to use and
can only be distracted by.

```python
_REVISE_FIGURES_PATCH_SYSTEM = _WRITER_SYSTEM + """

You are now REVISING an existing draft rather than writing a new one, and you \
return ONLY the blocks you changed -- not the whole article.

A deterministic check could not find some of the numbers this draft reports in \
the material the draft was written from. Your ONLY job is to make each flagged \
sentence honest. For each one, do exactly one of: delete the number and keep the \
claim in words; restate the quantity qualitatively; or, when the number is real \
but credited to the wrong source, move the citation to the source that reports \
it -- and if you are not certain which source that is, delete the number instead.

You MUST NOT introduce any number that is not already in the draft, add a \
source, or "correct" a figure to a value you believe is right. Leave every block \
the brief does not name out of your reply entirely; anything you omit is kept \
exactly as it is. Every other "[N]" citation marker must survive exactly as it \
is and stay attached to the same claim.
"""

_REVISE_BRIEFING_FIGURES_PATCH_SYSTEM = _BRIEFING_SYSTEM + """ ...same body... """
```

```python
def revise_statistics(
    article: dict,
    brief: str,
    model: str | None = None,
    api_key: str | None = None,
) -> dict:
```

- Reuse `_REVISION_SCHEMA` and `apply_revisions` unchanged.
- Pick the briefing system prompt when `is_briefing(article)`.
- No full-text framing variants: nothing is sent, so the abstracts-only framing
  in the base prompt stays accurate. Do **not** add these two prompts to
  `_FULLTEXT_SUBSTITUTIONS`' test sweep expectations.
- Same `deep=True`.
- Same no-op guard as `revise_prose`: if `apply_revisions` applied nothing,
  raise `RuntimeError` with the count of edits offered. The caller catches it.

## Change 5 — `articlegen/pipeline.py`: `enforce_statistics`

```python
# How many times a draft's figures may go back to the model. One, not two: this
# pass removes or rewords, it never researches, so a figure the model could not
# fix on the first attempt it cannot fix on the second either (#189).
MAX_STATISTIC_PASSES = 1


def enforce_statistics(
    article: dict,
    papers: list[Paper],
    model: str | None = None,
    api_key: str | None = None,
    log: Logger = _silent,
    style_report: dict | None = None,
    direct_sources: int | None = None,
) -> tuple[dict, dict, dict]:
    """Check the figures and, if any missed, ask once for them to be removed.

    Returns (article, verification, style_report) -- all three describing the
    article that actually ships.
    """
```

Sequence, mirroring `enforce_style`:

1. `verification = check_statistics(article, papers)`.
2. `flagged = len(unverified) + len(misattributed)`. If `flagged == 0`:
   `log("Statistics: every figure checked out.")` and return the article,
   verification and the style report **untouched, with no LLM call**. This is the
   organic-style 0/0 case, and it must cost nothing.
3. Otherwise log the count and `revising (pass 1 of MAX_STATISTIC_PASSES)`, call
   `revise_statistics(article, statistics_brief(verification), ...)` inside
   `try/except Exception` — on failure log `revision failed (…); keeping the
   draft as it stands.` and return the originals. A failed figures pass must
   never lose the draft.
4. Re-check the revision: `revised_v = check_statistics(revised, papers)`.
5. Accept only if **all three** hold:
   - **intact** — same test `enforce_style` uses: `references` count not
     reduced, and (briefing) `findings` count not reduced / (Review) `sections`
     count equal.
   - **fewer flags** — `revised_flagged < flagged`, strictly.
   - **no new numbers** — `revised_v["total"] <= verification["total"]`. This is
     the deterministic half of "no new numbers": a fix that deletes or rewords a
     figure lowers the total, moving a citation leaves it equal, and inventing
     one raises it. Reject on `>`, and log which of the three rules refused it.
6. On acceptance: `log(f"  revised: {flagged} -> {revised_flagged} flagged
   figure(s).")`, and **recompute the style report** —
   `style_report = check_style(article, direct_sources=direct_sources)` — because
   the prose just changed and `render._working_draft_sentence` brands the page
   from that report. A stale report is a claim about text that is no longer
   there. This is a recompute only; it never buys another prose revision.
7. Return `(article, verification, style_report)`.

### Wiring in `generate_draft`

`verify.revision_brief` and `style.revision_brief` share a name, so import it
aliased at the top of `pipeline.py`:

```python
from .verify import check_statistics, revision_brief as statistics_brief
from .writer import (..., revise_statistics, ...)
```

Replace the single line `verification = check_statistics(article, papers)` with:

```python
    article, verification, style_report = enforce_statistics(
        article, papers, model=model, api_key=api_key, log=log,
        style_report=style_report,
        direct_sources=((curation or {}).get("counts") or {}).get("direct"),
    )
```

It stays **after** `enforce_style` and before `provenance` is built. Order
matters: style first (it may rewrite prose and so change which figures exist),
figures second, and nothing after them re-runs the writer.

`Draft.summary()` needs no change — it reads the post-revision `verification`.

---

## Tests — `tests/test_offline.py`

### Extend `test_statistic_verification` (existing; already cited in CLAUDE.md)

Add, in the same style as the existing blocks:

- **Title-only figure.** `Paper(title="Seclusion fell 37% after the intervention",
  abstract="No numbers here.")`, article sentence `"Seclusion fell 37% [1]."` →
  `"37%" not in v["unverified"]` and not in `v["misattributed"]`.
- **Hyphenated range, grounded.** Source abstract contains `"the interval was
  4.4-5.2"`; article says `"the interval was 4.4-5.2 [1]"` → nothing flagged,
  and `v["total"] == 1` for that sentence (one quantity, not two).
- **Hyphenated range, absent.** Source contains neither endpoint; article says
  `"9.1-9.8 [1]"` → `"9.1-9.8" in v["unverified"]`, and assert that neither
  `"-9.8"` nor `"9.8"` appears in the list on its own — that string is the bug.
- **Range written differently in the source.** Source abstract says `"from 4.4 to
  5.2"`, article says `"4.4-5.2 [1]"` → not flagged. This pins the
  endpoint-wise check rather than a raw substring match.
- **Negative range.** Source has `"-0.38 to -0.12"`, article has `"-0.38--0.12
  [1]"` → not flagged. This is the split-on-the-right-hyphen case.
- **En-dash range.** Article `"4.4–5.2 [1]"` against a source writing
  `"4.4-5.2"` → not flagged.

### New `test_flagged_figures_buy_one_revision`

Follow the `enforce_style` test's monkeypatch pattern (save
`pipeline.revise_statistics` / `pipeline.check_statistics`, restore in
`finally`). Assert:

1. **Clean first write buys nothing.** `check_statistics` stubbed to return
   `{"unverified": [], "misattributed": [], "total": 4, "details": []}` →
   `revise_statistics` is never called, and the returned article is the same
   object.
2. **Flags buy exactly one call.** Stub returns two flags every time; assert the
   revise stub was called once, not `MAX_STATISTIC_PASSES + 1` times, and that
   `MAX_STATISTIC_PASSES == 1`.
3. **A revision that adds a number is refused.** Stub the re-check to return
   fewer flags but a larger `total` → the original article is returned and the
   log mentions why.
4. **A revision that fixes flags is accepted**, and the returned `style_report`
   is the recomputed one (stub `pipeline.check_style` to return a marker report
   and assert it comes back).
5. **A raising `revise_statistics` keeps the draft** and returns the original
   verification.
6. **The brief names the three fixes and forbids new numbers.** Call
   `verify.revision_brief` on a verification with one unverified and one
   misattributed figure and assert both figures, both sentences, the word
   "delete"/"remove", and an explicit prohibition on new numbers appear in it.

Register both tests in `main()`'s tuple (`test_flagged_figures_buy_one_revision`
is new; `test_statistic_verification` is already there).

### Both suites must pass

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

The conformance suite renders five fixtures; if a fixture happens to contain a
hyphenated range, its flag list changes shape (one token instead of two). If a
conformance assertion counts flags, update the fixture expectation — do not
weaken the check.

---

## Docs

### `CLAUDE.md` (required — `.github/workflows/docs-current.yml` fails the PR without it)

Add three rows to the invariant table:

| A figure stated in a paper's title is grounded | `test_statistic_verification` |
| A hyphenated range is one figure, not two | `test_statistic_verification` |
| Flagged figures buy one revision, a clean draft buys none | `test_flagged_figures_buy_one_revision` |

Add to the `pipeline.generate_draft()` stage list in **Architecture**:
`… → `check_statistics` → `enforce_statistics` (one `revise_statistics` pass
when figures are flagged)`.

Add a short block under the not-pinned-by-a-test bullets in **Invariants** or
alongside the style-enforcement section:

- The figures pass **removes, it never researches.** `MAX_STATISTIC_PASSES` is 1
  and the accepted revision must satisfy three deterministic rules — intact,
  strictly fewer flags, and `total` not increased. The third one is what stops
  the model "fixing" a flag by inventing a number that would make the sentence
  true, which is the exact failure this pass could otherwise cause.
- An accepted figures revision **recomputes the style report**, because
  `render._working_draft_sentence` brands the page from it and the prose just
  changed. Recompute only — it never buys another prose pass.
- The statistics haystack is **title + abstract + shown excerpt**, in step with
  `writer._format_sources`, which prints all three. If one side gains a field
  the other must too, or verification starts checking text the writer never saw.

Every constant and test name written into CLAUDE.md must exist —
`test_claude_md_still_describes_this_code` sweeps both files.

### `docs/decisions.md`

Add the story: the 21 Aug 2026 Grok 4.6 batch, 3 of 4 branded working-draft on a
‡ pile, organic 0/0, the recurring `4.4-5.2` split, and why the pass is capped at
one and forbidden from adding numbers. Note that `95% CI` noise did **not**
recur and is deliberately left alone.

---

## Verify it works

```
python tests/test_offline.py            # exit 0
python tests/test_journal_conformance.py # exit 0
```

Judge both by exit status, not by grepping the output — these suites print the
word "unverified" constantly in passing runs.

Optional, spends credit, only if a key is set: `articlegen draft "seclusion and
restraint reduction in adult acute mental health units"` and read the log for
the new `Statistics:` lines. Not required for the PR.

## Ship it

Branch off `main`, one commit per change is fine, push, `gh pr create`. The PR
body must touch CLAUDE.md (it does) so the docs gate passes. Reference the issue
as **"Refs #189, stays open"** — never write "does not close #189"; GitHub's
parser ignores the negation and closes it.

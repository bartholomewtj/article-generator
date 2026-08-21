# Plan — stop branding leftover style nits as "a working draft" (issue #169)

## What the problem is

Four of the five shipped drafts in `drafts/` end their Limitations paragraph with:

> An automated check of the writing against journal prose conventions was not
> satisfied by this draft: it reuses phrasing between sections. A revision was
> attempted and did not resolve this, so the text below should be read as a
> working draft rather than a finished review.

The trigger in three of them is `recycled-phrasing`, in one `repeated-opener`.
Both are prose nits. The reader who forwards the briefing forwards a claim that
the page is unfinished, for a leftover six-word n-gram.

`render._style_failure_sentence` (articlegen/render.py:1021) currently prints for
**any** style issue with `severity == "error"`. That is the whole bug.

## What "done" is

The "working draft rather than a finished review" wording prints only when
something changes whether the page can be sent:

- `clinical-directive` survived the revision, or
- a substance rule survived the revision — **except** `recycled-phrasing` and
  `repeated-opener` (and `under-length`, which is a warning and never reached
  this code anyway), or
- the statistics check left residual `unverified` / `misattributed` figures.

`recycled-phrasing` and `repeated-opener` keep firing, keep buying a revision
pass, keep appearing in the CLI log (`style.format_report`, printed
unconditionally at articlegen/pipeline.py:322) and in `draft.style_report` and
`Draft.summary()`. They just say nothing in the rendered page.

Both suites green:
```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

## Files to touch

1. `articlegen/render.py`
2. `tests/test_offline.py`
3. `tests/test_journal_conformance.py`
4. `CLAUDE.md`

Nothing else. In particular: do not touch `articlegen/style.py` (no rule is
deleted, downgraded, or exempted from the revision pass), do not regenerate
`drafts/`, do not touch `docs/decisions.md` (the reasoning is short enough to
live in CLAUDE.md, and the file set above is the agreed scope).

---

## 1. `articlegen/render.py`

### 1a. Import the substance-rule set

`render.py` does not import `style` today. `style.py` imports only stdlib, so
there is no cycle. Add beside the existing `from .sources import Paper`:

```python
from .style import SUBSTANCE_RULES
```

### 1b. New constant, next to `_STYLE_FAILURE_WORDING`

```python
# Style errors that change whether this page can be sent, as against prose nits
# a reader would never notice. Only these reach the article; every rule still
# fires, still buys a revision pass, and still prints in the CLI log and in
# `style_report` (#169).
#
# Derived from SUBSTANCE_RULES with the two exemptions named, so a *new*
# substance rule brands the page by default — the safe direction — while the
# two that were branding four of five shipped drafts are listed where the
# reason for exempting them is readable. `under-length` is severity 'warning',
# so it never reaches this code; it is named anyway so that a future promotion
# to error does not silently start branding pages on a length count.
SENDABLE_BLOCKING_RULES = frozenset({"clinical-directive"}) | (
    SUBSTANCE_RULES - {"recycled-phrasing", "repeated-opener", "under-length"}
)
```

That resolves to: `clinical-directive`, `too-few-sections`, `hedge-monotony`,
`echoed-abstract`, `bundled-citations`.

Deliberately **not** included: the register errors (`second-person`,
`contraction`, `rhetorical-question`, `exclamation`, `booster`, `overclaim`,
`first-person`, `under-hedged`). Issue #169's list is the specification, and a
register slip does not change whether the page can be sent. Do not widen the
set beyond the issue without a new issue saying so.

### 1c. Filter `_style_failure_sentence`, and split the branding clause out

Change the failure filter from "every error" to "every blocking error", and end
the sentence at the revision attempt — the branding clause moves to its own
sentence so the figure case can use it too:

```python
def _style_failure_sentence(style_report: dict | None, esc=lambda s: s) -> str:
    """State, in the article, that the prose check still objected — when it matters.

    A draft that failed the style gate used to be indistinguishable from one that
    passed (issue #53). It then went too far the other way: four of five shipped
    drafts carried this line over a repeated sentence opener or a recycled
    six-word phrase (#169). Only SENDABLE_BLOCKING_RULES reach the reader now.
    """
    failures = [
        i for i in (style_report or {}).get("issues", [])
        if i.get("severity") == "error" and i.get("rule") in SENDABLE_BLOCKING_RULES
    ]
    if not failures:
        return ""
    ...                       # dedupe-by-rule and the faults joining: unchanged
    return (
        "An automated check of the writing against journal prose conventions was "
        f"not satisfied by this draft: it {esc(faults)}. A revision was attempted "
        "and did not resolve this."
    )
```

### 1d. New `_working_draft_sentence`

```python
def _working_draft_sentence(style_report: dict | None, verification: dict | None) -> str:
    """The one sentence that tells a reader not to send this page as it stands.

    Printed for defects that change whether the page can be sent: a surviving
    clinical directive, a substance failure a revision did not clear, or a
    figure the statistics check could not place. Never for a prose nit (#169).
    It always follows a sentence that has just named the defect, hence
    "therefore".
    """
    blocking = any(
        i.get("severity") == "error" and i.get("rule") in SENDABLE_BLOCKING_RULES
        for i in (style_report or {}).get("issues", [])
    )
    figures = bool((verification or {}).get("unverified")
                   or (verification or {}).get("misattributed"))
    if not (blocking or figures):
        return ""
    return (
        "The text below should therefore be read as a working draft rather than "
        "a finished review."
    )
```

### 1e. Wire it into `_assessment_paragraphs`

At articlegen/render.py:993, keep the existing style sentence and append the new
one last, so the paragraph runs: full-text/abstract caveat → no-direct-source →
unverified → misattributed → style failure → working-draft verdict.

```python
    surviving = _style_failure_sentence(style_report, esc)
    if surviving:
        limitations.append(surviving)
    verdict = _working_draft_sentence(style_report, verification)
    if verdict:
        limitations.append(verdict)
    return {"opening": opening, "limitations": limitations}
```

No signature changes are needed: `_assessment_paragraphs` already takes both
`verification` and `style_report`, and both the HTML (`_assessment_html`) and
Markdown (`_assessment_markdown`) renderers go through it. `esc` is not applied
to the verdict sentence because it contains no interpolated text.

Leave `_STYLE_FAILURE_WORDING` intact — every entry stays, including the two
exempt rules, so promoting a rule back into the set needs no second edit.

---

## 2. `tests/test_offline.py`

Add one test, named exactly:

```python
def test_only_sendable_defects_brand_the_page() -> None:
```

CLAUDE.md will cite this name, and `test_claude_md_still_describes_this_code`
checks the name exists — so do not rename it without editing CLAUDE.md too.

What it must assert, all through `render._assessment_paragraphs` (cheaper and
more direct than rendering a whole page; pass a couple of `Paper` objects, an
empty `counts` dict is fine):

1. **Nits do not brand.** A `style_report` whose only errors are
   `recycled-phrasing` and `repeated-opener` produces limitations containing
   neither `"working draft"` nor `"journal prose conventions"`.
2. **A clinical directive brands.** A report with a `clinical-directive` error
   produces both the prose-check sentence (`"instructs the reader on treatment"`)
   and `"working draft rather than a finished review"`.
3. **A surviving substance failure brands.** Same with `too-few-sections`.
4. **A mixed report names only the blocking fault.** `clinical-directive` +
   `recycled-phrasing` together → the sentence names the directive and does
   **not** contain `"reuses phrasing between sections"`.
5. **Residual figures brand, with no style errors at all.** `style_report`
   with no errors, `verification={"unverified": ["42%"]}` → the unverified
   sentence is still there *and* the working-draft sentence prints. Same for
   `{"misattributed": ["18%"]}`.
6. **A clean draft says nothing.** No style errors, `verification={"unverified":
   [], "misattributed": []}` → neither string appears anywhere in the
   limitations.
7. **`under-length` stays out.** It is severity `"warning"`, so a report
   carrying it as a warning brands nothing — assert that, and assert
   `"under-length" in style.SUBSTANCE_RULES` so the exemption in
   `SENDABLE_BLOCKING_RULES` is still subtracting a name that exists.
8. **The exemptions are still real names.** `{"recycled-phrasing",
   "repeated-opener", "under-length"} <= style.SUBSTANCE_RULES`, and neither of
   the first two is in `render.SENDABLE_BLOCKING_RULES`. Without this, renaming
   a rule in `style.py` would silently re-brand every draft.
9. **The rules still fire and still buy a revision.** Nothing in `style.py`
   changed: assert `"recycled-phrasing" in style.SUBSTANCE_RULES` and that
   `style.revision_brief` on a recycled-phrasing report still asks for the fix
   (the brief text contains the rule's `detail`). This is the guard against a
   future session "simplifying" by deleting the rule.

Register the test in whatever list/`main()` the suite uses to run tests — copy
the pattern from a neighbouring test; each test is wrapped so one crash does not
abort the rest.

Also check whether any existing test asserts the old sentence text end-to-end
(`grep -n "working draft" tests/test_offline.py`). At the time of planning the
only hit is a docstring in `test_a_second_style_pass_runs_only_after_progress`
describing why a residual error matters. That docstring is now half-wrong —
a residual *nit* no longer prints anything. Edit the docstring (not the
assertions) to say the residual is what a second pass is sized for, and that
whether it reaches the page is `SENDABLE_BLOCKING_RULES`' business.

---

## 3. `tests/test_journal_conformance.py`

The fixture loop calls `render_article(...)` with no `style_report`, so the
`CONVENTIONS` list cannot see this behaviour. Add a small dedicated block rather
than bending the convention predicates:

- A function, e.g. `_check_sendable_branding()`, that takes the first fixture's
  `(article, papers, curation, provenance, topic)` and renders it three ways:
  - nits-only style report + clean verification → the rendered HTML contains
    **no** `"working draft rather than a finished review"`;
  - `clinical-directive` style report → it does contain it;
  - clean style report + `{"unverified": ["4.91"]}` → it does contain it.
- Append failures to `FAILURES` with the same `f"{name}: {convention}"` shape
  the loop uses, and print `OK  `/`FAIL ` lines the same way, so the output
  reads as one suite.
- Call it from `main()` after the fixture loop, before the summary print.

Note the existing fixture "many authors, clinical topic" carries
`{"unverified": ["-0.90", "4.91", "12.5"]}`. It renders without a style report,
so under the new code it now prints the working-draft sentence off the figures
alone. That is correct and no convention asserts against it — but re-read the
`FAIL` lines after the first run rather than assuming.

---

## 4. `CLAUDE.md`

Two edits. (The `docs-current.yml` gate requires a CLAUDE.md change on any PR
touching `articlegen/**`, so this is not optional.)

1. **Invariant table** — add a row under "Prose style"/invariants:

   | Only sendable-blocking defects brand the page a working draft | `test_only_sendable_defects_brand_the_page` |

2. **"Prose style (enforced, not prompted)" section** — add a bullet:

   - **A leftover nit is not a "working draft".** The Limitations sentence
     saying the text "should be read as a working draft rather than a finished
     review" prints only for `SENDABLE_BLOCKING_RULES` — `clinical-directive`
     plus the substance rules except `recycled-phrasing`, `repeated-opener` and
     `under-length` — or for residual unverified/misattributed figures. Four of
     five shipped drafts wore that sentence over a recycled six-word phrase or a
     repeated sentence opener, so a reader forwarding the briefing forwarded a
     claim that the prose was unfinished (#169). The exempt rules still fire,
     still buy a revision pass, and still print in the CLI log and
     `style_report` — they just do not brand the page.

   While editing that section, fix the existing line that says a single residual
   error "is enough to print the 'working draft rather than a finished review'
   line in Limitations (#146)" — that is now true only for a blocking rule.

`test_claude_md_still_describes_this_code` will check both the test name and the
`SENDABLE_BLOCKING_RULES` constant exist in source. They will, if the names above
are used verbatim.

---

## Verify

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Judge both by exit status, not by scanning output text.

Optional sanity read, no API cost:

```
python -c "from articlegen import demo, render; print(render.render_markdown(demo.SAMPLE_ARTICLE, [], 'demo')[:0] or 'ok')"
```
— or simply run `articlegen demo` and confirm the Limitations paragraph of the
generated page carries no working-draft sentence (the sample article is clean by
invariant).

## Out of scope

- Deleting or downgrading `recycled-phrasing` / `repeated-opener`.
- Letting either rule skip the revision pass.
- Regenerating anything in `drafts/` (the four shipped drafts keep their
  sentence; the next run of each topic will not).
- Putting `--long` on the web UI.
- Widening the blocking set to register errors such as `overclaim` or
  `under-hedged` — considered and left out; #169's list is the specification.

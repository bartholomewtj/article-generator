# Next session

_Last handoff: 7 August 2026 — branch `main`_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article and grounded in real paper abstracts and, where
available, open-access full texts. It runs as a CLI and as a hosted web app
(GitHub Pages front end → Render backend).

6 August closed out all three quality issues from the last handoff:

- **#63 (abstract echoed as Introduction) — verdict: the model, not the
  pipeline.** The single-variable test (PR #66) reran the same topic with
  `anthropic/claude-sonnet-5`; the echo vanished. Fable is now the Anthropic
  default (PR #68).
- **#64 (20 sources screened, 3 cited) — same root cause.** The writer prompt
  now says to cite `related` sources too (PR #68). On the sonnet test run, 12
  of 20 screened sources were cited and the body ran 1,661 words — against a
  471-word stub on Llama. One confirming run on a second topic would be nice
  but wasn't required to close it.
- **#62 (corporate authors mangled)** — fixed; consortium names pass through
  unsplit (PR #69).

Then two bigger merges: **full-text grounding** (PR #72 — direct/related
sources with open-access full text get excerpt-level grounding, not just
abstracts) and an **article layout rearrange** (PR #73 — Table 1 to back
matter, key points before Conclusions).

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints `ALL PASS` / `ALL CONVENTIONS MET`. No keys, no network.

Backend check (reports the commit and branch it built):

```bash
curl https://articlegen-api.onrender.com/api/health
```

## What happened later on 7 August

A live article was generated from the web app and read. It ran on Llama (the
old OpenRouter default) and reproduced the known defects exactly: a stub body
of two-sentence sections with the Introduction restating the abstract. Two
things came out of reading it:

- **PR #74 — OpenRouter now defaults to `anthropic/claude-fable-5`.** The
  #63/#64 verdict was that the writer was the problem, so the default follows
  the quality. Costs roughly $1–2 per article instead of a fraction of a cent;
  `--model meta-llama/llama-3.3-70b-instruct` is still there for cheap runs.
- **#75 / PR #76 — the article contradicted itself about what it had read.**
  Methods said 7 full texts were retrieved; Limitations said "prepared from
  abstracts alone", under an "Abstract-derived synthesis" masthead. Five
  statements were hardcoded to abstracts-only wording while only Methods
  branched on provenance. All now count the cited papers, the same data Table
  1 renders from.

Two things that reading confirmed are working: **all 20 screened sources were
cited** (#64's collapse is gone), and the style gate detected the thin prose,
attempted a revision, failed, and said so plainly in Limitations rather than
shipping quietly.

## The Opus 5 article — the pipeline works

Generated 7 Aug on `anthropic/claude-opus-5`, same subject area as the Llama
baseline, and it is the first article that vindicates the whole design:
<https://bartholomewtj.github.io/article-generator/#p=AC7NQV359>

| | Llama (morning) | Opus 5 (evening) |
|---|---|---|
| Body | ~470 words, 2-sentence sections | **3,311 words, 8 sections** |
| Sources cited | 3 of 20 | **19 of 20** |
| Style-gate failures | 4, revision failed | **1** (recycled phrasing) |
| Introduction | restated the abstract | its own argument |
| Unverified figures | — | **none** |

The title is a finding rather than a topic label, effect estimates carry
confidence intervals and GRADE certainty, and it adjudicates its own evidence
base — flagging that a cohort "probably supports association rather than an
intervention effect", and that an injury-risk meta-analysis and two register
studies "are not entirely concordant". Every numerical claim was located in
the material the model was shown, so `verify.py` flagged nothing.

## Next thing to do

1. **The one remaining style failure is `recycled-phrasing`**, and the
   revision pass could not resolve it. Worth reading the article for where the
   repetition actually is before touching the rule — it may be correct.
2. **Only 4 of 19 sources had open-access full text.** That is the binding
   constraint on depth now, not the writer. Whether more can be reached (other
   OA sources, publisher APIs) is the next real capability question.
3. Consider whether Opus 5 is worth its cost against Sonnet 5 on the same
   topic — Sonnet is 2.5x cheaper and was what the #63 test validated.

## Open

- No open PRs, no open issues.
- **#71 (Pages push trigger dead) was closed on 7 Aug.** A no-op workflow
  edit did not fix it; renaming the file (`pages.yml` → `deploy-pages.yml`)
  did — GitHub registered it as a new workflow with a working push trigger,
  and also delivered the backlogged push events for the two orphaned commits.
  If pushes ever go quiet again, rename the file again; don't bother with
  no-op edits.

## Watch out for

- **Never re-run a failed Pages deploy** — the rerun double-uploads the
  artifact and fails on that. Dispatch a fresh run instead.
- **Generate with OpenRouter or Anthropic, not Groq.** Groq's daily cap kills
  runs mid-day and its per-minute ceiling means abstracts-only grounding. Both
  paid paths now default to Claude Fable 5, so watch the spend: roughly $1–2
  an article, not a fraction of a cent.
- **Model ids live in two places** — `llm.py` and the `PROVIDERS` map in
  `index.html`. Change both together; `test_front_end_models_match_the_allowlist`
  catches the drift. The front end is what picks the model, so a stale Pages
  deploy silently keeps using the old one — that is why the 7 August article
  ran on Llama after the default had been discussed.
- **`/api/health` before assuming a merge reached the backend;** `/api/diag`
  is the only trustworthy answer on which scholarly source is currently
  working — never write that down, it flips.
- **Searches are cached 24h** (refusals 2 min). Testing fetch changes needs
  `sources.clear_search_cache()` or `ARTICLEGEN_SEARCH_CACHE_TTL=0`.
- Everything structural (module map, style-gate calibration, deployment
  constraints, provider quirks) lives in `CLAUDE.md` — this file only carries
  what changed hands at the last session boundary.

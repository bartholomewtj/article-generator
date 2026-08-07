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

## Next thing to do

1. **Generate an article on Fable and read it.** Everything is now in place —
   full-text grounding, the new layout, Fable on both paid providers, and
   truthful provenance statements — but no one has read an article with all of
   it combined. That reading is what has surfaced every defect so far. Not
   Groq: it never gets full text, its token ceiling can't fit any.
2. Compare it against the 7 August Llama article (same topic: night-shift
   scheduling) — that one is the before picture, and it is worth keeping as a
   baseline.

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

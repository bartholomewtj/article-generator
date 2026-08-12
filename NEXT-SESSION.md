# Next session

_Last handoff: 12 August 2026 — branch `feat/issue-84-multi-api-oa`_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article, grounded in paper abstracts plus open-access
full texts where they exist. It runs as a CLI and as a hosted web app (GitHub
Pages front end → Render backend).

This session did two things. **PR #103 is open and waiting on you** — an
Unpaywall fallback that should raise full-text coverage (#84). And a ten-lens
council review of the whole project produced **13 new issues, #91–#102 and
#104**. Nothing else is half-finished; the working tree is clean.

The review's blunt finding: the engineering is good and almost none of it is
visible or working where it counts. Six of the ten articles published to the
live site carry no AI disclosure at all, the README understates the default
per-article cost by about 100x, and nothing runs the 2,750 lines of tests.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git status --short && git branch --show-current && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints the branch and any dirty files first, then `ALL PASS` /
`ALL CONVENTIONS MET`. No keys, no network. Verified at handoff time.

Backend health (reports the commit it built from):

```bash
curl https://articlegen-api.onrender.com/api/health
```

## Next thing to do

1. **Merge or close PR #103** — it is the only thing in flight. Then pick up
   from the list below.
2. **#91 — clean up what is published.** Delete the three test drafts
   (`peer-support-fable-test`, `peer-support-fable-insession`,
   `night-shift-sonnet-63`), regenerate or drop the four with no AI disclosure,
   and add a disclosure line under the `<h1>` in `render._TEMPLATE` and
   `_INDEX_TEMPLATE`. This is public right now.
3. **#93 then #94.** #93 is a README/`index.html` text fix — the docs send
   people to OpenRouter expecting "well under a cent" when the default is
   Opus 5 at 50c–$1. #94 is two ~15-line GitHub Actions workflows: run the
   tests on push, and check `/api/health` daily. #94 is the cheapest item on
   the whole list and it stops several other problems recurring.

Everything else is in the issue list, roughly in priority order from #91 down.

## Open

- **PR #103** — Unpaywall fallback for full-text coverage (#84). Waiting on
  your review. No CI exists yet, so nothing else gates it.
- **#91–#99** — the council review's ranked findings, highest impact first.
- **#100** — article iframe has no `sandbox`, so model-written HTML runs
  same-origin with the stored API keys. Cheap fix, real exposure.
- **#101** — `check_statistics` accepts a figure found in *any* source, so
  misattribution passes as verified; bare integers with clinical units are
  never checked.
- **#102** — nothing stops the writer producing dose and titration
  instructions; one published draft already does, for a population the same
  article says has zero studies.
- **#104** — the new Unpaywall lookup fails silently and `/api/diag` does not
  probe it.
- **#84, #85** — pre-existing. #84 is what PR #103 addresses. #85 (Sonnet 5 vs
  Opus 5 on cost and quality) is still untouched and still worth one `--model`
  flag.

## Watch out for

- **`CLAUDE.md` is out of date in the full-text section** and has been since
  #88/#89 merged. It documents `FULLTEXT_TARGET` and `MAX_FULLTEXT_REQUESTS`
  only; the code also has `FULLTEXT_PREFERRED_TARGET` (5),
  `FULLTEXT_MINIMUM_DESIRED` (3) and `MAX_FULLTEXT_FETCHES` (an alias kept for
  outside callers). Tracked in #97. Trust `pipeline.py:29-47` over the doc.
- **Nothing runs the tests automatically.** A commit that breaks them still
  deploys the front end. Until #94 lands, run both scripts by hand before
  pushing anything.
- **Never send Unpaywall a made-up contact address.** It requires a real one
  and blocks addresses that bounce; `resolve_pmcid` uses `OPENALEX_MAILTO`
  when set and the repo URL otherwise.
- **Generate with OpenRouter or Anthropic, not Groq.** Groq's daily cap kills
  runs mid-day, and its per-minute ceiling means abstracts-only grounding.
  Budget roughly 50c–$1 an article on the Opus 5 default.
- **The OpenRouter key carries its own spending cap**, separate from account
  credit. A 403 mentioning a limit is fixed at openrouter.ai/keys; topping up
  credit does nothing.
- **Model ids live in two places** — `llm.py` and the `PROVIDERS` map in
  `index.html`. The front end picks the model, so a stale Pages deploy quietly
  keeps using the old one. Hard-refresh after a deploy.
- **Every provenance statement must be derived, never hardcoded.** Methods
  counts what provenance says was *fetched*; everything else counts the
  *cited* papers (`render._full_text_count`). Breaking this shipped an article
  claiming both "7 full texts retrieved" and "prepared from abstracts alone"
  (#75).
- **`/api/diag` is the only trustworthy answer** on which scholarly source is
  working right now — never write it down, it flips.
- **Searches are cached 24h** (refusals 2 min). Testing fetch changes needs
  `sources.clear_search_cache()` or `ARTICLEGEN_SEARCH_CACHE_TTL=0`.
- Everything structural — module map, style-gate calibration, deployment
  constraints, provider quirks — is in `CLAUDE.md`. This file only carries
  what changed hands at the session boundary.

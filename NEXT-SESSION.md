# Next session

_Last handoff: 7 August 2026 — branch `main`_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article, grounded in paper abstracts plus open-access
full texts where they exist. It runs as a CLI and as a hosted web app (GitHub
Pages front end → Render backend).

**The pipeline now works end to end.** After a day of fixing the paid-model
path, it produced its first genuinely good article — 3,311 words, 19 sources,
effect estimates with confidence intervals, and it argues with its own
evidence rather than summarising it:
<https://bartholomewtj.github.io/article-generator/#p=AC7NQV359>

Everything is merged and deployed. Nothing is half-finished.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints `ALL PASS` / `ALL CONVENTIONS MET`. No keys, no network. Both verified
at handoff time.

To check the live backend (reports the commit it built from):

```bash
curl https://articlegen-api.onrender.com/api/health
```

## Next thing to do

1. **#83 — read the Opus article and find the recycled phrasing** before
   touching `style.py`. Either the revision pass in `enforce_style` is too
   weak, or the rule is wrong for a register that legitimately repeats terms
   of art. Opposite fixes; decide which before tuning anything.
2. **#84 — full-text coverage is now the ceiling.** Only 4 of 19 sources had
   OA full text. First check one log line: did `MAX_FULLTEXT_FETCHES` stop the
   fetch early, or did only 4 sources have a PMCID with both OA flags?
3. **#85 — run the same topic on `anthropic/claude-sonnet-5`.** It is 2.5x
   cheaper than the Opus 5 default and was the model the #63 test validated.
   One `--model` flag.

## Open

- No PRs.
- **#83** — `recycled-phrasing` fires on a good article; revision can't clear it.
- **#84** — full-text coverage (4 of 19) is the binding constraint on depth.
- **#85** — compare Sonnet 5 against the Opus 5 default on cost and quality.

## Watch out for

- **Today's four fixes were all on the paid path, and each hid the next.** In
  order: output ceiling too small for a thinking model (#77) → no refusal
  handling (#79) → OpenRouter routing to Azure, which rejects structured
  outputs (#81). If a new provider-side failure appears, read `provider_name`
  in the error body first — **provider selection is dynamic**, so a routing
  fault looks like a fresh bug every time.
- **The OpenRouter key carries its own spending cap**, separate from account
  credit. A 403 mentioning a limit is fixed at openrouter.ai/keys; topping up
  credit does nothing. This blocked generation today.
- **Generate with OpenRouter or Anthropic, not Groq.** Groq's daily cap kills
  runs mid-day, and its per-minute ceiling means abstracts-only grounding.
  Budget roughly 50c–$1 an article on the Opus 5 default.
- **Model ids live in two places** — `llm.py` and the `PROVIDERS` map in
  `index.html`. The front end picks the model, so a stale Pages deploy quietly
  keeps using the old one; that is why an article ran on Llama this morning
  after the default had already changed. Hard-refresh after a deploy.
- **Every provenance statement must be derived, never hardcoded.** Methods
  counts what provenance says was *fetched*; everything else counts the
  *cited* papers (`render._full_text_count`). Breaking this shipped an article
  claiming both "7 full texts retrieved" and "prepared from abstracts alone"
  (#75). Same rule as the database list.
- **`/api/diag` is the only trustworthy answer** on which scholarly source is
  working right now — never write it down, it flips.
- **Searches are cached 24h** (refusals 2 min). Testing fetch changes needs
  `sources.clear_search_cache()` or `ARTICLEGEN_SEARCH_CACHE_TTL=0`.
- Everything structural — module map, style-gate calibration, deployment
  constraints, provider quirks — is in `CLAUDE.md`. This file only carries
  what changed hands at the session boundary.

# Next session

_Last handoff: 5 August 2026 — branch `main`_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article and grounded in real paper abstracts. It runs as a
CLI and as a hosted web app (GitHub Pages front end → Render backend).

Everything open at the start of the day is closed. Two real articles were
generated through OpenRouter and read; the defects they exposed were fixed and
merged. The default branch was renamed to `main`. **The tree is clean, nothing is
half-finished, and there are no open PRs.**

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints `ALL PASS` / `ALL CONVENTIONS MET`. No keys, no network.

To check the live backend — it now reports which commit and branch it built:

```bash
curl https://articlegen-api.onrender.com/api/health
```

## Next thing to do

1. **Run the model test in #63.** One flag, ~10c of OpenRouter credit, and it
   decides whether the remaining quality problem is the model or the pipeline:
   `python -m articlegen draft "<topic>" --model anthropic/claude-sonnet-5`, then
   measure the abstract-to-Introduction overlap. Everything else in #63 waits on
   this answer, so do it before touching the revision loop.
2. **Then #64** — 20 sources were screened and only 3 cited, all of them labelled
   `direct`. Start by logging the relevance tally at draft time; it tells you
   whether curation is too strict or the writer too timid, which need different
   fixes.
3. **#62** if you want something small and self-contained — corporate authors
   (`GBD 2019 Collaborators`) render as `Collaborators, G.` in the reference list.

## Open

- No PRs.
- **#63** — the abstract is still reproduced verbatim as the Introduction (100%
  on the last article). Retrieval, the prompt and the tone setting are all ruled
  out by measurement; the model and the revision pass are what's left.
- **#64** — only `direct`-labelled sources get cited, so the evidence base
  collapses (20 → 3) and the article comes out as a 471-word stub.
- **#62** — corporate/consortium author names are mangled in references.

## Watch out for

- **Generate with OpenRouter, not Groq.** Same Llama 3.3 70B, but prepaid credit
  instead of a 100,000-token daily cap, so a run never fails because the day is
  spent. Well under a cent per article. Set `OPENROUTER_API_KEY`, or paste the key
  into Settings in the web app. Any catalogue slug works with `--model`.
- **`/api/health` reports the deployed commit and branch.** Use it before assuming
  a merge reached production — that one line is what made the branch rename safe,
  and it is the fastest way to answer "is the backend running my code".
- **A branch rename touches three places, not one:** the trigger list in
  `pages.yml`, the `github-pages` *environment* branch allowlist (which is
  separate, and silently rejected `main` until it was added), and the host. Render
  turned out to follow a GitHub rename by itself, contrary to every earlier note.
- **`render.yaml`'s `branch:` is a record, not a control.** Blueprint auto-sync is
  off — measured. Editing it moves nothing.
- **Don't write down which scholarly source is working.** It changes, and it has
  been recorded backwards twice. `/api/diag` is the only trustworthy answer, and
  it bypasses the cache to give one.
- **Searches are cached 24h** (refusals 2 min). Testing changes to fetching means
  `sources.clear_search_cache()` or `ARTICLEGEN_SEARCH_CACHE_TTL=0`, or you are
  reading yesterday's results and will think your change did nothing.
- **Calibrate style rules against body prose, not abstracts.** The hedging floor
  looked badly wrong against abstracts (median 0.031 vs a 0.20 floor) and is
  almost exactly right against review body prose (median 0.216). Both corpora are
  in `tests/`; use `body_prose_measurements.json` for anything density-related.
- **Never hardcode the database list, including as a fallback** — that is exactly
  how a false Methods claim came back after being fixed once.
- **`protocol_version = "HTTP/1.1"` in `web.py` is load-bearing.** Without it
  about half of browser fetches fail in ~140ms, and curl cannot reproduce it.
- **Hugging Face Spaces and Fly.io are settled dead ends** (both need a payment
  method); so is moving Render region (same shared egress IP problem).
- **"Copy Link" and "Publish public link" are deliberately different.** The first
  encodes the article in the URL; the second uploads to a public pastebin behind a
  confirmation. Don't re-merge them.

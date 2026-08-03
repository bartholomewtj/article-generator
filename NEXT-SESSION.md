# Next session

_Last handoff: 4 August 2026 — branch `claude/article-generator-html-yth1u4` (default)_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article and grounded in real paper abstracts. It runs as a
CLI and as a hosted web app (GitHub Pages front end → Render backend).

This session was a ground-up review of the project against its own docs, not
feature work. Two PRs merged: Europe PMC as a third evidence source (#43), and a
search cache plus a batch of correctness and documentation fixes (#44). Nothing
is half-finished — the tree is clean and both test suites pass.

The one thing still unproven is whether the deployment can now reliably reach a
scholarly source. That's step 1 below.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Both should print `ALL PASS` / `ALL CONVENTIONS MET`. No keys or network needed.

To check the deployed backend (costs quota, don't poll it):

```bash
curl https://articlegen-api.onrender.com/api/diag
```

## Next thing to do

1. **Check whether Europe PMC fixed the deployment.** Run the `curl` above a few
   times, a minute apart. `papers_found > 0` with `europe_pmc` among the sources
   that answered is what closes issue #41. The deploy carrying Europe PMC only
   just landed, so this has never been observed.
2. **Generate one article and read it.** Still the oldest outstanding question.
   Several output-quality changes (#28, #29, #36, #37, and the substance rules)
   have never been watched producing an article end to end. Look at whether the
   substance rules fire, whether the revision pass triggers, and whether the
   prose is less repetitive than the night-shift article that started this.
3. **Then decide about issue #38** (evidence pool skews old, median paper year
   2013). Whether it's worth fixing depends entirely on how step 2 reads.

## Open

- No open PRs.
- **#41** — 429s from the shared Render egress IP. The live one; updated today
  with measurements. Step 1 above is what closes it.
- **#47** — rename the default branch to `main`. Do it at the *start* of a
  session: Render tracks the branch by name and deploys stop silently otherwise.
- **#38** — evidence pool skews old; ranking reorders it but can't refresh it.
- **#45** — decide whether Opus 5 calls should use server-side refusal fallbacks.
- **#46** — Box, Table and Fig. 1 are still built twice (HTML and Markdown).
- **#34** — substance rules double token cost; revisit only if quota bites.
- **#33** — seven orphaned `theme:` issues; the workflow reading them is gone.

## Watch out for

- **Don't write down which scholarly source is working.** It changes, and it has
  now been recorded backwards twice — issue #32 said Semantic Scholar was the
  broken one while OpenAlex was in fact refusing every call. `/api/diag` is the
  only trustworthy answer, and it bypasses the cache specifically to give one.
- **Searches are cached for 24h** (refusals for 2 minutes). Re-running a topic is
  free and repeatable, which is what makes a demo work. But if you are testing
  changes to fetching, call `sources.clear_search_cache()` or set
  `ARTICLEGEN_SEARCH_CACHE_TTL=0` — otherwise you are reading yesterday's results
  and will think your change did nothing.
- **Never hardcode the database list, including as a fallback.** That is exactly
  how it came back after being fixed once: `provenance.get("databases") or
  _DATABASES` kept a false Methods claim alive for every draft without
  provenance. There is no fallback now — an unrecorded search says so and names
  nothing.
- **Groq's free tier allows roughly 4–7 articles a day**, and failed attempts
  still spend quota. This is the failure a new user is most likely to hit. The
  Settings copy and the error handler now say so in plain language rather than
  showing the raw `rate_limit_exceeded ... TPD` string.
- **`protocol_version = "HTTP/1.1"` in `web.py` is load-bearing.** Without it
  roughly half of browser fetches fail in ~140ms, and **curl cannot reproduce
  it** — each invocation opens a fresh connection, so only a connection-pooling
  client sees the bug. Don't "simplify" it away.
- **Hugging Face Spaces and Fly.io are settled dead ends** — both require a
  payment method for their free tier. Evidence is in `CLAUDE.md` → Deployment.
  Moving Render region is also settled: a different region is a different shared
  egress IP with the same problem (PR #42, closed).
- **"Copy Link" and "Publish public link" are deliberately different.** The first
  encodes the article in the URL and uploads nothing; the second posts it to a
  public pastebin behind a confirmation. Don't re-merge them.

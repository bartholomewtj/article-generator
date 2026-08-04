# Next session

_Last handoff: 4 August 2026 — branch `claude/article-generator-html-yth1u4` (default)_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article and grounded in real paper abstracts. It runs as a
CLI and as a hosted web app (GitHub Pages front end → Render backend).

This session (4 Aug, later): **the deployment is confirmed working.** Three
`/api/diag` probes a minute apart all found papers — Europe PMC answered every
time, Semantic Scholar twice, OpenAlex 429'd throughout. #41 closed with the
measurements. Also verified from the browser: the Pages front end loads,
`API_BASE` is right, `/api/health` returns 200 cross-origin. Both test suites
pass. Stale PR #48 (a static-asset refactor based on pre-journal-format code
from a forgotten second clone at `C:\geminiprojects\article generator\`) was
closed as superseded; that clone should not be used again.

The tree is clean. Nothing is half-finished.

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

0. **Set `GROQ_API_KEY` and generate one article — this is the only step left.**
   Both PR #49 and the rule-review work on `feat/per-study-depth` are complete and
   green, but neither has been watched producing an article, because no key is set
   on this machine (no `.env`, not in the environment). Get a free key at
   console.groq.com, then: `export GROQ_API_KEY=...` and
   `python -m articlegen draft "artificial light and night shift workers"`.
   The research half is confirmed working keyless (12 papers gathered on 4 Aug).

1. **Context for what to look for.** An article was
   finally generated and read (4 Aug, via the deployed web app) and it was badly
   repetitive: the abstract, key points and Introduction were the same paragraph
   three times (38% and 24% shared 6-word runs), and studies were only ever cited
   in bundles, so no individual study was ever described. #49 fixes the cause —
   the schema had asked all three surfaces to be self-contained summaries — and
   adds `echoed-abstract` and `bundled-citations` to enforce it deterministically.
   **The new rules are proven against the bad output; the prompt changes are not
   verified end to end.** That needs `GROQ_API_KEY` (not set on this machine — no
   `.env`, not in the environment) and one real generation.
2. **Watch the quota when you do.** More substance rules firing means the
   revision pass runs more often, and each revision spends tokens against the
   ~4–7 articles/day free tier. If it becomes the binding constraint, that is
   issue #34.
3. **Then decide about issue #38** (evidence pool skews old, median paper year
   2013). Whether it's worth fixing depends on how the next article reads.

## Open

- **#49** — repetition/per-study-depth fix, plus the style-rule review (real-prose
  false positives, hedge split, nominalisation deleted, scaled section floor).
  Open, both suites green, awaiting merge.
- **#47** — rename the default branch to `main`. Do it at the *start* of a
  session: Render tracks the branch by name and deploys stop silently otherwise.
  Needs the Render dashboard (owner login), so the rename and the dashboard
  change must happen in the same sitting, by the owner.
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

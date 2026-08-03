# Next session

_Last handoff: 3 August 2026 — branch `claude/article-generator-html-yth1u4`_

## Where this stopped

The web app used to run a second, simplified copy of the pipeline in JavaScript —
which is what every visitor to the demo actually got. That's gone: one pipeline
(`articlegen/pipeline.py`), the front end calls it over HTTP, backend on Render.
PRs #21–#37 are merged, both suites pass, and the Render deploy is live.

**The deployed app currently cannot generate anything.** `GET /api/diag` on the
live backend reports *both* scholarly APIs returning HTTP 429:

```json
{"papers_found": 0,
 "sources": [{"source": "semantic_scholar", "error": "HTTP 429 after 3 attempts"},
             {"source": "openalex",         "error": "HTTP 429 after 3 attempts"}],
 "openalex_mailto_set": false}
```

OpenAlex works fine from a laptop and 429s from Render, so Render's shared IP is
being throttled. **This is one dashboard field away from fixed** — see step 1.

## Resume with

```bash
curl https://articlegen-api.onrender.com/api/diag
```

That says in one line whether the backend can reach its sources. `papers_found`
above 0 means it's working; 0 with 429s means still throttled.

Offline, everything runs without keys or network:

```bash
python tests/test_offline.py && python tests/test_journal_conformance.py
```

## Next thing to do

1. **Set `OPENALEX_MAILTO`** to your email in the Render dashboard →
   `articlegen-api` → Environment (issue #31). This puts requests in OpenAlex's
   polite pool and is the most likely fix for the 429 above. Re-run the `curl`
   and confirm `papers_found` is no longer 0. **Nothing else works until this does.**
2. **Generate one article and read it.** Six changes to output quality
   (#28, #29, #36, #37 and the two before them) have never been observed
   producing an article. The questions are whether the substance rules fire,
   whether the revision pass triggers, and whether the result is less repetitive
   than the night-shift article that started this.
3. **Then, and only then**, decide about issue #38 (the evidence pool skews old,
   median paper year 2013). Whether it needs fixing depends on how step 2 reads.

## Open

- No open PRs.
- Issue #31 — set `OPENALEX_MAILTO` (this is step 1; do it first)
- Issue #32 — Semantic Scholar 429s on every call, contributing nothing
- Issue #33 — seven orphaned `theme:` issues; the workflow reading them is gone
- Issue #34 — substance rules double token cost; revisit only if quota bites
- Issue #38 — evidence pool skews old; ranking reorders it but can't refresh it

## Watch out for

- **Groq free tier is the binding constraint.** 12,000 tokens/minute *and*
  100,000 per day. One article costs ~14–23k, so **4–7 articles a day**, and
  failed attempts still spend quota. Both limits were hit in one session.
  Claude is selectable in Settings and has no comparable ceiling.
- **`protocol_version = "HTTP/1.1"` in `web.py` is load-bearing.** Without it
  roughly half of browser fetches fail in ~140ms, and **curl cannot reproduce
  it** — each invocation opens a fresh connection, so only a pooling client sees
  the bug. Don't "simplify" it away.
- **Never hardcode the database list again.** The Methods section claimed both
  Semantic Scholar and OpenAlex were searched while Semantic Scholar returned
  nothing — false in every article produced. It now comes from
  `provenance["databases"]`; add new sources to `sources.DATABASE_NAMES`.
- **Hugging Face Spaces and Fly.io are settled dead ends** — each requires a
  payment method for its free tier. Evidence is in `CLAUDE.md` → Deployment.
- **"Copy Link" and "Publish public link" are deliberately different.** The
  first encodes the article in the URL and uploads nothing; the second posts it
  to a public pastebin behind a confirmation. Don't re-merge them.
- The default branch is still `claude/article-generator-html-yth1u4`. Renaming
  to `main` works via `gh api`, but **Render tracks the branch by name** — rename
  and update Render in the same sitting or deploys stop silently.

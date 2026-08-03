# Next session

_Last handoff: 4 August 2026 — branch `fix/source-cache-and-stale-docs`_

## Where this stopped

The previous handoff said the deployed backend could not generate anything, that
setting `OPENALEX_MAILTO` was the fix, and that "nothing else works until this
does". All three claims are now out of date:

- `OPENALEX_MAILTO` **is** set (issue #31 closed). Joining OpenAlex's polite pool
  did not fix it — OpenAlex 429s from the deployment with a cool-off longer than
  30 seconds, which the client treats as an immediate failure.
- The two sources have **swapped roles** since those notes were written. A
  four-call sample of `/api/diag` on 4 Aug: OpenAlex refused 4/4; Semantic
  Scholar — recorded in issue #32 as never working — answered once with 2
  papers. Do not trust any written claim about which source works. Measure.
- The real constraint is the shared cloud egress IP, not headers or region. That
  is why PR #42 (move region) was closed: a different Render region is a
  different shared IP with the same problem.

## Resume with

```bash
curl https://articlegen-api.onrender.com/api/diag
```

`papers_found` above 0 means the host can reach at least one source. Each call
now costs quota and is rate-limited, so don't poll it in a loop.

Offline, everything runs without keys or network:

```bash
python tests/test_offline.py && python tests/test_journal_conformance.py
```

## Next thing to do

1. **Merge PR #43 (Europe PMC), then this branch.** Europe PMC is the only one
   of the three sources without a contested keyless pool, and its biomedical
   coverage suits the mental-health topics this gets used for. It is the durable
   fix for the 429s; the deployed backend does not have it yet. This branch is
   stacked on top of it, so merging this one brings both.
2. **Generate one article and read it.** Still the outstanding question. Several
   output-quality changes (#28, #29, #36, #37 and the substance rules) have
   never been observed producing an article end to end. Watch whether the
   substance rules fire, whether the revision pass triggers, and whether the
   result is less repetitive than the night-shift article that started this.
3. **Then, and only then**, decide about issue #38 (evidence pool skews old,
   median paper year 2013). Whether it needs fixing depends on how step 2 reads.

## Open

- PR #43 — Add Europe PMC as a third evidence source (merge first)
- Issue #41 — 429s from the shared Render egress IP (the real one)
- Issue #38 — evidence pool skews old; ranking reorders it but can't refresh it
- Issue #34 — substance rules double token cost; revisit only if quota bites
- Issue #33 — seven orphaned `theme:` issues; the workflow reading them is gone

Closed as wrong or superseded: #31 (mailto set, didn't fix it), #32 (claimed
Semantic Scholar was the broken one — superseded by #41), PR #42 (region move).

## Watch out for

- **Don't record which scholarly source is working.** It changes, and two
  separate notes have already been written down backwards. `/api/diag` is the
  only trustworthy answer, and it deliberately bypasses the cache to give one.
- **Searches are cached for 24h** (refusals for 2 minutes). Re-running a topic
  is free and repeatable — good for demos. If you are testing changes to
  fetching, call `sources.clear_search_cache()` or set
  `ARTICLEGEN_SEARCH_CACHE_TTL=0`, or you will be reading yesterday's results.
- **Never hardcode the database list — including as a fallback.** That is how it
  came back the first time: `provenance.get("databases") or _DATABASES` kept the
  false Methods claim alive for every draft without provenance. There is no
  fallback now; an unrecorded search says so.
- **Groq free tier: roughly 4-7 articles a day**, and failed attempts still
  spend quota. This is the failure a new user is most likely to hit; the
  Settings copy and the error handler now say so in plain language.
- **`protocol_version = "HTTP/1.1"` in `web.py` is load-bearing.** Without it
  roughly half of browser fetches fail in ~140ms, and **curl cannot reproduce
  it** — each invocation opens a fresh connection, so only a pooling client sees
  the bug. Don't "simplify" it away.
- **Hugging Face Spaces and Fly.io are settled dead ends** — each requires a
  payment method for its free tier. Evidence is in `CLAUDE.md` → Deployment.
- **"Copy Link" and "Publish public link" are deliberately different.** The
  first encodes the article in the URL and uploads nothing; the second posts it
  to a public pastebin behind a confirmation. Don't re-merge them.
- The default branch is still `claude/article-generator-html-yth1u4`. Renaming
  to `main` works via `gh api`, but **Render tracks the branch by name** — rename
  and update Render in the same sitting or deploys stop silently.

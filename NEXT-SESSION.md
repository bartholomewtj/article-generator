# Next session

_Last handoff: 3 August 2026 — branch `claude/article-generator-html-yth1u4`_

## Where this stopped

The web app used to run a **second, simplified copy of the pipeline in JavaScript**,
which is what every visitor to the GitHub Pages demo actually got — no Semantic
Scholar, no relevance gate, no prose-style enforcement, no statistic verification.
That's gone. There is now one pipeline (`articlegen/pipeline.py`), the front end
calls it over HTTP, and the backend runs on Render. Ten PRs (#21–#30) are merged
and both test suites pass.

**One thing is unfinished:** the Render service is still running older code. Its
`/api/health` answers, but `/api/diag` 404s, so the last two merges (#29 token
budget, #30 source-failure diagnosis) are not live yet.

## Resume with

```bash
python tests/test_offline.py && python tests/test_journal_conformance.py
```

Both pass as of this handoff. To check what's actually deployed:

```bash
curl https://articlegen-api.onrender.com/api/diag
```

`404` means the deploy still hasn't landed. `200` means it has, and the JSON
shows whether the scholarly APIs are answering *that host*.

## Next thing to do

1. **Force the Render deploy.** https://dashboard.render.com/web/srv-d9o5qjdaeets73d5a12g
   → Manual Deploy → Deploy latest commit. Then confirm `/api/diag` returns 200.
   If auto-deploy stalled for a reason, Settings → Build & Deploy shows the
   branch it watches; it must be `claude/article-generator-html-yth1u4`.
2. **Set `OPENALEX_MAILTO`** in the Render dashboard (issue #31). OpenAlex is
   currently doing all the source fetching alone, and this is what gets us
   better rate limits.
3. **Generate one article end to end and read it.** Nothing since #28 has been
   verified against real output. The question is whether the substance rules
   fire and force a rewrite, and whether the result is less repetitive than
   the night-shift article that prompted them.

## Open

- No open PRs — #21–#30 all merged.
- Issue #31 — set `OPENALEX_MAILTO` on Render (quick, do it with step 2 above)
- Issue #32 — Semantic Scholar returns 429 on every call; OpenAlex is carrying
  the pipeline alone, and the Methods text claims both
- Issue #33 — seven orphaned `theme:` issues; the workflow that read them is gone
- Issue #34 — substance rules double token cost; revisit only if the Groq daily
  limit gets in the way
- Ten merged branches still exist locally and on the remote. Not deleted —
  that needs your say-so.

## Watch out for

- **Groq free tier is the real constraint.** 12,000 tokens/minute *and* 100,000
  per day. One article costs ~14–23k, so about **4–7 articles a day**, and failed
  attempts still spend quota. Both limits were hit during this session. Switching
  to Claude in Settings removes the ceiling; a key per provider is stored separately.
- **`protocol_version = "HTTP/1.1"` in `web.py` is load-bearing.** Without it
  roughly half of all browser fetches fail in ~140ms. `curl` cannot reproduce
  this — each invocation opens a fresh connection, so only a pooling client sees
  it. Don't "simplify" it away.
- **Hugging Face Spaces and Fly.io are both dead ends** for hosting: each
  requires a payment method for its free tier. That was settled with evidence,
  not preference — see the Deployment section of `CLAUDE.md`.
- **The Share button publishes to a public pastebin.** That's now behind an
  explicit confirmation, but "Copy Link" and "Publish public link" do genuinely
  different things and shouldn't be re-merged.
- The default branch is still `claude/article-generator-html-yth1u4`. Renaming to
  `main` is possible via `gh api` (CLAUDE.md used to claim otherwise — wrong), but
  **Render tracks the branch by name**, so a rename means updating Render in the
  same sitting or deploys stop silently.

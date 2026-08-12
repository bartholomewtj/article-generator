# Next session

_Last handoff: 12 August 2026 — `main` @ `8b6e1ea`, everything merged and deployed_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article, grounded in paper abstracts plus open-access full
texts. It runs as a CLI and as a hosted web app (GitHub Pages front end → Render
backend).

**Nothing is in flight.** PR #112 merged, working tree clean, one branch (`main`),
local and remote in sync. Pages and Render both serve `cd2cd28`.

This was a streamlining pass. Four changes:

1. **Groq removed.** It was the default provider and unverified for months. The
   real cost was its 12,000 tokens/**minute** ceiling counting reserved output,
   which is why `prompt_budget_chars()`, the abstract-trimming path in
   `_format_sources`, and a gate that skipped full-text fetching all existed.
   **Every draft is now grounded in full text where one exists**, instead of
   that depending on which provider was picked. `DEFAULT_PROVIDER` is
   `openrouter`.
2. **The reader iframe is sandboxed** — `allow-same-origin`, no `allow-scripts`.
   It ran same-origin with the OpenRouter key in localStorage while being fed
   model-written and, via `#read=`/`#p=` links, attacker-chosen HTML.
   `render_article` grew a `standalone` flag so the app's copy has no scripts
   and no toolbar. Verified in Chromium: injected script blocked.
3. **The two draft libraries are one**, with a star for "keep this". Fixed two
   real bugs on the way — a bare `setItem` that silently lost articles at quota,
   and `openDraftFromGallery`, which was called from the list and defined
   nowhere.
4. **`CLAUDE.md` trimmed** 37KB → 22KB and corrected — it had named the wrong
   workflow file, three constants that no longer existed, and Groq as the
   default.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git branch --show-current && git status --short && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints `main`, no file list, then `ALL PASS` and `ALL CONVENTIONS MET`. No keys,
no network. Verified at handoff.

**Branch and dirtiness come first on purpose** (#97): the tests print a green
`ALL PASS` even on a dirty tree on the wrong branch, so a returning session gets
reassured before it gets informed.

Is the live site current?

```bash
git rev-parse --short=7 HEAD
curl -s https://bartholomewtj.github.io/article-generator/ | grep -o 'build <code>[a-f0-9]*'
curl -s -m 90 https://articlegen-api.onrender.com/api/health
```

All three should agree. The backend sleeps after 15 min idle and takes ~50s to
wake.

To drive the front end: `articlegen web --port 8765`, then Playwright via
`playwright-core` with the cached Chromium under `$LOCALAPPDATA/ms-playwright`
(`chromium.launch({ channel: 'chromium' })`).

## Next thing to do

1. **#111 — a first-time visitor has no free path.** Removing Groq sharpened
   this rather than causing it: the web app needs a paid OpenRouter key before
   it does anything. The CLI has `--model cli:opus` on your subscription, which
   a shared host can never offer. This is a product decision, not a bug.
2. **#113 — the stored key is readable by every other Pages site** under
   `bartholomewtj.github.io`, and the Settings panel says the opposite ("never
   shared with anyone else"). Cheapest honest fix is disclosure plus a
   session-only key option. Filed this session.
3. **More articles.** `drafts/` holds one, so the published queue reads as a
   sample rather than a portfolio. ~4½ minutes each on `cli:opus`, no money.
4. **#101 and #102** are the substantive work — both clinical-safety changes to
   verification and to what the writer is allowed to say.

## Open

Closed this session: **#110** (obsolete, Groq gone), **#100** (sandbox),
**#97** (doc drift). Read #100's closing comment before touching the sandbox —
it was fixed the *opposite* way to what the issue proposed.

- **#113** — stored key readable across the shared Pages origin. New.
- **#114** — nothing in the PR process keeps `CLAUDE.md` up with the code. New;
  it is a workflow decision, four options laid out, your call.
- **#111** — no free path for a visitor.
- **#101** — `check_statistics` accepts a figure found in *any* source, so
  misattribution passes as verified.
- **#102** — nothing stops the writer producing dose and titration instructions.
- **#104** — the Unpaywall lookup fails silently and `/api/diag` does not probe it.
- **#99** — split `CLAUDE.md` into invariants and a decisions log. Partly
  overtaken by the trim; see the comment added this session.
- **#92, #95, #96, #98** — council-review findings, roughly in priority order.
  Read #98's comments before starting it.
- **#84, #85** — both carry real measurements; probably closeable after one run
  each. Read the comments before redoing work.

## Watch out for

- **The sandbox must never gain `allow-scripts`.** That one flag hands back
  everything #100 closed. `allow-same-origin` on its own does not run scripts —
  it is what keeps `contentDocument` reachable for the theme sync, edit mode and
  save. `test_article_in_the_web_app_cannot_run_scripts` fails if it is added.
- **Don't reinstate a source char budget.** It existed only for Groq's
  per-minute ceiling. Nothing left has one, and reinstating it would silently
  take full text away from every draft again.
- **`feat/issue-94-ci` was deleted this session** with `-D`, because it was
  squash-merged as #105 and so was never an ancestor of `main`. Verified fully
  subsumed first — no unique files, every artifact present in `main`. If it is
  ever wanted back: `git branch feat/issue-94-ci e32db2c`.
- **Don't squash-merge a stacked PR and delete its base branch.** GitHub will
  not reopen a PR whose base is gone.
- **`claude-cli` cannot enforce a JSON schema**, unlike OpenRouter and
  Anthropic. It asks, retries once, then gives up. Right for drafting at your
  desk, wrong for anything automated. Local-only and deliberately absent from
  `web.ALLOWED_MODELS`.
- **`claude` on Windows is a `.cmd` shim**, so argv goes through cmd.exe: the
  ceiling is **8,191** characters, not 32,767. Anything scaling with the sources
  must go on stdin.
- **`/api/diag` is the only trustworthy answer** on which scholarly source works
  right now — never write it down, it flips.
- **Searches are cached 24h** (refusals 2 min). Testing fetch changes needs
  `sources.clear_search_cache()` or `ARTICLEGEN_SEARCH_CACHE_TTL=0`.
- Everything structural is in `CLAUDE.md`. This file only carries what changed
  hands at the session boundary.

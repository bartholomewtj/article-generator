# Next session

_Last handoff: 12 August 2026 — branch `streamline`, PR open_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article, grounded in paper abstracts plus open-access full
texts. It runs as a CLI and as a hosted web app (GitHub Pages front end → Render
backend).

This session was a streamlining pass. Four commits on `streamline`, one PR,
nothing else in flight:

1. **Groq removed.** It was the default provider, unverified for months (#110),
   and the reason a whole token-ceiling apparatus existed:
   `prompt_budget_chars()`, the abstract-trimming path in `_format_sources`, and
   a gate that skipped full-text fetching entirely on Groq. **Every draft is now
   grounded in full text where one exists**, instead of that depending on which
   provider was picked. `DEFAULT_PROVIDER` is now `openrouter`.
2. **The reader iframe is sandboxed** (#100). It ran same-origin with the
   OpenRouter key in localStorage while being fed model-written — and via
   `#read=`/`#p=` links, attacker-chosen — HTML. `render_article` grew a
   `standalone` flag so the app's copy carries no scripts and no toolbar; the
   sandbox then costs nothing. Verified in Chromium: injected script blocked.
3. **The two draft libraries are one.** Same articles, two storage keys, ~250
   lines of duplicate UI, and saving stored a second full copy of the HTML.
   Now one list with a star. Fixed two real bugs on the way — a bare `setItem`
   that silently lost articles on a full quota, and `openDraftFromGallery`,
   which was called from the list and defined nowhere.
4. **`CLAUDE.md` trimmed** 37KB → 22KB, and corrected: it named the wrong
   workflow file, three FULLTEXT constants that no longer exist, and an
   incomplete `SUBSTANCE_RULES`.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git status --short && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints `ALL PASS` then `ALL CONVENTIONS MET`. No keys, no network. Verified at
handoff.

To drive the front end, `articlegen web --port 8765` and point Playwright at it
(`playwright-core` + the cached Chromium under `$LOCALAPPDATA/ms-playwright`,
`chromium.launch({ channel: 'chromium' })`).

## Next thing to do

1. **Merge the PR.** Nothing else can be built on top until it lands.
2. **#111 — what does a visitor with no paid key do?** Removing Groq sharpened
   this: there is now no free path in the web app at all. The CLI has
   `--model cli:opus`, which the hosted app can never offer.
3. **More articles.** `drafts/` still holds one, so the published queue reads as
   a sample rather than a portfolio. ~4½ minutes each on `cli:opus`, no money.
4. **#101 and #102** are the real work — both substantive clinical-safety
   changes to verification and to what the writer is allowed to say.

## Open

- **#110 is obsolete** — Groq is gone, so "does Groq still work" no longer
  matters. Close it, referencing the removal commit.
- **#100 is done** in this branch; close it when the PR merges.
- **#101** — `check_statistics` accepts a figure found in *any* source, so
  misattribution passes as verified.
- **#102** — nothing stops the writer producing dose and titration instructions.
- **#104** — the Unpaywall lookup fails silently and `/api/diag` does not probe it.
- **#97** — the `CLAUDE.md` full-text section was wrong; fixed here, so close it.
- **#92, #95, #96, #98, #99** — council-review findings, roughly in priority
  order. Read #98's comments before starting it.
- **#84, #85** — both carry real measurements; probably closeable after one run
  each. See the comments before redoing work.

## Watch out for

- **The sandbox is `allow-same-origin` and must never gain `allow-scripts`.**
  That one flag would hand back everything #100 closed. `allow-same-origin` on
  its own does not run scripts — it is what keeps `contentDocument` reachable
  for the theme sync, edit mode and save.
- **Don't reinstate a source char budget.** It only ever existed for Groq's
  per-minute ceiling. Nothing left has one, and reinstating it would silently
  take full text away from every draft again.
- **Do not squash-merge a stacked PR and delete its base branch.** GitHub will
  not reopen a PR whose base is gone — it has to be re-created.
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

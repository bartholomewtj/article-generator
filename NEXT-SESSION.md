# Next session

_Last handoff: 12 August 2026 — branch `main`, everything merged and deployed_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article, grounded in paper abstracts plus open-access
full texts. It runs as a CLI and as a hosted web app (GitHub Pages front end →
Render backend).

Nothing is in flight. Five PRs merged this session and all of it is live:
**#91** (published drafts), **#93** (cost figures), **#94** (CI) are closed,
plus a front-end build stamp and a narrowing of the web app to OpenRouter only.
The working tree is clean and `main` is deployed.

The session's two substantial additions: **CI now exists** — the tests run on
every push and gate the Pages deploy — and **you can draft on your Claude
subscription** with `--model cli:opus`, which needs no API key.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git status --short && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints `ALL PASS` then `ALL CONVENTIONS MET`. No keys, no network. Verified at
handoff.

Is the live site current? Compare these two:

```bash
git rev-parse --short=7 HEAD
curl -s https://bartholomewtj.github.io/article-generator/ | grep -o 'build <code>[a-f0-9]*'
```

Same = you are seeing the current build. Different = browser or CDN cache,
hard-refresh. This is new; before it, "the site isn't updating" and "the deploy
failed" were indistinguishable without diffing the served bytes.

## Next thing to do

1. **#110 — check whether Groq still works.** It is `DEFAULT_PROVIDER`, it is
   what a fresh clone with no keys uses, and the README calls it the free place
   to start. Nobody has verified it in a long time and there is no key on this
   machine to try. Free key at console.groq.com, run one draft. Ten minutes,
   and everything else about the README's "start here" advice depends on it.
2. **#100 — add `sandbox` to the article iframe.** One attribute. Model-written
   HTML currently runs same-origin with the API key in browser storage.
3. **#111 or more articles.** `drafts/` holds **one** article, so the published
   queue reads as a sample rather than a portfolio. Generating two or three more
   costs ~4½ minutes each on `cli:opus` and nothing in money. #111 is the
   related question of what a visitor with no paid key is meant to do.

After that the list turns into real work: #101 and #102 are both substantive
clinical-safety changes to verification and to what the writer is allowed to say.

## Open

- **No open PRs.** Nothing is waiting on you.
- **#110, #111** — filed at this handoff, see above.
- **#100** — article iframe has no `sandbox`; model HTML runs same-origin with
  stored keys. Cheapest real security fix left.
- **#101** — `check_statistics` accepts a figure found in *any* source, so
  misattribution passes as verified.
- **#102** — nothing stops the writer producing dose and titration instructions.
- **#104** — the Unpaywall lookup fails silently and `/api/diag` does not probe it.
- **#92, #95, #96, #97, #98, #99** — council-review findings, roughly in priority
  order. #97 and #98 both grew new detail this session; read the comments.
- **#84, #85** — both now carry real measurements from this session and are
  probably closeable after one more run each. See the comments before redoing work.

## Watch out for

- **`CLAUDE.md` is still wrong in the full-text section** (#97). It names
  `FULLTEXT_TARGET` and `MAX_FULLTEXT_REQUESTS` only; the code also has
  `FULLTEXT_PREFERRED_TARGET` (5), `FULLTEXT_MINIMUM_DESIRED` (3) and
  `MAX_FULLTEXT_FETCHES`. Trust `pipeline.py:35-47` over the doc.
- **`CLAUDE.md` says model ids live in two parallel places.** Still true but
  misleading now: `PROVIDERS` in `index.html` holds one entry (OpenRouter)
  while `llm.py` has four providers.
- **Do not squash-merge a stacked PR and delete its base branch.** Doing that
  this session auto-closed the stacked PR, and GitHub will not reopen a PR whose
  base is gone — it had to be re-created as a new one. Merge the base without
  `--delete-branch` if something is stacked on it.
- **`claude-cli` cannot enforce a JSON schema**, unlike the three API providers.
  It asks, retries once, then gives up on the article. Right for drafting at your
  desk, wrong for anything automated. It is also local-only and deliberately
  absent from `web.ALLOWED_MODELS` — Render has no `claude` binary.
- **`claude` on Windows is a `.cmd` shim**, so its command line goes through
  cmd.exe: the ceiling is **8,191** characters, not 32,767. Anything that scales
  with the sources or the schema must go on stdin. A test pins argv under 2,000.
- **The web app requires a paid key now** (#109/#111). There is no free path for
  a visitor.
- **Every provenance statement must be derived, never hardcoded** — including
  the new disclosure banner, which counts full texts the same way Table 1 does.
  Breaking this shipped an article claiming both "7 full texts retrieved" and
  "prepared from abstracts alone" (#75).
- **`/api/diag` is the only trustworthy answer** on which scholarly source works
  right now — never write it down, it flips. Semantic Scholar 429s almost
  permanently from Render's IP; OpenAlex and Europe PMC both answered all session.
- **Searches are cached 24h** (refusals 2 min). Testing fetch changes needs
  `sources.clear_search_cache()` or `ARTICLEGEN_SEARCH_CACHE_TTL=0`.
- Everything structural — module map, style-gate calibration, deployment
  constraints, provider quirks — is in `CLAUDE.md`. This file only carries what
  changed hands at the session boundary.

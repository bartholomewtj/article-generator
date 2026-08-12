# Next session

_Last handoff: 12 August 2026 — `main` @ `f24e7f9`, plus one PR open for review_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article, grounded in paper abstracts plus open-access full
texts. It runs as a CLI and as a hosted web app (GitHub Pages front end → Render
backend).

Two things landed this session, both merged:

1. **The web app's article options are gone.** Every article is now an in-depth
   longform review at a strict empirical focus — `TONE_LABEL`, `LENGTH_LABEL`
   and `DEPTH_LABEL` are constants in `index.html`, not selectors. Output
   language is the only remaining choice. API Settings lost the writing-model
   block and gained five bullet steps for getting an OpenRouter key.
2. **A token-efficiency pass, and a new provider** (PR #115). Three changes cut
   what a draft spends; a fourth was measured and rejected.

**PR #116 is open and unreviewed** — the `CLAUDE.md` corrections and this note.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git branch --show-current && git status --short && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints the branch, no file list, then `ALL PASS` and `ALL CONVENTIONS MET`. No
keys, no network. Verified at handoff. Branch and dirtiness come first on
purpose (#97): the tests print green even on a dirty tree on the wrong branch.

**Drafting needs a provider, and the default one is currently broken** — see
"Watch out for". What works today:

```bash
python -m articlegen --model agy:gemini-3.6-flash-high draft "your topic"   # Gemini subscription
python -m articlegen --model cli:opus draft "your topic"                    # Claude subscription
```

A full run is ~4 minutes. Is the live site current?

```bash
git rev-parse --short=7 HEAD
curl -s https://bartholomewtj.github.io/article-generator/ | grep -o 'build <code>[a-f0-9]*'
curl -s -m 90 https://articlegen-api.onrender.com/api/health
```

The backend sleeps after 15 min idle and takes ~50s to wake.

## Next thing to do

1. **Merge or close PR #116.** It only touches `CLAUDE.md` and this file.
2. **Replace the OpenRouter key.** `.env` holds a dead one, so the default
   provider path cannot be run or tested locally until it is swapped. Visitors
   to the deployed app use their own keys and are unaffected.
3. **#101 and #102** remain the substantive work — both clinical-safety changes,
   to what `check_statistics` will accept and to what the writer may say.

## Open

- **PR #116** — `CLAUDE.md` reconciliation + this note. Waiting on your review.
- **#116/#117** (issues, filed this session) — the `gemini-cli` revision call
  costs far more context than its prompt explains; and curating on truncated
  abstracts would save ~24k input tokens but needs the relevance gate
  re-validated first.
- **#113** — stored key readable across the shared Pages origin, and Settings
  says the opposite.
- **#111** — no free path for a first-time visitor.
- **#101** — `check_statistics` accepts a figure found in *any* source, so
  misattribution passes as verified.
- **#102** — nothing stops the writer producing dose and titration instructions.
- **#114, #99** — `CLAUDE.md` upkeep. #114 was proved right this session: one
  session's work drifted six passages, all corrected by hand in PR #116.
- **#104, #92, #95, #96, #98, #84, #85** — unchanged. Read the comments on #84,
  #85 and #98 before starting; they carry real measurements.

## Watch out for

- **The `OPENROUTER_API_KEY` in `.env` is dead.** OpenRouter returns
  `401 User not found`, meaning the key was revoked or its account removed.
  Topping up will not help — issue a new one at openrouter.ai/keys. This is why
  every run this session used `agy:`.
- **`agy` is the only working route to Gemini on your subscription.** The Google
  `gemini` CLI refuses to authenticate: `IneligibleTierError`, Code Assist for
  individuals is retired in favour of Antigravity.
- **Do not run the shallow stages at a cheaper reasoning tier.** It is a one-line
  change, it looks free, and it was measured: at `-low` curation agreed with
  `-high` on only 14 of 20 relevance labels and collapsed everything toward
  "related" — that is the gate that stops topic drift. `plan_queries` emits
  run-on queries at `-low` *and* `-medium`. Both tiers report `thinking=0`, which
  is the tell. The measurement is in `llm.py` above `GEMINI_CLI_DEFAULT_MODEL`.
- **On `gemini-cli`, 88% of output tokens are thinking.** Changes that reduce
  emitted *text* barely move the bill. The patch-based revision cut emitted
  content 75% and total output 6%. Measure against `thinking_tokens`, not word
  count.
- **The SOURCE numbering has gaps now.** `write_article` omits tangential
  sources by number and never re-packs the list, because the index *is* the
  citation scheme. Anything that renumbers to close a gap breaks `render` and
  `verify` together.
- **The sandbox must never gain `allow-scripts`.** That one flag hands back
  everything #100 closed. `allow-same-origin` alone does not run scripts.
- **Don't reinstate a source char budget.** It existed only for Groq's
  per-minute ceiling, and reinstating it takes full text away from every draft.
- **`/api/diag` is the only trustworthy answer** on which scholarly source works
  right now — never write it down, it flips. Semantic Scholar 429'd on every run
  this session; OpenAlex and Europe PMC carried them.
- **Searches are cached 24h** (refusals 2 min). Testing fetch changes needs
  `sources.clear_search_cache()` or `ARTICLEGEN_SEARCH_CACHE_TTL=0`.
- Everything structural is in `CLAUDE.md`. This file only carries what changed
  hands at the session boundary.

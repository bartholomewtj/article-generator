# Next session

_Last handoff: 13 August 2026 — `main` @ `850cc6c`, everything merged, nothing in flight_

## Where this stopped

`articlegen` turns a topic into a single-page HTML evidence review, formatted
like a journal Review article, grounded in paper abstracts plus open-access full
texts. It runs as a CLI and as a hosted web app (GitHub Pages front end → Render
backend).

**The whole issue backlog was worked through in one session** — 15 PRs, all
merged, nothing in flight. Ten issues fixed outright, four deliberately left
open because they need a run I could not do, and two new ones filed.

The suite went from ~640 checks to 844. `CLAUDE.md` shrank 573 → 445 lines with
the history moved to `docs/decisions.md`.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git branch --show-current && git status --short && python tests/test_offline.py && python tests/test_journal_conformance.py
```

Prints `main`, no file list, then `ALL PASS` and `ALL CONVENTIONS MET`. No keys,
no network. Verified at handoff. Branch and dirtiness come first on purpose
(#97): the tests print green even on a dirty tree on the wrong branch.

Drafting needs a provider, and **the default one is still broken** — see "Watch
out for". What works today:

```bash
python -m articlegen --model agy:gemini-3.6-flash-high draft "your topic"   # Gemini subscription
python -m articlegen --model cli:opus draft "your topic"                    # Claude subscription
```

## Next thing to do

1. **Get a working OpenRouter key.** It is the single blocker on all four open
   issues and on #134 and #135. `.env` holds a dead one (401 User not found,
   unchanged since 6 Aug); issue a new one at openrouter.ai/keys, then also add
   it as a repo secret so `live-smoke.yml` can run (#134).
2. **Run the four harnesses and close what they answer.** Each open issue now
   has the measurement built and a comment saying exactly what to paste back:
   `tools/compare_models.py "<topic>"` (#85), `tools/compare_curation.py
   --chars 400` (#117), one `agy:` draft for #116, any draft for #84.
3. **Generate two or three more example articles** into `drafts/` (#135) — the
   new free demo path currently points at an index of one.

## Open

- **#116** — `gemini-cli` revision call reports 135,273 input for a ~20,000-char
  prompt. All three providers now log `sent[chars= ~tok=]`; one `agy` run
  answers the ratio. Hypothesis in `docs/decisions.md`: the prompt is reachable
  three ways (`-p @file`, `--add-dir`, `cwd`). **Do not change those flags on a
  guess** — `--add-dir` is load-bearing.
- **#117** — curating on truncated abstracts saves ~24k input tokens.
  `tools/compare_curation.py` decides it. Accepts only if `direct` *and*
  `tangential` are stable; agreement on `related` is the failure mode, not a pass.
- **#85** — Opus 5 vs Sonnet 5 for the OpenRouter default. 2.5× cost gap,
  verified at $1.000 vs $0.400. `tools/compare_models.py` measures the countable
  half; the half that decides it needs you to read both drafts.
- **#84** — full-text coverage. Two of three questions now answered in code:
  every run says *which* limit bound it and prints the read-subset skew. The
  third (other open-access routes) needs data from a few runs.
- **#134** — `live-smoke.yml` needs `OPENROUTER_API_KEY` as a repo secret.
- **#135** — `drafts/` holds one article, so the new demo path is a list of one.

No open PRs. All 15 from this session are merged.

## Watch out for

- **A PR that touches `articlegen/**` now fails CI unless it also touches
  `CLAUDE.md`.** New gate, `docs-current.yml` (#114). The escape hatch is a line
  in the PR body: `Docs: n/a - <why>`. It is not a bug; do not delete the
  workflow when it goes red.
- **Never write "does not close #NNN" in a PR body or commit message.** GitHub's
  parser matches `close #NNN` and ignores the negation — this closed #84, #85
  and #117 on merge, all of which had to be reopened by hand. Write "Refs #NNN,
  stays open" instead.
- **`test_claude_md_still_describes_this_code` will push back on correct prose.**
  It checks every file, guard test and constant the docs name. Twice this
  session it flagged sentences *recounting* an old error (`pages.yml`, "Groq as
  the default"). Both times the right fix was the check, not the text — a doc
  guard that fails on true sentences trains you to ignore it.
- **The `OPENROUTER_API_KEY` in `.env` is dead.** `401 User not found` — revoked
  or the account went. Topping up will not help. This is why every run last
  session used `agy:`.
- **`agy` is the only working route to Gemini on your subscription.** The Google
  `gemini` CLI refuses to authenticate: `IneligibleTierError`.
- **Do not run the shallow stages at a cheaper reasoning tier.** Measured: at
  `-low` curation agreed with `-high` on only 14 of 20 relevance labels and
  collapsed everything toward "related" — that is the gate that stops topic
  drift. Both cheap tiers report `thinking=0`, which is the tell.
- **The SOURCE numbering has gaps.** `write_article` omits tangential sources by
  number and never re-packs, because the index *is* the citation scheme.
  Anything that renumbers to close a gap breaks `render` and `verify` together.
- **The sandbox must never gain `allow-scripts`** — that one flag hands back
  everything #100 closed.
- **Don't reinstate a source char budget.** It existed only for Groq's
  per-minute ceiling and takes full text away from every draft.
- **`/api/diag` is the only trustworthy answer** on which scholarly source works
  right now — never write it down, it flips. It now also probes Unpaywall.
- **Searches are cached 24h** (refusals 2 min). Testing fetch changes needs
  `sources.clear_search_cache()` or `ARTICLEGEN_SEARCH_CACHE_TTL=0`.
- Everything structural is in `CLAUDE.md`; the history behind it is in
  `docs/decisions.md`. This file only carries what changed hands at the session
  boundary.

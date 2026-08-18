# Next session

_Last handoff: 18 August 2026 — branch `main`, no open PRs_

## Where this stopped

PR #159 merged: articlegen now gets open-access full text through the `papers`
CLI (the separate, private `paperfetch` project) with the old Europe PMC path
as fallback. DOI-only papers with no PMCID — arXiv, anything non-biomedical —
are fetchable for the first time. Closed #150 and #151. Built by the claudeSSSF
`adw_simple_sdlc` workflow (session e54dda88, $2.53, one clean run) and
live-checked before merge: a medRxiv DOI with no PMCID returned 33k chars via
`papers`; a closed DOI returned `""` and fell back.

Earlier this month: PR #156 (ten-fix quality sweep, #139–#147) merged.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git checkout main && git pull && python tests/test_offline.py && python tests/test_journal_conformance.py
```

To use full text locally, `papers` must resolve. In Git Bash it is not on
PATH; either run from PowerShell or set
`ARTICLEGEN_PAPERS_CMD="python -m papers"` with paperfetch installed
(`pip install -e C:/claudeOS/Projects/paperfetch`). Set `PAPERS_MAILTO`.

## Next thing to do

1. **Regenerate a draft with full text on** and compare against
   `drafts/seclusion-restraint-cli.md` — first real look at #84 (full-text
   coverage) after slice 5. Check the Methods paragraph wording and the
   `(N via papers, M via Europe PMC)` log line.
2. **Set `SEMANTIC_SCHOLAR_API_KEY`** (free, semanticscholar.org/product/api) —
   closes the ops half of #148. Keyless S2 is measured-dead under shared limits.
   paperfetch reads the same variable.
3. **Decide the hosted deploy question**: Render cannot pip-install the private
   paperfetch repo, so the web app is still abstracts-only outside PMC. Options:
   make paperfetch public, or vendor it into the Docker image. Not urgent.

## Open

- #84 full-text coverage (should improve now — measure), #148 S2 key (ops),
  #134 live-smoke secret, #135 demo drafts index, #152–#154 homepage / brief
  render / cheaper hosted default.

## Watch out for

- **Live-smoke every ADW slice before merging.** Both suites are offline; the
  paperfetch project found a real bug (S2 429 on `%2F`) that way.
- **The factory lives in this repo** (`adws/`, `justfile`). `just obs` opens
  the run visualizer at localhost:4600. Requests go in `requests/` in the
  four-line shape (see `requests/slice-5-paperfetch.md`); run
  `uv run adws/adw_simple_sdlc.py requests/<file>.md` from a fresh branch.
- **Two stashes** hold leftovers from a failed pilot run — safe to
  `git stash drop` both. Local branch `fix/quality-improvements` is superseded
  by the #155 squash — safe to delete with `-D`.
- Everything from the 13 Aug note still applies (dead OpenRouter key, `agy` is
  the only Gemini route, docs-current CI gate, "Refs #NNN, stays open").

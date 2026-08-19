# Next session

_Last handoff: 19 August 2026 — branch `main`, no open PRs_

## Where this stopped

PR #160 merged (squash, `338eaab`). It repositions
the public site around "a sourced evidence briefing you can send": new
title/hero on `index.html`, three featured reviews linked straight into
`drafts/` above the setup card, drafts index retitled "Evidence reviews",
README and CLAUDE.md updated, new test
`test_the_landing_page_leads_with_finished_reviews`. Both suites green,
grok-4.5 reviewer approved 14/14. Closed #152. #135 still open.

Issue triage the same day: #154, #153, #148, #134 closed as not planned.

Built by claudeSSSF session `1bdf74c3` (~$2.06 notional). Not one clean run —
see "Watch out for".

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git checkout main && git pull && python tests/test_offline.py && python tests/test_journal_conformance.py
```

To use full text locally, `papers` must resolve. In Git Bash it is not on
PATH; either run from PowerShell or set
`ARTICLEGEN_PAPERS_CMD="python -m papers"` with paperfetch installed
(`pip install -e C:/claudeOS/Projects/paperfetch`). Set `PAPERS_MAILTO`.

## Next thing to do

1. **Look at the live GitHub Pages site** now that #160 has deployed — check
   the featured cards and the "Evidence reviews" index. Decide whether that is
   enough to close #135.
2. **Regenerate a draft with full text on** and compare against
   `drafts/seclusion-restraint-cli.md` — first real look at #84 (full-text
   coverage) after slice 5. Check the Methods paragraph wording and the
   `(N via papers, M via Europe PMC)` log line.
3. **Decide the hosted deploy question**: Render cannot pip-install the private
   paperfetch repo, so the web app is still abstracts-only outside PMC. Options:
   make paperfetch public, or vendor it into the Docker image. Not urgent.

## Open

- #84 full-text coverage (measure), #135 demo drafts index (probably closable
  now #160 is live). Nothing else open.

## Watch out for

- **agy CLI 1.1.15 dies after the agent finishes.** Two terminal errors in run
  `1bdf74c3`, both after the work was done and on disk: the builder's final
  result came back `ERROR invalid arguments: missing property 'toolSummary'`
  with the full envelope in `response`; the documenter was refused a
  `write_to_file` on `context_handoff/document.md` as "not a valid artifact
  path" (agy treats `.md` as its own artifacts) — the file had already been
  written. The adapter treats both as unrecognised and fails the phase. Both
  events are committed in `adws/adw_data/limit_events.jsonl`. Workaround that
  worked: rerun the build-first ADWs under the same `--adw-id`
  (`adw_build_test` → `adw_build_review` → `adw_document`), then commit by hand
  — none of those three commit. Candidate factory fix: accept an agy `ERROR`
  result whose `response` parses as the envelope. Not filed yet.
- **`adw_simple_sdlc` has no skip-on-rejoin** — `--adw-id` re-runs the planner
  and tries to commit the plan again. Resume with the build-first chains, not
  simple_sdlc.
- **Live-smoke every ADW slice before merging.** Both suites are offline; the
  paperfetch project found a real bug (S2 429 on `%2F`) that way.
- **The factory lives in this repo** (`adws/`, `justfile`). Requests go in
  `requests/` in the four-line shape (see
  `requests/issue-152-homepage-evidence-briefings.md`); run
  `PYTHONUTF8=1 AGY_PRINT_TIMEOUT=30m uv run adws/adw_simple_sdlc.py requests/<file>.md`
  from a fresh branch. Roster: opus planner, gemini-3.7-flash builder and
  documenter (agy), grok-4.5 reviewer.
- **Two stashes** hold leftovers from a failed pilot run — safe to
  `git stash drop` both. Local branch `fix/quality-improvements` is superseded
  by the #155 squash — safe to delete with `-D`.
- Everything from the 13 Aug note still applies (dead OpenRouter key, `agy` is
  the only Gemini route, docs-current CI gate, "Refs #NNN, stays open").

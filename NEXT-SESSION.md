# Next session

_Last handoff: 21 August 2026 — `main` has #165–#172_

## Where this stopped

The first-principles batch is on `main`: named-source snowball, design-weighted
deep reads, working-draft branding scoped, cite ~12, empty curation fails
loud, `--long` titles, Fig. 1 by design, idea-card search terms. Builder and
documenter now run `openrouter/google/gemini-3.7-flash` via pi (agy quota ran
out). Existing `drafts/` files were not regenerated.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git checkout main && git pull && python tests/test_offline.py && python tests/test_journal_conformance.py
```

To use full text locally, `papers` must resolve. In Git Bash it is not on
PATH; either run from PowerShell or set
`ARTICLEGEN_PAPERS_CMD="python -m papers"` with paperfetch installed
(`pip install -e C:/claudeOS/Projects/tools/paperfetch`). Set `PAPERS_MAILTO`.

## Next thing to do

1. **Generate one real briefing** (`articlegen draft "<question>" --open`) and
   read it. First look at the new artefact, and the first measurement of #165
   (did a named landmark come in first-hand?) and #166 (are the five deep reads
   reviews/trials?).
2. **#173** — pick one: vendor a minimal `papers get` into the Docker image, or
   say on the landing page that the hosted app is Europe PMC only. Do not do
   both. Do not put GitHub credentials in the Render build.
3. **#84** — measure full-text coverage on that new run (stop reason + read-subset
   skew). Close it if the log already answers; otherwise file what is still
   unknown.

## Open

- #173 hosted full text (Europe PMC only on Render) — needs a pick
- #84 full-text coverage — measure on a new run, not a code change yet

## Watch out for

- **Do not put `--long` on the web UI.** Parked on purpose.
- **Do not regenerate `drafts/`** unless asked. Those five Reviews are the
  public demo.
- **agy Gemini quota is exhausted.** Builder and documenter are
  `openrouter/google/gemini-3.7-flash` (pi, billed, ~$0.42 a builder run at
  the 75% headline discount). Scout is still agy — it will fail. Reviewer is
  still grok. Planner is still opus.
- **Do not leave `sssf.config.yaml` dirty during a run.** The reviewer is
  `writes: []`; a dirty roster file is blamed on the reviewer and rolled back,
  which fails the phase. Commit roster edits before launching.
- **Do not squash-merge the first PR of a stack.** #175 squash left #176–#183
  unmergeable on GitHub; the rest landed as one merge commit of
  `feat/172-idea-search-terms` into `main`.
- **A `?` in the briefing `question` field is allowed.** Other `?` still fail
  `rhetorical-question`.
- **agy CLI 1.1.15 dies after the agent finishes** (missing `toolSummary`;
  `.md` not a valid artifact path). Workaround: rerun build-first ADWs under
  the same `--adw-id`. Candidate factory fix not filed.
- Factory lives in this repo (`adws/`, `justfile`). Requests go in `requests/`
  in the four-line shape.
- Docs-current CI gate; write "Refs #NNN, stays open" never "does not close #NNN".

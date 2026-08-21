# Next session

_Last handoff: 21 August 2026 — `feat/briefing-first` merged as PR #174, closed #164_

## Where this stopped

Default artefact is now an **evidence briefing** (question, answer, findings,
unknowns, three papers to open). `articlegen draft --long` still writes the
journal-style Review. Ideas propose briefing questions; the popular-science
magazine register is gone. Existing files in `drafts/` are historical Reviews
and were not regenerated. Both suites were green on the PR.

The other first-principles recommendations are filed, not built.

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
   read it. First look at the new artefact, not another Review.
2. **Search batch, in this order:** #165 snowball named papers after curation,
   then #166 full-text order by design not recency. Those two change what the
   writer sees.
3. **#169** — stop branding leftover style nits as a working draft. Hits the
   page a reader copies.

## Open

Search and evidence: #165 snowball, #166 full-text by design, #167 cite ~12,
#168 fail loud when curation is empty.

What the page says: #169 working-draft branding, #170 `--long` titles,
#171 Fig. 1 / Cited by.

Process: #172 idea-card search terms, #173 hosted full text (Europe PMC only).

Older: #84 full-text coverage (measure on a new run), #135 drafts index
(probably closable; look at the live Pages site).

## Watch out for

- **Do not put `--long` on the web UI.** Parked on purpose.
- **Do not regenerate `drafts/`** unless asked. Those five Reviews are the
  public demo.
- **`LENGTH_LABEL` is now "Evidence briefing".** `test_house_style_is_fixed_not_a_preference`
  bans `Executive Briefing` as a register option; "Evidence briefing" is fine.
- **A `?` in the briefing `question` field is allowed.** Other `?` still fail
  `rhetorical-question`.
- **agy CLI 1.1.15 dies after the agent finishes** (missing `toolSummary`;
  `.md` not a valid artifact path). Workaround: rerun build-first ADWs under
  the same `--adw-id`, then commit by hand. Candidate factory fix not filed.
- **`adw_simple_sdlc` has no skip-on-rejoin.** Resume with build-first chains.
- Factory lives in this repo (`adws/`, `justfile`). Requests go in `requests/`
  in the four-line shape. Roster: opus planner, gemini-3.7-flash builder and
  documenter (agy), grok-4.5 reviewer.
- Docs-current CI gate; write "Refs #NNN, stays open" never "does not close #NNN".

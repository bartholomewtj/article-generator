# Next session

_Last handoff: 21 August 2026 — #194 on `main`; implement #189, then #188, #190, #192_

## Where this stopped

#191 is on `main` (PR #194). `queued_ckn` now counts as no-open-access, not
as “OA but empty”; #84 closed with it. Four Grok 4.6 briefings stay in
`drafts/` as measurement. Four slices still to implement:

| Slice | Issue | Request |
|---|---|---|
| Statistic check + revision | #189 | `requests/issue-189-statistic-revision.md` |
| Cite cap + pin question | #188 | `requests/issue-188-cite-cap-pin-question.md` |
| Generic names + paraphrase queries | #190 | `requests/issue-190-generic-names-distinct-query.md` |
| Table 1 design labels | #192 | `requests/issue-192-table1-design-labels.md` |

#173 is still a pick, not a slice. Do not implement it as part of these.

The public demo Reviews were not regenerated.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git checkout main && git pull && python tests/test_offline.py && python tests/test_journal_conformance.py
```

To use full text locally, `papers` must resolve. In Git Bash it is not on
PATH; either run from PowerShell or set
`ARTICLEGEN_PAPERS_CMD="python -m papers"` with paperfetch installed
(`pip install -e C:/claudeOS/Projects/tools/paperfetch`). Set `PAPERS_MAILTO`.

## Next thing to do

1. **Implement #189, then #188, #190, #192**, one slice per PR, factory
   requests already in `requests/`.
2. **#173** — pick one: vendor a minimal `papers get` into the Docker image, or
   say on the landing page that the hosted app is Europe PMC only. Do not do
   both. Do not put GitHub credentials in the Render build.

## Measured drafts (keep)

All `x-ai/grok-4.6`, 21 August 2026, local `papers` CLI on:

- `drafts/2026-08-21-psychosis-ed-grok-4.6` — 7 direct, cited 12, 1† / 20‡
- `drafts/2026-08-21-synthetic-substances-psychiatry-grok-4.6` — 13 direct, cited 12, 0† / 3‡ (`4.4-5.2` split)
- `drafts/2026-08-21-psych-ed-management-grok-4.6` — 7 direct, cited 12, 0† / 8‡; named-source `'Twelve study'`
- `drafts/2026-08-21-organic-causes-psychosis-grok-4.6` — 21 direct, cited 12, 0† / 0‡; question narrowed to first-episode

Do not delete or regenerate these. They are the evidence for #188–#190, #192.

## Open

- #189 statistic check + revision — ready (next)
- #188 cite cap + pin question — ready
- #190 generic names + distinct extra query — ready
- #192 Table 1 design labels — ready
- #173 hosted full text (Europe PMC only on Render) — needs a pick
- #185, #186, #187 — stay open until the slices above land

## Watch out for

- **Do not put `--long` on the web UI.** Parked on purpose.
- **Do not regenerate the public demo Reviews** in `drafts/` (the `*-cli` and
  `*-opus-5` files). The four `*-grok-4.6` briefings stay as measurement.
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
- **Grok `max_tokens` edits are in stash** `wip: grok max_tokens unrelated to 191`
  (`CLAUDE.md`, `articlegen/llm.py`, `tests/test_offline.py`). Do not fold them
  into a #188–#190 / #192 PR.

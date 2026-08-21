# Next session

_Last handoff: 21 August 2026 — #193 on `main`; implement #188–#192_

## Where this stopped

#193 is on `main`. Four Grok 4.6 briefings are in `drafts/`, labelled date +
`grok-4.6`. The measurement issues (#185–#187, #84) met their “two or more
runs” bar. Work is filed as five slices, ready to implement, not parked:

| Slice | Issue | Request |
|---|---|---|
| Cite cap + pin question | #188 | `requests/issue-188-cite-cap-pin-question.md` |
| Statistic check + revision | #189 | `requests/issue-189-statistic-revision.md` |
| Generic names + paraphrase queries | #190 | `requests/issue-190-generic-names-distinct-query.md` |
| `queued_ckn` tally | #191 | `requests/issue-191-queued-ckn-tally.md` |
| Table 1 design labels | #192 | `requests/issue-192-table1-design-labels.md` |

#173 is still a pick, not a slice. Do not implement it as part of #188–#192.

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

1. **Implement #188–#192**, one slice per PR, factory requests already in
   `requests/`. Suggested order: #191 (small, unblocks closing #84), then
   #189, #188, #190, #192.
2. **#173** — pick one: vendor a minimal `papers get` into the Docker image, or
   say on the landing page that the hosted app is Europe PMC only. Do not do
   both. Do not put GitHub credentials in the Render build.

## Measured drafts (keep)

All `x-ai/grok-4.6`, 21 August 2026, local `papers` CLI on:

- `drafts/2026-08-21-psychosis-ed-grok-4.6` — 7 direct, cited 12, 1† / 20‡
- `drafts/2026-08-21-synthetic-substances-psychiatry-grok-4.6` — 13 direct, cited 12, 0† / 3‡ (`4.4-5.2` split)
- `drafts/2026-08-21-psych-ed-management-grok-4.6` — 7 direct, cited 12, 0† / 8‡; named-source `'Twelve study'`
- `drafts/2026-08-21-organic-causes-psychosis-grok-4.6` — 21 direct, cited 12, 0† / 0‡; question narrowed to first-episode

Do not delete or regenerate these. They are the evidence for #188–#192.

## Open

- #188 cite cap + pin question — ready
- #189 statistic check + revision — ready
- #190 generic names + distinct extra query — ready
- #191 `queued_ckn` tally — ready; closes #84 when it lands
- #192 Table 1 design labels — ready
- #173 hosted full text (Europe PMC only on Render) — needs a pick
- #185, #186, #187, #84 — stay open until the slices above land

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
- **Unrelated dirty files may be on `main`** (`CLAUDE.md`, `articlegen/llm.py`,
  `tests/test_offline.py`). Do not fold them into a #188–#192 PR.

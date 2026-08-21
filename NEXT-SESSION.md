# Next session

_Last handoff: 21 August 2026 — #196–#199 on `main`; next is #173 (a pick)_

## Where this stopped

#189, #188, #190, and #192 are on `main` (PRs #196–#199, merge commits,
not squash). Statistic check includes titles, keeps hyphenated ranges
whole, and runs one revision pass. Cite ceiling is `min(12, n_direct+2)`;
question and title stay on the user's topic. Generic named-source lookups
are skipped; paraphrase search terms require one distinct extra query.
Table 1 prints `Other` and labels narrative / scoping / consensus / case
reports; Europe PMC `pubTypeList` is parsed; Fig. 1 widens past 6 design
buckets. Fallback-to-years is unchanged.

#185, #186, #187 closed with those slices. The four Grok 4.6 briefings
stay in `drafts/` as the measurement that produced the slices. Public
demo Reviews were not regenerated.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git checkout main && git pull && python tests/test_offline.py && python tests/test_journal_conformance.py
```

To use full text locally, `papers` must resolve. In Git Bash it is not on
PATH; either run from PowerShell or set
`ARTICLEGEN_PAPERS_CMD="python -m papers"` with paperfetch installed
(`pip install -e C:/claudeOS/Projects/tools/paperfetch`). Set `PAPERS_MAILTO`.

## Next thing to do

1. **#173** — pick one: vendor a minimal `papers get` into the Docker image,
   or say on the landing page that the hosted app is Europe PMC only. Do
   not do both. Do not put GitHub credentials in the Render build.
2. **Optional live check** — one new briefing (not the public demo Reviews)
   to see the four slices on a real run: cite cap, pinned question,
   generic-name skip, Table 1 labels.
3. **Grok `max_tokens` stash** — `wip: grok max_tokens unrelated to 191`
   (`CLAUDE.md`, `articlegen/llm.py`, `tests/test_offline.py`). Land it or
   drop it; do not fold it into a #173 PR.

## Measured drafts (keep)

All `x-ai/grok-4.6`, 21 August 2026, local `papers` CLI on:

- `drafts/2026-08-21-psychosis-ed-grok-4.6` — 7 direct, cited 12, 1† / 20‡
- `drafts/2026-08-21-synthetic-substances-psychiatry-grok-4.6` — 13 direct, cited 12, 0† / 3‡ (`4.4-5.2` split)
- `drafts/2026-08-21-psych-ed-management-grok-4.6` — 7 direct, cited 12, 0† / 8‡; named-source `'Twelve study'`
- `drafts/2026-08-21-organic-causes-psychosis-grok-4.6` — 21 direct, cited 12, 0† / 0‡; question narrowed to first-episode

Do not delete or regenerate these.

## Open

- #173 hosted full text (Europe PMC only on Render) — needs a pick

## Watch out for

- **Do not put `--long` on the web UI.** Parked on purpose.
- **Do not regenerate the public demo Reviews** in `drafts/` (the `*-cli` and
  `*-opus-5` files). The four `*-grok-4.6` briefings stay as measurement.
- **agy Gemini quota is exhausted.** Builder and documenter are
  `openrouter/google/gemini-3.7-flash` (pi, billed). Scout is still agy —
  it will fail. Reviewer is still grok. Planner is still opus.
- **Do not leave `sssf.config.yaml` dirty during a run.** The reviewer is
  `writes: []`; a dirty roster file is blamed on the reviewer and rolled
  back, which fails the phase. Commit roster edits before launching.
- **Do not squash-merge the first PR of a stack.** #175 squash left
  #176–#183 unmergeable; this stack (#196–#199) landed as merge commits.
- **A `?` in the briefing `question` field is allowed.** Other `?` still
  fail `rhetorical-question`.
- **agy CLI 1.1.15 dies after the agent finishes** (missing `toolSummary`;
  `.md` not a valid artifact path). Workaround: rerun build-first ADWs
  under the same `--adw-id`. Candidate factory fix not filed.
- Factory lives in this repo (`adws/`, `justfile`). Requests go in
  `requests/` in the four-line shape.
- Docs-current CI gate; write "Refs #NNN, stays open" never "does not
  close #NNN".
- **Grok `max_tokens` edits are in stash** `wip: grok max_tokens unrelated
  to 191`. Do not fold them into a #173 PR.

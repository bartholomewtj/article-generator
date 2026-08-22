# Next session

_Last handoff: 22 August 2026 — #205 on `main`; Pages stamp `21bc369`; Render still `e8fe9b4`_

## Where this stopped

Landing chrome is the workspace software look (#205). GitHub Pages
deployed; the live page stamps `21bc369` (Segoe UI, software tokens,
you-step on the topic box). Generated articles still use the journal
look. Render did not need a deploy — this was front end only.

#203 is still the running backend (`/api/health` → `"commit": "e8fe9b4"`,
`"public": true`, Luna).

A public OA-only sibling of paperfetch exists:
`bartholomewtj/paperfetch-oa` (`Projects\tools\paperfetch-oa`). Missing OA
is status `no_oa`. articlegen still only treats the private name as
"not OA".

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git checkout main && git pull && python tests/test_offline.py && python tests/test_journal_conformance.py
```

To use full text locally, `papers` must resolve. In Git Bash it is not on
PATH; either run from PowerShell or set
`ARTICLEGEN_PAPERS_CMD="python -m papers"` with the **private** paperfetch
installed (`pip install -e C:/claudeOS/Projects/tools/paperfetch`). Set
`PAPERS_MAILTO`. Do **not** `pip install` paperfetch-oa on this machine —
both packages own the `papers` command.

## Next thing to do

1. **Re-run delusional disorder** on the hosted site. That run branded
   itself a working draft over RADAR's "dose reduction" arm and left
   Cochrane unread. It is the check for all three #203 fixes.
2. **#173** — articlegen `NOT_OA_STATUSES` must accept `no_oa` (keep the
   private name too). Then add `paperfetch-oa` to the Docker image from
   the public git URL. Do not put GitHub credentials in the Render build.
   Do not also rewrite the landing page as "Europe PMC only" if you ship
   this — pick one story.
3. Leave local `papers` on the private package.

## Measured drafts (keep)

Public Luna, 21–22 August 2026 (dpaste, 30 days; the #203 baseline):

- `#p=CG5VQHDC7` — SC vs cannabis psychosis. 5 cited / 3 direct; Waters
  psych-admission likely from outside the abstract.
- `#p=HTTSX62CZ` — thyroid and FEP. 5 / 4; two meta-analyses unread.
- `#p=88BGDXUGM` — antipsychotics in delusional disorder. 4 cited / 2
  direct; false clinical-directive brand; Cochrane OA unread.
- `#p=6AJ5D2N3K` — stimulants and new-onset psychosis in ADHD. Best of
  the four (Moran numbers check).

Grok 4.6, 21 August 2026, local `papers` CLI on (git-tracked):

- `drafts/2026-08-21-psychosis-ed-grok-4.6`
- `drafts/2026-08-21-synthetic-substances-psychiatry-grok-4.6`
- `drafts/2026-08-21-psych-ed-management-grok-4.6`
- `drafts/2026-08-21-organic-causes-psychosis-grok-4.6`

Luna vs Gemini 3.7 Flash, 22 August 2026, local, **untracked**: lithium
toxicity, NMS, catatonia — one file pair per model. Do not delete. Do
not regenerate the public demo Reviews.

## Open

- #173 hosted full text — public package exists; articlegen + Docker not wired
- Phantom Fig. 1: briefings mention it, renderer does not draw it
- Methods grammar: `1 of which are cited`
- Cite floor: delusional-disorder run cited 4 against a floor of 5

## Watch out for

- **Do not put `--long` on the web UI.** Parked on purpose.
- **Do not regenerate the public demo Reviews** in `drafts/` (the `*-cli`
  and `*-opus-5` files). The four `*-grok-4.6` briefings stay as
  measurement.
- **The public key is a bill.** Rate limits (20/IP, 120/hour everyone)
  are the spend cap. Never commit it.
- **#203 adds a second write call** when any cited paper is OA (~2c extra
  on Luna).
- **agy Gemini quota is exhausted.** Builder and documenter are
  `openrouter/google/gemini-3.7-flash` (pi, billed). Scout is still agy —
  it will fail. Reviewer is still grok. Planner is still opus.
- **Do not leave `sssf.config.yaml` dirty during a run.** The reviewer is
  `writes: []`; a dirty roster file is blamed on the reviewer and rolled
  back, which fails the phase. Commit roster edits before launching.
- **Do not squash-merge the first PR of a stack.** #175 squash left
  #176–#183 unmergeable; #201 and #203 landed as merge commits.
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
- Local leftover: `tools/compare_models.py` is dirty (`wip: compare_models
  write-drafts`). Land or drop separately. Untracked Luna/Gemini ED
  drafts stay; do not commit unless asked.
- **Do not `pip install` paperfetch-oa locally.** It would replace the
  private `papers` CLI.
- **Landing chrome is house recipe software.** Do not restyle `render.py`
  journal HTML to match it.

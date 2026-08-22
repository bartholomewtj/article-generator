# Next session

_Last handoff: 22 August 2026 — #203 on `main`; next is a Render deploy, then #173_

## Where this stopped

Four public Luna briefings were read against the papers they cited.
Three product failures showed up on more than one run and are now on
`main` (#203, merge commit): trial-arm `dose reduction` is a report, not
advice; generic named lookups (`RCTs trial`, `International Clinical
trial`) are skipped; full text is fetched for **cited** sources, then the
briefing is rewritten if any cited OA lands.

Public generation is live (`/api/health` → `"public": true`, Luna). The
Render service is still built from `06f062c` (pre-#203). Blueprint
auto-sync is off, so a dashboard deploy is required before the three
fixes are on the hosted site.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git checkout main && git pull && python tests/test_offline.py && python tests/test_journal_conformance.py
```

To use full text locally, `papers` must resolve. In Git Bash it is not on
PATH; either run from PowerShell or set
`ARTICLEGEN_PAPERS_CMD="python -m papers"` with paperfetch installed
(`pip install -e C:/claudeOS/Projects/tools/paperfetch`). Set `PAPERS_MAILTO`.

## Next thing to do

1. **Deploy Render** — dashboard → `articlegen-api` → Manual Deploy of
   `main`. Then `curl https://articlegen-api.onrender.com/api/health`
   should show `"commit"` at `7c82a01` (or the #203 merge short hash).
   Until that, hosted drafts still fetch full text *before* the writer
   cites.
2. **Re-run delusional disorder** on the hosted site after the deploy.
   That run branded itself a working draft over RADAR's "dose reduction"
   arm and left Cochrane unread. It is the check for all three #203
   fixes.
3. **#173** — pick one: vendor a minimal `papers get` into the Docker
   image, or say on the landing page that the hosted app is Europe PMC
   only. Do not do both. Do not put GitHub credentials in the Render
   build.

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

- Render deploy of #203 — dashboard, not git
- #173 hosted full text (Europe PMC only on Render) — needs a pick
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

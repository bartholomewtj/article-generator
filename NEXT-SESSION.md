# Next session

_Last handoff: 22 August 2026 — run analytics on `run-analytics` (on top of
#211); Pages/Render still `5f74677` until this PR lands_

## Where this stopped

Website run analytics is built (`adw_id` `bc72253d`). Every `/api/ideas`,
`/api/draft` and `/api/gallery` request writes one JSON line to stderr.
Optional durable copy: set `ARTICLEGEN_ANALYTICS_GIST` on Render (secret
gist, same gist-scoped token as the gallery). No topic, key, IP, or
article text is logged.

#173 is shipped (#211). Hosted image installs public `paperfetch-oa`.
`NOT_OA_STATUSES` accepts `no_oa` and `queued_ckn`. `PAPERS_MAILTO` is
set on Render.

Public visitor gallery is live (#208). First real publish is up:

- **Measured energy and inference latency of GPUs, TPUs, and
  application-specific accelerators across AI workloads** (Luna, 22 Aug
  2026). 8 cited / 2 full text (Kong 2026 Scientific Reports, Xu 2020
  AutoDNNchip). Non-biomed topic — Europe PMC would have missed these;
  that is the #173 check.
- Gist: https://gist.github.com/bartholomewtj/cad249350b8e5c9a3f5237f69467c035
- Index: https://gist.github.com/bartholomewtj/3b864ca05620472d2644c3e9c1fd6a03

`/api/health` → `"commit": "5f74677"`, `"gallery": true`, Luna. Pages
stamps the same commit. Generating still does not publish; **Share to
gallery** asks first. Cap 50.

The GitHub PAT named **articlegen cloudsync api** is not used by the
site, Pages, or Render. Let it expire.

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

1. **Merge the `run-analytics` PR**, then create a secret gist
   (`gh gist create --secret runs.jsonl`) and set
   `ARTICLEGEN_ANALYTICS_GIST` on Render. Until that env is set, logs
   are stderr-only and die when the free instance sleeps.
2. **Re-run delusional disorder** on the hosted site. That run branded
   itself a working draft over RADAR's "dose reduction" arm and left
   Cochrane unread. It is the check for all three #203 fixes.
3. Phantom Fig. 1: briefings mention it (the GPU-energy one does),
   renderer does not draw it.
4. Leave local `papers` on the private package.

## Measured drafts (keep)

Hosted gallery (gist, public):

- GPU / TPU / ASIC energy and latency — 8 cited / 2 full text. First
  gallery item.

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
- **Do not put a repo-scoped GitHub token on Render.** Gallery token is
  gist scope only. The `gh` login on this machine has `repo`; that is
  the wrong secret.
- **#203 adds a second write call** when any cited paper is OA (~2c extra
  on Luna).
- **Roster after #211 is subscription:** opus planner, sonnet builder,
  haiku scout/documenter, grok-4.6 reviewer. agy still exhausted — do
  not put scout back on agy. Do not `pip install` paperfetch-oa locally.
- **Do not leave `sssf.config.yaml` dirty during a run.** The reviewer is
  `writes: []`; a dirty roster file is blamed on the reviewer and rolled
  back, which fails the phase. Commit roster edits before launching.
- **ADW tests run with `ARTICLEGEN_STATELESS=1`** (`adws/adw_modules/quality.py`).
  Without it the suite writes `drafts/index.html` (and stray briefings) and
  the reviewer treats that as a blocking miss.
- **Unapproved reviews are not replayed.** A rejected review is a successful
  phase, so the old checkpoint stored it and resume replayed the rejection
  even after the cause was fixed (`adws/adw_modules/tracer.py`).
- **Do not squash-merge the first PR of a stack.** #175 squash left
  #176–#183 unmergeable; #201, #203, #208 and #211 landed as merge
  commits.
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
  to 191`.
- Local leftover: `tools/compare_models.py` is dirty (`wip: compare_models
  write-drafts`). Untracked Luna/Gemini ED drafts stay; do not commit
  unless asked. A test-generated `drafts/2026-08-22-seclusion` pair was
  committed by the analytics ADW and then dropped — do not put it back.
- **Landing chrome is house recipe software.** Do not restyle `render.py`
  journal HTML to match it.

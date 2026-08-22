# Next session

_Last handoff: 22 August 2026 — #208 on `main` (`e5d755c`); Pages will stamp that; Render still `89b401d` at merge_

## Where this stopped

Public visitor gallery is on `main` (#208). Generating still does not
publish. **Share to gallery** asks first, then stores the briefing in a
public gist and lists it under **From other visitors**. Cap 50.

The Share button stays hidden until `ARTICLEGEN_GALLERY_TOKEN` is set on
Render (gist scope only — not repo). `/api/health` on the live backend
is still `"commit": "89b401d"` with no `gallery` field; auto-deploy of
`e5d755c` had not finished at this handoff. After deploy, look for
`"gallery": true` — false means the secret is still unset.

Index gist (public, empty until someone shares):
https://gist.github.com/bartholomewtj/3b864ca05620472d2644c3e9c1fd6a03

#207 stays open until that token is set.

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

1. **Set `ARTICLEGEN_GALLERY_TOKEN` on Render** (gist-only PAT). Then
   confirm `curl https://articlegen-api.onrender.com/api/health` shows
   `"gallery": true` and commit `e5d755c` (or later). Share one briefing
   and check the landing list.
2. **Re-run delusional disorder** on the hosted site. That run branded
   itself a working draft over RADAR's "dose reduction" arm and left
   Cochrane unread. It is the check for all three #203 fixes.
3. **#173** — articlegen `NOT_OA_STATUSES` must accept `no_oa` (keep the
   private name too). Then add `paperfetch-oa` to the Docker image from
   the public git URL. Do not put GitHub credentials in the Render build.
   Do not also rewrite the landing page as "Europe PMC only" if you ship
   this — pick one story.
4. Leave local `papers` on the private package.

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

- #207 gallery token on Render — code is merged; secret is not
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
- **Do not put a repo-scoped GitHub token on Render.** Gallery token is
  gist scope only. The `gh` login on this machine has `repo`; that is
  the wrong secret.
- **#203 adds a second write call** when any cited paper is OA (~2c extra
  on Luna).
- **agy Gemini quota is exhausted.** Builder and documenter are
  `openrouter/google/gemini-3.7-flash` (pi, billed). Scout is still agy —
  it will fail. Reviewer is still grok. Planner is still opus.
- **Do not leave `sssf.config.yaml` dirty during a run.** The reviewer is
  `writes: []`; a dirty roster file is blamed on the reviewer and rolled
  back, which fails the phase. Commit roster edits before launching.
- **Do not squash-merge the first PR of a stack.** #175 squash left
  #176–#183 unmergeable; #201, #203 and #208 landed as merge commits.
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

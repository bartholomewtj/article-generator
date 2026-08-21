# Next session

_Last handoff: 22 August 2026 — #201 on `main`; next is the Render secret, then #173_

## Where this stopped

Public web writes with GPT-5.6 Luna on a host-held OpenRouter key
(`ARTICLEGEN_PUBLIC_OPENROUTER_KEY`). Visitors do not paste a key. A keyless
request is forced to Luna — a crafted POST cannot select Opus on that bill.
CLI default is still Opus. Measured against Gemini 3.7 Flash on three
psychiatry ED topics (lithium toxicity, NMS, catatonia): Luna keeps the
question on the topic and names the shape of the evidence.

#201 is on `main` (merge commit, not squash). CI was green. The Render
secret is **not set yet** — until it is, the public site still asks for a
key.

#173 is still open (hosted full text is Europe PMC only). Do not fold it
into this.

## Resume with

```bash
cd /c/claudeOS/Projects/articlegenerator && git checkout main && git pull && python tests/test_offline.py && python tests/test_journal_conformance.py
```

To use full text locally, `papers` must resolve. In Git Bash it is not on
PATH; either run from PowerShell or set
`ARTICLEGEN_PAPERS_CMD="python -m papers"` with paperfetch installed
(`pip install -e C:/claudeOS/Projects/tools/paperfetch`). Set `PAPERS_MAILTO`.

## Next thing to do

1. **Set the Render secret** — dashboard → `articlegen-api` → Environment →
   `ARTICLEGEN_PUBLIC_OPENROUTER_KEY` (an OpenRouter key, as a secret).
   Blueprint auto-sync is off; the `render.yaml` line does not set it.
   Then `curl https://articlegen-api.onrender.com/api/health` should show
   `"public": true`. Worst-case spend is the hourly cap: 120 Luna drafts
   ≈ $2.40. Do not put the key in git.
2. **#173** — pick one: vendor a minimal `papers get` into the Docker image,
   or say on the landing page that the hosted app is Europe PMC only. Do
   not do both. Do not put GitHub credentials in the Render build.
3. **Grok `max_tokens` stash** — `wip: grok max_tokens unrelated to 191`
   (`CLAUDE.md`, `articlegen/llm.py`, `tests/test_offline.py`). Land it or
   drop it; do not fold it into a #173 PR.

## Measured drafts (keep)

Grok 4.6, 21 August 2026, local `papers` CLI on (git-tracked):

- `drafts/2026-08-21-psychosis-ed-grok-4.6` — 7 direct, cited 12, 1† / 20‡
- `drafts/2026-08-21-synthetic-substances-psychiatry-grok-4.6` — 13 direct, cited 12, 0† / 3‡ (`4.4-5.2` split)
- `drafts/2026-08-21-psych-ed-management-grok-4.6` — 7 direct, cited 12, 0† / 8‡; named-source `'Twelve study'`
- `drafts/2026-08-21-organic-causes-psychosis-grok-4.6` — 21 direct, cited 12, 0† / 0‡; question narrowed to first-episode

Luna vs Gemini 3.7 Flash, 22 August 2026, same pipeline (local, untracked
unless committed): lithium toxicity, NMS, catatonia — one file pair per
model. Do not delete. Do not regenerate the public demo Reviews.

## Open

- Render secret for public Luna — not in git, must be set in the dashboard
- #173 hosted full text (Europe PMC only on Render) — needs a pick

## Watch out for

- **Do not put `--long` on the web UI.** Parked on purpose.
- **Do not regenerate the public demo Reviews** in `drafts/` (the `*-cli` and
  `*-opus-5` files). The four `*-grok-4.6` briefings stay as measurement.
- **The public key is a bill.** Rate limits (20/IP, 120/hour everyone) are
  the spend cap. Never commit it.
- **agy Gemini quota is exhausted.** Builder and documenter are
  `openrouter/google/gemini-3.7-flash` (pi, billed). Scout is still agy —
  it will fail. Reviewer is still grok. Planner is still opus.
- **Do not leave `sssf.config.yaml` dirty during a run.** The reviewer is
  `writes: []`; a dirty roster file is blamed on the reviewer and rolled
  back, which fails the phase. Commit roster edits before launching.
- **Do not squash-merge the first PR of a stack.** #175 squash left
  #176–#183 unmergeable; #201 landed as a merge commit.
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
- Local leftover: stash `wip: compare_models write-drafts` (`compare_models.py`
  now writes drafts/ and uses the 40-paper pool). Land or drop separately.

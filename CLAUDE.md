# CLAUDE.md — project memory for `articlegen`

Context for a fresh session. Read this first.

## What this is

`articlegen` turns a topic into a **single-page HTML evidence review, formatted
like a scientific-journal Review article** (plus a Markdown copy), grounded in
journal-article abstracts. It runs two ways:

1. **Mobile Web Site** — hosted on GitHub Pages or locally via `articlegen web`.
2. **Local CLI** — `articlegen ideas` / `draft` / `queue` / `demo`.

## Repo / branch state (important)

- GitHub repo: **`bartholomewtj/article-generator`** (was `Dispatch-test` — old
  URLs still redirect).
- The default branch is currently the auto-generated name
  **`claude/article-generator-html-yth1u4`**. A rename to `main` was requested
  but must be done in the GitHub UI (Settings → Branches) — no API tool exposes
  it. Workflows reference the default branch dynamically, so a rename is safe.
- `drafts/` is intentionally git-tracked — it's the review surface.

## Architecture (module map)

```
articlegen/
  cli.py       subcommands (ideas / draft / queue / demo / web); file output only
  pipeline.py  THE draft pipeline — generate_draft(); every caller goes through it
  web.py       HTTP server + REST API for the web app UI
  llm.py       provider layer: ONE generate_json(); Groq or Claude backend
  ideas.py     LLM: theme -> shortlist of article ideas
  writer.py    LLM: plan_queries -> curate_sources -> write_article
  sources.py   Semantic Scholar + OpenAlex fetch, dedupe, relevance-blended rank
  verify.py    deterministic: flag article statistics absent from source abstracts
  style.py     deterministic: flag prose that breaks journal writing conventions
  render.py    structured article -> journal-format HTML + Markdown + drafts/ index
  demo.py      built-in sample for `articlegen demo` (no API/network)
docs/
  journal-style.md  the journal conventions we follow + where each came from
.github/workflows/
  pages.yml    deploy index.html & drafts/ to GitHub Pages
tests/
  test_offline.py             pure-logic tests; no network/keys
  test_journal_conformance.py journal conventions as assertions over 5 fixtures
```

Draft pipeline — **`pipeline.generate_draft()`, and nowhere else**: `plan_queries`
(queries + `core_entity`) → `gather_evidence` → `curate_sources` (relevance
labels) → `write_article` → `enforce_style` (`check_style`, and one
`revise_prose` pass if it finds errors) → `check_statistics` → a `Draft`
carrying the article, papers, curation, verification, style report and a
`provenance` dict (queries, model, date) that the deterministic **Methods**
section is written from. Keep provenance populated.

Callers differ **only** in what they do with the `Draft`: `cli.cmd_draft` writes
files into `drafts/` and rebuilds the index; `web._handle_draft` renders and
returns it. Never re-implement a stage in a caller — the web handler used to
have its own copy that silently skipped the style gate and provenance, which is
how web-generated articles ended up without the enforced hedging.
`test_pipeline_is_shared` fails if a caller starts calling stages directly.

## Article format (journal Review)

Output follows scientific-journal conventions; `docs/journal-style.md` is the
reference and cites the author instructions each convention came from. Read it
before changing the layout.

- Article schema (`writer._ARTICLE_SCHEMA`): `title`, `abstract` (Nature-style
  unstructured summary paragraph, 150–220 words, no citation markers),
  `keywords`, `evidence_note`, `featured_study`, `sections`, `key_points`,
  `glossary`, `references`. **`standfirst`, `key_takeaways` and `pull_quote` are
  gone** — `render.py` and `verify.py` still read the old names so drafts written
  against the previous schema keep rendering; don't drop those fallbacks.
- Sections must run `Introduction` → thematic sections → `Conclusions`.
- Three display items are built **deterministically** in `render.py` and must
  stay that way (they're the part a model can't fabricate): `Box 1` (featured
  study), `Fig. 1` (inline SVG of cited sources by year, segmented by relevance,
  themed through CSS variables), `Table 1` (the cited records). They interleave
  after sections 1, 2 and the penultimate one.
- Citations render as Nature superscripts after the punctuation, with runs of
  three or more collapsed (`.¹,³–⁵`). References are Vancouver/Nature form.
- Warnings are **prose in a Limitations paragraph**, not emoji callout boxes.

## Prose style (enforced, not just prompted)

`docs/journal-style.md` §13–18 records the writing conventions and their sources.
`style.py` turns them into a deterministic check that `cmd_draft` runs after
drafting; on any `error` it sends `revision_brief()` back through `revise_prose`
**once**, and keeps the revision only if it reduces the error count *and* leaves
citations and sections intact.

- Errors: second person, contractions, rhetorical questions, exclamations,
  boosters ("clearly", "striking", "unprecedented"), claims of proof
  ("proves", "definitively"), first person outside the `here we review` frame,
  and under-hedging (< 0.20 hedges/sentence).
- Warnings: sentences over 45 words, high nominalisation, passive ratio > 55%.
- Density rules only fire above 12 sentences **and** 250 words — below that the
  figures are noise. If you add a fixture, give it real prose or the rules skip it.
- Don't make this an LLM pass; a model asked "is this journal style?" agrees with
  itself. Same reasoning as `verify.py`.
- Never add fabricated journal apparatus — no invented journal name, volume,
  DOI, received/accepted dates, affiliations or ORCIDs. The masthead states
  "Not peer reviewed"; the back matter states that a machine wrote it.

## Serving (`web.py`)

Two modes, because a laptop and a shared host want opposite things:

- **Local** (default, `articlegen web`): writes each draft into `drafts/` and
  rebuilds the queue, matching the CLI.
- **Shared** (`ARTICLEGEN_STATELESS=1`, what the public deployment sets):
  renders and returns the article, persists nothing. A common `drafts/` on a
  shared host would make every visitor's article readable by every other
  visitor at a guessable URL and list their topics in the index.

Other env knobs: `ARTICLEGEN_ALLOWED_ORIGINS` (comma-separated; default `*` for
localhost, pinned to the Pages origin in production) and `ARTICLEGEN_RATE_LIMIT`
(per-IP requests/hour, default 20). The throttle exists because the scholarly
APIs meter against the *server's* IP — one abusive client throttles everyone.
It is charged only after validation, so a malformed request costs no quota.

## AI providers (`llm.py`)

- **API keys are passed per call**, never through `os.environ`. The server is
  threaded and the environment is process-global, so an env-var handoff lets one
  request's pipeline pick up another request's key mid-run and bill it to them.
  `generate_json(..., api_key=...)` and every wrapper takes it; `None` falls back
  to the environment, which is what the CLI uses. Guarded by
  `test_per_request_api_key`.
- **Groq is the default** (free tier / fast inference). `GROQ_API_KEY` is used
  automatically and wins even if `ANTHROPIC_API_KEY` is also set.
- Use Claude by setting repo variable `ARTICLEGEN_PROVIDER=anthropic`, passing a
  `claude-*` `--model`, or having only an Anthropic key.
- Default models: `llama-3.3-70b-versatile` / `claude-opus-4-8`.

## Grounding / trust design (why the pipeline is shaped this way)

- **Citations use the SOURCE-index scheme.** The writer cites papers by their fed
  "SOURCE N" label; `references` lists those N in first-citation order; `render`
  renumbers inline markers AND the Sources list to a matching 1..N. Don't assume
  inline numbers are already sequential.
- **Relevance gate.** `curate_sources` labels each paper direct/related/tangential
  to the *exact* topic; the writer is told the counts and must flag when nothing
  is directly on-topic and label extrapolation. Prevents topic drift (e.g. a
  "schizophrenia" article silently leaning on depression studies).
- **Statistic verification is deterministic** (`verify.py`), not an LLM pass — an
  LLM verifier can hallucinate agreement; substring presence in the real abstract
  can't. Figures not found in any abstract are flagged "verify against full text."
- **Abstracts only.** The writer never sees full text; it must not invent precise
  stats. Clinical topics get a "not medical advice" disclaimer (`_is_clinical`).

## Setup / testing

- Setup: `pip install -e .` (a SessionStart hook in `.claude/settings.json` runs
  `.claude/setup.sh` automatically in web sessions).
- **Offline tests (no keys/network):** `python tests/test_offline.py` — provider
  resolution, citation renumbering and superscript style, reference formatting,
  statistic verification, ranking, render blocks, display-item placement,
  legacy-schema drafts, prose-style gate.
- **Format conformance:** `python tests/test_journal_conformance.py` — asserts
  every convention in `docs/journal-style.md` over five fixture articles
  (including no-direct-sources, sparse metadata, and a 40-year source range).
  Run this after any render change; add a convention here when you add one there.
- Rendered pages can be eyeballed with the preinstalled Chromium:
  `articlegen demo -o /tmp/demo.html` then screenshot it with Playwright
  (`NODE_PATH=/opt/node22/lib/node_modules`, `executablePath: '/opt/pw-browsers/chromium'`).

## Environment setup

- Set `GROQ_API_KEY` (free key at console.groq.com) or `ANTHROPIC_API_KEY`.
- Optional: `SEMANTIC_SCHOLAR_API_KEY` and `OPENALEX_MAILTO` raise scholarly-API rate limits.

## Conventions

- Keep all LLM calls behind `llm.generate_json`; don't call the SDKs directly
  from `writer.py` / `ideas.py`.
- New structured-output schemas must produce valid JSON matching the schema — avoid
  `additionalProperties` reliance and unsupported JSON-Schema constraints.
- Add a case to `tests/test_offline.py` for any new pure-logic behavior.

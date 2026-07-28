# CLAUDE.md — project memory for `articlegen`

Context for a fresh session. Read this first.

## What this is

`articlegen` turns a topic into a **single-page HTML evidence review, formatted
like a scientific-journal Review article** (plus a Markdown copy), grounded in
journal-article abstracts. It runs two ways:

1. **Local CLI** — `articlegen ideas` / `draft` / `queue` / `demo`.
2. **GitHub-issue workflow (mobile-first)** — open an issue titled `theme: …`
   → a bot comments article ideas → reply `draft N` → the draft is committed to
   `drafts/` and linked back in a comment. Driven from the GitHub mobile app.

## Repo / branch state (important)

- GitHub repo: **`bartbtc/article-generator`** (was `Dispatch-test` — if a rename
  hasn't happened yet, old URLs still redirect).
- The default branch is currently the auto-generated name
  **`claude/article-generator-html-yth1u4`**. A rename to `main` was requested
  but must be done in the GitHub UI (Settings → Branches) — no API tool exposes
  it. Workflows reference the default branch dynamically, so a rename is safe.
- `drafts/` is intentionally git-tracked — it's the review surface.

## Architecture (module map)

```
articlegen/
  cli.py       subcommands + orchestration (ideas / draft / queue / demo / web)
  web.py       HTTP server + REST API for mobile web app UI
  llm.py       provider layer: ONE generate_json(); Claude or Gemini backend
  ideas.py     LLM: theme -> shortlist of article ideas
  writer.py    LLM: plan_queries -> curate_sources -> write_article
  sources.py   Semantic Scholar + OpenAlex fetch, dedupe, relevance-blended rank
  verify.py    deterministic: flag article statistics absent from source abstracts
  render.py    structured article -> journal-format HTML + Markdown + drafts/ index
  bot.py       GitHub Actions glue: build ideas comment, parse `draft N`
  demo.py      built-in sample for `articlegen demo` (no API/network)
docs/
  journal-style.md  the journal conventions we follow + where each came from
.github/workflows/
  ideas.yml    'theme: …' issue opened  -> ideas posted as a comment
  draft.yml    'draft N' comment         -> draft committed + review links
  pages.yml    deploy index.html & drafts/ to GitHub Pages
tests/
  test_offline.py             pure-logic tests; no network/keys
  test_journal_conformance.py journal conventions as assertions over 5 fixtures
```

Draft pipeline (in `cli.cmd_draft`): `plan_queries` (queries + `core_entity`) →
`gather_evidence` → `curate_sources` (relevance labels) → `write_article` →
`check_statistics` → `render_article` + `render_markdown` → commit + `build_index`.
`cmd_draft` also passes a `provenance` dict (queries, model, date) that the
deterministic **Methods** section is written from — keep it populated.

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
- Never add fabricated journal apparatus — no invented journal name, volume,
  DOI, received/accepted dates, affiliations or ORCIDs. The masthead states
  "Not peer reviewed"; the back matter states that a machine wrote it.

## AI providers (`llm.py`)

- **Gemini is the default** (free tier). `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
  is used automatically and wins even if `ANTHROPIC_API_KEY` is also set.
- Use Claude by setting repo variable `ARTICLEGEN_PROVIDER=anthropic`, passing a
  `claude-*` `--model`, or having only an Anthropic key.
- Default models: `gemini-flash-latest` / `claude-opus-4-8`.
- **Gemini gotchas already handled** — don't regress these:
  - Model auto-discovery: if the configured model 404s ("no longer available"),
    it lists the key's models and picks a current flash-tier one (cached).
  - Transient 503/429 retried with backoff.
  - `thinking_budget=0` on the JSON calls (2.5-flash thinking runs away under
    structured output and truncates into invalid JSON).
  - Schema translation strips `additionalProperties` and converts
    `["T","null"]` unions to nullable (Gemini rejects both).

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
  resolution, Gemini schema translation, model discovery, citation renumbering
  and superscript style, reference formatting, statistic verification, ranking,
  render blocks, display-item placement, legacy-schema drafts, bot parsing.
- **Format conformance:** `python tests/test_journal_conformance.py` — asserts
  every convention in `docs/journal-style.md` over five fixture articles
  (including no-direct-sources, sparse metadata, and a 40-year source range).
  Run this after any render change; add a convention here when you add one there.
- Rendered pages can be eyeballed with the preinstalled Chromium:
  `articlegen demo -o /tmp/demo.html` then screenshot it with Playwright
  (`NODE_PATH=/opt/node22/lib/node_modules`, `executablePath: '/opt/pw-browsers/chromium'`).
- **Live end-to-end** can't be tested offline (needs a Gemini key + scholarly-API
  access from a GitHub runner). Verify by opening a `theme:` issue on GitHub and
  watching for the ideas comment, then reply `draft N`.

## One-time GitHub setup (for the workflow to run)

- Add repo **secret** `GEMINI_API_KEY` (free key at aistudio.google.com).
- Optional: `SEMANTIC_SCHOLAR_API_KEY` secret and `OPENALEX_MAILTO` variable
  raise scholarly-API rate limits.
- Workflows are gated to OWNER/MEMBER/COLLABORATOR so strangers can't spend API
  quota. Failure comments show which provider keys the run saw + the error detail.
- **Tappable "Read the article" link.** The draft comment links each article
  through `https://htmlpreview.github.io/?<blob-url>`, which renders the styled
  page as a live web page in the browser (the HTML is fully self-contained —
  inline CSS, no external assets). This needs the **repo to be public** (the
  proxy fetches raw content anonymously); it is. No Pages/setup required. If the
  repo ever goes private again, this link 404s — switch to GitHub Pages
  (`Settings → Pages → Source: GitHub Actions`, publishing `drafts/`) instead.

## Conventions

- Keep all LLM calls behind `llm.generate_json`; don't call the SDKs directly
  from `writer.py` / `ideas.py`.
- New structured-output schemas must survive `llm._gemini_schema` — avoid
  `additionalProperties` reliance and unsupported JSON-Schema constraints.
- Add a case to `tests/test_offline.py` for any new pure-logic behavior.

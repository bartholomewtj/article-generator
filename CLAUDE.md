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
- **The default branch is now `main`** (renamed from the auto-generated
  `claude/article-generator-html-yth1u4`, issue #47). Old URLs still redirect.
- **Render followed the rename by itself**, which the old note here said it
  would not. It builds from `main` and reports so. What that note got right is
  that `render.yaml` cannot move it: Blueprint auto-sync is off for this service
  — measured, by setting `branch:` and watching a deploy stay put. So the
  `branch:` line is a record, not a control.
- **`GET /api/health` reports the branch and commit the running service was
  actually built from.** That is what made the rename safe to attempt at all: it
  turned "deploys may have silently stopped" into a one-line check, and it is how
  every claim in these two bullets was verified rather than assumed.
- The `github-pages` **environment** carries its own branch allowlist, separate
  from `pages.yml`'s trigger list, and it silently rejected `main` until `main`
  was added to it (`gh api .../environments/github-pages/deployment-branch-policies`).
  A branch rename has to consider both.
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
  sources.py   Semantic Scholar + OpenAlex + Europe PMC fetch, 24h result cache,
               dedupe, relevance-blended rank; open-access full-text fetch +
               the excerpt budget both writer and verifier derive from
  verify.py    deterministic: flag article statistics absent from what the
               writer was shown (abstracts + full-text excerpts)
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
  `featured_study.why` is gone too, replaced by `limitations`; old drafts still
  carry `why` and the renderer must keep ignoring it silently.
- Sections must run `Introduction` → thematic sections → `Conclusions`.
- Three display items are built **deterministically** in `render.py` and must
  stay that way (they're the part a model can't fabricate): `Box 1` (featured
  study: Method / Results / Limitations, no editorial "why" line), `Fig. 1`
  (inline SVG of cited sources by year, segmented by relevance, themed through
  CSS variables), `Table 1` (the cited records). Layout (owner's preference,
  recorded in `docs/journal-style.md` §3/§6): Fig. 1 after the Introduction,
  Box 1 after the first thematic section, **key points directly before the
  concluding section** (not under the abstract), and **Table 1 in the back
  matter after Methods** — never mid-prose.
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
- **`tests/real_abstracts.json` is the guard against these rules being wrong.**
  Every rule is a guess about journal prose, and checking them against real
  published abstracts is what exposed the guesses that were wrong: the
  first-person allowlist required "we" immediately followed by an approved verb,
  so "we also review" / "we searched" / "we aimed to" all failed, and three more
  false positives were clinical notation — `Axis I`, `I2 = 70.6%` (heterogeneity)
  and `US $16.3 million` all matched a first-person pronoun. Add to the corpus
  before adding a rule; two entries carry a documented expected failure, one of
  which is a positive control.
- **`tests/style_corpus.json` is the second corpus, and it answers a different
  question.** 20 high-cited abstracts, 20 journals, stratified across article
  type (primary / systematic review / narrative review) × domain (clinical
  psychiatry / neuroscience / health services) — all nine cells. Two findings are
  now pinned by tests and written up in `docs/journal-style.md`:
  - **The register rules model one voice: a synthesis speaking about other
    people's work.** A trial report legitimately says "we randomly assigned
    patients"; `articlegen` must not, because it ran nothing. The split is total —
    7/7 investigator-voice abstracts fire a register rule, 0/13 synthesis-voice
    ones do. So a primary-research abstract is *not* a negative control for the
    first-person rule, which is what the older corpus was papering over with
    per-entry exceptions.
  - **The hedging floor (0.20/sentence) is correct — but only body prose shows
    it.** Published *abstracts* run at a median of 0.031, which looked damning
    until the right comparison was made. `tests/body_prose_measurements.json`
    holds the statistics for the body paragraphs of 18 open-access reviews
    (Lancet, BMJ, PLoS, Frontiers): **median 0.216 hedges/sentence, median 12
    distinct hedges**, and all 18 are long enough for the density gate where only
    2 of 20 abstracts are. The floor sits on the median of the register we write
    in. Don't re-open this with abstract data; that is the wrong text type, and
    it is the mistake #56 was originally filed over.
  - **`hedge-monotony` needs volume before it means anything.** Requiring no
    single marker above 40% implies three distinct hedges, which body prose
    easily supplies (median 12) but a short draft does not: at 7 hedges, 3 of one
    is 43%, so one extra "suggest" flips a pass to a fail with no change in
    quality. `MIN_HEDGES_FOR_MONOTONY = 8` gates it.
  - The passive-ratio and sentence-length thresholds *do* check out against the
    same corpus, which is what makes the §15 result a signal rather than an
    artefact.
- **Hedges and softeners are separate lists.** Frequency/degree adverbs (often,
  typically, generally, approximately, relatively) do not qualify a claim's
  evidential strength, so they are counted but never satisfy the hedging floor —
  otherwise "approximately 40%... typically higher... often persist" scores 1.0
  hedges/sentence while hedging nothing. `cannot be` is not a hedge either; it
  asserts certainty.
- **Nominalisation counting was deleted, deliberately.** It counted every
  -tion/-sion/-ment/-ance/-ence/-ity/-ism word against an 11% threshold, which in
  this domain measures the topic: a routine clinical sentence scores 42% because
  depression, treatment, intervention, assessment and population are the subject
  matter. Don't reinstate it without a domain stoplist.
- **The section floor scales with the evidence** (`_required_sections`). A flat
  floor of 5 is a thinness rule that causes thinness: told to produce five
  sections from three usable abstracts, the cheapest way to fill the fifth is to
  restate the fourth. `enforce_style` passes the direct-source count in.
- **Substance errors** (`SUBSTANCE_RULES`): `too-few-sections`, `hedge-monotony`,
  `repeated-opener`, `recycled-phrasing`, `echoed-abstract`, `bundled-citations`.
  Every other rule is a *prohibition*,
  and a model optimising only against prohibitions writes vague hedged filler —
  asserting nothing breaks no rule. A real draft passed every check at 803 words
  with one number in it, hedging at 0.69/sentence (three times the floor) using
  four stock phrases. These fail a draft for saying too little.
- **Calibrate against `demo.SAMPLE_ARTICLE`.** It must always pass. Length does
  *not* discriminate — the good sample is 773 words, the bad draft was 803 — so
  `under-length` is a warning, not an error. What separates them is hedge variety
  (8 distinct hedges vs one phrase at 50%) and verbatim recycling.
- **The abstract, key points and Introduction are three jobs, not three renderings
  of one paragraph.** The schema used to ask all three to be self-contained
  summaries — `key_points` said "a reader must be able to take the whole claim
  from these alone" — so the model dutifully wrote the same paragraph three times.
  A shipped draft repeated 38% of the abstract's 6-word runs in its Introduction
  and 24% in its key points. `echoed-abstract` measures that share (threshold
  0.12; the curated sample scores 0% and 2.4%), and the writer prompt now carries
  a DIVISION OF LABOUR block. Don't reinstate "self-contained" wording on more
  than one of the three fields.
- **`bundled-citations`**: a source cited only ever inside a bundle (`[1, 4]`) has
  had nothing said about it individually. Fires when more than a third of cited
  sources never appear as a solo marker. A bundle asserts studies agree; it has
  to be earned by first reporting what each one found.
- When a substance rule fires, `revision_brief()` **inverts**: instead of "do not
  introduce new claims or numbers" it tells the model to pull specific findings
  from the sources, and `enforce_style` passes `papers`/`curation` into
  `revise_prose` so it has something to pull from. Without that the revision can
  only reshuffle what it already wrote, and a thin draft comes back thin.
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

`protocol_version = "HTTP/1.1"` is load-bearing. http.server defaults to
HTTP/1.0, which closes the connection after every response; browsers and proxies
pool connections and then fail instantly on a socket the server already hung up
on. It presents as flaky networking — about half of all fetches failing in
~140ms — and **curl cannot reproduce it**, because each invocation opens a fresh
connection. Only a pooling client sees it.

## Deployment

```
index.html on GitHub Pages  ──POST /api/draft──▶  backend on Render
   (static, holds the key)                        (stateless, holds nothing)
```

- **Front end**: GitHub Pages, deployed by `.github/workflows/pages.yml` on push
  to the default branch. `API_BASE` in `index.html` points at the backend.
- **Backend**: Render free tier, service `articlegen-api`, declared in
  `render.yaml` (Blueprint). Deploys from GitHub; there is no workflow and no
  token. URL `https://articlegen-api.onrender.com` — must stay in step with
  `name:` in `render.yaml`, since the subdomain derives from it.
- Free tier sleeps after 15 min idle and takes ~50s to wake. That is tolerable
  only because the page is static and the backend is touched solely by
  *Generate*, which already runs 40-90s behind a progress bar.
- **Hugging Face Spaces was tried and abandoned**: free CPU Spaces require a
  payment method, and without one the Space is created but pinned at
  `Quota exceeded for flavor cpu-basic ... limit=0` forever. Fly.io fails the
  same no-card constraint by its own docs. Don't re-litigate either.
- `GET /api/diag` runs one keyless search and reports what *that host* gets back
  from the scholarly APIs. It exists because everything works locally, so a
  deployment reporting "no papers found" is otherwise undiagnosable from outside.
  It bypasses the search cache (a cached answer can't tell you what the sources
  are doing now) and is therefore rate-limited like drafting: each call spends
  real quota. Its per-source `cached` flag is always `false`; in `/api/draft`
  logs it may be `true`.

### The scholarly APIs are the actual constraint — measure, don't assume

Both open sources refuse constantly from Render's shared egress IP, and **which
one is failing changes**. Do not write down "X is the working source": in a
four-call sample on 4 Aug 2026, OpenAlex 429'd every time with a cool-off longer
than 30s, while Semantic Scholar — which earlier notes and issue #32 recorded as
never working — answered once. Earlier notes had it exactly the other way round.
Run `/api/diag` and read the result rather than trusting any claim here.

`OPENALEX_MAILTO` **is** set on the deployment, and joining the polite pool did
not fix OpenAlex. The constraint is the shared cloud IP, not the contact
address. This is also why moving region is not a fix — a different Render region
is a different shared IP with the same problem — and why Europe PMC (no key, no
contested keyless pool, biomedical coverage that suits the mental-health topics
this gets used for) is the durable answer rather than more header tuning.

## AI providers (`llm.py`)

- **API keys are passed per call**, never through `os.environ`. The server is
  threaded and the environment is process-global, so an env-var handoff lets one
  request's pipeline pick up another request's key mid-run and bill it to them.
  `generate_json(..., api_key=...)` and every wrapper takes it; `None` falls back
  to the environment, which is what the CLI uses. Guarded by
  `test_per_request_api_key`.
- **Three providers: Groq, OpenRouter, Anthropic.** Groq is the default (free
  tier / fast inference); `GROQ_API_KEY` is used automatically and wins even if
  the others are also set. The web app offers all three in Settings, storing a
  key per provider.
- **OpenRouter's default is Claude Fable 5** (`anthropic/claude-fable-5`, at
  Anthropic's pass-through pricing: $10/$50 per million tokens, so roughly
  $1–2 per article). It used to default to the same Llama 3.3 70B as Groq,
  but the #63/#64 model test pinned the quality problems on the Llama writer,
  so the default follows the quality. OpenRouter still bills prepaid credit
  with no daily allowance — a run never fails because the day's quota is
  spent. Pass `meta-llama/llama-3.3-70b-instruct` with `--model` when cost
  matters more than prose.
  - **A slash is what makes a model name an OpenRouter slug**, and it is checked
    *before* the `claude` prefix in `resolve_provider`. OpenRouter re-sells the
    other providers' models as `vendor/model`, and `anthropic/claude-sonnet-5`
    routed to Anthropic's own SDK is a 404. No direct provider's model id
    contains a slash, so the discriminator is unambiguous.
  - **`provider: {"require_parameters": true}` is load-bearing.** Without it
    OpenRouter may route to a provider that ignores `response_format`, and the
    article comes back as prose — which reads like the model being bad at
    instructions rather than a routing choice. The schema also goes in the
    system prompt, same belt-and-braces as the Groq path.
  - Implemented with `requests` against the OpenAI-compatible endpoint; no new
    dependency. A 200 can still carry an `error` body (no provider matched, or
    an upstream refusal), so that is checked separately from the status code.
- **Groq's free tier is the binding constraint, and it bites twice.**
  - **12,000 tokens/minute.** Groq counts the *reserved output* against this as
    well as the prompt, so `max_completion_tokens` must fit inside the limit —
    the article call once reserved 16,000 against a 12,000 ceiling, which could
    never succeed regardless of prompt length. `llm.prompt_budget_chars()`
    sizes the source payload; `_format_sources` shortens long abstracts before
    dropping any paper, because breadth is what stops sections repeating.
  - **100,000 tokens/day.** One article costs ~14-23k (more when the substance
    rules trigger a revision), so the free tier allows roughly **4-7 articles a
    day**, and failed attempts still spend quota. Neither Claude nor OpenRouter
    has a comparable ceiling, and `prompt_budget_chars` returns `None` for both —
    so even Llama via OpenRouter (`--model meta-llama/llama-3.3-70b-instruct`)
    runs untrimmed, which is correct: the ceiling is the tier's, not the model's.
- Select a provider by setting `ARTICLEGEN_PROVIDER` (`anthropic` / `openrouter`
  / `groq`), passing a `--model` that identifies one, or having only that
  provider's key set.
- Default models: `llama-3.3-70b-versatile` / `anthropic/claude-fable-5`
  / `claude-fable-5`. Model ids live in **two** places — `llm.py` and the
  `PROVIDERS` map in `index.html`. Nothing links them, and `web._requested_model`
  silently drops an unrecognised name rather than erroring, so a stale front end
  quietly stops honouring the provider the user picked.
  `test_front_end_models_match_the_allowlist` catches the drift; change both
  together.
- **On Claude Opus 5, thinking is on unless you say otherwise**, and `max_tokens`
  caps thinking *plus* the reply. The shallow (`deep=False`) call was sized for
  Opus 4.8, which did not think by default, so its ceiling was raised to 16,000
  — the curation call grades twenty sources in one response and a truncated
  reply is invalid JSON, not a short one. `_anthropic_generate` also handles
  `stop_reason` of `refusal` and `max_tokens` explicitly: a refusal returns a
  normal 200 with no text block, which otherwise surfaced as a bare
  `StopIteration`. On Opus 5 (and Fable/Mythos) the call also opts into the
  server-side refusal fallback (`fallbacks: "default"` +
  `server-side-fallback-2026-07-01` beta, issue #45), so a classifier false
  positive is re-served by Anthropic's recommended substitute model inside the
  same call; a visible refusal error now means the fallback declined too.
  Older models reject the parameter — `_refusal_fallback_kwargs` attaches it
  by model prefix, and every Anthropic call goes through `client.beta.messages`.

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
- **Abstracts plus open-access full text — with one invariant.** After curation,
  the pipeline fetches full text for direct/related sources that Europe PMC can
  serve (PMCID + both OA flags; `MAX_FULLTEXT_FETCHES` bounds the HTTP calls).
  The writer is shown excerpts derived by `sources.full_text_excerpts` —
  deterministic per-paper and total char caps — and `verify.check_statistics`
  searches **exactly those excerpts plus the abstracts, never the unseen tail
  of a paper**: verifying against text the writer was not shown would let a
  figure recalled from training pass as grounded. Because both sides call the
  same function, nothing has to be recorded per run. Groq never gets full text
  (its TPM ceiling cannot fit any); there the draft stays abstracts-only and
  says so. `provenance["full_text_sources"]` records what was actually
  fetched — the Methods sentence is written from it, same no-fallback rule as
  `databases`. **Every other statement about grounding counts the *cited*
  papers instead** (`render._full_text_count`), because that is what Table 1's
  Read column shows and the two must never disagree. Getting this wrong
  shipped an article that said "full texts of 7 sources were retrieved" in
  Methods and "prepared from abstracts alone" in Limitations, under an
  "Abstract-derived synthesis" masthead (#75): Methods branched on provenance
  while four other statements stayed hardcoded to the abstracts-only wording.
  `_synthesis_label` and `_read_phrase` own that wording now, and
  `test_full_text_grounding` asserts a mixed-grounding article renders none of
  the abstracts-only phrases in either output format. The full-text framing of the
  system prompt is derived from the abstracts-only one by substitution
  (`_FULLTEXT_SUBSTITUTIONS`) so the two cannot drift; a test pins every
  target. Full texts get their bracketed citation numbers stripped at parse
  time — they collide with the [N] SOURCE-index scheme. Known bias: the
  deeply-read subset skews open-access, which Table 1 makes visible
  per-source. Clinical topics get a "not medical advice" disclaimer
  (`_is_clinical`).
- **Methods must name only databases that actually answered.** It used to read
  them from a constant in `render.py`, so every article claimed both Semantic
  Scholar and OpenAlex had been searched while one of them was 429ing every
  request. That made the claim false in every article produced, in the one
  section whose purpose is to state what was done. `provenance["databases"]` is
  derived from sources that returned records. If you add a source, add it to
  `sources.DATABASE_NAMES`; never hardcode the list again — including **as a
  fallback**, which is how it came back the first time: the constant survived as
  `provenance.get("databases") or _DATABASES` and went on making the same false
  claim for every draft whose provenance lacked the key. There is now no
  fallback. An unrecorded search says "the databases searched were not recorded
  for this draft" and names nothing.
- **Ranking**: topic overlap is the primary key, then `citation_weight +
  recency`. Recency was once `year / 1000` — spanning 0.02 across two decades
  against a citation term spanning 0-4, so it was a rounding error and old
  heavily-cited reviews always won (a real search returned a median paper year
  of 2013). It now decays over `RECENCY_HALF_LIFE` on the citation term's scale.
  Ranking matters more than it looks: it decides what the writer sees first,
  which paper is featured, and **which papers survive the Groq token trim**,
  since the lowest-ranked are dropped first.
- **A source that refuses once is skipped for the rest of the run**
  (`gather_evidence`'s `exhausted` set). Each attempt is three tries with
  backoff, ~10s, while the limits are per-minute and a run takes seconds —
  retrying a dead source across every query cost more than half the gather time.
  Live: 31.1s before, ~14s after. Source keys are explicit, never derived from
  `search.__name__` — that is not a stable identity and two lambdas collide.
  Note the interaction with `_MAX_BACKOFF`: a source asking for a cool-off
  longer than 30s fails *immediately, without retrying*, and is then exhausted —
  so one long `Retry-After` removes a source from the whole run rather than
  slowing it down. Assume you are running on fewer sources than the code lists.
- **Searches are cached** (`sources._search_cache`, 24h; refusals 2 min). The
  literature for a topic does not change hour to hour, but these free tiers
  refuse constantly, so re-running the same query is likelier to fail than to
  return anything new. This is what makes a demo repeatable and what stops a
  retry storm deepening a throttle. `clear_search_cache()` for tests;
  `ARTICLEGEN_SEARCH_CACHE_TTL=0` disables it. The cache is consulted *before*
  the `exhausted` set, so an already-refused source can still contribute stored
  results. `/api/diag` passes `use_cache=False` — it exists to report what the
  sources are doing right now, which a cached answer cannot do, and it is
  rate-limited precisely because that makes each call cost real quota.

## Setup / testing

- Setup: `pip install -e .` (a SessionStart hook in `.claude/settings.json` runs
  `.claude/setup.sh` automatically in web sessions).
- **Offline tests (no keys/network):** `python tests/test_offline.py` — provider
  resolution, citation renumbering and superscript style, reference formatting,
  statistic verification, ranking, render blocks, display-item placement,
  legacy-schema drafts, prose-style gate, the search cache, and the front
  end/server model allowlist agreeing.
- **Format conformance:** `python tests/test_journal_conformance.py` — asserts
  every convention in `docs/journal-style.md` over five fixture articles
  (including no-direct-sources, sparse metadata, and a 40-year source range).
  Run this after any render change; add a convention here when you add one there.
- Rendered pages can be eyeballed with the preinstalled Chromium:
  `articlegen demo -o /tmp/demo.html` then screenshot it with Playwright
  (`NODE_PATH=/opt/node22/lib/node_modules`, `executablePath: '/opt/pw-browsers/chromium'`).

## Environment setup

- Set `GROQ_API_KEY` (free key at console.groq.com), `OPENROUTER_API_KEY`
  (prepaid credit, openrouter.ai/keys) or `ANTHROPIC_API_KEY`.
- Optional: `SEMANTIC_SCHOLAR_API_KEY` and `OPENALEX_MAILTO` raise scholarly-API rate limits.

## Conventions

- Keep all LLM calls behind `llm.generate_json`; don't call the SDKs directly
  from `writer.py` / `ideas.py`.
- New structured-output schemas must produce valid JSON matching the schema — avoid
  `additionalProperties` reliance and unsupported JSON-Schema constraints.
- Add a case to `tests/test_offline.py` for any new pure-logic behavior.

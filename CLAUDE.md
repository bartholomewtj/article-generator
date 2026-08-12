# CLAUDE.md — project memory for `articlegen`

Context for a fresh session. Read this first.

**What belongs here:** invariants, and traps that cost real time to rediscover.
Not the story of how each one was found — that lives in `docs/decisions.md`,
which you read only when touching the area it covers. `docs/journal-style.md`
owns the writing conventions and their sources; this file does not restate them.

**Most invariants below are pinned by a named test.** Where one is, the line
names it and stops — the test is the specification, and prose that restates a
test goes stale while the test does not. Where no test pins it, the line carries
its own reasoning, because nothing else will.

**This file is checked, twice.** `.github/workflows/docs-current.yml` fails a PR
that touches `articlegen/**` without touching this file — satisfied either by
editing it or by writing `Docs: n/a - <why>` in the PR body, so opting out is a
sentence someone wrote rather than a box someone clicked.
`test_claude_md_still_describes_this_code` then checks that every file, guard
test and constant named here or in `docs/decisions.md` still exists. A wrong
line costs more than a missing one: every session loads this file and trusts it
on sight (#114).

## What this is

`articlegen` turns a topic into a **single-page HTML evidence review, formatted
like a scientific-journal Review article** (plus a Markdown copy), grounded in
journal-article abstracts and open-access full texts. Two front ends:

1. **Web app** — GitHub Pages front end calling a Render backend, or
   `articlegen web` locally.
2. **CLI** — `articlegen ideas` / `draft` / `queue` / `demo`.

Repo: **`bartholomewtj/article-generator`**, default branch `main`.
`drafts/` is intentionally git-tracked — it's the review surface.

## Architecture

```
articlegen/
  cli.py       subcommands (ideas / draft / queue / demo / web); file output only
  pipeline.py  THE draft pipeline — generate_draft(); every caller goes through it
  web.py       HTTP server + REST API for the web app UI
  llm.py       provider layer: ONE generate_json(); OpenRouter, Anthropic,
               claude-cli, gemini-cli
  ideas.py     LLM: theme -> shortlist of article ideas
  writer.py    LLM: plan_queries -> curate_sources -> write_article
  sources.py   Semantic Scholar + OpenAlex + Europe PMC fetch, 24h cache, dedupe,
               rank; open-access full-text fetch + the excerpt budget
  verify.py    deterministic: flag article statistics absent from what the
               writer was shown (abstracts + full-text excerpts)
  style.py     deterministic: flag prose that breaks journal writing conventions
  render.py    structured article -> journal HTML + Markdown + drafts/ index
  demo.py      built-in sample for `articlegen demo` (no API/network)
docs/journal-style.md    the journal conventions and where each came from
docs/decisions.md        settled history; read per-area, not cover to cover
tools/compare_curation.py  full vs truncated abstracts for curation (#117)
tools/compare_models.py    one topic through two models, side by side (#85)
tests/test_offline.py             pure-logic tests; no network/keys
tests/test_journal_conformance.py conventions as assertions over 5 fixtures
```

**`pipeline.generate_draft()`, and nowhere else**: source pre-flight →
`plan_queries` → `gather_evidence` → `curate_sources` → full-text fetch →
`write_article` → `enforce_style` (one `revise_prose` pass if `check_style`
finds errors) → `check_statistics` → a `Draft` carrying article, papers,
curation, verification, style report and `provenance` (queries, model, date,
databases, full_text_sources).

Callers differ **only** in what they do with the `Draft`. Never re-implement a
stage in a caller — the web handler once had its own copy that silently skipped
the style gate and provenance. → `test_pipeline_is_shared`

## Invariants — break these and the article lies

**Pinned by a test.** The test is the specification; read it before changing the
behaviour it describes.

| Invariant | Guard |
|---|---|
| Every caller runs the one pipeline | `test_pipeline_is_shared` |
| API keys travel as arguments, never through `os.environ` | `test_per_request_api_key` |
| Methods names only databases that actually answered | `test_methods_names_only_sources_that_answered` |
| Verification searches exactly what the writer was shown | `test_full_text_grounding` |
| A cited sentence is checked against its own sources | `test_statistic_verification` |
| Flagged figures are marked where the number is | `test_unverified_figures_are_marked_inline` |
| The article never instructs a clinician | `test_clinical_directives_are_an_error` |
| Front-end model ids match the server allowlist | `test_front_end_models_match_the_allowlist` |
| The stored API key is tab-only (`sessionStorage`) unless opted in | `test_api_key_is_session_only_by_default` |
| Nothing needing a key costs a round trip to discover it | `test_first_visit_does_not_dead_end` |
| The full-text dependencies fail loudly enough to diagnose | `test_full_text_dependencies_fail_loudly_enough_to_diagnose` |
| A doomed run is refused before the caller is billed | `test_dead_sources_fail_before_the_caller_is_billed` |
| The article shape is not a preference (`TONE_LABEL`, `LENGTH_LABEL`, `DEPTH_LABEL` are constants) | `test_house_style_is_fixed_not_a_preference` |
| Register rules fire on investigator voice, not synthesis voice | `test_register_rules_are_scoped_to_the_synthesis_voice` |
| Sources travel with a revision only when usable | `test_revision_carries_sources_only_when_they_can_be_used` |
| Every article still matches the writer's schema | `test_real_articles_still_match_the_schema` |

**Not pinned by a test** — these need the reasoning, because nothing else
carries it:

- **Every provenance statement is derived, never hardcoded.** Methods names only
  databases that actually returned records (`provenance["databases"]`, from
  `sources.DATABASE_NAMES`). There is deliberately **no fallback**: an
  unrecorded search says so and names nothing. A fallback constant is how a
  false claim came back the first time (#75). Same rule for the full-text count
  — `_synthesis_label`, `_read_phrase` and `render._full_text_count` own that
  wording, and Table 1's Read column must agree with Methods.
- **`verify.check_statistics` searches exactly the abstracts plus the excerpts
  the writer was shown** — never the unseen tail of a paper. Both sides call
  `sources.full_text_excerpts`, so nothing has to be recorded per run. A cited
  sentence is checked against *its own* sources: a figure that is real but in
  the wrong source comes back as `misattributed`, not `unverified`, and an
  uncited sentence has no attribution to break (#101).
- **Methods must describe the check that runs, not the check you wish ran.** It
  claimed "every numerical value" while `_FIGURE_RE` skipped bare integers, and
  `_unverified_sentence` said "the abstracts" on drafts that had read full
  texts. Derived, never aspirational.
- **The statistical check is generous about form and strict about presence.** A
  quantity verifies on its number alone, because a source may write the same
  amount a different way. A missed figure is a warning the reader never sees; a
  false flag is a wrong warning printed in the article.
- **Figure marks go in after escaping, before citation linking.** At that point
  the only brackets left are literal `[N]` markers, which `_flag_pattern` skips,
  so a flagged figure of `12` is never found inside `[12]`. Each mark links to
  `#limitations`, so tapping it lands on the paragraph that explains it.
- **Statistic and style checking are deterministic, not LLM passes.** A model
  asked "is this grounded / is this journal style?" agrees with itself.
- **Three display items are built deterministically in `render.py`**: `Box 1`
  (most relevant source), `Fig. 1` (inline SVG of sources by year), `Table 1`
  (cited records). They are the part a model can't fabricate. Keep them that
  way, and keep Box 1's caption claiming relevance rather than quality —
  nothing here appraises study quality (#102).
- **Citations use the SOURCE-index scheme.** The writer cites papers by their
  fed "SOURCE N" label; `render` renumbers inline markers *and* the Sources list
  to a matching 1..N. Don't assume inline numbers are already sequential.
- **Never add fabricated journal apparatus** — no invented journal name, volume,
  DOI, dates, affiliations or ORCIDs. The masthead says "Not peer reviewed"; the
  back matter says a machine wrote it.
- **Legacy schema fallbacks stay.** `standfirst`, `key_takeaways`, `pull_quote`
  and `featured_study.why` are gone from the schema, but `render.py` and
  `verify.py` still read them so older drafts keep rendering. Don't drop them.

## Article format

`docs/journal-style.md` is the reference — read it before changing layout.
Sections run `Introduction` → thematic → `Conclusions`. Layout: Fig. 1 after the
Introduction, Box 1 after the first thematic section, key points directly before
the conclusions, Table 1 in the back matter after Methods — never mid-prose.
Citations are Nature superscripts after the punctuation, runs of 3+ collapsed
(`.¹,³–⁵`). Warnings are prose in a Limitations paragraph, not callout boxes.
Flagged figures carry `†` (unverified) or `‡` (found only in another source).

`render_article(..., standalone=False)` drops the head theme script, the
Share/Copy/Theme toolbar and the script behind it. The web API returns that
copy because the front end shows it in a **sandboxed** iframe; files written to
`drafts/` stay standalone.

## Prose style (enforced, not prompted)

`style.py` turns `docs/journal-style.md` §13–18 into a deterministic check.
`enforce_style` sends `revision_brief()` back through `revise_prose` **once**,
and keeps the revision only if it reduces the error count *and* leaves citations
and sections intact.

- **The revision is a patch, not a new article.** `revise_prose` asks for a list
  of `{where, replacement}` edits and `writer.apply_revisions` merges them into
  a copy. **An unknown `where` is skipped, never appended** — a heading the
  model invented means it restructured the article, which a style pass may not
  do. `too-few-sections` is the one failure that still buys a whole rewrite
  (`rewrite_whole=True`). Measurements: `docs/decisions.md`.
- **Errors**: second person, contractions, rhetorical questions, exclamations,
  boosters, claims of proof, first person outside the `here we review` frame,
  under-hedging (`MIN_HEDGES_PER_SENTENCE = 0.20`), clinical directives.
- **`clinical-directive` is the one rule with real-world consequences.** The
  line is grammatical because that is what a deterministic check can see: past
  tense with a study subject **reports**, a modal or imperative aimed at a
  clinical act **instructs**. Exempt: research recommendations and idioms that
  borrow a clinical verb. `_IMPERATIVE_RE` is deliberately **not** built from
  `_CLINICAL_ACTS` — those end in `\w*` and would fire on "Screening was…". The
  negative controls in the test are the specification.
- **`SUBSTANCE_RULES`** (`under-length`, `too-few-sections`, `hedge-monotony`,
  `repeated-opener`, `recycled-phrasing`, `echoed-abstract`, `bundled-citations`)
  fail a draft for saying too little. When one fires, `revision_brief()`
  **inverts** and `enforce_style` passes `papers`/`curation` through. **That is
  the only case where the sources travel with a revision**, and the split is
  keyed on `SUBSTANCE_RULES` in both places.
- **The two corpora are the guard against a rule being wrong.**
  `tests/real_abstracts.json` and `tests/style_corpus.json`. **Add to a corpus
  before adding a rule.** What they have already settled is in
  `docs/decisions.md` — including that a primary-research abstract is *not* a
  negative control, and that the hedging floor is calibrated on body prose
  (`tests/body_prose_measurements.json`), not abstracts (#56).
- `MIN_HEDGES_FOR_MONOTONY = 8` gates `hedge-monotony`, which needs volume
  before it means anything.
- **Hedges and softeners are separate lists.** Frequency/degree adverbs (often,
  typically, approximately) are counted but never satisfy the floor — they
  qualify nothing. `cannot be` is not a hedge; it asserts certainty.
- **Nominalisation counting was deleted deliberately.** Don't reinstate it
  without a stoplist.
- **The section floor scales with the evidence** (`_required_sections`). A flat
  floor of 5 causes the thinness it was meant to prevent.
- **The abstract, key points and Introduction are three jobs.** Don't reinstate
  "self-contained" on more than one.
- **Calibrate against `demo.SAMPLE_ARTICLE`** — it must always pass. Length does
  not discriminate, so `under-length` is a warning.
- Density rules only fire above 12 sentences **and** 250 words. A new fixture
  needs real prose or the rules skip it.

## Sources and grounding

- **Abstracts plus open-access full text.** `FULLTEXT_TARGET` (5) matches what
  `full_text_excerpts` can show (5 × 12,000 = 60,000 chars);
  `MAX_FULLTEXT_REQUESTS` (18) stops a topic with no open-access literature
  spending a request per paper. **Tangential sources are never fetched**, even
  when the target goes unmet.
- **Every run says *why* full-text fetching stopped.** "4 of 19" is not an
  answer: a request cap that bit is a tuning problem, genuinely absent open
  access is a property of the literature and not fixable here, and the log used
  to report the count and then *assert* availability (#84). It now names the
  exit — target reached / request cap reached / ran out of eligible sources —
  with the eligible, no-open-access and fetched-but-empty tallies, and warns
  explicitly when the cap bound before the target. It also prints the
  **read-subset skew** (median year and citations, read vs abstract-only),
  because Limitations tells the reader that subset skews and nobody had
  measured how. **Never fetch paywalled full text** — the Methods section's
  honesty depends on the open-access constraint.
- **Tangential sources never reach the writer either**
  (`_format_sources(..., omit=...)`). **They are dropped by number, never
  re-packed**: the SOURCE index *is* the citation scheme, so SOURCE 7 stays the
  seventh paper whether or not SOURCE 6 was dropped. The prompt says how many
  were withheld and that the numbering has gaps — a prompt that misdescribes its
  own inputs teaches the model to ignore it.
- **The full-text path has four keyless dependencies and all of them fail
  soft**: Europe PMC search, Europe PMC fetch, DOI resolution, Unpaywall. Soft
  failure is right for the reader and useless for the operator, so both `except
  SearchFailure` branches in `resolve_pmcid` log the DOI and the reason — the
  pipeline must pass `log=log` or none of it is reachable — and `/api/diag`
  carries a `full_text` block from `sources.probe_unpaywall()`, which reports
  rather than raises (#104).
- **Don't trust `paper.pmcid` alone.** Only the Europe PMC *search* returns
  pmcid/inEPMC, so anything from OpenAlex arrives empty regardless of licence.
  An empty pmcid means nobody asked — `sources.resolve_pmcid` looks the DOI up
  first. Full texts get bracketed citation numbers stripped at parse time — they
  collide with the SOURCE-index scheme.
- **Relevance gate.** `curate_sources` labels each paper direct/related/
  tangential to the *exact* topic; the writer is told the counts and must flag
  when nothing is directly on-topic. Prevents a "schizophrenia" article quietly
  leaning on depression studies.
- **`CURATION_ABSTRACT_CHARS` is `None` and stays that way until measured.**
  Truncating the abstracts sent to curation would cut ~39,000 input tokens to
  ~15,000, but `style._required_sections` reads the `direct` count and
  `write_article` omits `tangential` sources, so a degraded label degrades the
  article silently. Run `tools/compare_curation.py` and read its verdict: it
  accepts only if `direct` **and** `tangential` are stable, because overall
  agreement is satisfiable by collapsing everything to `related` — which is
  exactly what happened when curation ran at a cheaper tier (#117).
- **Ranking**: topic overlap first, then `citation_weight + recency`, decaying
  over `RECENCY_HALF_LIFE` on the citation term's scale.
- **A source that refuses once is skipped for the rest of the run**
  (`gather_evidence`'s `exhausted` set). Note the interaction with
  `_MAX_BACKOFF`: a source asking for a cool-off longer than 30s fails
  *immediately without retrying* and is then exhausted — so one long
  `Retry-After` removes it from the whole run. **Assume you are running on fewer
  sources than the code lists.** Source keys are explicit, never derived from
  `search.__name__`.
- **Searches are cached** 24h (refusals 2 min). `clear_search_cache()` for
  tests; `ARTICLEGEN_SEARCH_CACHE_TTL=0` disables it. The cache is consulted
  *before* the `exhausted` set.
- **Which scholarly API works changes — measure, don't write it down.** Run
  `/api/diag` and read the result; the constraint is Render's shared egress IP,
  not the contact address (`docs/decisions.md`).

## AI providers (`llm.py`)

- **Four providers: OpenRouter (default), Anthropic, `claude-cli`, `gemini-cli`.**
  Defaults: `anthropic/claude-opus-5` / `claude-fable-5` / `cli:opus` /
  `agy:gemini-3.6-flash-high`, plus
  `OPENROUTER_REFUSAL_FALLBACK = anthropic/claude-sonnet-5`. Both CLI providers
  are local-only and absent from `web.ALLOWED_MODELS` (`test_claude_cli_provider`,
  `test_gemini_cli_provider`).
- **The default is not settled (#85).** `anthropic/claude-opus-5` is $5/$25 per
  Mtok against Sonnet 5's $2/$10 — 2.5x on every article, and Sonnet carries no
  elevated bio/cyber classifiers, so the refusal path would stop being
  load-bearing on the common route. Sonnet is already the refusal fallback, so
  this is a one-flag experiment: `tools/compare_models.py "<topic>"`. It
  measures the countable half and says outright that the half that decides it —
  whether the draft *adjudicates* its evidence base or just summarises it —
  needs a human reading both drafts.
- **Model ids live in two places** — `llm.py` and `PROVIDERS` in `index.html`.
  Nothing links them and `web._requested_model` silently drops an unrecognised
  name, so a stale front end quietly stops honouring the model the user picked.
- **A slash makes a model name an OpenRouter slug**, checked *before* the
  `claude` prefix. `anthropic/claude-sonnet-5` routed to Anthropic's SDK is a
  404. No direct provider's model id contains a slash.
- **`provider: {"require_parameters": true}` is necessary and not sufficient.**
  Without it OpenRouter may route to a provider that ignores `response_format`
  and the article comes back as prose; with it, the filter still trusts what a
  provider *advertises*. So `_openrouter_provider_routing` pins `anthropic/*` to
  `only: ["anthropic"]` (#81).
- **`max_tokens` is per-model and thinking is spent from it.** Two pairs in
  `_openrouter_max_tokens` because OpenRouter caps Llama at 16,384 completion
  tokens while Anthropic allows 128,000. **A truncated reply is invalid JSON,
  not a short one.** Headroom is free — OpenRouter bills tokens generated.
- **Refusals retry once on `OPENROUTER_REFUSAL_FALLBACK`, which must stay a
  model without elevated classifiers** — falling back to another one just
  reproduces the refusal (#79). On the Anthropic path, Opus/Fable/Mythos opt
  into the server-side fallback in `_refusal_fallback_kwargs`, attached by model
  prefix since older models reject it; every call goes through
  `client.beta.messages`.
- **A 403 mentioning a limit is a per-key spending cap, not exhausted credit.**
  Different page, different fix (openrouter.ai/keys). Topping up does nothing.
  A 200 can still carry an `error` body, checked separately from the status code.
- **Both CLI providers are opt-in and must stay that way.** `--model cli:opus` /
  `cli:sonnet` / `agy:<name>` (`agy models` lists them), or
  `ARTICLEGEN_PROVIDER=claude-cli` / `ARTICLEGEN_PROVIDER=gemini-cli`. They
  answer as whoever is signed in on this machine, so a threaded server would
  answer every visitor from the host's own seat. Both run in a scratch cwd — the
  Claude CLI auto-discovers `CLAUDE.md` from the working directory and would
  prepend *this file* to every call. `--effort high` always on `claude-cli`;
  subscription time is not metered per token, so `deep` and `api_key` are
  ignored and neither is an oversight.
- **`claude-cli` enforces no response schema**, unlike the API paths. Three
  defences, all load-bearing: the format demand is repeated at the *end* of the
  user prompt, a fenced or prose-wrapped object is recovered by string-aware
  brace matching, and an unparseable reply is retried once. A **refusal** is not
  retried: same model, same answer. Suppress MCP servers with
  `--strict-mcp-config` and an empty `--mcp-config`, or pay a 10x prompt tax.
- **`gemini-cli`'s `--json-schema` genuinely enforces the schema** and returns
  the parsed object in `structured_output`. It is the one CLI path as reliable
  as the API ones. `agy` ignores stdin, so the prompt goes over as `-p "@<file>"`
  with `--add-dir`. **Every call runs the model the operator named — do not step
  the shallow ones down a tier** (measured; `docs/decisions.md`).
- **The gemini-cli revision call's input is unexplained and still open (#116).**
  All three providers log `sent[chars=… ~tok=…]` beside what they were charged,
  so one real run answers it. Read `docs/decisions.md` before changing any of
  `-p @file`, `--add-dir` or the scratch cwd.

## Web app (`index.html` + `web.py`)

- **The reader iframe is sandboxed** `allow-same-origin` — deliberately **not**
  `allow-scripts` (#100). `allow-same-origin` does not re-enable scripts; it is
  what keeps `contentDocument` reachable for the theme sync, in-place edit and
  save. Older draft files on disk still carry a toolbar and
  `hideArticleToolbar()` hides it.
- **The read-only path comes before the key prompt.** There is no free way to
  *generate* anything since the provider list narrowed to OpenRouter, so a
  stranger sent this link would otherwise have to open a payments account
  before seeing the thing work at all (#111). `drafts/` is public and already
  deployed by the Pages workflow (`path: '.'`), so `.demo-band` on the landing
  view points at it — above `#setupCard`, because a first impression of "paste
  a credential" is the thing worth avoiding. Don't reorder them.
- **A visitor never sees a raw exception.** `_unexpected()` logs the detail
  server-side and returns a sentence, unless the message names something the
  caller can act on (`_ACTIONABLE` — key, credit, rate limit). `NoPapersFound`
  is passed through deliberately: its text is written for the visitor.
- **One article library**, `articlegen_library`, with a star for "keep this".
  All writes go through `writeLibrary()`, which sheds the oldest unstarred
  entries on QuotaExceededError — a bare `setItem` silently lost the article on
  a full quota. `migrateLegacyLibraries()` folds the old keys in once.
- **Two server modes.** Local (default) writes each draft into `drafts/` and
  rebuilds the queue, matching the CLI. Shared (`ARTICLEGEN_STATELESS=1`, what
  the deployment sets) renders, returns, persists nothing — a common `drafts/`
  on a shared host would make every visitor's article readable by every other
  visitor at a guessable URL.
- **The per-IP limit needs a real client IP and an aggregate partner** (#96).
  `_client_ip` takes the **rightmost** `X-Forwarded-For` entry, and only when
  `TRUST_PROXY`: a caller can send their own header and the proxy appends the
  real peer to it, so the leftmost entry is attacker-chosen and an untrusted
  deployment that believed the header would let anyone pick their bucket.
  Auto-on via `RENDER_GIT_COMMIT`, or `ARTICLEGEN_TRUST_PROXY=1`.
  `ARTICLEGEN_RATE_LIMIT_TOTAL` (120/hour, all visitors) matches the real
  constraint; `ARTICLEGEN_RATE_LIMIT` (20/hour/IP) and
  `ARTICLEGEN_ALLOWED_ORIGINS` are the others. Charged after validation, so a
  malformed request costs no quota.
- **`pipeline._preflight_sources` refuses only when *every* source errored** —
  the same condition `generate_draft` already raises on afterwards, so it cannot
  block a draft that would have worked. Two memos keep it off the healthy path
  (`SOURCE_PROBE_TTL`, `SOURCE_PROBE_FAIL_TTL`); `ARTICLEGEN_SOURCE_PROBE=0`
  disables it.
- **`protocol_version = "HTTP/1.1"` is load-bearing.** http.server defaults to
  HTTP/1.0, which closes the connection after every response and makes pooling
  clients fail instantly. It presents as flaky networking and **curl cannot
  reproduce it** (`docs/decisions.md`).

## Deployment

```
index.html on GitHub Pages  ──POST /api/draft──▶  backend on Render
   (static, holds the key)                        (stateless, holds nothing)
```

- **Front end**: Pages, deployed by `.github/workflows/deploy-pages.yml` on push
  to `main`. `API_BASE` in `index.html` points at the backend. The page stamps
  the commit it was built from — compare it against `git rev-parse --short=7
  HEAD` to tell "stale cache" from "deploy failed".
- **Backend**: Render free tier, service `articlegen-api`, declared in
  `render.yaml`. The URL derives from `name:`, so they must stay in step.
  **Blueprint auto-sync is off**, so the `branch:` line is a record, not a
  control. Sleeps after 15 min idle, ~50s to wake.
- **`GET /api/health`** reports the branch and commit the running service was
  built from. `.github/workflows/health.yml` runs it daily.
- **`GET /api/diag`** runs one keyless search and reports what *that host* gets
  from the scholarly APIs. Bypasses the cache and is therefore rate-limited —
  each call spends real quota. Its per-source `cached` flag is always `false`.
  The `full_text` block probes Unpaywall, which the search probes never touch.
- The `github-pages` **environment** carries its own branch allowlist, separate
  from the workflow's trigger list. A branch rename has to consider both.
- **Hugging Face Spaces and Fly.io were tried and rejected** — both require a
  payment method. Don't re-litigate.

## Setup / testing

- `pip install -e .` (a SessionStart hook in `.claude/settings.json` runs
  `.claude/setup.sh` in web sessions).
- `python tests/test_offline.py` — pure logic, no keys or network. Each test is
  wrapped, so one crash no longer aborts the rest against a dirty environment.
- `python tests/test_journal_conformance.py` — every convention in
  `docs/journal-style.md` over five fixtures. Run after any render change; add a
  convention here when you add one there.
- `python tests/test_offline.py --live` — one real `generate_json` and one
  `gather_evidence` query. Spends credit and quota, so it is opt-in and lives
  behind `workflow_dispatch` in `.github/workflows/live-smoke.yml`. **Every
  production failure on record happened on the seam the offline suite fakes**
  (#77, #79, #81), so run it after touching a model id, a ceiling, the routing
  or `sources.py`.
- **Provider tests assert on the payload, not on the source text** (#98).
  `_capture_openrouter` returns what a fake `requests.post` received;
  `_FakeAnthropic` goes into `sys.modules` because `_anthropic_generate` imports
  the SDK inside the function. Ceiling assertions follow
  `OPENROUTER_DEFAULT_MODEL` rather than named models.
- **The key-leak guard is behavioural.** It sweeps all seven modules with a
  regex covering `[...]=`, `.update(` and `.setdefault(`, then runs a real call
  through a fake transport and asserts `os.environ` is byte-identical.
- Set `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`, or use `--model cli:opus`
  with no key at all. Optional: `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_MAILTO`.

## Conventions

- Keep all LLM calls behind `llm.generate_json`; don't call the SDKs directly
  from `writer.py` / `ideas.py`.
- New structured-output schemas must produce valid JSON matching the schema —
  avoid `additionalProperties` reliance and unsupported constraints.
- Add a case to `tests/test_offline.py` for any new pure-logic behaviour.
- When you fix something that cost real time to find, the invariant goes here
  and the story goes in `docs/decisions.md`.

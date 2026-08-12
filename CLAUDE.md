# CLAUDE.md — project memory for `articlegen`

Context for a fresh session. Read this first.

**What belongs here:** invariants, and traps that cost real time to rediscover.
Not the story of how each one was found — that lives in the git history and the
issues. `docs/journal-style.md` owns the writing conventions and their sources;
this file does not restate them.

**This file is checked, twice.** `.github/workflows/docs-current.yml` fails a PR
that touches `articlegen/**` without touching this file — satisfied either by
editing it or by writing `Docs: n/a - <why>` in the PR body, so opting out is a
sentence someone wrote rather than a box someone clicked.
`test_claude_md_still_describes_this_code` then checks that every file, guard
test and constant named here still exists. It was written against four real
errors that survived until someone went looking: a workflow filename that had
been renamed, three FULLTEXT constants that no longer matched, a rule list
missing an entry, and Groq described as the default provider after it was
deleted (#114). A wrong line here costs more than a missing one — every session
loads this file and trusts it on sight.

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
tests/test_offline.py             pure-logic tests; no network/keys
tests/test_journal_conformance.py conventions as assertions over 5 fixtures
```

**`pipeline.generate_draft()`, and nowhere else**: `plan_queries` → full-text
fetch → `gather_evidence` → `curate_sources` → `write_article` →
`enforce_style` (one `revise_prose` pass if `check_style` finds errors) →
`check_statistics` → a `Draft` carrying article, papers, curation,
verification, style report and `provenance` (queries, model, date, databases,
full_text_sources).

Callers differ **only** in what they do with the `Draft`. Never re-implement a
stage in a caller — the web handler once had its own copy that silently skipped
the style gate and provenance. `test_pipeline_is_shared` fails if a caller
starts calling stages directly.

## Invariants — break these and the article lies

- **Every provenance statement is derived, never hardcoded.** Methods must name
  only databases that actually returned records (`provenance["databases"]`, from
  `sources.DATABASE_NAMES`). There is deliberately **no fallback**: an
  unrecorded search says so and names nothing. A fallback constant is how a
  false claim came back the first time. Same rule for the full-text count —
  `_synthesis_label`, `_read_phrase` and `render._full_text_count` own that
  wording, and Table 1's Read column must agree with Methods (#75).
- **`verify.check_statistics` searches exactly the abstracts plus the excerpts
  the writer was shown** — never the unseen tail of a paper. Both sides call
  `sources.full_text_excerpts`, so nothing has to be recorded per run.
  Verifying against text the writer never saw would let a figure recalled from
  training pass as grounded.
- **A cited sentence is checked against its own sources, with no fallback to the
  rest.** There used to be one, and it hid the failure that most changes
  clinical meaning: a real figure lifted from paper 12 and credited to paper 3
  passed silently. A figure that is real but in the wrong source is now returned
  as `misattributed`, not `unverified`, and gets its own Limitations sentence.
  A sentence citing nothing has no attribution to break and is still checked
  against everything (#101).
- **Methods must describe the check that runs, not the check you wish ran.**
  It claimed "every numerical value" while `_FIGURE_RE` skipped bare integers,
  and `_unverified_sentence` said "the abstracts" on drafts that had read full
  texts. Same rule as `databases` — derived, never aspirational.
- **The statistical check is generous about form and strict about presence.** A
  quantity verifies on its number alone, because a source may write the same
  amount a different way. A missed figure is a warning the reader never sees; a
  false flag is a wrong warning printed in the article.
- **A flagged figure is marked where it appears**, `†` unverified / `‡`
  misattributed, linked to `#limitations`, plus a grounding line under the Key
  points. The check used to reach the reader only as a clause ninety lines
  below the number it retracted — and the Key points are the block people paste
  into an email, so the numbers travelled and the caveats did not (#92). Marks
  go in **after escaping, before citation linking**: at that point the only
  brackets left are literal `[N]` markers, which `_flag_pattern` skips, so a
  flagged figure of `12` is never found inside `[12]`.
- **Statistic and style checking are deterministic, not LLM passes.** A model
  asked "is this grounded / is this journal style?" agrees with itself.
- **Three display items are built deterministically in `render.py`**: `Box 1`
  (featured study), `Fig. 1` (inline SVG of sources by year), `Table 1` (cited
  records). They are the part a model can't fabricate. Keep them that way.
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

`render_article(..., standalone=False)` drops the head theme script, the
Share/Copy/Theme toolbar and the script behind it. The web API returns that
copy because the front end shows it in a **sandboxed** iframe; files written to
`drafts/` stay standalone. See "Web app" below.

## Prose style (enforced, not prompted)

`style.py` turns `docs/journal-style.md` §13–18 into a deterministic check.
`enforce_style` sends `revision_brief()` back through `revise_prose` **once**,
and keeps the revision only if it reduces the error count *and* leaves citations
and sections intact.

- **The revision is a patch, not a new article.** `revise_prose` asks for a list
  of `{where, replacement}` edits — keyed on the `where` that `check_style`
  already reports — and `writer.apply_revisions` merges them into a copy. It
  still *returns* a whole article, so callers are unchanged. Rewriting 3,586
  words to fix three sentences cost 26,632 output tokens against the 24,191 that
  wrote the article; a patch emitted 333 where a rewrite emitted 1,341 on the
  same draft. **An unknown `where` is skipped, never appended** — a heading the
  model invented means it restructured the article, which a style pass may not
  do. `too-few-sections` is the one failure that still buys a whole rewrite
  (`rewrite_whole=True`), because a patch can only replace a block that exists.

- **Errors**: second person, contractions, rhetorical questions, exclamations,
  boosters, claims of proof, first person outside the `here we review` frame,
  under-hedging (`MIN_HEDGES_PER_SENTENCE = 0.20`), clinical directives.
- **`clinical-directive` is the one rule with real-world consequences.** A
  shipped draft carried a titration protocol for a population the same article
  said had zero studies (#102); the footer disclaimer does nothing against a
  reader who has been given a dose and a schedule. The line is grammatical
  because that is what a deterministic check can see: past tense with a study
  subject **reports**, a modal or imperative aimed at a clinical act
  **instructs**. Exempt: research recommendations ("future trials should
  measure X") and idioms that borrow a clinical verb ("treated as provisional",
  "referred to as"). `_IMPERATIVE_RE` is deliberately **not** built from
  `_CLINICAL_ACTS` — those end in `\w*` and would fire on "Screening was…",
  "Dosing varied…". The negative controls in
  `test_clinical_directives_are_an_error` are the specification; a rule that
  cannot tell reporting from instructing is the wrong rule.
- **Box 1 is captioned "Most relevant source", not "Key study".** Nothing in
  this pipeline appraises study quality — `curate_sources` ranks on topic fit —
  so the old caption claimed a judgement that was never made, and one draft
  boxed a scoping review while a powered trial sat in the body. The box carries
  a fixed disclaimer saying so (#102).
- **`SUBSTANCE_RULES`** (`under-length`, `too-few-sections`, `hedge-monotony`,
  `repeated-opener`, `recycled-phrasing`, `echoed-abstract`, `bundled-citations`)
  exist because every other rule is a *prohibition*, and a model optimising only
  against prohibitions writes vague hedged filler — asserting nothing breaks no
  rule. These fail a draft for saying too little. When one fires,
  `revision_brief()` **inverts**: it tells the model to pull specific findings
  from the sources, and `enforce_style` passes `papers`/`curation` through so it
  has something to pull from. **That is the only case where the sources travel
  with a revision.** A register failure is told to reword and add nothing, so
  shipping it 20 abstracts and 60,000 characters of full text was ~30,000 input
  tokens the model was forbidden to use: measured, 95,042 → 30,540. The split is
  keyed on `SUBSTANCE_RULES` in both places, so changing one without the other
  is what `test_revision_carries_sources_only_when_they_can_be_used` catches.
- **The two corpora are the guard against a rule being wrong.**
  `tests/real_abstracts.json` and `tests/style_corpus.json` (20 abstracts, 20
  journals, stratified by article type × domain). **Add to a corpus before
  adding a rule.** Findings already pinned by tests:
  - The register rules model **one voice: a synthesis speaking about other
    people's work.** A trial report legitimately says "we randomly assigned";
    `articlegen` must not. 7/7 investigator-voice abstracts fire a register
    rule, 0/13 synthesis-voice ones do — so a primary-research abstract is *not*
    a negative control for the first-person rule.
  - **The hedging floor is calibrated on body prose, not abstracts.**
    `tests/body_prose_measurements.json`: 18 open-access reviews, median 0.216
    hedges/sentence. Published abstracts run at 0.031 and are the wrong text
    type — don't re-open this with abstract data (#56).
  - `MIN_HEDGES_FOR_MONOTONY = 8` gates `hedge-monotony`, which needs volume
    before it means anything.
- **Hedges and softeners are separate lists.** Frequency/degree adverbs (often,
  typically, approximately) are counted but never satisfy the floor — they
  qualify nothing. `cannot be` is not a hedge; it asserts certainty.
- **Nominalisation counting was deleted deliberately.** In this domain it
  measures the topic, not the prose. Don't reinstate it without a stoplist.
- **The section floor scales with the evidence** (`_required_sections`). A flat
  floor of 5 causes the thinness it was meant to prevent.
- **The abstract, key points and Introduction are three jobs.** Asking all three
  to be self-contained made the model write the same paragraph three times;
  `echoed-abstract` measures the overlap and the writer prompt carries a
  DIVISION OF LABOUR block. Don't reinstate "self-contained" on more than one.
- **Calibrate against `demo.SAMPLE_ARTICLE`** — it must always pass. Length does
  not discriminate, so `under-length` is a warning.
- Density rules only fire above 12 sentences **and** 250 words. A new fixture
  needs real prose or the rules skip it.

## Sources and grounding

- **Abstracts plus open-access full text.** After curation the pipeline fetches
  full text for direct/related sources Europe PMC can serve. `FULLTEXT_TARGET`
  (5) matches what `full_text_excerpts` can show (5 × 12,000 = 60,000 chars);
  `MAX_FULLTEXT_REQUESTS` (18) stops a topic with no open-access literature
  spending a request per paper. **Tangential sources are never fetched**, even
  when the target goes unmet — 12,000 characters of an off-topic paper is the
  drift the relevance gate exists to stop.
- **Tangential sources never reach the writer either.** `write_article` omits
  them from the prompt (`_format_sources(..., omit=...)`). They are background by
  the curation prompt's own definition, and they were arriving with a full
  abstract each. **They are dropped by number, never re-packed**: the SOURCE
  index *is* the citation scheme, so SOURCE 7 stays the seventh paper whether or
  not SOURCE 6 was dropped, and `render`/`verify` still resolve. The prompt says
  how many were withheld and that the numbering has gaps — the tally above it
  counts them, and a prompt that misdescribes its own inputs teaches the model to
  ignore it. If curation returned no labels at all, nothing is dropped.
- **The full-text path has four keyless dependencies and all of them fail
  soft.** Europe PMC search, Europe PMC fetch, DOI resolution, Unpaywall — each
  metered against Render's shared egress IP. Soft failure is right for the
  reader and useless for the operator: a blocked Unpaywall contact address
  halves full-text coverage across every article, Methods correctly reports the
  lower count, and nothing points at the cause (#104). So both `except
  SearchFailure` branches in `resolve_pmcid` **log the DOI and the reason** —
  the pipeline must pass `log=log` or none of it is reachable — and
  `/api/diag` carries a `full_text` block from `sources.probe_unpaywall()`,
  which reports rather than raises. Its default DOI is a PLOS ONE paper open
  access since 2007, so "reports this known open-access DOI as closed" catches
  a changed response shape rather than reading it as a miss.
- **Don't trust `paper.pmcid` alone.** Only the Europe PMC *search* returns
  pmcid/inEPMC, so anything from OpenAlex arrives empty regardless of licence.
  An empty pmcid means nobody asked. `sources.resolve_pmcid` looks the DOI up
  first; on one real run that recovered 9 of 11 available full texts. Full texts
  get bracketed citation numbers stripped at parse time — they collide with the
  SOURCE-index scheme.
- **Relevance gate.** `curate_sources` labels each paper direct/related/
  tangential to the *exact* topic; the writer is told the counts and must flag
  when nothing is directly on-topic. Prevents a "schizophrenia" article quietly
  leaning on depression studies.
- **Ranking**: topic overlap first, then `citation_weight + recency`, decaying
  over `RECENCY_HALF_LIFE` on the citation term's scale. It decides what the
  writer sees first and which paper is featured.
- **A source that refuses once is skipped for the rest of the run**
  (`gather_evidence`'s `exhausted` set). Note the interaction with
  `_MAX_BACKOFF`: a source asking for a cool-off longer than 30s fails
  *immediately without retrying* and is then exhausted — so one long
  `Retry-After` removes it from the whole run. **Assume you are running on fewer
  sources than the code lists.** Source keys are explicit, never derived from
  `search.__name__`.
- **Searches are cached** 24h (refusals 2 min). These free tiers refuse often
  enough that re-running a query is likelier to fail than to find anything new.
  `clear_search_cache()` for tests; `ARTICLEGEN_SEARCH_CACHE_TTL=0` disables it.
  The cache is consulted *before* the `exhausted` set.
- **Which scholarly API works changes — measure, don't write it down.** Both
  open sources refuse constantly from Render's shared egress IP and they swap
  places. `OPENALEX_MAILTO` is set and joining the polite pool did not fix
  OpenAlex; the constraint is the shared cloud IP, not the contact address, so
  changing region is not a fix either. Run `/api/diag` and read the result.

## AI providers (`llm.py`)

- **API keys are passed per call**, never through `os.environ`. The server is
  threaded and the environment is process-global, so an env-var handoff lets one
  request's pipeline pick up another request's key and bill it. Guarded by
  `test_per_request_api_key`.
- **Four providers: OpenRouter (default), Anthropic, `claude-cli`, `gemini-cli`.**
  Defaults: `anthropic/claude-opus-5` / `claude-fable-5` / `cli:opus` /
  `agy:gemini-3.6-flash-high`, plus
  `OPENROUTER_REFUSAL_FALLBACK = anthropic/claude-sonnet-5`. Both CLI providers
  are local-only and absent from `web.ALLOWED_MODELS`.
- **Groq was removed.** Its free tier metered 12,000 tokens/**minute** counting
  reserved output, which is why `prompt_budget_chars()` and the abstract-trimming
  path in `_format_sources` existed, and why Groq drafts were abstracts-only.
  Nothing left has a per-minute ceiling. Don't reinstate a char budget without a
  provider that needs one. A bare Groq-era model name now raises with the
  OpenRouter slug to use instead.
- **Model ids live in two places** — `llm.py` and `PROVIDERS` in `index.html`
  (one entry, OpenRouter). Nothing links them and `web._requested_model`
  silently drops an unrecognised name, so a stale front end quietly stops
  honouring the model the user picked.
  `test_front_end_models_match_the_allowlist` catches the drift.

### OpenRouter

- **A slash makes a model name an OpenRouter slug**, checked *before* the
  `claude` prefix. `anthropic/claude-sonnet-5` routed to Anthropic's SDK is a
  404. No direct provider's model id contains a slash.
- **`provider: {"require_parameters": true}` is necessary and not sufficient.**
  Without it OpenRouter may route to a provider that ignores `response_format`
  and the article comes back as prose. It filters on what a provider
  *advertises*, and the advertisement can be wrong — so
  `_openrouter_provider_routing` also pins `anthropic/*` to `only: ["anthropic"]`
  (#81). Provider selection is dynamic, so a routing fault appears
  intermittently and looks like a new bug each time; the server that answered is
  in the error body's `provider_name`.
- **`max_tokens` is per-model and thinking is spent from it.**
  `_openrouter_max_tokens` gives `anthropic/*` 64,000 deep / 16,000 shallow and
  everything else 16,000 / 8,000 — two pairs because OpenRouter caps Llama at
  16,384 completion tokens while Anthropic allows 128,000. **A truncated reply
  is invalid JSON, not a short one**, so it surfaces as a parse error nowhere
  near its cause; both the truncation check and the parse error name the finish
  reason and the ceiling. Headroom is free — OpenRouter bills tokens generated.
- **Refusals.** Opus 5 and Fable 5 run elevated bio/cyber classifiers that
  false-positive on exactly what this project writes about (#79).
  `finish_reason == "content_filter"` or `native_finish_reason == "refusal"`
  retries once on `OPENROUTER_REFUSAL_FALLBACK`. **The fallback must stay a
  model without elevated classifiers** — falling back to another one just
  reproduces the refusal. A refusal can arrive mid-reply with partial content;
  that fragment is discarded, which is what stops it resurfacing as "invalid
  JSON" pointing at the model's own half-written sentence.
- **A 403 mentioning a limit is a per-key spending cap, not exhausted credit.**
  Different page, different fix (openrouter.ai/keys). Topping up does nothing.
- A 200 can still carry an `error` body, so that is checked separately from the
  status code.

### Anthropic

- **On Opus 5 thinking is on unless you say otherwise**, and `max_tokens` caps
  thinking *plus* the reply. The shallow ceiling is 16,000 because the curation
  call grades twenty sources in one response.
- `_anthropic_generate` handles `stop_reason` of `refusal` and `max_tokens`
  explicitly — a refusal returns a normal 200 with no text block, which
  otherwise surfaced as a bare `StopIteration`.
- Opus/Fable/Mythos opt into the server-side refusal fallback (`fallbacks:
  "default"` + `server-side-fallback-2026-07-01` beta, #45), attached by model
  prefix in `_refusal_fallback_kwargs` since older models reject it. Every call
  goes through `client.beta.messages`. A visible refusal means the fallback
  declined too.

### `claude-cli` — drafting on a Claude subscription

`claude -p` driven non-interactively. `--model cli:opus` / `cli:sonnet`, or
`ARTICLEGEN_PROVIDER=claude-cli`.

- **Opt-in only, and must stay that way.** With no key to detect there is
  nothing to auto-detect it by — which is the point: it answers as whoever is
  signed into the CLI on this machine, so a threaded server would answer every
  visitor from the host's own seat. Deliberately absent from
  `web.ALLOWED_MODELS`; Render has no `claude` binary. `test_claude_cli_provider`
  pins both.
- **The CLI enforces no response schema**, unlike the API paths. Three defences,
  all load-bearing: the format demand is repeated at the *end* of the user
  prompt (the system prompt's copy loses to tens of kilobytes of sources in
  between), a fenced or prose-wrapped object is recovered by string-aware brace
  matching, and an unparseable reply is retried once with the failure named. A
  **refusal** is not retried: same model, same answer.
- **Suppress MCP servers or pay a 10x prompt tax** — 22,944 tokens with them
  against 2,363 without, for the same trivial call. Only `--strict-mcp-config`
  with an empty `--mcp-config` suppresses them; `--tools ""` does not.
- **It runs in a scratch cwd**, because the CLI auto-discovers `CLAUDE.md` from
  the working directory — running here would prepend *this file* to every call.
- **On Windows `claude` is a `.cmd` shim**, so its command line goes through
  cmd.exe: the ceiling is **8,191** characters, not 32,767. Anything that scales
  with the sources or the schema must go on stdin. A test pins argv under 2,000.
- `--effort high` always; subscription time is not metered per token. `deep` and
  `api_key` are ignored, and neither is an oversight.

### `gemini-cli` — drafting on a Gemini subscription

The Antigravity CLI (`agy`) driven non-interactively. `--model
agy:gemini-3.6-flash-high` — the name after `agy:` goes to `agy --model`
verbatim, and `agy models` lists them — or `ARTICLEGEN_PROVIDER=gemini-cli`.

- **Opt-in and local-only, for the same reason as `claude-cli`**: it answers as
  whoever is signed in on this machine. Absent from `web.ALLOWED_MODELS`;
  `test_gemini_cli_provider` pins that.
- **`agy` is the only working route to a Gemini subscription here.** The Google
  `gemini` CLI refuses to authenticate at all — `IneligibleTierError`, Code
  Assist for individuals is retired in favour of Antigravity.
- **`--json-schema` genuinely enforces the schema** and returns the parsed
  object in the envelope's `structured_output`. This is the one CLI path as
  reliable as the API ones; the brace-matching recovery is a fallback here, not
  the main road.
- **`agy` ignores stdin.** The prompt goes over as `-p "@<file>"` with
  `--add-dir`, which the CLI inlines verbatim — tested at 98KB. The article
  prompt is ~95,000 characters against a 32,767-character Windows command line,
  so argv is not an option either. Asking the agent to *open* a file instead is
  worse: it costs a tool round-trip and once answered from a different file in
  the same directory.
- **Every call runs the model the operator named — do not step the shallow ones
  down a tier.** It is a one-line change and it looks free (both cheap tiers
  report `thinking=0`), but at `-low` curation agreed with `-high` on only 14 of
  20 relevance labels and collapsed everything toward "related" — that is the
  gate that stops topic drift. `plan_queries` emits run-on queries at `-low`
  *and* `-medium`. The measurement is in `llm.py` above `GEMINI_CLI_DEFAULT_MODEL`.
- **~21,600 tokens of agent scaffolding per call**, ~39% of a run's input, and
  no flag suppresses it. The metered API providers pay none of it.
- **The revision call's input is unexplained and still open (#116).** 135,273
  fresh plus 440,871 cached for a ~20,000-character prompt — ~27,000 expected.
  `turns=1`, so it is not an agent loop. All three providers now log
  `sent[chars=… ~tok=…]` beside what they were charged, in one line shape, so a
  single run answers the ratio instead of it being re-derived by hand. The
  standing hypothesis is that the prompt is reachable **three ways** — inlined
  by `-p @prompt_path`, exposed by `--add-dir scratch`, and sitting in `cwd` —
  which is why the schema's size is logged too. Confirm or kill it with a real
  `agy` run before changing any of those flags; removing `--add-dir` on a guess
  breaks the provider.
- On this provider **88% of output tokens are thinking**, so changes that reduce
  emitted *text* barely move the bill. Measure output against `thinking_tokens`,
  not against word count.

## Web app (`index.html` + `web.py`)

- **The reader iframe is sandboxed** `allow-same-origin` — deliberately **not**
  `allow-scripts`. It is fed model-written HTML, and `#read=`/`#p=` links let
  anyone hand a visitor a page of their choosing; unsandboxed it ran same-origin
  with the OpenRouter key in localStorage (#100). `allow-same-origin` does not
  re-enable scripts; it is what keeps `contentDocument` reachable for the theme
  sync, in-place edit and save. Articles for the app are rendered
  `standalone=False` so there is no dead toolbar behind the sandbox; older draft
  files on disk still have one and `hideArticleToolbar()` hides it.
- **The API key is tab-only unless the visitor opts in.** `localStorage` is
  scoped to the *origin*, and every Pages site under `bartholomewtj.github.io`
  shares one — a remembered key is readable by any other project published
  there, now or years from now (#113). So a new key goes to `sessionStorage`,
  `activeKey()` reads session first, and `saveApiKey` clears **both** stores
  before writing one. The sandbox (#100) is a different threat and does nothing
  about this. `test_api_key_is_session_only_by_default` pins it, including the
  Settings and README wording — "never shared with anyone else" was true about
  the network and misleading about the origin.
- **Nothing that needs a key may cost a round trip to discover it.** A first
  visitor typed a theme, tapped, sat out the ~50s Render cold start and got the
  server's 400 as a raw `alert()` pointing at an unlabelled gear icon (#95).
  `requireKey()` gates `requestIdeas` and `selectDraft` *before* the fetch, a
  `setupCard` on the landing view says a key is needed, `warmBackend()` starts
  the cold start on page load, and `whileWaking()` swaps in the explanation
  after 8s — the copy existed but only in `apiError`, so it appeared after a
  failure and never during the wait it explains. **No `alert()` anywhere**:
  failures land in `#progressError` with a Try again that repeats `lastAction`.
  `test_first_visit_does_not_dead_end` pins all of it, including that the
  progress timeline runs past 30s (a run takes 60-90s and the screen used to
  stop changing at 30).
- **A visitor never sees a raw exception.** `_unexpected()` logs the detail
  server-side and returns a sentence, unless the message names something the
  caller can act on (`_ACTIONABLE` — key, credit, rate limit). Someone was once
  shown `RuntimeError(... invalid JSON ...)` plus 500 characters of raw JSON on
  their phone. `NoPapersFound` is passed through deliberately: its text is
  written for the visitor.
- **The article shape is not a preference.** Tone, length and evidence depth are
  constants in `index.html` (`TONE_LABEL`, `LENGTH_LABEL`, `DEPTH_LABEL`), not
  selectors. Every article is an in-depth longform review at a strict empirical
  focus. The options that were removed all asked for prose `style.py` then
  failed: a ~500-word draft has no room to report what each study did, in whom
  and what it found, and the narrative depth asked for storytelling over methods.
  Output language is the only choice left.
  `test_house_style_is_fixed_not_a_preference` fails if a selector comes back.
- **One article library**, `articlegen_library`, with a star for "keep this".
  There were two stores holding the same articles, and saving to the second
  wrote a second full copy of ~65KB of HTML. All writes go through
  `writeLibrary()`, which sheds the oldest unstarred entries on
  QuotaExceededError — a bare `setItem` silently lost the article on a full
  quota. `migrateLegacyLibraries()` folds the old keys in once; deletable later.
- **Two server modes.** Local (default) writes each draft into `drafts/` and
  rebuilds the queue, matching the CLI. Shared (`ARTICLEGEN_STATELESS=1`, what
  the deployment sets) renders, returns, persists nothing — a common `drafts/`
  on a shared host would make every visitor's article readable by every other
  visitor at a guessable URL.
- `ARTICLEGEN_ALLOWED_ORIGINS` (default `*`, pinned to the Pages origin in
  production) and `ARTICLEGEN_RATE_LIMIT` (per-IP/hour, default 20). The
  throttle exists because the scholarly APIs meter against the *server's* IP.
  It is charged after validation, so a malformed request costs no quota.
- **The per-IP limit needs a real client IP and an aggregate partner.** Behind
  Render's load balancer `client_address[0]` is the *proxy*, so every visitor
  shared one bucket and a single abuser locked out everybody — the exact
  failure the throttle exists to prevent (#96). `_client_ip` takes the
  **rightmost** `X-Forwarded-For` entry, and only when `TRUST_PROXY`: a caller
  can send their own header and the proxy appends the real peer to it, so the
  leftmost entry is attacker-chosen and an untrusted deployment that believed
  the header would let anyone pick their bucket. Auto-on via
  `RENDER_GIT_COMMIT`, or `ARTICLEGEN_TRUST_PROXY=1`.
  `ARTICLEGEN_RATE_LIMIT_TOTAL` (default 120/hour, all visitors) is the one
  that matches the real constraint — upstream load scales with visitor count
  while every individual stays politely under 20.
- **A dead-sources day must not bill the caller.** `plan_queries` is a paid LLM
  call and ran before anything touched a scholarly API, so a doomed run was
  charged in full. `pipeline._preflight_sources` probes one query first and
  refuses only when *every* source errored — the same condition
  `generate_draft` already raises on afterwards, so it cannot block a draft
  that would have worked. Two memos keep it off the healthy path: a server
  that heard from a source within `SOURCE_PROBE_TTL` skips the probe, and one
  that just saw everything fail reuses that verdict for
  `SOURCE_PROBE_FAIL_TTL`. `ARTICLEGEN_SOURCE_PROBE=0` disables it.
- **`protocol_version = "HTTP/1.1"` is load-bearing.** http.server defaults to
  HTTP/1.0, which closes the connection after every response; pooling clients
  then fail instantly on a socket the server already hung up on. It presents as
  flaky networking, ~half of fetches failing in ~140ms, and **curl cannot
  reproduce it** because each invocation opens a fresh connection.

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
- **`GET /api/health` reports the branch and commit the running service was
  built from.** That turns "deploys may have silently stopped" into a one-line
  check. `.github/workflows/health.yml` runs it daily.
- **`GET /api/diag`** runs one keyless search and reports what *that host* gets
  from the scholarly APIs. Bypasses the cache (a cached answer can't tell you
  what the sources are doing now) and is therefore rate-limited — each call
  spends real quota. Its per-source `cached` flag is always `false`. The
  `full_text` block probes Unpaywall, which the three search probes never touch
  (#104).
- The `github-pages` **environment** carries its own branch allowlist, separate
  from the workflow's trigger list. A branch rename has to consider both.
- **Hugging Face Spaces and Fly.io were tried and rejected** — both require a
  payment method. Don't re-litigate.

## Setup / testing

- `pip install -e .` (a SessionStart hook in `.claude/settings.json` runs
  `.claude/setup.sh` in web sessions).
- `python tests/test_offline.py` — pure logic, no keys or network. Each test is
  wrapped, so one crash no longer aborts the rest against a dirty environment.
- `python tests/test_offline.py --live` — one real `generate_json` and one
  `gather_evidence` query. Spends credit and quota, so it is opt-in and lives
  behind `workflow_dispatch` in `.github/workflows/live-smoke.yml`. **Every
  production failure on record happened on the seam the offline suite fakes**
  (#77 ceiling, #79 refusal, #81 routing), so run it after touching a model id,
  a ceiling, the routing or `sources.py`.
- **Provider tests assert on the payload, not on the source text.** `'"type":
  "json_schema"' in src` passes if the string sits in a comment and breaks on a
  refactor (#98). `_capture_openrouter` returns what a fake `requests.post`
  received; `_FakeAnthropic` goes into `sys.modules` because
  `_anthropic_generate` imports the SDK inside the function. The ceiling
  assertions follow `OPENROUTER_DEFAULT_MODEL` rather than named models —
  pinning names is how #77 stayed green while live requests truncated.
- **The key-leak guard is behavioural.** It greps *all* seven modules with a
  regex covering `[...]=`, `.update(` and `.setdefault(`, then runs a real call
  through a fake transport and asserts `os.environ` is byte-identical. The old
  version checked one exact spelling in two modules, on the project's most
  security-relevant invariant.
- `python tests/test_journal_conformance.py` — every convention in
  `docs/journal-style.md` over five fixtures. Run after any render change; add a
  convention here when you add one there.
- Set `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`, or use `--model cli:opus`
  with no key at all. Optional: `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_MAILTO`.

## Conventions

- Keep all LLM calls behind `llm.generate_json`; don't call the SDKs directly
  from `writer.py` / `ideas.py`.
- New structured-output schemas must produce valid JSON matching the schema —
  avoid `additionalProperties` reliance and unsupported constraints.
- Add a case to `tests/test_offline.py` for any new pure-logic behaviour.

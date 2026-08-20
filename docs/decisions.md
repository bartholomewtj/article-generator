# Decisions and post-mortems

Settled history. **Read this only when you are about to touch the area it
covers** — nothing here constrains a change you are not already making. Live
invariants live in `CLAUDE.md`; this file is where the story behind them went so
that file could stay short.

Each entry says what was tried, what was measured, and what was decided. If an
entry ever stops being true, delete it rather than editing it into a claim —
that is what `CLAUDE.md` is for.

---

## Providers

### Groq was removed (August 2026)

Groq was the free default. Its free tier metered **12,000 tokens per minute**
and counted reserved output against that, which is why `prompt_budget_chars()`
and the abstract-trimming path in `_format_sources` existed, and why Groq drafts
were abstracts-only — a single full text did not fit inside the minute.

Nothing left has a per-minute ceiling, so both mechanisms went with it. **Don't
reinstate a character budget without a provider that needs one.** A bare
Groq-era model name now raises with the OpenRouter slug to use instead, rather
than reaching OpenRouter as a slug it has never heard of and 404ing seconds
later — that error named neither the removed provider nor the fix.

### `#77` — the output ceiling was sized for the wrong model

`#74` repointed the default model without resizing the output ceiling. Thinking
is spent from the same budget as the reply, so a ceiling that was ample for a
bare JSON reply on a non-reasoning model truncated one mid-object.

**A truncated reply is invalid JSON, not a short one.** It surfaced as a parse
error nowhere near its cause. Both the truncation check and the parse error now
name the finish reason and the ceiling. Headroom is free — OpenRouter bills
tokens generated, not tokens reserved.

The lesson for the tests: the regression test pinned *named models*, so it
stayed green while live requests truncated. Ceiling assertions now follow
`OPENROUTER_DEFAULT_MODEL`.

### `#79` — refusals on exactly what this project writes about

Opus 5 and Fable 5 run elevated bio/cyber classifiers that false-positive on
clinical and life-sciences topics. On OpenRouter a refusal arrives as
`finish_reason == "content_filter"` or `native_finish_reason == "refusal"`; on
the direct Anthropic path it is a normal HTTP 200 with `stop_reason == "refusal"`
and **no text block**, which surfaced as a bare `StopIteration`.

A refusal can arrive mid-reply with partial content. That fragment is discarded,
which is what stops it resurfacing as "invalid JSON" pointing at the model's own
half-written sentence.

`#45` added the Anthropic server-side fallback (`fallbacks: "default"` plus the
`server-side-fallback-2026-07-01` beta), attached by model prefix because older
models reject the parameter outright.

### `#81` — OpenRouter advertised a capability that was not there

`provider: {"require_parameters": true}` filters on what a provider
*advertises*. OpenRouter re-sells the Anthropic models from nine endpoints and
listed an Azure one as supporting structured outputs; the workspace behind it
returned `400 structured_outputs not supported in your workspace`.

So `_openrouter_provider_routing` also pins `anthropic/*` to
`only: ["anthropic"]`. Provider selection is dynamic, so a routing fault appears
intermittently and looks like a new bug each time. The server that answered is
in the error body's `provider_name`.

### `claude-cli` — the MCP prompt tax

MCP servers are attached to every `claude -p` call unless suppressed:
**22,944 tokens with them against 2,363 without**, for the same trivial call.
Only `--strict-mcp-config` with an empty `--mcp-config` suppresses them;
`--tools ""` does not.

On Windows `claude` is a `.cmd` shim, so its command line goes through cmd.exe
and the ceiling is **8,191** characters, not 32,767. Anything that scales with
the sources or the schema has to go on stdin.

The CLI enforces no response schema, unlike the API paths. The first real call
answered a JSON-schema prompt in YAML and cost the whole run at the first of
eight stages.

### `#147` — repairing near-miss JSON on `claude-cli`

`claude-cli` cannot enforce a response schema. Measured: 3 of 5 `write_article`
calls on `cli:opus` returned non-JSON at least once, and one run died after its
retry with `Expecting ',' delimiter: line 1 column 4942` — a complete article
one comma short.

Repair is deterministic rather than an LLM retry: asking a model to fix its own
JSON rewrites the text, and the article we were trying to salvage is what gets
lost. Acceptance requires both valid JSON and a dict root — callers of
`generate_json` expect a mapping, so a repair that yields a list or scalar is
unusable.

### `gemini-cli` — do not step the shallow calls down a tier

It is a one-line change and it looks free: both cheap tiers report
`thinking=0`. Measured, at `-low` curation agreed with `-high` on only **14 of
20** relevance labels and collapsed everything toward "related" — and that gate
is what stops topic drift. `plan_queries` emits run-on queries at `-low` *and*
`-medium`. The measurement sits in `llm.py` above `GEMINI_CLI_DEFAULT_MODEL`.

Other measurements on this provider:

- **~21,600 tokens of agent scaffolding per call**, about 39% of a run's input.
  No flag suppresses it. The metered API providers pay none of it.
- **88% of output tokens are thinking**, so changes that reduce emitted *text*
  barely move the bill. Measure output against `thinking_tokens`, not word count.
- `agy` ignores stdin. The prompt goes over as `-p "@<file>"` with `--add-dir`,
  which the CLI inlines verbatim — tested at 98KB. The article prompt is ~95,000
  characters against a 32,767-character Windows command line, so argv is not an
  option either. Asking the agent to *open* a file instead is worse: it costs a
  tool round-trip and once answered from a different file in the same directory.
- The Google `gemini` CLI is not an alternative. It refuses to authenticate at
  all — `IneligibleTierError`; Code Assist for individuals is retired in favour
  of Antigravity.

### `#116` — the revision call's input, explained

**Closed.** It was measured against the wrong number. Nothing was overcounting.

One full `agy` draft, all four calls, reported input against what was sent:

| call | sent `~tok` | `in` | against `33,000 + 0.77 × ~tok` |
| --- | ---: | ---: | ---: |
| plan_queries | 235 | 33,858 | +677 |
| curate | 13,095 | 43,315 | +232 |
| write | 28,343 | 55,381 | +557 |
| revise | 35,293 | 101,549 | +41,373 |

Three of the four sit within ~700 tokens of a straight line: a fixed floor of
about 33,000 tokens, plus the prompt counted **once**. The slope is 0.77, not 3
— our `~tok` estimate at 4 characters per token simply runs about 25% high on
this prose.

**The three-ways hypothesis is dead**, by two independent routes. The slope
rules it out arithmetically. A direct A/B rules it out by experiment: three runs
each with and without `--add-dir`, same 20,159-character prompt, gave 47,122 vs
47,088 mean total context — a 0.07% difference — and a canary buried at 80%
depth of the prompt came back in all three runs *without* `--add-dir`. So
`--add-dir` neither multiplies the count nor is needed for the prompt to
arrive. Contrary to what this file used to say, it is not load-bearing.

**Where the original figure went wrong.** "A brief-plus-draft of roughly 20,000
characters" left out the SOURCES block. `revise_prose` sends brief + sources +
draft, and `sources.FULLTEXT_TOTAL_CHARS` allows 60,000 characters of full text
on its own. The measured revision prompt was **141,173 characters**, seven times
the assumed size. The note above in this same file already said the article
prompt is ~95,000 characters; the two never got reconciled.

Two further traps this ran into, worth keeping:

- **Read `in + cached`, not `in`.** The fresh/cached split swings hard on
  identical inputs — 18,514 to 26,775 fresh across six runs of one prompt —
  while the total held to ±0.1%. The 135,273 in the original report is one side
  of a noisy split.
- **The floor moves between sessions, not within them.** A 61-character prompt
  reported ~88,500 total in one session and a 940-character prompt ~90,900 in
  another, but six runs inside a single session varied by 111 tokens. Compare
  calls within a run; never across.

**Left open, deliberately:** the revision call — and only it — sits ~41,000
tokens above the line. It is both the largest prompt and by far the most
thinking (31,735 tokens, roughly double the next call). It is not prompt
duplication. The cause is unidentified and the cost is small enough to leave.

---

## Prose style

### The revision is a patch because a rewrite was measured

Rewriting 3,586 words to fix three sentences cost **26,632 output tokens against
the 24,191 that wrote the article**. A patch emitted 333 where a rewrite emitted
1,341 on the same draft.

`too-few-sections` is the one failure that still buys a whole rewrite
(`rewrite_whole=True`), because a patch can only replace a block that exists.

### Sources travel with a revision only when they can be used

A register failure is told to reword and add nothing, so shipping it 20
abstracts and 60,000 characters of full text was ~30,000 input tokens the model
was forbidden to use. Measured: **95,042 → 30,540**.

The substance rules are the opposite case — they fail a draft for saying too
little, so `revision_brief()` inverts and tells the model to pull specific
findings, and it needs the sources to pull from.

### Why the substance rules exist at all

Every other rule is a *prohibition*, and a model optimising only against
prohibitions writes vague hedged filler: asserting nothing breaks no rule.

### The corpora, and what they settled

`tests/real_abstracts.json` and `tests/style_corpus.json` — 20 abstracts, 20
journals, stratified by article type × domain.

- **The register rules model one voice: a synthesis speaking about other
  people's work.** A trial report legitimately says "we randomly assigned";
  `articlegen` must not. 7/7 investigator-voice abstracts fire a register rule,
  0/13 synthesis-voice ones do. So **a primary-research abstract is not a
  negative control** for the first-person rule.
- **The hedging floor is calibrated on body prose, not abstracts.**
  `tests/body_prose_measurements.json`: 18 open-access reviews, median 0.216
  hedges/sentence. Published abstracts run at 0.031 and are the wrong text type
  — don't re-open this with abstract data (`#56`).
- Clinical advice is the same argument as investigator voice, with consequences.
  A *Lancet* trial abstract in the corpus concludes its intervention "should be
  standard treatment". Those authors ran the trial and may say it; `articlegen`
  may only report that they said it. It is the one corpus abstract that fires
  `clinical-directive`, and that is correct.

### Nominalisation counting was deleted deliberately

In this domain it measures the topic, not the prose. Don't reinstate it without
a stoplist.

### The abstract, key points and Introduction are three jobs

Asking all three to be self-contained made the model write the same paragraph
three times. `echoed-abstract` measures the overlap and the writer prompt
carries a DIVISION OF LABOUR block. Don't reinstate "self-contained" on more
than one of them.

### `#102` — a shipped draft contained a treatment plan

`drafts/2026-07-19-prescribing-the-blue-sky-….md` carried a titration protocol —
"starting with a low-dose exposure of 15 minutes per day… titrated upward by 15
minutes each week… ensuring therapeutic antipsychotic levels is an absolute
prerequisite" — for a population the same article stated had **zero** studies.

The footer disclaimer does no work against that: a reader who has reached a dose
and a schedule has already been given advice.

The same issue found `Box 1 | Key study`, which claimed an appraisal nothing in
the pipeline performs. `curate_sources` ranks on topic fit alone, so one draft
boxed a scoping review as the "key study" while an adequately powered trial sat
in the body.

### `#145` — long-sentence warnings survived every draft

Measured across three recent runs: 21 long-sentence warnings total (4, 5 and 12
per draft), mean sentence length 28–30 words, including a 61-word sentence in a
Conclusions section. One run logged "Prose style: clean" while printing 12
long-sentence lines in its diagnostic output. Because `long-sentence` was a
warning rather than an error, `revision_brief()` excluded it: the revision pass
fixed error-level issues and left every long sentence in place.

Warnings were excluded from the brief originally because a warning is a matter
of degree and must not be able to spend an LLM revision call on its own.
Promoting `long-sentence` to an error would have bought a revision for every
single long sentence and put sentence length into the acceptance count, which
is calibrated strictly on journal-breaking errors.

The fix is ride-along: `RIDE_ALONG_WARNINGS` (long-sentence, wordiness,
passive-voice) are appended to `revision_brief()` under a secondary "Also fix
these" heading only when errors have already triggered the revision pass. If
there are no errors, no revision occurs and warnings remain informational.
`under-length` is excluded from the ride-along set because it is a substance
rule and would cause the brief to reference sources that `enforce_style` does
not provide for register-only fixes.

### `#146` — a second revision pass, gated on progress

Two of three runs finished with exactly one residual style error after a
revision that had already worked: 3 → 1 and 2 → 1. One error is enough for
Limitations to brand the article "a working draft rather than a finished
review", so the last error was costing the article's framing for want of one
more targeted edit.

The gate is progress, not a retry count. `enforce_style` loops only through the
accept branch, and acceptance already required strictly fewer errors, so an
error the model cannot fix still costs exactly one call. `MAX_STYLE_PASSES` is
2 rather than 3 because the residual being paid for is one error; nothing on
record suggests a third pass has anything to do.

---

## Grounding and provenance

### `#139` — one paper, two references

Two of three recent runs cited the same paper twice as separate references:
`10.1001/jamapsychiatry.2025.1317` (Janik et al.) and `10.1111/jan.16056` (N-PACT).
The four search sources spell a DOI three ways — resolver URL, mixed case,
bare — and wording differences in the title (such as a subtitle or markup)
allowed duplicates to slip past title-based dedupe.

The fix normalises DOIs with `_normalize_doi` and merges duplicate metadata
field by field into the first-seen record (`_merge_duplicate`). A literal
"keep the richer record" swap would have broken the invariant that querying
arXiv last discards a preprint in favour of the published version, since a
preprint with higher citation counts would displace the peer-reviewed
article. Merging field by field enriches the kept record while preserving
first-seen identity.

### `#144` — preprints were indistinguishable from peer-reviewed papers

A draft cited a Research Square preprint (DOI `10.21203/rs.3.rs-9924877/v1`)
beside a Cochrane review with nothing to tell them apart; the only difference on
the page was a blank journal cell in Table 1's Source column. The masthead's
"Not peer reviewed" refers to the generated article itself, not its sources.

Preprints are now detected in `articlegen/sources.py` using API type metadata
(OpenAlex `type == "preprint"`, Europe PMC `PPR`, arXiv unconditionally) with
an identifier fallback (`_looks_like_preprint`) in `Paper.__post_init__` for
DOI prefixes like Research Square and bioRxiv/medRxiv. `10.1101` requires a
following digit (`10.1101/\d`) because Cold Spring Harbor Laboratory Press
uses the same prefix for both preprints and its peer-reviewed journals (such as
Genome Research, `10.1101/gr.*`).

The preprint flag is never merged across duplicate records in
`_merge_duplicate` because first-seen identity wins and arXiv is queried last
specifically to favour published versions over preprints. `articlegen/render.py`
marks preprints in Table 1's Source column and appends `(preprint, not peer
reviewed)` to reference entries in HTML and Markdown.

### `#75` — the article contradicted itself about its own evidence

A shipped article said "full texts of 7 sources were retrieved" in Methods and
"prepared from abstracts alone" in Limitations, plus an "Abstract-derived
synthesis" masthead and a "(not full texts)" colophon. Methods read provenance;
the other four were hardcoded.

That is why **every provenance statement is derived and there is deliberately no
fallback**. A fallback constant is how the false claim came back the first time.

### `#54` — the model's own tallies contradicted the computed ones

The model used to write an `evidence_note` in the Evidence assessment section.
One article claimed "13 out of 20 sources" beside a computed line reading 9;
another claimed "5 sources", "the majority is related" and "some are tangential"
against a computed 3 cited, all direct, none related, none background.

Nothing countable in that section is model-written now.

### `#101` — the global fallback hid misattribution

`check_statistics` accepted a figure found anywhere in any source. So a real
number lifted from paper 12 and credited in the prose to paper 3 passed silently
as verified — the misattribution that most changes clinical meaning was the one
thing the check could not see.

The same pass found `_FIGURE_RE` matching no bare integers and no dose or
concentration units, so "7,000 lux", "15 minutes per day", "50 ng/mL", "109
cases" and "441 participants" were never checked at all.

### `#92` — the retraction did not travel with the number

A draft's first Key point stated an odds ratio of 0.66 (95% CI 0.43–0.99). The
note that those figures could not be located appeared about **ninety lines
later**, with no way to tell which figure it meant — while the number carried a
superscript citation, the strongest "this came from that paper" signal on the
page.

The practical failure: someone copies the Key points into a team email. The
numbers travel; every qualification stays behind.

### Resolving PMCIDs recovered 9 of 11 full texts

Only the Europe PMC *search* returns `pmcid`/`inEPMC`, so anything from OpenAlex
arrives with an empty pmcid regardless of licence — including wholly open-access
journals whose full text Europe PMC serves perfectly well. On one real run that
cost 9 of 11 available full texts: 2 were fetched where 11 could have been.

### `#104` — a fourth keyless dependency that failed invisibly

`resolve_pmcid` gained an Unpaywall fallback in `#103`. Both failure paths were
`except SearchFailure: pass`, so a rate limit, a blocked contact address or a
changed response shape would drop every article to abstracts-only grounding,
with Methods correctly reporting the lower count and nothing pointing at the
cause.

### Which scholarly API works changes — measure, don't write it down

Both open sources refuse constantly from Render's shared egress IP and they swap
places. `OPENALEX_MAILTO` is set and joining the polite pool did **not** fix
OpenAlex: the constraint is the shared cloud IP, not the contact address, so
changing region is not a fix either. Run `/api/diag` and read the result.

### `#117` — curating on truncated abstracts destabilises the gate

**Closed. Do not truncate at 400 characters.** `CURATION_ABSTRACT_CHARS` stays
`None`, now on evidence rather than caution.

`tools/compare_curation.py --chars 400`, four topics, 20 papers each, same paper
list curated twice so prompt length was the only variable:

| | result |
| --- | --- |
| overall agreement | 64/80 |
| `direct` retained | 27/30 — **gate degraded** |
| `tangential` retained | 12/17 — **gate degraded** |

Every one of the four topics moved at least one gating label, so it fails the
acceptance rule outright, with no marginal call to make.

**It fails differently from the cheaper-tier run, and the difference matters.**
That one collapsed every disagreement toward `related`. This one moved 8 labels
*into* `related` and 8 *out* — 5 `tangential`→`related` against 5 the other way,
3 `related`→`direct` against 3 the other way. Perfectly symmetric. Truncation
does not bias the gate, it destabilises it: the first 400 characters keep the
title and topic but drop the population and outcome detail that separates
`direct` from `related`, and what replaces that signal is noise, not a lean.

The harness reported this as a collapse, because it counted only the moves
*into* `related`. That counter now reports both directions and nets them — a
one-way count cannot tell a collapse from churn, and the two want different
fixes.

**The prize was smaller than advertised.** The issue estimated ~24,000 input
tokens saved per curation call. Measured across the four topics: 13,688 /
19,154 / 12,877 / 5,438, mean **~12,800**. Roughly half.

Measured on `agy:gemini-3.6-flash-high`, not on the metered default, because
the OpenRouter key was dead. A different model could in principle hold its
labels better under truncation — but the margin here is wide, not marginal, so
that would change the explanation and not the verdict. If it is ever re-run,
a larger `--chars` is the only version worth trying, under the same rule.

### `#143` — the deep reads went to the oldest papers

Measured on a recent run: the read-subset skew line reported `read n=5 median
year 2019, median citations 122; abstract-only n=15 median year 2023` — the five
full texts went to older, highly-cited papers while the most current
directly-relevant syntheses got abstract-only treatment. The article then
printed the standing limitation that abstract-only sources could not be
appraised — about exactly the papers doing the most work.

Rank order sorts on topic overlap then citation weight, so citation weight
inside `_rank_score` pulled old, heavily-cited work to the top of the fetch
list. Raising `FULLTEXT_TARGET` was not the fix: the excerpt budget is already
full at 5 × 12,000 characters (`FULLTEXT_PER_PAPER_CHARS` × `FULLTEXT_TARGET` =
`FULLTEXT_TOTAL_CHARS`).

The fix is ordering only (`full_text_order`): attempt the eligible set in
relevance order (direct before related), newest publication year first within a
tier, search rank breaking remaining ties. Tangential and unlabelled sources are
still excluded even if the target goes unmet.

What to watch next: the skew line on the next few real runs. If the read subset
now runs *newer* than the abstract-only rest, that is the change working, not a
new problem.

### `#141` — a pool of 20 was inclusion, not curation

Three mental-health runs on 2026-08-15 each collected **exactly 20** candidates
and cited 16-19 of them. Hitting the cap every time is the tell: the pool was
capped, not exhausted, so the direct/related/tangential gate was choosing from a
list that had already been cut for it.

The cost was specific. The seclusion run planned the query "Safewards trial
conflict containment acute mental health wards" and the Bowers Safewards cluster
RCT still never made the pool — it reached the article only second-hand, quoted
inside an integrative review. Twenty slots ranked with a recency weight fill
with recent reviews, and the landmark primary trial they all cite is what gets
squeezed out.

The default is now `DEFAULT_MAX_PAPERS = 40`, defined once in `sources.py` and
read by `gather_evidence`, `generate_draft`, the `--max-papers` flag and the web
handler. It was previously written out four times, and the web handler's copy
was a hardcoded argument rather than a default — raising the pipeline default
alone would have left the deployed app on 20.

**Paid for in tokens, not in truncation.** Curation grades every candidate on a
full abstract, so the curation call roughly doubles (~13,000 input tokens
measured at 20). That is the accepted price. Truncating those abstracts is the
one thing that must not be traded here: `#117` measured it and it destabilises
the gate, so `CURATION_ABSTRACT_CHARS` stays `None`.

What to watch on the next few real runs:

- **Does the gate now discard?** Cited-of-collected should fall well below the
  16-19 of 20 that prompted this. If runs still cite nearly everything, the
  problem is the gate's labelling, not the pool size.
- **`per_query` is still 25 and was not raised.** A topic that comes back with
  fewer than 40 candidates is a thin literature, not a bug — but if that is the
  common case, the cap is not the binding constraint and this change is inert.
- **The full-text stop reason.** The eligible list doubles while
  `MAX_FULLTEXT_REQUESTS` stays 18, so "request cap reached" should become the
  usual exit and its NOTE should fire routinely. That is the log doing its job.
  Whether 18 is still the right number is a separate question with its own
  measurement.

### `#142` — load-bearing statistics arrived second-hand

A draft from the 2026-08-15 runs opened its Introduction with three numbers the
writer never saw at first hand (14.4%, 15.8% and 25.6% restraint-seclusion
prevalence; 25–47% PTSD; and a Cochrane review quoted inside a realist review).
The prose labelled this honestly ("a meta-analysis cited within a Canadian pilot
study estimated…"), but `verify.check_statistics` searches only the material the
writer was shown. The quoted figure is present in that text, so it verifies —
the check can only ever confirm that the quoting paper printed the number, not
that the originating study reported it. If the quoting paper misquoted, the error
entered the article with a citation that looked verified.

Chasing nested references — resolving a DOI mentioned inside body text and
fetching the original study — would introduce a new fetch path, new failure modes,
and no guarantee the nested work is open access. That path was left out of scope.

Instead, the writer's system prompt now instructs it to avoid building the
`title`, `abstract`, `key_points` or the opening claim of the Introduction on a
figure its source attributes to another work, whenever any supplied source
reports a comparable figure at first hand. Where a second-hand figure is the only
evidence available, the existing "cited within"-style attribution is preserved so
the reader can see it is second-hand, citing the source actually read.

Because this is a prompt-side rule without deterministic enforcement, it is a
tendency rather than a guarantee: a future draft may still occasionally lead with
a quoted figure if no first-hand alternative exists or if the model leans toward
it. Refs #142.

### `#148` — keyless Semantic Scholar 429'd for a whole session

Measured across four runs spanning more than an hour: every FIRST Semantic
Scholar query returned HTTP 429 after 3 attempts, and the `exhausted` set
then (correctly, per design) skipped the source for the rest of each run.
Net effect: Semantic Scholar contributed nothing all session, and every draft
ran on the remaining databases.

Weakening the `exhausted` set was rejected: re-attempting a dead source on
every query wasted ~10s each time. Raising `_MAX_BACKOFF` or waiting out a
cool-off longer than the 30s cap was also rejected: a user is watching a
progress bar.

The code-side change is narrow: `_S2_PATIENT_WAIT` gives ONLY the first Semantic
Scholar attempt of a run one extra retry round after waiting at the existing
`_MAX_BACKOFF` ceiling (30s) before declaring the failure that exhausts the
source. `_preflight_sources` passes `patient=False` so the probe fails fast
without adding 30s. A failure with `retry_later = False` (non-retryable HTTP
status or cool-off past `_MAX_BACKOFF`) gets no wait.

The real fix remains setting the free `SEMANTIC_SCHOLAR_API_KEY`, which is an ops
task and stays open. Refs #148, stays open.

---

## Web app and deployment

### `#100` — the reader iframe ran same-origin

It is fed model-written HTML, and `#read=`/`#p=` links let anyone hand a visitor
a page of their choosing. Unsandboxed, that page ran same-origin with the
OpenRouter key in localStorage.

`allow-same-origin` without `allow-scripts` is the fix. It does not re-enable
scripts; it is what keeps `contentDocument` reachable for the theme sync,
in-place edit and save. Articles for the app are rendered `standalone=False` so
there is no dead toolbar behind the sandbox.

### `#113` — localStorage is scoped to the origin, not the path

Every GitHub Pages site under `bartholomewtj.github.io` is one origin, so a
stored key was readable by any other project the account publishes — now, or
years from now — and by anyone with push access to those repos. The article
generator was never the risk; the neighbour is.

The Settings panel said the key was "never shared with anyone else": true about
the network, misleading about the origin, and the second half is what a reader
takes to mean "only this app can reach it".

The `#100` sandbox is a different threat and does nothing about this.

### `#95` — the first visit dead-ended after the longest possible wait

A stranger opened the site, saw nothing about a key, typed a theme, tapped, sat
through the ~50s Render cold start, and got the server's 400 as a raw browser
`alert()` telling them to open a gear icon among five icon buttons.

Related, same session: a visitor was shown `RuntimeError(... invalid JSON ...)`
plus 500 characters of raw JSON on their phone, and the progress timeline's last
message fired at 30s against a 60–90s run, so the longest part of the wait was
the part where nothing changed.

The pieces, since the test pins the behaviour and not the names: `requireKey()`
gates `requestIdeas` and `selectDraft` before the fetch and reads `activeKey()`;
`setupCard` on the landing view is hidden by `refreshSetupCard()` once
`saveApiKey` has stored one; `warmBackend()` starts the cold start on page load;
`whileWaking()` swaps in the explanation after 8s — the copy existed but only
inside `apiError`, so it appeared after a failure and never during the wait it
explains. Failures land in `#progressError` with a Try again that repeats
`lastAction`.

### `#96` — the throttle was one global bucket

`_rate_limited` keyed on `client_address[0]`, which behind Render's load
balancer is the *proxy*. So "per-IP, 20 requests/hour" was a single bucket
shared by every visitor: one abuser locked out everyone — the exact failure the
throttle exists to prevent — and a direct attacker could not be attributed.

The per-IP limit also protects nothing the scholarly APIs care about. They meter
against the server's single egress IP, so upstream load scales with visitor
count while every individual stays politely under 20.

And `plan_queries` is a paid LLM call that ran before anything touched a
scholarly API, so on a day when every API refused, the caller paid for a run
that was doomed from the start.

### One article library, because two cost 65KB a save

There were two stores holding the same articles — a "Draft Review Queue" over
`articlegen_local_drafts` and a "Published Library" over
`articlegen_published_library`. Same articles, duplicated search / delete /
clear-all / open, and saving to the second wrote a second full copy of ~65KB of
HTML against a ~5MB quota, with a bare `setItem` that silently lost the article
when it threw.

### The article shape stopped being a preference

Tone, length and evidence depth were selectors. Every option except *in-depth
longform + strict empirical* asked for prose that `style.py` then failed: a
~500-word draft has no room to report what each study did, in whom, and what it
found, and the narrative depth asked for storytelling over methods. Output
language is the only choice left.

### `protocol_version = "HTTP/1.1"` — the flaky-network investigation

`http.server` defaults to HTTP/1.0, which closes the connection after every
response. Pooling clients then fail instantly on a socket the server already
hung up on.

It presents as flaky networking — roughly half of fetches failing in ~140ms —
and **curl cannot reproduce it**, because each invocation opens a fresh
connection. That is what made it expensive to find.

### Hugging Face Spaces and Fly.io were tried and rejected

Both require a payment method. Don't re-litigate.

### `#47` — a branch rename could stop deploys invisibly

"Is the running backend the code I just merged?" and "which branch does the host
deploy from?" both needed a dashboard login to answer. `GET /api/health` reports
the branch and commit the running service was built from, which turns "deploys
may have silently stopped" into a one-line check.

The `github-pages` **environment** carries its own branch allowlist, separate
from the workflow's trigger list. A rename has to consider both.

---

## Process

### `#114` — CLAUDE.md drifted and nothing noticed

By the audit on 12 August 2026 it named `.github/workflows/pages.yml` (the file
is `deploy-pages.yml`), documented three FULLTEXT constants that no longer
matched the code, listed `SUBSTANCE_RULES` without `under-length`, and described
Groq as the default provider after Groq had been removed in the same session's
earlier work.

None were hard to fix. All four survived until someone went looking, and a wrong
doc costs more than a missing one — every session loads that file and trusts it
on sight.

Four options were on the table: a PR-template checkbox, a CI gate, a periodic
audit, or nothing. The CI gate was chosen, with the objection to it answered:
the override is `Docs: n/a - <reason>` in the PR body, so opting out is a
sentence someone wrote rather than a box someone clicked.

### `#98` — the tests covered everything except where the failures were

All seven production failures on record happened on the live provider and
scholarly-API seam, which the suite excludes by design. Two of three provider
functions had no behavioural test at all; the load-bearing assertions were
source-text greps that pass if the string sits in a comment; the key-leak guard
checked one exact spelling in two modules; and one crash aborted the rest of the
run against a dirty environment.

### `#99` — this file exists because `CLAUDE.md` was 573 lines

It mixed live invariants with settled history at the same visual weight, so a
reader returning cold had to read all of it to learn which roughly fifteen
warnings still constrain a change. Most of those invariants already have a named
guard test, so the prose was duplicating the test suite and growing every
session.

### `AGENTS.md` and `GEMINI.md` were removed (August 2026)

An ICM review of the workspace found both sitting at the repo root: two
byte-identical 427-byte files whose entire content was "read `CLAUDE.md`".
Neither was tracked, neither was gitignored, and nothing in CI, the hooks or
the doc-link scripts referenced either name. Some agent tool's `/init` had
written them and nobody had noticed.

The content was harmless. The links were not. Both pointed at
../../config/CLAUDE.md and ../../IDENTITY.md — paths that resolve correctly on
the author's disk, which is the whole trap. They work when you test them, and
they point a **public** repo at a private layout the first time anyone runs
`git add -A`. Collie found the same generated pair for the same reason and
deleted it in its 0.41.2, having also had to unpick it from an entry-doc list
and a pre-commit pattern first.

Three options: fix the links to be relative-safe, keep the files as pointers,
or delete them. Deleting won because a pointer file that says only "read the
other file" costs a read and buys nothing — a cold agent opening it learns to
open the file it would have opened anyway. What it does buy is a second place
for the agreement to live, and two hand-maintained agreements drift. The root
of the workspace keeps one `AGENTS.md`, because a non-Claude agent starting
there has no other route to the rules; a repo that already has a `CLAUDE.md`
does not need the hop.

Both names went into `.gitignore` rather than being left to vigilance, since
the tool that wrote them once will write them again. That makes a deliberate
one need `git add -f`, which is the right way round: the accident is silent and
the intent is typed.

`.agents/AGENTS.md` was a separate case and was *not* simply deleted. It held
two real UI rules — matching a sub-template's `:root` defaults to the app's
dark theme, and opting key inputs out of password-manager autofill — that
existed nowhere else and that no session ever loaded, because Claude does not
read that folder. Both moved into the Web app section of `CLAUDE.md` before the
file went. Content stranded in a runtime folder is a worse failure than a
redundant pointer: the pointer wastes a read, the stranded rule gets
rediscovered the expensive way.

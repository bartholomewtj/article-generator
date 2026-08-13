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

---

## Grounding and provenance

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

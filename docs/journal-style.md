# House style: the conventions of a scientific journal article

This is the reference for how `articlegen` output is shaped. It was written by
reading the author instructions of the highest-profile journals (Nature, Science,
the Nature Reviews titles, JAMA) and extracting the conventions a reader
recognises on sight. Every convention below is mapped to the concrete thing the
code does, so the mapping can be checked rather than argued about.

## Where the conventions came from

| Source | What it fixes |
| --- | --- |
| [Nature formatting guide](https://www.nature.com/nature/for-authors/formatting-guide) / [initial submission](https://www.nature.com/nature/for-authors/initial-submission) | Summary paragraph, ~3,000 words of body text, ≤6 display items, ~30 references, references carry full titles |
| [Nature summary-paragraph guidance](https://www.nature.com/documents/nature_3a_initial_revised_submissions.pdf) | The four rhetorical moves of an abstract, ≤200 words, no unexplained numbers/abbreviations |
| [Science: instructions for authors of Reviews](https://www.science.org/content/page/instructions-authors-reviews) | Reviews *must* run Introduction → subsections → Conclusions → References and Notes; abstract ≤150 words for the general reader, no citations in it; ~6 display items |
| [Nature Reviews article format guide](https://www.nature.com/documents/natrev-articleformatguide-review.pdf) | "Key points" box of 4–6 bullets; Boxes for self-contained asides; Glossary of defined terms; "Outlook" as the closing move |
| [JAMA instructions for authors](https://pubrica.com/wp-content/uploads/2025/08/JAMA_Instructions-for-Authors.pdf) | Key Points as Question / Findings / Meaning, 75–100 words, placed before the body |
| [Royal Society: title, abstract and keywords](https://royalsocietypublishing.org/rspb/article/291/2027/20241222/105261/Title-abstract-and-keywords-a-practical-guide-to) | Keyword/index-term block, 4–8 terms, chosen for retrieval not for style |
| [Rhetorical structure of science headings](https://arxiv.org/pdf/1903.04427) | Headings are short noun phrases; IMRaD-adjacent ordering is what readers expect |

## The conventions, and what we do about them

### 1. Front matter announces the article, it doesn't sell it

A journal page opens with an **article-type label** ("Review", "Perspective"), the
title, then a metadata strip (dates, subject terms, how to cite). There is no
kicker, no deck written to hook, no byline photo.

→ `render.py` emits an `EVIDENCE REVIEW` type label, a title, and a metadata
strip carrying the generation date, the subject area, the number of sources and
the screening counts. The magazine kicker and the "standfirst" deck are gone.

### 2. The abstract is a single unstructured paragraph with four moves

Nature: one paragraph, ≤200 words, accessible to any scientist, no citations, no
undefined abbreviations, structured as (i) 2–3 sentences of general introduction,
(ii) background and rationale, (iii) a "here we show" statement of the main
conclusion, (iv) 2–3 sentences of wider context. Science: ≤150 words, explicitly
"for the general reader", no citations.

→ `writer.py` replaces `standfirst` with `abstract` and specifies those four
moves and the 150–220 word budget in the schema description and the system
prompt. `render.py` sets it as a run-in `Abstract` block above the body.

**The abstract-into-Introduction echo is a model-capability limit, not a prompt
or pipeline defect** (issue #63). With the prompt's DIVISION OF LABOUR block in
place, `llama-3.3-70b-instruct` still reproduced the abstract as the
Introduction — 61% of six-word runs on one article, 100% on another — and one
revision pass did not recover it. The single-variable test (same topic, same
pipeline, `--model anthropic/claude-sonnet-5`, 6 Aug 2026) measured **0%**
overlap for both the Introduction and the key points, with 12 of 20 screened
sources cited instead of 3. The `echoed-abstract` rule stays as the guard, and a
draft that fails it says so in its Limitations paragraph — but the durable fix
for the echo is a stronger writer model, not more prompt emphasis.

### 3. A "Key points" box carries the argument in 4–6 bullets

Nature Reviews prints Key points in a tinted box at the head of the article; JAMA
prints Question / Findings / Meaning. Both exist so a reader can take the paper's
claim without reading the paper.

→ `key_takeaways` becomes `key_points`, 4–6 bullets in a bordered box — placed
**directly before the concluding section**, a deliberate departure from Nature's
head-of-article position: read in sequence, the points bridge the evidence just
presented to the verdict about to be drawn, instead of pre-empting an argument
the reader has not seen.

### 4. Index terms are printed

→ `keywords`: 4–8 retrieval-oriented terms, printed in the metadata strip.

### 5. Section structure is Introduction → thematic sections → Conclusions

Science makes this mandatory for Reviews. Headings are short noun phrases in
sentence case, not questions or jokes.

→ The schema requires the first section to be `Introduction` and the last to be
`Conclusions` (or `Conclusions and outlook`), with 3–5 thematic sections between.
The prompt bans magazine headings.

### 6. Display items are numbered, captioned, and referenced from the text

Journals run ~6 of them. A figure caption is `Fig. 1 | Bold title sentence.` then
description. Tables have the title above. Boxes hold self-contained material.

→ Three display items are generated **deterministically** from data we already
hold, so they cannot be hallucinated:

- **`Fig. 1 | Composition of the evidence base.`** — an inline SVG bar chart of
  cited sources by publication year, segmented by relevance (direct / related /
  background).
- **`Table 1 | Characteristics of the cited evidence.`** — one row per cited
  source: number, authors, year, venue, relevance to the topic, citation count
  (and, in full-text mode, how deeply it was read). It is reference apparatus,
  so it sits in the **back matter after Methods** rather than interrupting the
  prose — a second deliberate departure from journal convention.
- **`Box 1 | <featured study title>`** — the featured study's **Method,
  Results and Limitations**, each from its abstract only. The box carries no
  editorial "why this study" line: it reports the study and lets that speak.

In the body, Fig. 1 follows the Introduction and Box 1 follows the first
thematic section.

### 7. Citations are superscript numerals, numbered by first appearance

Nature style: superscript, after the punctuation, consecutive runs collapsed to a
range — `…as previously reported^1,3–5`. Not bracketed, not author-date.

→ `render.py` keeps the existing SOURCE-index renumbering, then formats markers
as superscript comma/en-dash runs linked to the reference list. Bracketed `[1]`
markers from the model are converted, never printed.

### 8. References carry full titles in Vancouver/Nature form

`Author, A. B., Author, C. D. & Author, E. F. Title of the paper. *Journal*
(Year). https://doi.org/…` — titles upright, first word capitalised, full stop at
the end.

→ Author names are reformatted to `Surname, I.` form, joined with `&` before the
last, `et al.` past three authors, DOI printed as a resolvable link.

### 9. Methods are reported so the search can be repeated

A review states its search strategy: databases, queries, dates, and how many
records were screened versus included.

→ A deterministic **Methods** section prints the databases queried, the exact
search strings, the number of records screened, the number cited, and how
deeply the sources were read: either that only abstracts were read, or that the
open-access full texts of a stated number of sources were retrieved from Europe
PMC and read alongside them. In all drafts, **Table 1 (Evidence Assessment Table)**
explicitly itemises whether full text or abstract was accessed for every cited source
in a mandatory **Read** column (`Full text` vs `Abstract`), ensuring full-text vs
abstract grounding is 100% transparent. Both claims come from provenance recorded at
draft time, never from a constant.

### 10. Limitations are stated in the article's own voice, in back matter

Journals do not print warning triangles; they print a limitations paragraph.

→ The relevance tally, the "no directly on-topic source" condition and the
unverified-figure list are rendered as a prose **Limitations** subsection under
Evidence assessment. The emoji warning boxes are gone; the information is not.

### 11. Standard back matter closes the article

Data availability, Competing interests, Author contributions, References, and a
statement of provenance.

→ All five are emitted, honestly: data availability points at the DOIs, competing
interests declares none, author contributions declares machine generation with
the model named, and the disclaimer keeps the "abstracts only" and clinical
caveats.

### 12. Typography reads as a journal, not a magazine

Serif body at a modest size on a narrow measure; sans-serif bold headings; small
sans metadata; hairline rules; a single restrained accent colour (Nature blue
rather than magazine teal). No drop caps, no pull quotes, no emoji.

→ The stylesheet is rebuilt on those rules. Drop caps and pull quotes are removed
from both the schema and the renderer.

## The prose itself

Layout is the easy half. A page can carry every display item a journal uses and
still read like a magazine feature. These conventions govern the sentences, and
because each is specific enough to test, `articlegen/style.py` tests them —
`cli.cmd_draft` runs the check after drafting and sends any failures back to the
model for one targeted revision.

| Source | What it fixes |
| --- | --- |
| [Nature Portfolio: how to write your paper](https://www.nature.com/nature-portfolio/for-authors/write) | Active voice preferred; the "Here we show" first-person frame |
| [Verb tense conventions in research papers](https://casrai.org/guides/verb-tense-conventions-in-research-papers) / [when to use past and present tense](https://milnepublishing.geneseo.edu/medical-writing/chapter/2-when-to-use-the-past-and-present-tense-of-verbs/) | Present for established knowledge, past for a specific study's methods and results, present perfect for an accumulated body of work |
| [Corpus studies of hedges and boosters](https://files.eric.ed.gov/fulltext/EJ1285159.pdf) (Hyland's epistemic-marker categories) | Hedging density: research articles hedge roughly once every two to three sentences |
| [Nominalisation guidance](https://lifelong-learning.ox.ac.uk/nominalisation/) | Prefer verbs to abstract nouns — "evaluated", not "conducted an evaluation" |
| [Sentence length and readability](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9955962/) | Sentence length is the single best proxy for grammatical complexity; vary it and cap it |
| `tests/style_corpus.json` — 20 high-cited abstracts, 20 journals, stratified across article type × domain | What published prose *actually does*, as opposed to what the guidance above says it does. See "How these numbers were checked" below |

### Which voice these rules model

Everything from §13 down describes **one register: a synthesis speaking about
other people's work.** That is the only voice `articlegen` ever writes in, and
several rules only make sense in it.

The clearest case is first person. A trial report in the *New England Journal of
Medicine* says "we randomly assigned patients"; a meta-analysis says "our
objective was to quantify". That is correct, unremarkable journal prose — those
authors ran the study. `articlegen` did not run anything, so the same sentence in
its output would claim work it has not done. §13 bans it for that reason, not
because it is bad writing.

The consequence matters when checking the rules against real articles: **a
primary-research abstract is not a negative control for the register rules.**
Measured over the corpus, the split is total — all 7 investigator-voice abstracts
trip a register rule, and 0 of 13 synthesis-voice abstracts do. So the rules are
precisely aimed; what was missing was any statement of what they were aimed at.
`test_register_rules_are_scoped_to_the_synthesis_voice` pins both halves.

### 13. Voice and person

Active where the active is available; Nature says readers take concepts and
results more clearly that way. The passive stays where the actor is genuinely
irrelevant ("participants were randomized").

The only first person permitted is the reviewing frame journals use themselves —
"here we review", "we consider". Everything else ("our findings", "I") would
imply a human author this pipeline does not have. Second person is banned
outright: it is the clearest single marker of magazine register.

→ `style.py` flags any first person outside that frame, and any second person.

### 14. Tense carries evidential weight

Present tense asserts that something is established; past tense reports what one
study did. Using the present for a single recent finding claims a consensus that
one study cannot support.

→ The prompt specifies the three-way split (present / past / present perfect) and
requires tense to stay consistent within a paragraph.

### 15. Hedge to the strength of the evidence

Corpus work on research articles puts hedging at roughly one marker every two to
three sentences — more than one word in fifty. Under-hedging is not neutrality;
it is over-claiming.

→ `style.py` counts hedges from the standard epistemic-marker categories and
raises an error below one per five sentences (0.20), once the draft is long
enough for the density to mean anything.

**That floor is a house preference, not a measurement — and the corpus shows how
far it sits from published practice.** Across the 20 abstracts:

| | hedges per sentence |
| --- | --- |
| all 20 | median **0.031**, range 0–0.86 |
| synthesis voice only (the register we write in) | median **0.000** |
| systematic reviews | median 0.101 |
| primary research | median 0.034 |
| narrative reviews | median 0.000 |

**17 of 20 fall below the 0.20 floor, and 10 use no hedge at all.** The floor
would reject most of the corpus.

The number cited above is not wrong; it was being applied to the wrong text. The
corpus figures for hedging describe **whole research articles**, where the
Discussion carries most of the epistemic load. An abstract compresses and
asserts, and 18 of the 20 are too short to pass the density gate (>12 sentences
*and* >250 words) at all.

**Measured against body prose, the floor is right.**
`tests/body_prose_measurements.json` holds the statistics for the body paragraphs
of 18 open-access reviews — *Lancet*, *Lancet Psychiatry*, *BMJ*, *PLoS*,
*Frontiers*, *Brain Behavior and Immunity* — with abstract and references
excluded:

| | body prose (n=18) | abstracts (n=20) |
| --- | --- | --- |
| hedges per sentence | median **0.216** | median 0.031 |
| distinct hedges | median **12** | median 0.5 |
| long enough for the density gate | 18 of 18 | 2 of 20 |

The 0.20 floor sits almost exactly on the median of published review prose. The
guess was sound; only the comparison was wrong. This is the register
`articlegen` writes in, so this is the number that governs.

The same measurement rescues `hedge-monotony`. Real review prose uses a median of
**12** distinct hedges, so requiring that no single marker exceed 40% is a fair
expectation — of an article-length text. It is not fair of a short one: at 7
hedges, 3 of one is 43%, so one extra "suggest" flips a passing draft with no
change in quality. That fired on a real article hedging at 0.389/sentence across
3 distinct markers — better on both counts than nearly every abstract measured.
`MIN_HEDGES_FOR_MONOTONY` now gates the rule at 8 hedges, below which variety is
not something published prose reliably shows either.

### 16. No boosters, no claims of proof

"Clearly", "dramatically", "remarkable", "striking", "unprecedented" assert
confidence the source abstract does not carry. "Proves", "definitively",
"conclusively" claim something almost no review can.

→ Both lists are hard errors in `style.py`.

### 17. Findings are attributed to their design

A claim's weight comes from the design behind it, so the design is named in the
sentence: "a randomized trial", "a retrospective cohort", "a two-patient case
series", "an animal model".

### 18. Sentences and paragraphs

15–30 words on average, none over 45, varied. Paragraphs of two to four
sentences: topic sentence, evidence, qualification.

→ `style.py` warns on any sentence over 45 words and on a passive ratio above
55%. (Nominalisation counting was deleted deliberately — in this domain it
measured the subject matter rather than the writing.)

**These two thresholds check out.** Unlike §15, both sit comfortably outside what
published prose does, so they flag outliers instead of the norm:

| | measured across the corpus | threshold | fires on |
| --- | --- | --- | --- |
| mean sentence length | median 23.8 words, 18 of 20 inside 15–30 | 15–30 guidance | 2 of 20 |
| passive ratio | median 0.236 | warn above 0.55 | 2 of 20 |

That contrast is the useful part: it shows the corpus is capable of ratifying a
threshold, so §15 failing against it is a real signal rather than an artefact of
measuring abstracts.

## How these numbers were checked

`tests/style_corpus.json` holds 20 abstracts drawn from Europe PMC, chosen to
span the dimensions that plausibly move the register and density figures:

- **article type** — primary research (RCTs), systematic reviews and
  meta-analyses, narrative reviews;
- **domain** — clinical psychiatry, neuroscience, health services;

all nine combinations, 20 distinct journals (*NEJM*, *Lancet Neurology*, *BMJ*,
*JAMA*, *Biological Psychiatry*, *Nature Genetics*, …), selected by citation
count within each cell and filtered to those whose title actually places them in
their cell. Each entry records the measured statistics alongside the text, and
the voice it is written in.

Two tests consume it: `test_register_rules_are_scoped_to_the_synthesis_voice`
(the investigator/synthesis split above) and
`test_density_thresholds_are_documented_against_the_corpus`, which pins the
measured distribution so that changing a threshold without re-measuring fails.

The corpus records what published prose does, which is the thing the guessed
numbers can be checked against — the same role `tests/real_abstracts.json` plays
for the register rules, and the reason both files are stored rather than fetched.

**`tests/body_prose_measurements.json` is the second half**, added because the
first has a limitation the density rules care about: abstracts are not body
prose. It holds per-article statistics for the body paragraphs of 18 open-access
reviews, fetched from Europe PMC's full-text service with abstract, tables,
figures and references stripped. Only the measurements are stored — the numbers
are the evidence, and the repo has no business carrying other people's articles.
`test_hedging_floor_is_calibrated_against_body_prose` consumes it and is what now
justifies §15's floor.

Between them the two corpora answer different questions: what register the rules
model (abstracts, where the investigator/synthesis split is visible) and what
density body prose actually runs at (full texts, the only fair comparison for a
rule that judges an article).

## What we deliberately do *not* copy

- **Fabricated apparatus.** No invented journal name, volume, issue, page range,
  DOI, received/accepted dates, author affiliations or ORCID iDs. Those are the
  parts of a journal page that would make an AI-generated synthesis look like a
  peer-reviewed paper, which it is not. The provenance line says what it is.
- **A Methods section describing experiments.** We report the *search* method,
  which is what actually happened.
- **Precision we don't have.** The abstracts-only constraint and the deterministic
  statistic check (`verify.py`) stay exactly as they were.

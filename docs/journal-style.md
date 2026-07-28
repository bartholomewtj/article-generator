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

### 3. A "Key points" box carries the argument in 4–6 bullets

Nature Reviews prints Key points in a tinted box at the head of the article; JAMA
prints Question / Findings / Meaning. Both exist so a reader can take the paper's
claim without reading the paper.

→ `key_takeaways` becomes `key_points`, 4–6 bullets, rendered in a bordered box
directly under the abstract instead of at the foot of the page.

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
  source: number, authors, year, venue, relevance to the topic, citation count.
- **`Box 1 | <featured study title>`** — the featured study's method and
  results, which used to be the "Featured study" magazine aside.

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
search strings, the number of records screened, the number cited, and the fact
that only abstracts — never full texts — were read.

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

## What we deliberately do *not* copy

- **Fabricated apparatus.** No invented journal name, volume, issue, page range,
  DOI, received/accepted dates, author affiliations or ORCID iDs. Those are the
  parts of a journal page that would make an AI-generated synthesis look like a
  peer-reviewed paper, which it is not. The provenance line says what it is.
- **A Methods section describing experiments.** We report the *search* method,
  which is what actually happened.
- **Precision we don't have.** The abstracts-only constraint and the deterministic
  statistic check (`verify.py`) stay exactly as they were.

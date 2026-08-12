"""LLM calls: plan queries, assess source relevance, then write a grounded article.

Works with any provider via articlegen.llm (OpenRouter by default, or Claude
when an ANTHROPIC_API_KEY is the available credential — see
llm.resolve_provider).

The pipeline is deliberately honest about evidence:
- `curate_sources` scores each fetched paper for how directly it addresses the
  *specific* topic, independently of how famous or highly cited it is.
- `write_article` receives those labels, is told it only ever sees abstracts,
  must flag when direct evidence is thin, and produces a featured-study box and
  an evidence note. Numeric claims are separately checked against the abstracts
  downstream (see articlegen.verify).
"""

from __future__ import annotations

import copy
import json

from .llm import generate_json
from .sources import Paper, full_text_excerpts

_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {"type": "array", "items": {"type": "string"}},
        "core_entity": {
            "type": "string",
            "description": "The single most specific subject that a source must address to be "
            "directly on-topic (e.g. 'schizophrenia', 'gravity batteries').",
        },
    },
    "required": ["queries", "core_entity"],
    "additionalProperties": False,
}

_CURATE_SCHEMA = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "The SOURCE number"},
                    "relevance": {
                        "type": "string",
                        "enum": ["direct", "related", "tangential"],
                        "description": "direct = studies the exact topic; related = adjacent "
                        "population/mechanism; tangential = only background/framing.",
                    },
                    "note": {"type": "string", "description": "≤12 words on why."},
                },
                "required": ["index", "relevance", "note"],
                "additionalProperties": False,
            },
        },
        "most_relevant_index": {
            "type": "integer",
            "description": "SOURCE number of the single best study to feature.",
        },
    },
    "required": ["assessments", "most_relevant_index"],
    "additionalProperties": False,
}

_ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "A declarative journal-style title: the subject and the finding, "
            "sentence case, no puns, no questions, no colon-clickbait.",
        },
        "abstract": {
            "type": "string",
            "description": "ONE unstructured paragraph, 150-220 words, in journal-abstract "
            "register: (1) 2-3 sentences introducing the field for any scientist, "
            "(2) the background and why the question matters, (3) a 'here we review/here "
            "the evidence shows' statement of the main conclusion, (4) 2-3 sentences of "
            "wider context. No citation markers, no undefined abbreviations, no rhetorical "
            "questions, no second person.",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "4-8 lowercase index terms a reader would search on, most "
            "specific first. Retrieval terms, not adjectives.",
        },
        "featured_study": {
            "type": "object",
            "properties": {
                "source_index": {"type": "integer", "description": "SOURCE number of the featured study"},
                "limitations": {"type": "string", "description": "1-2 sentences: what this study could not show — design limits, sample, follow-up — from its abstract only."},
                "method": {"type": "string", "description": "1-2 sentences on design/method, from its abstract only."},
                "results": {"type": "string", "description": "1-2 sentences on the main result, from its abstract only."},
            },
            "required": ["source_index", "method", "results", "limitations"],
            "additionalProperties": False,
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {
                        "type": "string",
                        "description": "A short noun-phrase heading in sentence case naming a "
                        "THEME that cuts across several studies (a mechanism, an outcome "
                        "domain, a population, a disagreement) — never a restatement of the "
                        "article's topic. The FIRST section must be headed 'Introduction' and "
                        "the LAST 'Conclusions' (or 'Conclusions and outlook').",
                    },
                    "paragraphs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["heading", "paragraphs"],
                "additionalProperties": False,
            },
        },
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "4-6 declarative bullets, each resting on a NAMED finding from a "
            "specific study and citing it. Not a precis of the abstract: a bullet must give "
            "the reader something the abstract did not — the design, population, magnitude "
            "or disagreement behind the claim. If a bullet would survive deleting every "
            "source, it is too vague to include.",
        },
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string", "description": "One sentence, plain language."},
                },
                "required": ["term", "definition"],
                "additionalProperties": False,
            },
            "description": "0-6 technical terms used in the article that a non-specialist "
            "would not know. Omit terms you never use.",
        },
        "references": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "SOURCE indices in citation order; [1] in text = first entry",
        },
    },
    "required": [
        "title", "abstract", "keywords", "featured_study",
        "sections", "key_points", "glossary", "references",
    ],
    "additionalProperties": False,
}

_CURATE_SYSTEM = """\
You are a research librarian. You judge how directly each source addresses ONE \
specific topic — not how good, famous, or highly cited the paper is in general.

- "direct": the study is actually about the exact topic (right population, right \
intervention/mechanism, right question).
- "related": adjacent — e.g. the same intervention in a different disorder, or the \
right disorder but a different question. Useful for context, not direct evidence.
- "tangential": only good for background or framing sentences.

Be strict. A famous review that never studies the specific topic is "tangential" or \
"related", not "direct". Then name the single most relevant study to feature."""

_WRITER_SYSTEM = """\
You write Review articles for a leading scientific journal — the register of a \
Nature Reviews or Science Review piece: precise, hedged, impersonal, and readable \
by a scientist outside the field. You are NOT writing a magazine feature.

You are working from ABSTRACTS ONLY — never the full papers. This constrains you:

- Cite by the exact "SOURCE N" label in brackets at the sentence's end: [6], or \
[6, 18] to combine. Never invent a source or cite a number with no SOURCE. \
(The display converts these to superscript numerals.)
- In `references`, list every SOURCE number you cited, in first-appearance order. \
(The display renumbers to 1, 2, 3…)
- ONLY state a specific number (effect size, %, sample size, confidence interval, \
p-value, risk ratio) if that exact figure appears in the abstract you are citing. \
If the abstract doesn't give the number, describe the direction and rough magnitude \
in words instead ("approximately halved", "a large effect") — do NOT reconstruct \
precise statistics from memory. Invented-looking precision is the worst failure here.
- HONESTY ABOUT THE EVIDENCE IS MANDATORY. You are told each source's relevance \
(direct / related / tangential). If few or no sources are "direct", say so plainly \
in the prose, and explicitly label anything carried over from another population or \
condition as extrapolation ("no studies in X were identified; the following is \
extrapolated from Y"). Never imply an evidence base that the direct sources don't \
support. Do NOT state counts or tallies of the evidence — how many sources were \
cited, how many are direct, related or background, and the year range are computed \
and printed for you. Every count you write is one that can contradict them.
- Lead with the strongest DIRECT evidence, and cite the related and tangential \
sources too: they carry mechanism, context and adjacent-population findings, and \
the house style asks for extrapolation to be labelled, not left out. Report what \
each found under its own label — just don't let it masquerade as a direct finding.
- featured_study: summarize the single most relevant study's method and results \
FROM ITS ABSTRACT ONLY. Prefer the most-relevant source you were given. It is \
printed as a boxed display item, so it must stand alone.

DIVISION OF LABOUR — the single most common failure is writing the same summary \
four times. The abstract, the key points, the Introduction and the body sections \
are four DIFFERENT jobs, not four renderings of one paragraph:

- `abstract` — the standalone summary. It is the only place a general overview
  belongs.
- `key_points` — specific findings, each tied to a named study. Not the abstract
  in bullets.
- Introduction — scope, why the question matters, and what the review will cover.
  It must NOT re-summarise the findings; that is the body's job and the
  Conclusions'.
- body sections — the evidence itself, study by study, grouped by theme.

Do not reuse a phrase from the abstract anywhere else in the article. If a \
sentence in one of these would read equally well in another, it is redundant: cut \
it and write the specific thing instead.

SUBSTANCE — what makes this a review rather than a summary of a summary:

- Every section must report something specific: what a study DID (design,
  population, size, duration) and what it FOUND. "The evidence suggests these
  strategies may be effective" is not a finding; "a 12-week trial in rotating-shift
  nurses reported a 62% reduction in reported insomnia [4]" is.
- GO THROUGH THE STUDIES ONE BY ONE. Every source you cite must, at least once,
  be discussed on its own — its design, its population, and what it reported —
  and not merely appended to a general claim in a bundle like [1, 4]. A citation
  bundle asserts that several studies agree; earn it by having already said what
  each of them found.
- Attribute findings to their study, not to a vague body of evidence. Name the
  design and the population in the prose.
- ORGANISE BY THEME, NOT BY REPETITION. Each body section takes one theme that
  cuts across the evidence — a mechanism, an outcome domain, a population, a
  methodological split — and works through the studies bearing on it, comparing
  them. Sections must not each restate the article's overall topic.
- Where sources disagree, say so and say how they differ — different populations,
  designs, exposure definitions or follow-up lengths are the usual reasons.
  Where one study is much stronger than the others, say why.
- Do not restate a point once made. If a section is running short, the answer is
  another finding from the sources, never another sentence about the same one.
- Hedge to the evidence in front of you, and vary how: "in a single small trial",
  "consistently across three cohorts", "no controlled study has tested". Repeating
  "it appears that" and "the evidence suggests" is worse than not hedging, because
  it hides how strong each individual claim actually is.

STRUCTURE (journal Review, ~1000-1600 words of body text):
- 5-7 sections. The first is headed "Introduction"; the last is headed \
"Conclusions" or "Conclusions and outlook" and states what is established, what \
remains open, and what evidence would settle it. Sections in between are short \
noun-phrase headings in sentence case ("Mechanisms of clearance", "Interindividual \
variation") — never questions, puns, or magazine headings.
- The Introduction states the scope and why the question matters; it does not open \
with an anecdote, a scene, a rhetorical question, or "Imagine…".
- Plain prose paragraphs only — no markdown, HTML, bullets or sub-headings inside a \
paragraph. 2-4 paragraphs per section.

REGISTER — this is checked automatically after you write, so follow it exactly:

- VOICE. Active where the active is available: "the trial reported a reduction", \
not "a reduction was reported by the trial". Nature and Science both ask for this. \
The passive is fine where the actor is genuinely irrelevant ("participants were \
randomized").
- PERSON. Third person throughout. The ONLY permitted first person is the \
reviewing frame journals themselves use — "here we review", "we consider", "we \
focus on". Never "I", never "our findings", never "you".
- TENSE. Present tense for established knowledge and for what evidence indicates \
("GHB binds GABA-B receptors"; "these data suggest"). Past tense for what a \
specific study did and found ("participants were randomized"; "the trial reported \
a 40% reduction"). Present perfect for an accumulated body of work ("several \
series have reported"). Keep the tense consistent within a paragraph.
- HEDGING. Hedge every claim to the strength of the evidence behind it — corpus \
studies of research articles find roughly one hedge every two to three sentences, \
and that is the density to write at. Use "may", "appears to", "suggests", "is \
consistent with", "remains unresolved", "in part", "typically", "has been \
reported in a single cohort". Reserve flat assertion for what an abstract states \
outright.
- ATTRIBUTION. Name the study design when the abstract gives it ("a randomized \
trial", "a retrospective cohort", "a two-patient case series", "an animal model"). \
A finding's weight comes from its design, and the reader must be able to see it.
- SENTENCES. Average 15-30 words; none over 45. Vary the length. Prefer verbs to \
nominalisations: "evaluated", not "conducted an evaluation of".
- PARAGRAPHS. Topic sentence first, then the evidence, then the qualification. \
2-4 sentences each.

NEVER GIVE CLINICAL ADVICE — this is checked automatically and it is the one \
rule with real-world consequences:

- Report what studies DID and FOUND. Never state what a clinician, a patient or \
a service SHOULD do. That is a different act from reviewing, and this article \
is not qualified to perform it.
- No dose, no schedule, no titration step, no monitoring interval, no referral \
or screening instruction — not even a hedged one, and not even when a source \
recommends it. A published trial may conclude "X should be standard treatment"; \
you are a synthesis and may only report that the trial concluded that.
- A protocol detail is reportable only when it is attributed to the study that \
used it, in the past tense: "participants started at 15 minutes daily and the \
dose was increased weekly" is a finding; "start at 15 minutes daily and \
increase weekly" is a prescription.
- "Future trials should measure X" is fine — a recommendation for research is \
not a recommendation for care.
- The footer disclaimer does not cover you. A reader given a dose and a \
schedule has already been given advice.

BANNED OUTRIGHT: second person; contractions; rhetorical questions; exclamation \
marks; boosters and hype ("clearly", "obviously", "dramatically", "remarkable", \
"striking", "unprecedented", "groundbreaking", "game-changer"); claims of proof \
("proves", "definitively", "conclusively"); "in order to"; "utilize"; scare \
quotes; jokes; emoji.

The difference this makes:
  WRONG: "Astonishingly, scientists have now proven that sleep flushes waste from \
the brain — and you should worry if you are not getting enough."
  RIGHT: "Clearance of interstitial solutes increases during sleep in rodent \
models, which has been proposed as a mechanistic link to neurodegenerative risk. \
The human evidence remains indirect."

  WRONG: "Treatment should be initiated at 15 minutes of morning light daily and \
titrated upward by 15 minutes each week."
  RIGHT: "In the single open trial, participants began at 15 minutes of morning \
light daily, increasing by 15 minutes weekly; no controlled study has tested \
this schedule."
"""


_REVISE_SYSTEM = _WRITER_SYSTEM + """

You are now REVISING an existing draft rather than writing a new one. Return the \
complete article in the same JSON shape, with only the prose changed. Every \
"[N]" citation marker must survive exactly as it is and stay attached to the same \
claim; the section headings, the reference list and every number must be \
unchanged. Do not add claims, sources or figures.
"""

# The same job, returned as a list of replaced blocks instead of a whole article.
#
# Rewriting the entire article to fix three sentences is the most expensive call
# in the pipeline — measured at 26,632 output tokens against the 24,191 it took
# to write the article in the first place, and output is priced at 5x input. The
# blocks the checker did not complain about come back re-generated, which is
# both waste and risk: every untouched paragraph is another chance to drop a
# citation marker.
#
# `check_style` already reports a `where` for every issue, so the model is being
# asked for exactly the blocks that were named.
_REVISE_PATCH_SYSTEM = _WRITER_SYSTEM + """

You are now REVISING an existing draft rather than writing a new one, and you \
return ONLY the blocks you changed — not the whole article.

For each block that needs fixing, emit one edit naming `where` it goes and the \
`replacement` text. Leave every block the brief does not complain about out of \
your reply entirely; anything you omit is kept exactly as it is.

Within the blocks you do return: every "[N]" citation marker must survive exactly \
as it is and stay attached to the same claim, and every number must be unchanged. \
Do not add claims, sources or figures unless the brief explicitly tells you the \
draft is too thin, in which case new material must come from the SOURCES and \
carry its SOURCE number.
"""

# Uniform shape on purpose: `replacement` is always a list of strings, so the
# schema has no optional properties and no per-block variants. A single-string
# block (title, abstract, a featured-study field) uses the first entry.
_REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "description": "One entry per block you changed. Omit blocks you did not change.",
            "items": {
                "type": "object",
                "properties": {
                    "where": {
                        "type": "string",
                        "description": "Which block this replaces: 'title', 'abstract', "
                        "'key_points', 'featured_study/method', 'featured_study/results', "
                        "'featured_study/limitations', or the EXACT heading of a section.",
                    },
                    "replacement": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "The replacement text. For a section: its paragraphs "
                        "in order. For key_points: the bullets. For title, abstract or a "
                        "featured-study field: a single-entry list.",
                    },
                },
                "required": ["where", "replacement"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["edits"],
    "additionalProperties": False,
}

# What `style.check_style` calls a block, mapped to where it lives in the article.
# The checker's `where` values are what the model sees in the brief, so it will
# echo those spellings back rather than the schema's.
_PATCH_ALIASES = {
    "key points": "key_points",
    "key_takeaways": "key_points",
    "key takeaways": "key_points",
    "featured study/method": "featured_study/method",
    "featured study/results": "featured_study/results",
    "featured study/limitations": "featured_study/limitations",
    "featured study/why": "featured_study/why",
    "standfirst": "abstract",
}


def apply_revisions(article: dict, edits: list[dict]) -> tuple[dict, list[str]]:
    """Merge a list of block replacements into a copy of `article`.

    Returns (revised, applied) — `applied` names the blocks that actually landed,
    so a reply full of edits that matched nothing is distinguishable from a
    genuine no-op. Unknown targets are skipped rather than guessed at: a heading
    the model invented is a sign it rewrote the structure, and silently appending
    it would let a revision add sections the style gate never asked for.
    """
    revised = copy.deepcopy(article)
    applied: list[str] = []

    headings = {
        (s.get("heading") or "").strip().lower(): s
        for s in revised.get("sections") or []
    }

    for edit in edits or []:
        where = str(edit.get("where") or "").strip()
        replacement = [t for t in (edit.get("replacement") or []) if str(t).strip()]
        if not where or not replacement:
            continue
        key = _PATCH_ALIASES.get(where.lower(), where.lower())

        if key == "title":
            revised["title"] = replacement[0]
        elif key == "abstract":
            revised["abstract"] = " ".join(replacement)
        elif key == "key_points":
            revised["key_points"] = replacement
        elif key.startswith("featured_study/"):
            field = key.split("/", 1)[1]
            if field in ("method", "results", "limitations", "why"):
                revised.setdefault("featured_study", {})[field] = replacement[0]
            else:
                continue
        elif key in headings:
            headings[key]["paragraphs"] = replacement
        else:
            continue
        applied.append(where)

    return revised, applied

# When open-access full texts ride along in the payload, the abstracts-only
# framing above becomes false — and a prompt that lies about its own inputs
# teaches the model to ignore it. The full-text variants are derived by
# substitution so the two framings cannot drift apart; a test pins that every
# substitution still finds its target.
_FULLTEXT_SUBSTITUTIONS = (
    ("You are working from ABSTRACTS ONLY — never the full papers. This constrains you:",
     "You are working from the abstract of every source, plus the open-access FULL "
     "TEXT included below for some of them (the rest say so and stay abstract-only). "
     "This constrains you:"),
    ("if that exact figure appears in the abstract you are citing",
     "if that exact figure appears in the abstract or included full text of the "
     "source you are citing"),
    ("If the abstract doesn't give the number,",
     "If the material you were given doesn't contain the number,"),
    ("FROM ITS ABSTRACT ONLY",
     "from its abstract and included full text ONLY"),
)


def _with_fulltext_framing(system: str) -> str:
    for old, new in _FULLTEXT_SUBSTITUTIONS:
        system = system.replace(old, new)
    return system


_WRITER_SYSTEM_FULLTEXT = _with_fulltext_framing(_WRITER_SYSTEM)
_REVISE_SYSTEM_FULLTEXT = _with_fulltext_framing(_REVISE_SYSTEM)
_REVISE_PATCH_SYSTEM_FULLTEXT = _with_fulltext_framing(_REVISE_PATCH_SYSTEM)


def plan_queries(
    topic: str, model: str | None = None, api_key: str | None = None
) -> tuple[list[str], str]:
    """Turn the topic into scholarly queries and identify its core on-topic entity."""
    result = generate_json(
        (
            "I want journal articles to support an evidence review about: "
            f"{topic!r}\n\n"
            "Give 2-4 short keyword queries for scholarly search engines (Semantic "
            "Scholar / OpenAlex). Use researcher terminology. IMPORTANT: make at least "
            "one query specific enough to find work on the exact subject (include the "
            "most specific entity/population by name), not just the general area. Also "
            "return `core_entity`: the specific subject a source must be about to count "
            "as directly on-topic."
        ),
        _QUERY_SCHEMA,
        model=model,
        api_key=api_key,
    )
    return result["queries"][:4], result.get("core_entity", "").strip()


def _truncate_abstract(abstract: str, limit: int | None) -> str:
    """Cut an abstract to `limit` characters at a word boundary, or leave it.

    Only `curate_sources` may pass a limit, and only when explicitly asked
    (#117). Relevance labelling plausibly turns on the topic and the population,
    which live in the first few hundred characters — but that is a hypothesis
    about the gate that stops topic drift, and it has to be measured before it
    is believed. `tools/compare_curation.py` is the measurement.
    """
    if not limit or len(abstract) <= limit:
        return abstract
    cut = abstract[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip() + " […]"


def _format_sources(
    papers: list[Paper],
    relevance: dict[int, str] | None = None,
    excerpts: dict[int, str] | None = None,
    omit: set[int] | None = None,
    abstract_chars: int | None = None,
) -> str:
    """Render the sources for the prompt.

    `excerpts` (from `sources.full_text_excerpts`) appends each paper's
    open-access full text below its abstract.

    `omit` drops sources by index while leaving every other source's number
    alone, so SOURCE 7 is the seventh paper whether or not SOURCE 6 was
    dropped. The numbering is the citation scheme — `render` maps the writer's
    markers back through it — so it must never be re-packed to close a gap.

    There is no character budget any more. Until Groq was removed this function
    also trimmed abstracts — shortest-cap-first, then dropping the lowest-ranked
    papers — to fit a 12,000 tokens/minute ceiling that counted the reserved
    output as well as the prompt. `sources.full_text_excerpts` already bounds
    the payload (12,000 chars per paper inside a 60,000 total), and no remaining
    provider meters per minute, so the trimming was cost without benefit.
    """

    def render(paper: Paper, index: int, abstract: str) -> str:
        tag = f" [{relevance[index]} to topic]" if relevance and index in relevance else ""
        block = (
            f"SOURCE {index}{tag}\n"
            f"Title: {paper.title}\n"
            f"Authors: {paper.author_line} ({paper.year or 'n.d.'})\n"
            f"Venue: {paper.venue or 'unknown'} | Citations: {paper.citation_count}\n"
            f"Abstract: {abstract}"
        )
        if excerpts and index in excerpts:
            block += (
                "\nFull text (open access; may be truncated):\n" + excerpts[index]
            )
        elif excerpts:
            block += "\n(Abstract only — no open-access full text was available.)"
        return block

    return "\n\n".join(
        render(p, i, _truncate_abstract(p.abstract, abstract_chars))
        for i, p in enumerate(papers, start=1)
        if not (omit and i in omit)
    )


# Truncating the abstracts sent to curation would cut this call from ~39,000
# input tokens to roughly 15,000 for 20 papers. It is **off by default and must
# stay that way until measured** (#117): curation is the relevance gate, and two
# things downstream key off its labels — `style._required_sections` scales the
# section floor with the `direct` count, and `write_article` omits `tangential`
# sources from the prompt entirely.
#
# The failure mode is not theoretical. Running curation at a cheaper reasoning
# tier agreed with the full tier on only 14 of 20 labels, and every disagreement
# ran one way: collapsing toward "related". Truncation is a different change
# that can fail the same way, and the same measurement catches it.
#
# `tools/compare_curation.py` runs the comparison and applies the acceptance
# rule: `direct` and `tangential` must both be stable. Agreement on `related`
# alone is not enough — that is exactly where a degraded run parks everything.
CURATION_ABSTRACT_CHARS = None


def curate_sources(
    topic: str, papers: list[Paper], model: str | None = None, api_key: str | None = None,
    abstract_chars: int | None = None,
) -> dict:
    """Score each paper's relevance to the exact topic. Returns:
    {relevance: {index: label}, most_relevant_index: int,
     counts: {direct, related, tangential}}. Degrades to empty on failure.

    `abstract_chars` truncates each abstract in the prompt. Only the comparison
    harness passes it; the pipeline uses `CURATION_ABSTRACT_CHARS`, which is
    `None` until the measurement says otherwise.
    """
    if not papers:
        return {"relevance": {}, "most_relevant_index": None, "counts": {}}
    limit = abstract_chars if abstract_chars is not None else CURATION_ABSTRACT_CHARS
    try:
        result = generate_json(
            f"Topic: {topic}\n\nRate each source's relevance to that exact topic.\n\n"
            + _format_sources(papers, abstract_chars=limit),
            _CURATE_SCHEMA,
            system=_CURATE_SYSTEM,
            model=model,
            api_key=api_key,
        )
    except Exception:
        return {"relevance": {}, "most_relevant_index": None, "counts": {}}

    relevance: dict[int, str] = {}
    for a in result.get("assessments", []):
        idx = a.get("index")
        label = a.get("relevance")
        if isinstance(idx, int) and 1 <= idx <= len(papers) and label in ("direct", "related", "tangential"):
            relevance[idx] = label
    counts = {
        level: sum(1 for v in relevance.values() if v == level)
        for level in ("direct", "related", "tangential")
    }
    mri = result.get("most_relevant_index")
    if not (isinstance(mri, int) and 1 <= mri <= len(papers)):
        # fall back to a direct source, else the first
        mri = next((i for i, v in relevance.items() if v == "direct"), 1)
    return {"relevance": relevance, "most_relevant_index": mri, "counts": counts}


def write_article(
    topic: str,
    papers: list[Paper],
    model: str | None = None,
    style_note: str = "",
    curation: dict | None = None,
    api_key: str | None = None,
) -> dict:
    """Write the article as structured JSON, grounded in the fetched abstracts."""
    curation = curation or {}
    relevance = curation.get("relevance") or {}
    counts = curation.get("counts") or {}
    mri = curation.get("most_relevant_index")

    context = f"Topic: {topic}\n\n"
    if style_note:
        context += f"Extra guidance from the reader: {style_note}\n\n"
    if counts:
        context += (
            f"Source relevance tally: {counts.get('direct', 0)} directly on-topic, "
            f"{counts.get('related', 0)} related, {counts.get('tangential', 0)} tangential. "
        )
        if not counts.get("direct"):
            context += (
                "NOTE: no sources directly study this exact topic — you MUST say so and "
                "clearly label any evidence borrowed from adjacent populations. "
            )
        context += "\n\n"
    if mri:
        context += f"Suggested study to feature (most relevant): SOURCE {mri}.\n\n"
    excerpts = full_text_excerpts(papers)
    use_full_text = bool(excerpts)

    # Tangential sources are background by definition — the curation prompt
    # defines the label as "only good for background or framing sentences" —
    # and the pipeline already refuses to spend a full-text fetch on one. They
    # still arrived here with a full abstract each, several thousand tokens of
    # material the relevance gate exists to keep out of the article.
    #
    # They are dropped by number rather than filtered out of the list: the
    # SOURCE index IS the citation scheme, so the remaining sources keep the
    # numbers `render` and `verify` will look them up by.
    omit = {i for i, label in relevance.items() if label == "tangential"}
    context += (
        "Here are the candidate sources with their relevance labels. Choose the ones "
        "that genuinely support the article and write it.\n\n"
    )
    if omit:
        # The prompt must not misdescribe its own inputs. The tally above counts
        # the tangential sources, so without this the model is told about
        # material it cannot see and may cite a SOURCE number that is not there.
        context += (
            f"{len(omit)} tangential source(s) are counted in the tally above but are "
            "NOT reproduced below, because they are background only. The numbering "
            "below is unchanged and has gaps where they were. Cite only sources you "
            "can actually see.\n\n"
        )
    context += _format_sources(papers, relevance, excerpts, omit=omit)
    return generate_json(
        context,
        _ARTICLE_SCHEMA,
        system=_WRITER_SYSTEM_FULLTEXT if use_full_text else _WRITER_SYSTEM,
        model=model,
        deep=True,
        api_key=api_key,
    )


def revise_prose(
    article: dict,
    brief: str,
    model: str | None = None,
    api_key: str | None = None,
    papers: list[Paper] | None = None,
    curation: dict | None = None,
    rewrite_whole: bool = False,
) -> dict:
    """Re-write a draft's prose against a list of style violations from `style.py`.

    The brief names the specific conventions broken and quotes the offending text,
    so this is a targeted edit rather than a second attempt at the whole article.

    By default the model returns only the blocks it changed and they are merged
    in here — see `_REVISE_PATCH_SYSTEM` for why. `rewrite_whole=True` asks for
    the entire article instead, which `enforce_style` uses when the draft needs
    sections it does not yet have: a patch can only replace a block that exists.

    Either way the return value is a complete article, so callers do not need to
    know which path ran.
    """
    draft_json = json.dumps(article, ensure_ascii=False, indent=1)

    context = f"{brief}\n\n"
    if papers:
        # Without these the model can only reshuffle what it already wrote, so a
        # draft that failed for thinness comes back thin. The sources are the
        # only material it may legitimately add.
        relevance = (curation or {}).get("relevance") or {}
        excerpts = full_text_excerpts(papers)
        use_full_text = bool(excerpts)
        context += (
            "SOURCES — the material this article must be grounded in. Anything you "
            "add must come from here and be cited by its SOURCE number:\n\n"
            + _format_sources(papers, relevance, excerpts)
            + "\n\n"
        )
    else:
        use_full_text = False
    context += "Here is the draft to revise, as JSON:\n\n" + draft_json

    if rewrite_whole:
        return generate_json(
            context,
            _ARTICLE_SCHEMA,
            system=_REVISE_SYSTEM_FULLTEXT if use_full_text else _REVISE_SYSTEM,
            model=model,
            deep=True,
            api_key=api_key,
        )

    result = generate_json(
        context,
        _REVISION_SCHEMA,
        system=_REVISE_PATCH_SYSTEM_FULLTEXT if use_full_text else _REVISE_PATCH_SYSTEM,
        model=model,
        deep=True,
        api_key=api_key,
    )
    revised, applied = apply_revisions(article, result.get("edits") or [])
    if not applied:
        # Nothing landed: either the model returned no edits, or every `where`
        # it named was a block this article does not have. Both mean the draft
        # is unchanged, and returning it as if it were revised would let
        # `enforce_style` log a revision that never happened.
        raise RuntimeError(
            "the revision returned no edit that matched a block in the draft "
            f"({len(result.get('edits') or [])} edit(s) offered)"
        )
    return revised

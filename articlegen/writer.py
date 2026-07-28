"""LLM calls: plan queries, assess source relevance, then write a grounded article.

Works with either provider via articlegen.llm (Claude by default, Gemini when a
GEMINI_API_KEY is the available credential — see llm.resolve_provider).

The pipeline is deliberately honest about evidence:
- `curate_sources` scores each fetched paper for how directly it addresses the
  *specific* topic, independently of how famous or highly cited it is.
- `write_article` receives those labels, is told it only ever sees abstracts,
  must flag when direct evidence is thin, and produces a featured-study box and
  an evidence note. Numeric claims are separately checked against the abstracts
  downstream (see articlegen.verify).
"""

from __future__ import annotations

from .llm import generate_json
from .sources import Paper

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
        "evidence_note": {
            "type": "string",
            "description": "1-2 honest sentences on how much of the cited evidence directly "
            "addresses the exact topic vs. is extrapolated from adjacent populations.",
        },
        "featured_study": {
            "type": "object",
            "properties": {
                "source_index": {"type": "integer", "description": "SOURCE number of the featured study"},
                "why": {"type": "string", "description": "One sentence: why this is the key study here."},
                "method": {"type": "string", "description": "1-2 sentences on design/method, from its abstract only."},
                "results": {"type": "string", "description": "1-2 sentences on the main result, from its abstract only."},
            },
            "required": ["source_index", "why", "method", "results"],
            "additionalProperties": False,
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {
                        "type": "string",
                        "description": "A short noun-phrase heading in sentence case. The "
                        "FIRST section must be headed 'Introduction' and the LAST "
                        "'Conclusions' (or 'Conclusions and outlook').",
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
            "description": "4-6 declarative bullets carrying the article's argument, each "
            "citing the source(s) it rests on. A reader must be able to take the whole "
            "claim from these alone.",
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
        "title", "abstract", "keywords", "evidence_note", "featured_study",
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
in the prose and in `evidence_note`, and explicitly label anything carried over from \
another population or condition as extrapolation ("no studies in X were identified; \
the following is extrapolated from Y"). Never imply an evidence base that the direct \
sources don't support.
- Lead with the strongest DIRECT evidence. Use related/tangential sources only for \
mechanism or context, and don't let them masquerade as direct findings.
- featured_study: summarize the single most relevant study's method and results \
FROM ITS ABSTRACT ONLY. Prefer the most-relevant source you were given. It is \
printed as a boxed display item, so it must stand alone.

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

REGISTER:
- Third person and impersonal. No "you", no "we" except in "here we review"-type \
framing, no direct address to the reader.
- Hedge claims to the strength of the evidence: "these data suggest", "is \
consistent with", "remains unresolved", "has been reported in a single cohort". \
Reserve flat assertions for findings the abstracts state outright.
- Attribute findings to their study design where the abstract gives it \
("a randomized trial", "a retrospective cohort", "an animal model").
- No exclamation marks, no jokes, no scare quotes, no emoji, no second-person \
imperatives, no "game-changer"/"revolutionary"/"stunning" hype vocabulary.
"""


def plan_queries(topic: str, model: str | None = None) -> tuple[list[str], str]:
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
    )
    return result["queries"][:4], result.get("core_entity", "").strip()


def _format_sources(papers: list[Paper], relevance: dict[int, str] | None = None) -> str:
    blocks = []
    for i, p in enumerate(papers, start=1):
        tag = f" [{relevance[i]} to topic]" if relevance and i in relevance else ""
        blocks.append(
            f"SOURCE {i}{tag}\n"
            f"Title: {p.title}\n"
            f"Authors: {p.author_line} ({p.year or 'n.d.'})\n"
            f"Venue: {p.venue or 'unknown'} | Citations: {p.citation_count}\n"
            f"Abstract: {p.abstract}"
        )
    return "\n\n".join(blocks)


def curate_sources(topic: str, papers: list[Paper], model: str | None = None) -> dict:
    """Score each paper's relevance to the exact topic. Returns:
    {relevance: {index: label}, most_relevant_index: int,
     counts: {direct, related, tangential}}. Degrades to empty on failure."""
    if not papers:
        return {"relevance": {}, "most_relevant_index": None, "counts": {}}
    try:
        result = generate_json(
            f"Topic: {topic}\n\nRate each source's relevance to that exact topic.\n\n"
            + _format_sources(papers),
            _CURATE_SCHEMA,
            system=_CURATE_SYSTEM,
            model=model,
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
    context += (
        "Here are the candidate sources with their relevance labels. Choose the ones "
        "that genuinely support the article and write it.\n\n"
        + _format_sources(papers, relevance)
    )
    return generate_json(
        context,
        _ARTICLE_SCHEMA,
        system=_WRITER_SYSTEM,
        model=model,
        deep=True,
    )

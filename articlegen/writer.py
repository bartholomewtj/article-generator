"""LLM calls: plan search queries, then write the article grounded in the evidence.

Works with either provider via articlegen.llm (Claude by default, Gemini when a
GEMINI_API_KEY is the available credential — see llm.resolve_provider).
"""

from __future__ import annotations

from .llm import generate_json
from .sources import Paper

_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 scholarly search queries",
        }
    },
    "required": ["queries"],
    "additionalProperties": False,
}

_ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "standfirst": {
            "type": "string",
            "description": "One to two sentences below the title that hook the reader",
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "paragraphs": {"type": "array", "items": {"type": "string"}},
                    "pull_quote": {
                        "type": ["string", "null"],
                        "description": "A short striking line worth setting large, or null",
                    },
                },
                "required": ["heading", "paragraphs", "pull_quote"],
                "additionalProperties": False,
            },
        },
        "key_takeaways": {"type": "array", "items": {"type": "string"}},
        "references": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "SOURCE indices in citation order; [1] in text = first entry",
        },
    },
    "required": ["title", "standfirst", "sections", "key_takeaways", "references"],
    "additionalProperties": False,
}

_WRITER_SYSTEM = """\
You are a science writer for a smart general audience — think of the house style of \
Nautilus or The Atlantic's science desk. You turn a topic plus a stack of journal \
abstracts into a single-page article that is rigorous but genuinely enjoyable to read.

Rules:
- Ground every factual claim in the provided sources. Each source is labeled \
"SOURCE N". Cite by that exact number in brackets at the end of the sentence it \
supports — a claim from SOURCE 6 is cited [6]; combine as [6, 18]. Never invent a \
source or cite a number that has no matching SOURCE.
- In the `references` field, list every SOURCE number you actually cited, in the \
order they first appear in your text. (The display renumbers them to 1, 2, 3…, so \
you don't need to renumber anything yourself.)
- Prefer concrete findings — effect sizes, sample sizes, years, populations — over \
vague "studies show" phrasing, but only when the abstract actually states them.
- Be honest about uncertainty and disagreement between studies; that tension often \
makes the story more interesting, not less.
- Open with a hook: a scene, a question, or a surprising finding. No throat-clearing.
- Aim for roughly 900-1400 words across 4-6 sections with short, punchy headings.
- Write plain prose paragraphs only: no markdown, no HTML tags, no bullet lists \
inside paragraphs (key_takeaways is the place for bullets).
- Use at most one pull_quote per section, and only when a line truly earns it.
"""


def plan_queries(topic: str, model: str | None = None) -> list[str]:
    """Turn the user's topic into effective scholarly search queries."""
    result = generate_json(
        (
            "I want to find journal articles to support a popular-science "
            f"article about: {topic!r}\n\n"
            "Give me 2-4 short keyword queries for scholarly search engines "
            "(Semantic Scholar / OpenAlex). Cover distinct angles of the topic; "
            "use terminology researchers would use, not casual phrasing."
        ),
        _QUERY_SCHEMA,
        model=model,
    )
    return result["queries"][:4]


def _format_sources(papers: list[Paper]) -> str:
    blocks = []
    for i, p in enumerate(papers, start=1):
        blocks.append(
            f"SOURCE {i}\n"
            f"Title: {p.title}\n"
            f"Authors: {p.author_line} ({p.year or 'n.d.'})\n"
            f"Venue: {p.venue or 'unknown'} | Citations: {p.citation_count}\n"
            f"Abstract: {p.abstract}"
        )
    return "\n\n".join(blocks)


def write_article(
    topic: str,
    papers: list[Paper],
    model: str | None = None,
    style_note: str = "",
) -> dict:
    """Write the article as structured JSON, grounded in the fetched abstracts."""
    user_prompt = (
        f"Topic: {topic}\n\n"
        + (f"Extra guidance from the reader: {style_note}\n\n" if style_note else "")
        + "Here are the candidate sources. Choose the ones that genuinely support a "
        "good article (skip irrelevant or weak ones) and write the article.\n\n"
        + _format_sources(papers)
    )
    return generate_json(
        user_prompt,
        _ARTICLE_SCHEMA,
        system=_WRITER_SYSTEM,
        model=model,
        deep=True,
    )

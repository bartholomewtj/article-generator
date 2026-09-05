"""Stage 1: turn a broad theme into briefing questions to pick from."""

from __future__ import annotations

from .llm import generate_json
from .writer import PICO_FIELDS, PICO_LABELS

_IDEAS_SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "A specific evidence-briefing question as a "
                        "descriptive title: population, intervention or exposure, "
                        "and outcome. Sentence case. No puns, no colon-clickbait, "
                        "no result claimed.",
                    },
                    "angle": {
                        "type": "string",
                        "description": "One sentence on the review question and why "
                        "the published literature could answer it — including "
                        "'the evidence is thin' if that is likely.",
                    },
                    "search_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-3 scholarly search terms this question would draw on",
                    },
                    "population": {
                        "type": "string",
                        "description": "Who the question is about — the population or setting. "
                                       "Empty string if the question does not specify one.",
                    },
                    "intervention": {
                        "type": "string",
                        "description": "The intervention or exposure being asked about. Empty "
                                       "string if the question does not specify one.",
                    },
                    "comparator": {
                        "type": "string",
                        "description": "What it is compared against (usual care, placebo, another "
                                       "intervention). Empty string when there is no comparison.",
                    },
                    "outcome": {
                        "type": "string",
                        "description": "The outcome the question turns on. Empty string if the "
                                       "question does not specify one.",
                    },
                },
                "required": [
                    "title", "angle", "search_terms",
                    "population", "intervention", "comparator", "outcome",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ideas"],
    "additionalProperties": False,
}

_IDEAS_SYSTEM = """\
You propose specific evidence-briefing questions. Each one should be something \
a clinician or researcher could send as a sourced one-pager after the literature \
has been searched.

Each idea must be:
- A concrete review question (population, intervention or exposure, outcome or \
comparison) — not a theme, not a magazine hook, not "why X is more interesting \
than you think".
- Distinct from the others — different questions, not variations of one pitch.
- Something the peer-reviewed literature could actually address, including the \
honest case that the evidence is thin.
- Titled descriptively, in sentence case: names the question, does not claim \
the result.
- Broken out: name the population, the intervention or exposure, the comparator \
and the outcome as separate fields where the question has them, and leave a \
field empty rather than inventing one.

Do not write popular-science pitches, tension-for-its-own-sake, or clickbait.
"""


def generate_ideas(
    theme: str, n: int = 6, model: str | None = None, api_key: str | None = None
) -> list[dict]:
    result = generate_json(
        (
            f"Theme: {theme!r}\n\n"
            f"Propose {n} distinct evidence-briefing questions I could search "
            "the published literature for and send as a sourced one-pager. "
            "Make them concrete and varied."
        ),
        _IDEAS_SCHEMA,
        system=_IDEAS_SYSTEM,
        model=model,
        api_key=api_key,
    )
    return result["ideas"][:n]


def ideas_to_markdown(theme: str, ideas: list[dict]) -> str:
    lines = [f"# Briefing questions: {theme}", ""]
    for i, idea in enumerate(ideas, start=1):
        lines.append(f"## {i}. {idea['title']}")
        lines.append("")
        lines.append(idea["angle"])
        lines.append("")
        lines.append(f"*Search terms:* {', '.join(idea['search_terms'])}")
        for field in PICO_FIELDS:
            value = (idea.get(field) or "").strip()
            if value:
                lines.append(f"*{PICO_LABELS[field]}:* {value}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append('Pick one, then run: `articlegen draft "<title>" --open`')
    lines.append("")
    return "\n".join(lines)


def format_ideas_console(ideas: list[dict]) -> str:
    out = []
    for i, idea in enumerate(ideas, start=1):
        out.append(f"  {i}. {idea['title']}")
        out.append(f"     {idea['angle']}")
    return "\n".join(out)

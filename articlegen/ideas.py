"""Stage 1: turn a broad theme into a shortlist of concrete article ideas to pick from."""

from __future__ import annotations

import json

import anthropic

from .writer import DEFAULT_MODEL

_IDEAS_SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "A specific, publishable article title"},
                    "angle": {
                        "type": "string",
                        "description": "One sentence on the specific angle or tension that makes it interesting",
                    },
                    "search_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2-3 scholarly search terms this idea would draw on",
                    },
                },
                "required": ["title", "angle", "search_terms"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ideas"],
    "additionalProperties": False,
}

_IDEAS_SYSTEM = """\
You are an ideas editor for a popular-science publication. Given a broad theme, \
you propose specific, distinct article ideas a writer could actually research and \
write from peer-reviewed literature.

Each idea must be:
- Specific enough to research (not "the future of AI" but a concrete question or finding).
- Distinct from the others — cover different angles, not variations of one pitch.
- Genuinely interesting: a tension, a counter-intuitive result, a "why" question, or \
a live debate — not a bland overview.
- Grounded in something the scholarly literature could actually support.
"""


def generate_ideas(theme: str, n: int = 6, model: str = DEFAULT_MODEL) -> list[dict]:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        output_config={"format": {"type": "json_schema", "schema": _IDEAS_SCHEMA}},
        system=_IDEAS_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Theme: {theme!r}\n\n"
                    f"Propose {n} distinct article ideas I could research and write. "
                    "Make them concrete and varied."
                ),
            }
        ],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["ideas"][:n]


def ideas_to_markdown(theme: str, ideas: list[dict]) -> str:
    lines = [f"# Article ideas: {theme}", ""]
    for i, idea in enumerate(ideas, start=1):
        lines.append(f"## {i}. {idea['title']}")
        lines.append("")
        lines.append(idea["angle"])
        lines.append("")
        lines.append(f"*Search terms:* {', '.join(idea['search_terms'])}")
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

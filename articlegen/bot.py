"""GitHub Actions glue for the mobile workflow.

Two subcommands, invoked from .github/workflows/:

    python -m articlegen.bot ideas   --theme "..." [--guidance "..."] --out comment.md
        Generate the ideas shortlist and write it as an issue-comment body.
        A hidden HTML-comment marker embeds the titles as JSON so a later
        `draft N` comment can be resolved back to a title.

    python -m articlegen.bot resolve --body "draft 3" --comments comments.json
        Parse a `draft ...` comment against the issue's comment history and
        write GitHub Actions outputs: ok, title, style, stem (or error).

Everything GitHub-facing (posting comments, committing, pushing) stays in the
workflow YAML via the `gh` CLI; this module only produces text and outputs.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

MARKER_PREFIX = "<!-- articlegen:ideas "
MARKER_SUFFIX = " -->"

_THEME_PREFIX_RE = re.compile(r"^\s*theme\s*:\s*", re.IGNORECASE)
_MARKER_RE = re.compile(re.escape(MARKER_PREFIX) + r"(.*?)" + re.escape(MARKER_SUFFIX), re.DOTALL)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "article"


def write_output(name: str, value: str) -> None:
    """Write a single-line GitHub Actions step output (falls back to stdout)."""
    value = " ".join(str(value).split())  # force single line
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


# ---------------------------------------------------------------- ideas

def build_ideas_comment(theme: str, ideas: list[dict]) -> str:
    lines = [f"Here are {len(ideas)} article ideas for **{theme}**:", ""]
    for i, idea in enumerate(ideas, start=1):
        lines.append(f"**{i}. {idea['title']}**")
        lines.append(idea["angle"])
        lines.append(f"*Search terms:* {', '.join(idea['search_terms'])}")
        lines.append("")
    lines += [
        "---",
        "Reply **`draft 3`** (any number) to research and draft that idea.",
        'Or `draft "Your own title"` for something else on this theme.',
        "Add a tone/audience note with `style:`, e.g. `draft 2 style: for beginners`.",
        "",
    ]
    marker_payload = json.dumps(
        {"theme": theme, "titles": [idea["title"] for idea in ideas]}
    ).replace("-->", "--\\u003e")
    lines.append(f"{MARKER_PREFIX}{marker_payload}{MARKER_SUFFIX}")
    return "\n".join(lines)


def cmd_ideas(args) -> int:
    from .ideas import generate_ideas  # deferred: needs anthropic + API key

    theme = _THEME_PREFIX_RE.sub("", args.theme).strip()
    if not theme:
        print("Empty theme after stripping the 'theme:' prefix.", file=sys.stderr)
        return 1
    prompt_theme = theme
    guidance = (args.guidance or "").strip()
    if guidance:
        prompt_theme = f"{theme} — extra guidance from the reader: {guidance[:500]}"

    ideas = generate_ideas(prompt_theme, n=args.n)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(build_ideas_comment(theme, ideas))
    print(f"Wrote {len(ideas)} ideas to {args.out}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- resolve

def latest_ideas(comments: list[dict]) -> dict | None:
    """Find the most recent ideas marker across the issue's comments."""
    for comment in reversed(comments):
        match = None
        for match in _MARKER_RE.finditer(comment.get("body") or ""):
            pass  # keep the last marker in this comment
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
    return None


def parse_command(body: str) -> tuple[str | None, str, str | None]:
    """Return (selection, style, error). selection is a number string or a title."""
    lines = (body or "").strip().splitlines()
    first = lines[0].strip() if lines else ""
    rest_lines = " ".join(line.strip() for line in lines[1:] if line.strip())

    match = re.match(r"draft\b[:\s]*(.*)$", first, re.IGNORECASE)
    if not match:
        return None, "", "not a draft command"
    remainder = match.group(1).strip()

    style = ""
    style_split = re.split(r"\bstyle\s*:\s*", remainder, maxsplit=1, flags=re.IGNORECASE)
    if len(style_split) == 2:
        remainder, style = style_split[0].strip(), style_split[1].strip()
    if rest_lines:
        style = f"{style} {rest_lines}".strip()

    if re.fullmatch(r"#?\d+", remainder):
        return remainder.lstrip("#"), style, None
    quoted = re.fullmatch(r'["“](.+)["”]', remainder)
    if quoted:
        return quoted.group(1).strip(), style, None
    if not remainder:
        return None, style, (
            "Tell me which idea: `draft 3` (a number from the list) "
            'or `draft "your own title"`.'
        )
    return None, style, (
        f"I didn't understand `{remainder[:80]}`. "
        'Use `draft 3` (a number from the ideas list) or `draft "your own title"` '
        "(quotes required for custom titles)."
    )


def cmd_resolve(args) -> int:
    with open(args.comments, encoding="utf-8") as f:
        comments = json.load(f)

    selection, style, error = parse_command(args.body)
    title = None
    if error is None and selection is not None:
        if selection.isdigit():
            ideas = latest_ideas(comments)
            if not ideas:
                error = (
                    "I couldn't find an ideas list on this issue to pick from. "
                    'Use `draft "your own title"`, or open a new `theme: ...` issue.'
                )
            else:
                index = int(selection)
                titles = ideas.get("titles", [])
                if 1 <= index <= len(titles):
                    title = titles[index - 1]
                else:
                    error = f"There is no idea #{index} — the list has {len(titles)} ideas."
        else:
            title = selection

    if error or not title:
        write_output("ok", "false")
        write_output("error", error or "Could not resolve the request.")
        return 0  # graceful: the workflow posts the error as a comment

    stem = f"{datetime.date.today().isoformat()}-{_slugify(title)}"
    write_output("ok", "true")
    write_output("title", title)
    write_output("style", style)
    write_output("stem", stem)
    return 0


# ---------------------------------------------------------------- entry

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="articlegen.bot")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ideas = sub.add_parser("ideas")
    p_ideas.add_argument("--theme", required=True)
    p_ideas.add_argument("--guidance", default="")
    p_ideas.add_argument("-n", type=int, default=6)
    p_ideas.add_argument("--out", required=True)
    p_ideas.set_defaults(func=cmd_ideas)

    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("--body", required=True)
    p_resolve.add_argument("--comments", required=True)
    p_resolve.set_defaults(func=cmd_resolve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line interface — a three-stage workflow:

    articlegen ideas  "<theme>"        # 1. generate ideas to pick from
    articlegen draft  "<title>"        # 2. research + draft, into drafts/ for review
    articlegen queue                   # (re)build / open the drafts review index

Stages 1 and 2 are the two human gates: you choose an idea, then you review the draft.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import webbrowser

from . import demo
from .ideas import format_ideas_console, generate_ideas, ideas_to_markdown
from .llm import resolve_provider
from .render import build_index, render_article, render_markdown
from .sources import gather_evidence
from .writer import plan_queries, write_article

IDEAS_DIR = "ideas"
DRAFTS_DIR = "drafts"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "article"


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _open_in_browser(path: str) -> None:
    try:
        webbrowser.open(f"file://{os.path.abspath(path)}")
    except Exception:
        pass  # headless / no browser — the path is already logged


def _api_error(exc: Exception) -> int:
    provider, model = resolve_provider()
    _log(f"The {provider} API call failed (model {model}): {exc}")
    _log(
        "Set ANTHROPIC_API_KEY for Claude, or GEMINI_API_KEY for Gemini "
        "(free key at https://aistudio.google.com/), and try again."
    )
    return 1


def cmd_ideas(args) -> int:
    _log(f"Generating ideas for: {args.theme}")
    try:
        ideas = generate_ideas(args.theme, n=args.n, model=args.model)
    except Exception as exc:
        return _api_error(exc)

    os.makedirs(IDEAS_DIR, exist_ok=True)
    out_path = args.output or os.path.join(IDEAS_DIR, f"{_slugify(args.theme)}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ideas_to_markdown(args.theme, ideas))

    print(format_ideas_console(ideas))
    _log("")
    _log(f"Saved {len(ideas)} ideas to {out_path}")
    _log('Pick one, then run:  articlegen draft "<title>" --open')
    return 0


def cmd_draft(args) -> int:
    _log(f"Planning search queries for: {args.topic}")
    try:
        queries = plan_queries(args.topic, model=args.model)
    except Exception as exc:
        return _api_error(exc)
    _log("Queries: " + "; ".join(queries))

    _log("Fetching journal articles...")
    papers = gather_evidence(queries, max_papers=args.max_papers, log=_log)
    if not papers:
        _log(
            "No papers with abstracts found. The scholarly APIs may be rate-limiting "
            "— wait a minute and retry, or set SEMANTIC_SCHOLAR_API_KEY / OPENALEX_MAILTO."
        )
        return 1
    _log(f"Collected {len(papers)} candidate papers.")

    _log("Writing the article (this can take a few minutes)...")
    try:
        article = write_article(args.topic, papers, model=args.model, style_note=args.style)
    except Exception as exc:
        return _api_error(exc)

    os.makedirs(DRAFTS_DIR, exist_ok=True)
    date = datetime.date.today().isoformat()
    stem = args.name or f"{date}-{_slugify(args.topic)}"
    html_path = os.path.join(DRAFTS_DIR, f"{stem}.html")
    md_path = os.path.join(DRAFTS_DIR, f"{stem}.md")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_article(article, papers, args.topic))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(article, papers, args.topic))

    index_path = build_index(DRAFTS_DIR)
    _log(f"Draft ready ({len(article['references'])} sources cited):")
    _log(f"  HTML:     {html_path}")
    _log(f"  Markdown: {md_path}")
    _log(f"  Queue:    {index_path}")

    if args.open:
        _open_in_browser(html_path)
    return 0


def cmd_queue(args) -> int:
    if not os.path.isdir(DRAFTS_DIR):
        _log(f"No {DRAFTS_DIR}/ folder yet — run `articlegen draft \"<title>\"` first.")
        return 1
    index_path = build_index(DRAFTS_DIR)
    _log(f"Review queue: {index_path}")
    if args.open:
        _open_in_browser(index_path)
    return 0


def cmd_demo(args) -> int:
    output_path = args.output or "demo.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(render_article(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, "Sample topic"))
    _log(f"Demo article written to {output_path}")
    if args.open:
        _open_in_browser(output_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="articlegen",
        description=(
            "A three-stage workflow: generate ideas, auto-collate research, and prepare "
            "a draft article for your review — as a self-contained single-page HTML file "
            "(plus Markdown), grounded in journal-article abstracts."
        ),
    )
    parser.add_argument(
        "--model", default=None,
        help=(
            "Model to use; the name picks the provider (claude-* / gemini-*). "
            "Default: auto — claude-opus-4-8 with an Anthropic key, "
            "gemini-2.5-flash with a Gemini key."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ideas = sub.add_parser("ideas", help="Stage 1: turn a theme into article ideas to pick from")
    p_ideas.add_argument("theme", help="Broad theme or interest area")
    p_ideas.add_argument("-n", type=int, default=6, help="How many ideas to generate (default: 6)")
    p_ideas.add_argument("-o", "--output", help="Output .md path (default: ideas/<theme>.md)")
    p_ideas.set_defaults(func=cmd_ideas)

    p_draft = sub.add_parser("draft", help="Stage 2: research + draft an article for review")
    p_draft.add_argument("topic", help="The article title/idea to write")
    p_draft.add_argument("--name", help="Draft filename stem (default: <date>-<slug>)")
    p_draft.add_argument("--style", default="", help='Audience/tone note, e.g. "for high-school students"')
    p_draft.add_argument("--max-papers", type=int, default=20, help="Max candidate papers (default: 20)")
    p_draft.add_argument("--open", action="store_true", help="Open the draft in your browser when done")
    p_draft.set_defaults(func=cmd_draft)

    p_queue = sub.add_parser("queue", help="(Re)build and optionally open the drafts review index")
    p_queue.add_argument("--open", action="store_true", help="Open the queue in your browser")
    p_queue.set_defaults(func=cmd_queue)

    p_demo = sub.add_parser("demo", help="Render a built-in sample (no API calls) to preview the design")
    p_demo.add_argument("-o", "--output", help="Output HTML path (default: demo.html)")
    p_demo.add_argument("--open", action="store_true", help="Open the sample in your browser")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

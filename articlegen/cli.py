"""Command-line interface: topic in, single-page HTML article out."""

from __future__ import annotations

import argparse
import re
import sys

from . import demo
from .render import render_article
from .sources import gather_evidence
from .writer import DEFAULT_MODEL, plan_queries, write_article


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "article"


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="articlegen",
        description=(
            "Generate a readable, visually polished single-page HTML article on any "
            "topic, grounded in journal-article abstracts from Semantic Scholar and "
            "OpenAlex."
        ),
    )
    parser.add_argument("topic", help="The topic or idea to write about")
    parser.add_argument("-o", "--output", help="Output HTML path (default: <topic-slug>.html)")
    parser.add_argument(
        "--max-papers", type=int, default=20,
        help="Max candidate papers to feed the writer (default: 20)",
    )
    parser.add_argument(
        "--style", default="",
        help='Optional style/audience note, e.g. "for high-school students"',
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default: {DEFAULT_MODEL})")
    parser.add_argument(
        "--demo", action="store_true",
        help="Render a built-in sample article (no API calls) to preview the design",
    )
    args = parser.parse_args(argv)

    output_path = args.output or f"{_slugify(args.topic)}.html"

    if args.demo:
        html_page = render_article(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, args.topic)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_page)
        _log(f"Demo article written to {output_path}")
        return 0

    _log(f"Planning search queries for: {args.topic}")
    try:
        queries = plan_queries(args.topic, model=args.model)
    except Exception as exc:  # auth/config problems surface here first
        _log(f"Could not reach the Claude API: {exc}")
        _log("Set ANTHROPIC_API_KEY (or run `ant auth login`) and try again.")
        return 1
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
    article = write_article(args.topic, papers, model=args.model, style_note=args.style)

    html_page = render_article(article, papers, args.topic)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_page)
    _log(f"Done. Article written to {output_path} ({len(article['references'])} sources cited).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

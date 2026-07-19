"""Render the structured article + its cited sources into a self-contained HTML page."""

from __future__ import annotations

import datetime
import html
import re

from .sources import Paper

_CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def _link_citations(escaped_text: str, valid_numbers: set[int]) -> str:
    """Turn [1] / [2, 3] markers into superscript links to the references list."""

    def replace(match: re.Match) -> str:
        numbers = [n.strip() for n in match.group(1).split(",")]
        if not all(n.isdigit() and int(n) in valid_numbers for n in numbers):
            return match.group(0)
        links = ", ".join(f'<a href="#ref-{n}">{n}</a>' for n in numbers)
        return f'<sup class="cite">[{links}]</sup>'

    return _CITATION_RE.sub(replace, escaped_text)


def render_article(article: dict, papers: list[Paper], topic: str) -> str:
    # `references` holds 1-based SOURCE indices in citation order.
    cited: list[Paper] = []
    for source_index in article.get("references", []):
        if 1 <= source_index <= len(papers):
            cited.append(papers[source_index - 1])
    valid_numbers = set(range(1, len(cited) + 1))

    sections_html = []
    for i, section in enumerate(article["sections"]):
        paragraphs = []
        for j, para in enumerate(section["paragraphs"]):
            text = _link_citations(html.escape(para), valid_numbers)
            css = ' class="opener"' if i == 0 and j == 0 else ""
            paragraphs.append(f"<p{css}>{text}</p>")
        pull_quote = section.get("pull_quote")
        quote_html = (
            f'<blockquote class="pull">{html.escape(pull_quote)}</blockquote>'
            if pull_quote
            else ""
        )
        sections_html.append(
            f"<section>\n<h2>{html.escape(section['heading'])}</h2>\n"
            + quote_html
            + "\n".join(paragraphs)
            + "\n</section>"
        )

    takeaways_html = "\n".join(
        f"<li>{_link_citations(html.escape(t), valid_numbers)}</li>"
        for t in article.get("key_takeaways", [])
    )

    refs_html = []
    for n, paper in enumerate(cited, start=1):
        link = paper.link
        title = html.escape(paper.title)
        title_html = f'<a href="{html.escape(link, quote=True)}">{title}</a>' if link else title
        meta_bits = [b for b in (paper.venue, f"cited {paper.citation_count}× " if paper.citation_count else "") if b]
        meta = html.escape(" · ".join(m.strip() for m in meta_bits))
        refs_html.append(
            f'<li id="ref-{n}"><span class="ref-authors">{html.escape(paper.author_line)}'
            f" ({paper.year or 'n.d.'})</span> {title_html}"
            + (f' <span class="ref-meta">{meta}</span>' if meta else "")
            + "</li>"
        )

    today = datetime.date.today().strftime("%B %-d, %Y")
    return _TEMPLATE.format(
        page_title=html.escape(article["title"]),
        kicker=html.escape(topic),
        title=html.escape(article["title"]),
        standfirst=html.escape(article["standfirst"]),
        date=today,
        n_sources=len(cited),
        sections="\n\n".join(sections_html),
        takeaways=takeaways_html,
        references="\n".join(refs_html),
    )


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<style>
  :root {{
    --bg: #ffffff;
    --ink: #1d1f21;
    --muted: #6b6f76;
    --accent: #0b6e6a;
    --accent-soft: #0b6e6a22;
    --rule: #e4e2dd;
    --card: #f6f5f2;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #16181b;
      --ink: #e8e6e1;
      --muted: #9aa0a6;
      --accent: #5cc8c0;
      --accent-soft: #5cc8c026;
      --rule: #2c2f33;
      --card: #1e2125;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: Georgia, "Iowan Old Style", "Times New Roman", serif;
    font-size: 1.125rem;
    line-height: 1.65;
  }}
  main {{ max-width: 42rem; margin: 0 auto; padding: 3rem 1.25rem 5rem; }}
  header.masthead {{ margin-bottom: 3rem; }}
  .kicker {{
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--accent);
    margin: 0 0 1rem;
  }}
  h1 {{
    font-size: clamp(2rem, 5.5vw, 2.9rem);
    line-height: 1.12;
    margin: 0 0 1rem;
    letter-spacing: -0.01em;
  }}
  .standfirst {{
    font-size: 1.3rem;
    line-height: 1.45;
    color: var(--muted);
    margin: 0 0 1.5rem;
  }}
  .byline {{
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.85rem;
    color: var(--muted);
    border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule);
    padding: 0.6rem 0;
  }}
  h2 {{
    font-size: 1.45rem;
    line-height: 1.25;
    margin: 2.6rem 0 0.9rem;
  }}
  p {{ margin: 0 0 1.15rem; }}
  p.opener::first-letter {{
    float: left;
    font-size: 3.4em;
    line-height: 0.85;
    padding: 0.06em 0.08em 0 0;
    color: var(--accent);
  }}
  sup.cite {{
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.68em;
    letter-spacing: 0.02em;
  }}
  sup.cite a {{ color: var(--accent); text-decoration: none; }}
  sup.cite a:hover {{ text-decoration: underline; }}
  blockquote.pull {{
    margin: 2rem 0;
    padding: 0.2rem 0 0.2rem 1.2rem;
    border-left: 3px solid var(--accent);
    font-size: 1.45rem;
    line-height: 1.35;
    font-style: italic;
    color: var(--ink);
  }}
  aside.takeaways {{
    margin: 3rem 0;
    padding: 1.4rem 1.6rem;
    background: var(--card);
    border-radius: 10px;
  }}
  aside.takeaways h2 {{
    margin: 0 0 0.8rem;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--accent);
  }}
  aside.takeaways ul {{ margin: 0; padding-left: 1.2rem; }}
  aside.takeaways li {{ margin-bottom: 0.55rem; }}
  section.references {{ margin-top: 3.5rem; border-top: 1px solid var(--rule); padding-top: 1.5rem; }}
  section.references h2 {{
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--accent);
    margin: 0 0 1rem;
  }}
  section.references ol {{
    margin: 0;
    padding-left: 1.4rem;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.88rem;
    line-height: 1.5;
    color: var(--muted);
  }}
  section.references li {{ margin-bottom: 0.7rem; }}
  section.references li:target {{ background: var(--accent-soft); border-radius: 4px; }}
  section.references a {{ color: var(--accent); text-decoration: none; }}
  section.references a:hover {{ text-decoration: underline; }}
  .ref-authors {{ color: var(--ink); }}
  .ref-meta {{ display: block; font-size: 0.82rem; }}
  footer.colophon {{
    margin-top: 3rem;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.78rem;
    color: var(--muted);
  }}
  @media print {{
    body {{ font-size: 11pt; }}
    .kicker, sup.cite a, section.references a {{ color: black; }}
  }}
</style>
</head>
<body>
<main>
  <header class="masthead">
    <p class="kicker">{kicker}</p>
    <h1>{title}</h1>
    <p class="standfirst">{standfirst}</p>
    <p class="byline">Generated {date} · Grounded in {n_sources} peer-reviewed sources</p>
  </header>

  {sections}

  <aside class="takeaways">
    <h2>Key takeaways</h2>
    <ul>
      {takeaways}
    </ul>
  </aside>

  <section class="references">
    <h2>Sources</h2>
    <ol>
      {references}
    </ol>
  </section>

  <footer class="colophon">
    Written with AI assistance from the abstracts of the journal articles listed above.
    Follow the source links before relying on any specific claim.
  </footer>
</main>
</body>
</html>
"""

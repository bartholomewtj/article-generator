"""Render the structured article + its cited sources into a self-contained HTML page.

Also builds the Markdown export and the drafts/ review-queue index page.
"""

from __future__ import annotations

import datetime
import glob
import html
import os
import re

from .sources import Paper

_CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)


def _citation_map(article: dict, papers: list[Paper]) -> tuple[list[Paper], dict[int, int]]:
    """Resolve `references` (raw SOURCE indices, in first-citation order) into the
    ordered list of cited papers plus a map {raw SOURCE index -> display number 1..N}.

    The writer cites papers by their fed "SOURCE N" label; we renumber those to a
    clean 1..N sequence so the inline markers match the Sources list exactly.
    """
    ordered: list[int] = []
    for raw in article.get("references", []):
        if isinstance(raw, int) and 1 <= raw <= len(papers) and raw not in ordered:
            ordered.append(raw)
    cited = [papers[raw - 1] for raw in ordered]
    mapping = {raw: position for position, raw in enumerate(ordered, start=1)}
    return cited, mapping


def _remap_citations(text: str, mapping: dict[int, int]) -> str:
    """Rewrite raw SOURCE-index markers to display numbers; drop any with no source."""

    def replace(match: re.Match) -> str:
        mapped = [str(mapping[int(n)]) for n in match.group(1).split(",")
                  if int(n.strip()) in mapping]
        return f"[{', '.join(mapped)}]" if mapped else ""

    return _CITATION_RE.sub(replace, text)


def _cited_papers(article: dict, papers: list[Paper]) -> list[Paper]:
    return _citation_map(article, papers)[0]


def _link_citations(escaped_text: str, valid_numbers: set[int]) -> str:
    """Turn [1] / [2, 3] markers into superscript links to the references list."""

    def replace(match: re.Match) -> str:
        numbers = [n.strip() for n in match.group(1).split(",")]
        if not all(n.isdigit() and int(n) in valid_numbers for n in numbers):
            return match.group(0)
        links = ", ".join(f'<a href="#ref-{n}">{n}</a>' for n in numbers)
        return f'<sup class="cite">[{links}]</sup>'

    return _CITATION_RE.sub(replace, escaped_text)


_CLINICAL_HINTS = (
    "clinician", "patient", "clinical", "therapy", "treatment", "diagnos",
    "schizophreni", "depress", "disorder", "disease", "dose", "drug",
    "symptom", "psychiat", "medic", "health",
)


def _is_clinical(topic: str, article: dict) -> bool:
    blob = (topic + " " + article.get("title", "") + " " + article.get("standfirst", "")).lower()
    return any(h in blob for h in _CLINICAL_HINTS)


def _year_range(papers: list[Paper]) -> str:
    years = [p.year for p in papers if p.year]
    if not years:
        return ""
    lo, hi = min(years), max(years)
    return str(lo) if lo == hi else f"{lo}–{hi}"


def _paper_link_html(paper: Paper) -> str:
    title = html.escape(paper.title)
    if paper.link:
        return f'<a href="{html.escape(paper.link, quote=True)}">{title}</a>'
    return title


def _featured_html(article: dict, papers: list[Paper], cite_map: dict[int, int]) -> str:
    fs = article.get("featured_study") or {}
    idx = fs.get("source_index")
    if not (isinstance(idx, int) and 1 <= idx <= len(papers)):
        return ""
    paper = papers[idx - 1]
    display = cite_map.get(idx)
    ref = f' <a class="fs-ref" href="#ref-{display}">[{display}]</a>' if display else ""
    rows = []
    if fs.get("why"):
        rows.append(f'<p class="fs-why">{html.escape(fs["why"])}</p>')
    if fs.get("method"):
        rows.append(f"<p><strong>Method.</strong> {html.escape(fs['method'])}</p>")
    if fs.get("results"):
        rows.append(f"<p><strong>Results.</strong> {html.escape(fs['results'])}</p>")
    return (
        '<aside class="featured">\n'
        '<h2>Featured study</h2>\n'
        f'<p class="fs-cite">{_paper_link_html(paper)} · '
        f'{html.escape(paper.author_line)} ({paper.year or "n.d."})'
        f'{(" · " + html.escape(paper.venue)) if paper.venue else ""}{ref}</p>\n'
        + "\n".join(rows)
        + "\n</aside>"
    )


def _cited_relevance_counts(cite_map: dict[int, int], curation: dict | None) -> dict:
    """Tally direct/related/tangential over the CITED sources only (not all fetched)."""
    relevance = (curation or {}).get("relevance") or {}
    if not relevance:
        return {}
    counts = {"direct": 0, "related": 0, "tangential": 0}
    for raw in cite_map:
        label = relevance.get(raw)
        if label in counts:
            counts[label] += 1
    return counts


def _evidence_html(cited, papers, topic, article, curation, verification, cite_map) -> str:
    counts = _cited_relevance_counts(cite_map, curation)
    bits = [f"<strong>{len(cited)}</strong> sources cited"]
    if counts:
        bits.append(
            f'<strong>{counts.get("direct", 0)}</strong> directly on-topic, '
            f'{counts.get("related", 0)} related, {counts.get("tangential", 0)} background'
        )
    yr = _year_range(cited)
    if yr:
        bits.append(f"published {yr}")
    items = "".join(f"<li>{b}</li>" for b in bits)

    warn = ""
    if counts and not counts.get("direct"):
        warn += (
            '<p class="ev-warn">⚠ No cited source directly studies this exact topic — '
            "claims are extrapolated from adjacent work. Read the sources before relying on this.</p>"
        )
    unver = (verification or {}).get("unverified") or []
    if unver:
        shown = ", ".join(html.escape(u) for u in unver[:6])
        warn += (
            f'<p class="ev-warn">⚠ {len(unver)} figure(s) could not be located in the source '
            f"abstracts ({shown}) — verify against the full text before quoting.</p>"
        )
    return f'<aside class="evidence"><ul class="ev-stats">{items}</ul>{warn}</aside>'


def _disclaimer_html(topic: str, article: dict) -> str:
    base = (
        "Written with AI assistance from the abstracts (not full texts) of the journal "
        "articles listed above. Follow the source links before relying on any specific claim."
    )
    if _is_clinical(topic, article):
        base = (
            "<strong>Not medical or clinical advice.</strong> This is an AI-generated "
            "summary of journal <em>abstracts</em> (not full texts), for background only. "
            "It is not a substitute for professional judgement, primary sources, or "
            "clinical guidelines. Verify every claim, figure, and dose against the cited "
            "papers before acting on it."
        )
    return base


def render_article(
    article: dict,
    papers: list[Paper],
    topic: str,
    curation: dict | None = None,
    verification: dict | None = None,
) -> str:
    cited, cite_map = _citation_map(article, papers)
    valid_numbers = set(range(1, len(cited) + 1))

    sections_html = []
    for i, section in enumerate(article["sections"]):
        paragraphs = []
        for j, para in enumerate(section["paragraphs"]):
            remapped = _remap_citations(para, cite_map)
            text = _link_citations(html.escape(remapped), valid_numbers)
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
        f"<li>{_link_citations(html.escape(_remap_citations(t, cite_map)), valid_numbers)}</li>"
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

    evidence_note = article.get("evidence_note", "")
    note_html = (
        f'<p class="evidence-note">{_link_citations(html.escape(_remap_citations(evidence_note, cite_map)), valid_numbers)}</p>'
        if evidence_note
        else ""
    )
    featured_html = _featured_html(article, papers, cite_map)
    evidence_box = _evidence_html(cited, papers, topic, article, curation, verification, cite_map)

    today = datetime.date.today().strftime("%B %d, %Y").replace(" 0", " ")
    return _TEMPLATE.format(
        page_title=html.escape(article["title"]),
        kicker=html.escape(topic),
        title=html.escape(article["title"]),
        standfirst=html.escape(article["standfirst"]),
        date=today,
        n_sources=len(cited),
        evidence_note=note_html,
        featured=featured_html,
        sections="\n\n".join(sections_html),
        takeaways=takeaways_html,
        evidence_box=evidence_box,
        references="\n".join(refs_html),
        disclaimer=_disclaimer_html(topic, article),
    )


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<script>
  (function() {{
    var saved = localStorage.getItem('articlegen_theme') || 'system';
    if (saved === 'dark' || saved === 'light') {{
      document.documentElement.setAttribute('data-theme', saved);
    }}
  }})();
</script>
<style>
  :root, html[data-theme="dark"] {
    --bg: #0f1115;
    --ink: #f1f5f9;
    --muted: #cbd5e1;
    --accent: #2dd4bf;
    --accent-hover: #5eead4;
    --accent-soft: rgba(45, 212, 191, 0.15);
    --rule: #272a30;
    --card: #181b20;
    --warn-bg: rgba(245, 158, 11, 0.15);
    --warn-border: rgba(245, 158, 11, 0.35);
    --warn-ink: #fef08a;
    color-scheme: dark;
  }
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
      --bg: #ffffff;
      --ink: #111827;
      --muted: #4b5563;
      --accent: #0d9488;
      --accent-hover: #0f766e;
      --accent-soft: rgba(13, 148, 136, 0.1);
      --rule: #e5e7eb;
      --card: #f8fafc;
      --warn-bg: rgba(245, 158, 11, 0.1);
      --warn-border: rgba(245, 158, 11, 0.3);
      --warn-ink: #92400e;
      color-scheme: light;
    }
  }
  html[data-theme="light"] {
    --bg: #ffffff;
    --ink: #111827;
    --muted: #4b5563;
    --accent: #0d9488;
    --accent-hover: #0f766e;
    --accent-soft: rgba(13, 148, 136, 0.1);
    --rule: #e5e7eb;
    --card: #f8fafc;
    --warn-bg: rgba(245, 158, 11, 0.1);
    --warn-border: rgba(245, 158, 11, 0.3);
    --warn-ink: #92400e;
    color-scheme: light;
  }
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: Georgia, "Iowan Old Style", "Times New Roman", serif;
    font-size: 1.15rem;
    line-height: 1.7;
    text-rendering: optimizeLegibility;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }}
  main {{ max-width: 42rem; margin: 0 auto; padding: 3rem 1.25rem 5rem; }}
  header.masthead {{ margin-bottom: 3rem; }}
  .kicker {{
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--accent);
    margin: 0 0 1rem;
  }}
  h1 {{
    font-size: clamp(2rem, 5.5vw, 2.9rem);
    line-height: 1.15;
    margin: 0 0 1rem;
    letter-spacing: -0.01em;
    color: var(--ink);
  }}
  .standfirst {{
    font-size: 1.3rem;
    line-height: 1.5;
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
    font-size: 1.5rem;
    line-height: 1.25;
    margin: 2.6rem 0 0.9rem;
    color: var(--ink);
  }}
  p {{ margin: 0 0 1.2rem; }}
  p.opener::first-letter {{
    float: left;
    font-size: 3.4em;
    line-height: 0.85;
    padding: 0.06em 0.08em 0 0;
    color: var(--accent);
  }}
  sup.cite {{
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.7em;
    letter-spacing: 0.02em;
    font-weight: 600;
  }}
  sup.cite a {{ color: var(--accent); text-decoration: none; }}
  sup.cite a:hover {{ text-decoration: underline; }}
  blockquote.pull {{
    margin: 2rem 0;
    padding: 0.4rem 0 0.4rem 1.25rem;
    border-left: 3px solid var(--accent);
    font-size: 1.45rem;
    line-height: 1.38;
    font-style: italic;
    color: var(--ink);
  }}
  aside.takeaways {{
    margin: 3rem 0;
    padding: 1.5rem 1.75rem;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 12px;
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
  aside.takeaways li {{ margin-bottom: 0.6rem; color: var(--ink); }}
  p.evidence-note {{
    font-size: 0.98rem;
    color: var(--muted);
    font-style: italic;
    border-left: 3px solid var(--accent);
    padding-left: 1rem;
    margin: 1.5rem 0;
  }}
  aside.featured {{
    margin: 2.5rem 0;
    padding: 1.4rem 1.75rem;
    border: 1px solid var(--accent);
    border-radius: 12px;
    background: var(--accent-soft);
  }}
  aside.featured h2 {{
    margin: 0 0 0.7rem;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.8rem; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: var(--accent);
  }}
  aside.featured p {{ margin: 0 0 0.6rem; font-size: 1.05rem; line-height: 1.55; color: var(--ink); }}
  aside.featured .fs-cite {{ font-weight: 600; color: var(--ink); }}
  aside.featured .fs-why {{ font-style: italic; color: var(--ink); opacity: 0.9; }}
  aside.featured .fs-ref {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
  aside.featured a {{ color: var(--accent); font-weight: 600; }}
  aside.evidence {{
    margin: 2.5rem 0 0;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  aside.evidence ul.ev-stats {{
    display: flex; flex-wrap: wrap; gap: 0.4rem 1.4rem;
    list-style: none; margin: 0 0 0.6rem; padding: 0;
    font-size: 0.88rem; color: var(--muted);
  }}
  aside.evidence .ev-warn {{
    font-size: 0.92rem; line-height: 1.5; margin: 0.75rem 0 0;
    padding: 0.8rem 1rem; border-radius: 8px;
    background: var(--warn-bg); color: var(--warn-ink);
    border: 1px solid var(--warn-border);
  }}
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
    font-size: 0.9rem;
    line-height: 1.6;
    color: var(--muted);
  }}
  section.references li {{ margin-bottom: 0.75rem; color: var(--muted); }}
  section.references li:target {{ background: var(--accent-soft); border-radius: 4px; padding: 0.2rem 0.4rem; }}
  section.references a {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
  section.references a:hover {{ text-decoration: underline; }}
  .ref-authors {{ color: var(--ink); font-weight: 600; }}
  .ref-meta {{ display: block; font-size: 0.84rem; color: var(--muted); margin-top: 0.15rem; }}
  footer.colophon {{
    margin-top: 3rem;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.78rem;
    color: var(--muted);
  }}
  .article-share-bar {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin: 1.5rem 0 2rem;
    padding: 0.75rem 1rem;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 10px;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.85rem;
  }}
  .article-share-btn {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    background: var(--accent);
    color: #ffffff;
    border: none;
    padding: 0.45rem 0.9rem;
    border-radius: 6px;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
    font-size: 0.85rem;
    transition: opacity 0.2s;
  }}
  .article-share-btn:hover {{ opacity: 0.9; }}
  .article-share-btn.secondary {{
    background: transparent;
    color: var(--ink);
    border: 1px solid var(--rule);
  }}
  .share-toast {{
    display: none;
    font-size: 0.8rem;
    color: var(--accent);
    font-weight: 600;
  }}
  @media print {{
    body {{ font-size: 11pt; }}
    .kicker, sup.cite a, section.references a {{ color: black; }}
    .article-share-bar {{ display: none; }}
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
    
    <div class="article-share-bar">
      <button class="article-share-btn" onclick="shareArticle()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" y1="2" x2="12" y2="15"/></svg>
        Share
      </button>
      <button class="article-share-btn secondary" onclick="copyArticleLink()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        Copy Link
      </button>
      <button class="article-share-btn secondary" id="themeBtn" onclick="toggleArticleTheme()" title="Toggle Dark/Light Theme">
        <span id="themeIcon">🌙</span> Theme
      </button>
      <span id="shareToast" class="share-toast">Link copied!</span>
    </div>
  </header>

  {evidence_note}

  {featured}

  {sections}

  <aside class="takeaways">
    <h2>Key takeaways</h2>
    <ul>
      {takeaways}
    </ul>
  </aside>

  {evidence_box}

  <section class="references">
    <h2>Sources</h2>
    <ol>
      {references}
    </ol>
  </section>

  <footer class="colophon">
    {disclaimer}
  </footer>
</main>
<script>
function shareArticle() {{
  if (navigator.share) {{
    navigator.share({{
      title: document.title,
      text: '{title}',
      url: window.location.href
    }}).catch(function() {{}});
  }} else {{
    copyArticleLink();
  }}
}}
function copyArticleLink() {{
  navigator.clipboard.writeText(window.location.href).then(function() {{
    var t = document.getElementById('shareToast');
    if (t) {{
      t.style.display = 'inline';
      setTimeout(function() {{ t.style.display = 'none'; }}, 2500);
    }}
  }}).catch(function() {{}});
}}
function toggleArticleTheme() {{
  var cur = document.documentElement.getAttribute('data-theme');
  var isSysDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var effective = cur || (isSysDark ? 'dark' : 'light');
  var next = effective === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('articlegen_theme', next);
  updateArticleThemeIcon();
}}
function updateArticleThemeIcon() {{
  var icon = document.getElementById('themeIcon');
  if (!icon) return;
  var cur = document.documentElement.getAttribute('data-theme');
  var isSysDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var effective = cur || (isSysDark ? 'dark' : 'light');
  icon.textContent = effective === 'dark' ? '🌙' : '☀️';
}}
document.addEventListener('DOMContentLoaded', updateArticleThemeIcon);
</script>
</body>
</html>
"""


def render_markdown(
    article: dict,
    papers: list[Paper],
    topic: str,
    curation: dict | None = None,
    verification: dict | None = None,
) -> str:
    """Plain-Markdown version of the same article, for easy review/editing."""
    cited, cite_map = _citation_map(article, papers)
    today = datetime.date.today().strftime("%B %d, %Y")
    lines = [
        f"# {article['title']}",
        "",
        f"*{article['standfirst']}*",
        "",
        f"> Topic: {topic} · Generated {today} · {len(cited)} sources cited",
        "",
    ]

    evidence_note = article.get("evidence_note", "")
    if evidence_note:
        lines += [f"> **Evidence note.** {_remap_citations(evidence_note, cite_map)}", ""]

    fs = article.get("featured_study") or {}
    idx = fs.get("source_index")
    if isinstance(idx, int) and 1 <= idx <= len(papers):
        p = papers[idx - 1]
        ref = f" [{cite_map[idx]}]" if idx in cite_map else ""
        lines += [
            "> **Featured study.** "
            + (f"*{p.title}*" if not p.link else f"[{p.title}]({p.link})")
            + f" — {p.author_line} ({p.year or 'n.d.'})"
            + (f", {p.venue}" if p.venue else "") + ref,
        ]
        if fs.get("why"):
            lines.append(f"> {fs['why']}")
        if fs.get("method"):
            lines.append(f"> *Method:* {fs['method']}")
        if fs.get("results"):
            lines.append(f"> *Results:* {fs['results']}")
        lines.append("")

    for section in article["sections"]:
        lines.append(f"## {section['heading']}")
        lines.append("")
        for para in section["paragraphs"]:
            lines.append(_remap_citations(para, cite_map))
            lines.append("")
        if section.get("pull_quote"):
            lines.append(f"> **{section['pull_quote']}**")
            lines.append("")

    lines.append("## Key takeaways")
    lines.append("")
    for takeaway in article.get("key_takeaways", []):
        lines.append(f"- {_remap_citations(takeaway, cite_map)}")
    lines.append("")

    # Evidence quality
    counts = _cited_relevance_counts(cite_map, curation)
    unver = (verification or {}).get("unverified") or []
    yr = _year_range(cited)
    lines.append("## Evidence quality")
    lines.append("")
    tally = f"- {len(cited)} sources cited"
    if counts:
        tally += (f"; {counts.get('direct', 0)} directly on-topic, "
                  f"{counts.get('related', 0)} related, {counts.get('tangential', 0)} background")
    if yr:
        tally += f"; published {yr}"
    lines.append(tally)
    if counts and not counts.get("direct"):
        lines.append("- ⚠ No cited source directly studies this exact topic — claims are "
                     "extrapolated from adjacent work.")
    if unver:
        lines.append(f"- ⚠ {len(unver)} figure(s) not found in the source abstracts "
                     f"({', '.join(unver[:6])}) — verify against the full text.")
    lines.append("")

    lines.append("## Sources")
    lines.append("")
    for n, paper in enumerate(cited, start=1):
        meta = " · ".join(b for b in (paper.venue, f"cited {paper.citation_count}×" if paper.citation_count else "") if b)
        link = f" <{paper.link}>" if paper.link else ""
        lines.append(
            f"{n}. {paper.author_line} ({paper.year or 'n.d.'}). "
            f"*{paper.title}*."
            + (f" {meta}." if meta else "")
            + link
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(_markdown_disclaimer(topic, article))
    lines.append("")
    return "\n".join(lines)


def _markdown_disclaimer(topic: str, article: dict) -> str:
    if _is_clinical(topic, article):
        return (
            "**Not medical or clinical advice.** AI-generated summary of journal "
            "*abstracts* (not full texts), for background only — not a substitute for "
            "professional judgement, primary sources, or clinical guidelines. Verify "
            "every claim, figure, and dose against the cited papers."
        )
    return (
        "AI-generated from the *abstracts* (not full texts) of the cited articles. "
        "Follow the source links before relying on any specific claim."
    )


_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Draft review queue</title>
<script>
  (function() {{
    var saved = localStorage.getItem('articlegen_theme') || 'system';
    if (saved === 'dark' || saved === 'light') {{
      document.documentElement.setAttribute('data-theme', saved);
    }}
  }})();
</script>
<style>
  :root, html[data-theme="light"] {{ --bg:#fff; --ink:#1d1f21; --muted:#6b6f76; --accent:#0b6e6a; --rule:#e4e2dd; --card:#f6f5f2; color-scheme: light; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{ --bg:#16181b; --ink:#e8e6e1; --muted:#9aa0a6; --accent:#5cc8c0; --rule:#2c2f33; --card:#1e2125; color-scheme: dark; }}
  }}
  html[data-theme="dark"] {{ --bg:#16181b; --ink:#e8e6e1; --muted:#9aa0a6; --accent:#5cc8c0; --rule:#2c2f33; --card:#1e2125; color-scheme: dark; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif; line-height:1.5; }}
  main {{ max-width:44rem; margin:0 auto; padding:3rem 1.25rem 5rem; }}
  .header-row {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.3rem; }}
  h1 {{ font-size:1.6rem; margin:0; }}
  .theme-toggle-btn {{ background: var(--card); border: 1px solid var(--rule); color: var(--ink); border-radius: 8px; padding: 0.3rem 0.6rem; cursor: pointer; font-size: 0.85rem; }}
  .sub {{ color:var(--muted); margin:0 0 2rem; font-size:0.9rem; }}
  ul {{ list-style:none; margin:0; padding:0; }}
  li {{ background:var(--card); border-radius:10px; padding:1rem 1.2rem; margin-bottom:0.8rem; }}
  li a {{ color:var(--ink); text-decoration:none; font-size:1.15rem; font-weight:600; }}
  li a:hover {{ color:var(--accent); }}
  .meta {{ color:var(--muted); font-size:0.82rem; margin-top:0.3rem; }}
  .meta a {{ color:var(--accent); text-decoration:none; }}
  .empty {{ color:var(--muted); }}
</style>
</head>
<body>
<main>
  <div class="header-row">
    <h1>Draft review queue</h1>
    <button class="theme-toggle-btn" onclick="toggleIndexTheme()"><span id="idxThemeIcon">🌙</span> Theme</button>
  </div>
  <p class="sub">{count} draft(s) · newest first</p>
  <ul>
    {items}
  </ul>
</main>
<script>
function toggleIndexTheme() {{
  var cur = document.documentElement.getAttribute('data-theme');
  var isSysDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var effective = cur || (isSysDark ? 'dark' : 'light');
  var next = effective === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('articlegen_theme', next);
  updateIndexThemeIcon();
}}
function updateIndexThemeIcon() {{
  var icon = document.getElementById('idxThemeIcon');
  if (!icon) return;
  var cur = document.documentElement.getAttribute('data-theme');
  var isSysDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  var effective = cur || (isSysDark ? 'dark' : 'light');
  icon.textContent = effective === 'dark' ? '🌙' : '☀️';
}}
document.addEventListener('DOMContentLoaded', updateIndexThemeIcon);
</script>
</body>
</html>
"""


def _draft_title(html_path: str) -> str:
    try:
        with open(html_path, encoding="utf-8", errors="replace") as f:
            match = _TITLE_RE.search(f.read())
        if match:
            return html.unescape(match.group(1).strip())
    except Exception:
        pass
    return os.path.basename(html_path)


def build_index(drafts_dir: str) -> str:
    """Scan a drafts folder and write drafts/index.html listing every draft, newest first."""
    html_files = [
        p for p in glob.glob(os.path.join(drafts_dir, "*.html"))
        if os.path.basename(p) != "index.html"
    ]
    html_files.sort(key=os.path.getmtime, reverse=True)

    items = []
    for path in html_files:
        name = os.path.basename(path)
        title = html.escape(_draft_title(path))
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        md_name = name[:-5] + ".md"
        md_link = (
            f' · <a href="{html.escape(md_name, quote=True)}">markdown</a>'
            if os.path.exists(os.path.join(drafts_dir, md_name))
            else ""
        )
        items.append(
            f'<li><a href="{html.escape(name, quote=True)}">{title}</a>'
            f'<div class="meta">{mtime:%b %d, %Y %H:%M} · '
            f'<a href="{html.escape(name, quote=True)}">open</a>{md_link}</div></li>'
        )

    body = "\n    ".join(items) if items else '<li class="empty">No drafts yet.</li>'
    index_html = _INDEX_TEMPLATE.format(count=len(html_files), items=body)
    index_path = os.path.join(drafts_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)
    return index_path

"""Render the structured article + its cited sources as a journal-style page.

The layout follows the conventions of a scientific-journal Review article —
article-type label, unstructured abstract, Key points box, numbered display
items (Box 1 / Fig. 1 / Table 1), superscript Vancouver citations, a Methods
statement of the search strategy, and standard back matter. `docs/journal-style.md`
records where each convention comes from and why we copy it.

Three of the display items are built deterministically from the fetched papers
and the relevance curation, so they cannot be hallucinated.

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
# A citation marker sitting *before* the sentence punctuation, e.g. "…rest [1]."
_MARKER_BEFORE_PUNCT_RE = re.compile(r"[ \t]*(\[\d+(?:\s*,\s*\d+)*\])[ \t]*([.,;:?!])")
# A marker floated off the word it belongs to — the superscript should hug it.
_SPACE_BEFORE_MARKER_RE = re.compile(r"[ \t]+(\[\d+(?:\s*,\s*\d+)*\])")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)

RELEVANCE_LABELS = {"direct": "Direct", "related": "Related", "tangential": "Background"}


# --------------------------------------------------------------------------
# citation plumbing
# --------------------------------------------------------------------------

def _citation_map(article: dict, papers: list[Paper]) -> tuple[list[Paper], dict[int, int]]:
    """Resolve `references` (raw SOURCE indices, in first-citation order) into the
    ordered list of cited papers plus a map {raw SOURCE index -> display number 1..N}.

    The writer cites papers by their fed "SOURCE N" label; we renumber those to a
    clean 1..N sequence so the inline markers match the reference list exactly.
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


def _shift_markers_after_punctuation(text: str) -> str:
    """Move `[1].` to `.[1]` — journals set the superscript after the punctuation —
    and close up any space left between a marker and the word it attaches to."""
    return _SPACE_BEFORE_MARKER_RE.sub(r"\1", _MARKER_BEFORE_PUNCT_RE.sub(r"\2\1", text))


def _citation_runs(numbers: list[int]) -> list[tuple[int, int]]:
    """Collapse a sorted number list into (start, end) runs; runs of 3+ become ranges."""
    runs: list[tuple[int, int]] = []
    for n in numbers:
        if runs and n == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], n)
        else:
            runs.append((n, n))
    return runs


def _marker_parts(numbers: list[int], render_number) -> list[str]:
    """Format sorted citation numbers as runs — 1,3–5 — via `render_number(n)`."""
    parts = []
    for start, end in _citation_runs(numbers):
        if end - start >= 2:  # only a run of 3+ earns a range
            parts.append(f"{render_number(start)}–{render_number(end)}")
        elif end != start:
            parts.append(f"{render_number(start)},{render_number(end)}")
        else:
            parts.append(render_number(start))
    return parts


def _link_citations(escaped_text: str, valid_numbers: set[int]) -> str:
    """Turn [1] / [2, 3] markers into Nature-style superscript runs: ^1,3–5."""

    def replace(match: re.Match) -> str:
        raw = [n.strip() for n in match.group(1).split(",")]
        if not all(n.isdigit() and int(n) in valid_numbers for n in raw):
            return match.group(0)
        numbers = sorted({int(n) for n in raw})
        parts = _marker_parts(numbers, lambda n: f'<a href="#ref-{n}">{n}</a>')
        return f'<sup class="cite">{",".join(parts)}</sup>'

    return _CITATION_RE.sub(replace, escaped_text)


def _plain_citations(text: str) -> str:
    """Same run-collapsing for Markdown, where superscripts aren't available: [1,3–5]."""

    def replace(match: re.Match) -> str:
        raw = [n.strip() for n in match.group(1).split(",")]
        if not all(n.isdigit() for n in raw):
            return match.group(0)
        numbers = sorted({int(n) for n in raw})
        return "[" + ",".join(_marker_parts(numbers, str)) + "]"

    return _CITATION_RE.sub(replace, text)


def _prose(text: str, cite_map: dict[int, int], valid_numbers: set[int]) -> str:
    """Full text pipeline: renumber -> punctuation-first -> escape -> superscripts."""
    remapped = _shift_markers_after_punctuation(_remap_citations(text, cite_map))
    return _link_citations(html.escape(remapped), valid_numbers)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

_CLINICAL_HINTS = (
    "clinician", "patient", "clinical", "therapy", "treatment", "diagnos",
    "schizophreni", "depress", "disorder", "disease", "dose", "drug",
    "symptom", "psychiat", "medic", "health",
)


def _summary_text(article: dict) -> str:
    """The article's lead paragraph — `standfirst` on pre-journal-format drafts."""
    return article.get("abstract") or article.get("standfirst") or ""


def _key_points(article: dict) -> list[str]:
    return article.get("key_points") or article.get("key_takeaways") or []


def _is_clinical(topic: str, article: dict) -> bool:
    blob = (topic + " " + article.get("title", "") + " " + _summary_text(article)).lower()
    return any(h in blob for h in _CLINICAL_HINTS)


def _year_range(papers: list[Paper]) -> str:
    years = [p.year for p in papers if p.year]
    if not years:
        return ""
    lo, hi = min(years), max(years)
    return str(lo) if lo == hi else f"{lo}–{hi}"


# Surname particles stay attached to the surname: "Hans Van Dongen" -> "Van Dongen, H."
_NAME_PARTICLES = {
    "van", "von", "de", "del", "della", "der", "den", "di", "da", "dos", "du",
    "la", "le", "los", "ten", "ter", "bin", "ibn",
}


def _format_author(name: str) -> str:
    """`Susanne Diekelmann` -> `Diekelmann, S.` (journal reference form)."""
    name = " ".join(name.split())
    if not name:
        return ""
    parts = name.split(" ")
    if len(parts) == 1:
        return parts[0]
    split = len(parts) - 1
    while split > 1 and parts[split - 1].lower().strip(".") in _NAME_PARTICLES:
        split -= 1
    surname = " ".join(parts[split:])
    initials = " ".join(f"{p[0].upper()}." for p in parts[:split] if p[:1].isalpha())
    return f"{surname}, {initials}" if initials else surname


def _reference_authors(paper: Paper) -> str:
    """Vancouver/Nature author line: up to three names joined with `&`, then et al."""
    authors = [a.strip() for a in paper.authors if a and a.strip()]
    truncated = bool(authors) and authors[-1].lower().rstrip(".") == "et al"
    if truncated:
        authors = authors[:-1]
    if not authors:
        return "Unknown authors."
    formatted = [_format_author(a) for a in authors]
    if truncated or len(formatted) > 3:
        line = f"{formatted[0]} et al."
    elif len(formatted) == 1:
        line = formatted[0]
    else:
        line = ", ".join(formatted[:-1]) + " & " + formatted[-1]
    # The author line always closes with a stop, so a mononym or a corporate name
    # doesn't run straight into the title.
    return line if line.endswith(".") else line + "."


def _short_author(paper: Paper) -> str:
    """`Diekelmann & Born` / `Xie et al.` — for the table and box citation lines."""
    authors = [a.strip() for a in paper.authors if a and a.strip()]
    truncated = bool(authors) and authors[-1].lower().rstrip(".") == "et al"
    if truncated:
        authors = authors[:-1]
    if not authors:
        return "Unknown authors"
    surnames = [_format_author(a).split(",")[0] for a in authors]
    if truncated or len(surnames) > 2:
        return f"{surnames[0]} et al."
    return " & ".join(surnames)


def _titled(title: str) -> str:
    """Reference titles end in a full stop, per Nature's reference style."""
    title = title.strip()
    return title if title.endswith((".", "?", "!")) else title + "."


def _unverified_sentence(unverified: list[str]) -> str:
    """The 'figures we could not find in any abstract' limitation, in journal register."""
    shown = ", ".join(unverified[:6])
    more = "" if len(unverified) <= 6 else f" and {len(unverified) - 6} other(s)"
    if len(unverified) == 1:
        return (
            f"One numerical value reported above ({shown}) could not be located in the "
            "abstracts of the cited sources. It may originate in a full text, or may be "
            "unreliable, and should be verified before being quoted."
        )
    return (
        f"{len(unverified)} numerical values reported above ({shown}{more}) could not be "
        "located in the abstracts of the cited sources. They may originate in a full text, "
        "or may be unreliable, and should be verified before being quoted."
    )


def _display_relevance(cite_map: dict[int, int], curation: dict | None) -> dict[int, str]:
    """{display number -> relevance label} for the cited papers only."""
    relevance = (curation or {}).get("relevance") or {}
    return {
        display: relevance[raw]
        for raw, display in cite_map.items()
        if relevance.get(raw) in RELEVANCE_LABELS
    }


def _relevance_counts(cite_map: dict[int, int], curation: dict | None) -> dict:
    """Tally direct/related/tangential over the CITED sources only (not all fetched)."""
    labels = _display_relevance(cite_map, curation)
    if not labels:
        return {}
    return {level: sum(1 for v in labels.values() if v == level)
            for level in ("direct", "related", "tangential")}


def _source_link_html(paper: Paper) -> str:
    """A ` · doi:10.1038/nrn2762` (or ` · Source`) trailer for a citation line."""
    if not paper.link:
        return ""
    label = f"doi:{paper.doi.removeprefix('https://doi.org/')}" if paper.doi else "Source"
    return f' · <a href="{html.escape(paper.link, quote=True)}">{html.escape(label)}</a>'


# --------------------------------------------------------------------------
# display items
# --------------------------------------------------------------------------

def _box_html(article: dict, papers: list[Paper], cite_map: dict[int, int]) -> str:
    """Box 1 — the featured study, as a self-contained boxed display item."""
    fs = article.get("featured_study") or {}
    idx = fs.get("source_index")
    if not (isinstance(idx, int) and 1 <= idx <= len(papers)):
        return ""
    paper = papers[idx - 1]
    display = cite_map.get(idx)
    ref = f'<sup class="cite"><a href="#ref-{display}">{display}</a></sup>' if display else ""
    rows = []
    if fs.get("why"):
        rows.append(f'<p class="box-why">{html.escape(fs["why"])}</p>')
    if fs.get("method"):
        rows.append(f'<p><span class="run-in">Method.</span> {html.escape(fs["method"])}</p>')
    if fs.get("results"):
        rows.append(f'<p><span class="run-in">Results.</span> {html.escape(fs["results"])}</p>')
    return (
        '<aside class="display box" aria-labelledby="box-1">\n'
        f'<p class="di-caption" id="box-1"><span class="di-label">Box 1 |</span> '
        f'Key study: {html.escape(paper.title)}</p>\n'
        f'<p class="box-cite">{html.escape(_short_author(paper))} ({paper.year or "n.d."})'
        f'{(" · " + html.escape(paper.venue)) if paper.venue else ""}{ref}'
        f'{_source_link_html(paper)}</p>\n'
        + "\n".join(rows)
        + "\n</aside>"
    )


def _table_html(cited: list[Paper], labels: dict[int, str]) -> str:
    """Table 1 — characteristics of the cited evidence, one row per source."""
    if not cited:
        return ""
    rows = []
    for n, paper in enumerate(cited, start=1):
        label = labels.get(n)
        relevance = (
            f'<span class="swatch swatch-{label}"></span>{RELEVANCE_LABELS[label]}'
            if label else "—"
        )
        cites = f"{paper.citation_count:,}" if paper.citation_count else "—"
        rows.append(
            f'<tr><td class="t-num"><a href="#ref-{n}">{n}</a></td>'
            f"<td>{html.escape(_short_author(paper))}</td>"
            f'<td class="t-num">{paper.year or "n.d."}</td>'
            f'<td class="t-venue">{html.escape(paper.venue or "—")}</td>'
            f"<td>{relevance}</td>"
            f'<td class="t-num">{cites}</td></tr>'
        )
    return (
        '<div class="display table-wrap" aria-labelledby="table-1">\n'
        '<p class="di-caption" id="table-1"><span class="di-label">Table 1 |</span> '
        "Characteristics of the cited evidence. Relevance is the curation label for how "
        "directly each source addresses the review question; citation counts are as "
        "reported by the indexing database.</p>\n"
        '<div class="table-scroll"><table>\n'
        "<thead><tr><th>Ref.</th><th>Study</th><th>Year</th><th>Source</th>"
        "<th>Relevance</th><th>Cited by</th></tr></thead>\n"
        "<tbody>" + "".join(rows) + "</tbody>\n</table></div>\n</div>"
    )


def _year_buckets(years: list[int]) -> list[tuple[str, set[int]]]:
    """One bucket per year, or 5-year bins once there are more than ten distinct years."""
    distinct = sorted(set(years))
    if not distinct:
        return []
    if len(distinct) <= 10:
        return [(str(y), {y}) for y in distinct]
    start = (min(distinct) // 5) * 5
    buckets = []
    while start <= max(distinct):
        members = {y for y in distinct if start <= y < start + 5}
        if members:
            buckets.append((f"{start}–{str(start + 4)[-2:]}", members))
        start += 5
    return buckets


def _rounded_top_path(x: float, y: float, w: float, h: float, r: float = 4.0) -> str:
    r = max(0.0, min(r, w / 2, h))
    return (
        f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
        f"L{x + w:.1f},{y + h:.1f} Z"
    )


def _figure_html(cited: list[Paper], labels: dict[int, str]) -> str:
    """Fig. 1 — cited sources by publication year, segmented by relevance.

    An ordinal one-hue ramp (direct darkest -> background lightest) driven by CSS
    variables, so the figure re-steps itself for the dark theme.
    """
    dated = [(n, p) for n, p in enumerate(cited, start=1) if p.year]
    if len(dated) < 2:
        return ""
    buckets = _year_buckets([p.year for _, p in dated])
    if not buckets:
        return ""

    # Only segment by relevance when every cited source carries a label; otherwise the
    # stack would silently drop the unlabelled ones.
    segmented = all(labels.get(n) in RELEVANCE_LABELS for n, _ in dated)
    series = (
        [lvl for lvl in ("direct", "related", "tangential")
         if any(labels.get(n) == lvl for n, _ in dated)]
        if segmented else ["cited"]
    )

    counts: list[dict[str, int]] = []
    for _, members in buckets:
        tally = {lvl: 0 for lvl in series}
        for n, paper in dated:
            if paper.year in members:
                tally[labels[n] if segmented else "cited"] += 1
        counts.append(tally)

    totals = [sum(t.values()) for t in counts]
    y_max = max(totals)
    step = max(1, -(-y_max // 4))          # at most four ticks
    y_top = step * -(-y_max // step)

    width, height = 660.0, 250.0
    pad_l, pad_r, pad_t, pad_b = 40.0, 12.0, 24.0, 44.0
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    slot = plot_w / len(buckets)
    bar_w = min(46.0, slot * 0.6)

    def y_of(value: float) -> float:
        return pad_t + plot_h - (value / y_top) * plot_h

    parts = [
        f'<svg class="fig-svg" viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
        'aria-label="Cited sources by publication year, segmented by relevance">'
    ]
    for tick in range(0, y_top + 1, step):
        y = y_of(tick)
        parts.append(
            f'<line class="fig-grid" x1="{pad_l:.1f}" x2="{width - pad_r:.1f}" '
            f'y1="{y:.1f}" y2="{y:.1f}"></line>'
            f'<text class="fig-tick" x="{pad_l - 8:.1f}" y="{y + 3.5:.1f}" '
            f'text-anchor="end">{tick}</text>'
        )

    for i, ((label, _), tally) in enumerate(zip(buckets, counts)):
        x = pad_l + slot * i + (slot - bar_w) / 2
        cursor = pad_t + plot_h
        topmost = next((lvl for lvl in reversed(series) if tally.get(lvl)), None)
        for lvl in series:
            value = tally.get(lvl, 0)
            if not value:
                continue
            seg_h = (value / y_top) * plot_h
            top = cursor - seg_h
            drawn = max(seg_h - 2, 1.0)     # 2px surface gap between segments
            name = RELEVANCE_LABELS.get(lvl, "Cited sources")
            title = f"<title>{label}: {value} {name.lower()}</title>"
            if lvl == topmost:
                parts.append(
                    f'<path class="fig-seg seg-{lvl}" '
                    f'd="{_rounded_top_path(x, top, bar_w, drawn)}">{title}</path>'
                )
            else:
                parts.append(
                    f'<rect class="fig-seg seg-{lvl}" x="{x:.1f}" y="{top:.1f}" '
                    f'width="{bar_w:.1f}" height="{drawn:.1f}">{title}</rect>'
                )
            cursor = top
        total = sum(tally.values())
        if total:
            parts.append(
                f'<text class="fig-value" x="{x + bar_w / 2:.1f}" '
                f'y="{cursor - 6:.1f}" text-anchor="middle">{total}</text>'
            )
        parts.append(
            f'<text class="fig-tick" x="{x + bar_w / 2:.1f}" '
            f'y="{pad_t + plot_h + 18:.1f}" text-anchor="middle">{html.escape(label)}</text>'
        )

    parts.append(
        f'<line class="fig-axis" x1="{pad_l:.1f}" x2="{width - pad_r:.1f}" '
        f'y1="{pad_t + plot_h:.1f}" y2="{pad_t + plot_h:.1f}"></line>'
    )
    parts.append(
        f'<text class="fig-axis-title" x="{width / 2:.1f}" y="{height - 8:.1f}" '
        'text-anchor="middle">Year of publication</text>'
    )
    parts.append(
        f'<text class="fig-axis-title" x="{-(pad_t + plot_h / 2):.1f}" y="12" '
        'text-anchor="middle" transform="rotate(-90)">Cited sources</text>'
    )
    parts.append("</svg>")

    legend = ""
    if segmented:
        chips = "".join(
            f'<li><span class="swatch swatch-{lvl}"></span>{RELEVANCE_LABELS[lvl]}</li>'
            for lvl in series
        )
        legend = f'<ul class="fig-legend">{chips}</ul>'

    caption = "Composition of the evidence base. Cited sources by year of publication"
    caption += (
        ", segmented by how directly each addresses the review question. "
        if segmented else ". "
    )
    caption += (
        "Bar labels give the number of sources in each period; the underlying records "
        "are listed in Table 1."
    )
    return (
        '<figure class="display figure">\n'
        + "".join(parts)
        + f"\n{legend}\n"
        '<figcaption class="di-caption"><span class="di-label">Fig. 1 |</span> '
        f"{caption}</figcaption>\n</figure>"
    )


# --------------------------------------------------------------------------
# article furniture
# --------------------------------------------------------------------------

def _join_list(items: list[str]) -> str:
    """'A', 'A and B', 'A, B and C' — plain English, not 'A and B and C'.

    A two-source join read correctly by accident while there were only ever two
    databases to name; adding a third made the Methods sentence ungrammatical.
    """
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _methods_paragraphs(
    provenance: dict | None, screened: int, n_cited: int, topic: str, esc=lambda s: s
) -> dict[str, str]:
    """The three Methods paragraphs as sentences, before any markup.

    Both renderers build this section from the same text and differ only in how
    they label and wrap the paragraphs. `esc` escapes the values that come from
    outside the module — the topic, the queries, the model and database names;
    the HTML renderer passes `html.escape`, Markdown passes them through.

    Methods is the one section whose whole purpose is stating what was actually
    done, so nothing here may be guessed. In particular, the databases are named
    only when provenance records which ones answered — this used to fall back to
    a hardcoded pair, which made every article claim a search it had not run.
    """
    provenance = provenance or {}
    queries = [q for q in (provenance.get("queries") or []) if q]
    databases = [d for d in (provenance.get("databases") or []) if d]
    date = provenance.get("date") or datetime.date.today().strftime("%d %B %Y").lstrip("0")
    model = provenance.get("model")

    search = f"Candidate records were retrieved on {esc(date)}"
    if databases:
        search += " from " + _join_list([esc(d) for d in databases])
    if queries:
        search += ", using the search strings " + "; ".join(f"‘{esc(q)}’" for q in queries)
    search += ". "
    if not databases:
        search += "The databases searched were not recorded for this draft. "
    if screened:
        search += (
            f"Records without a retrievable abstract were discarded, leaving {screened} "
            "for screening. "
        )
    search += (
        f"Each remaining record was assessed for how directly it addresses {esc(topic)} "
        f"and labelled direct, related or background; {n_cited} were cited here and are "
        "listed in Table 1."
    )

    handling = (
        "Only titles and abstracts were read; full texts were not retrieved, so no claim "
        "in this review rests on data reported beyond an abstract. Every numerical value "
        "in the text was checked automatically against the abstracts of the cited sources, "
        "and any figure that could not be located is flagged under Limitations."
    )

    generation = (
        "Search planning, source curation and drafting were performed by a large language "
        + (f"model ({esc(model)})." if model else "model.")
        + " Source retrieval, relevance tabulation, citation numbering, Table 1, Fig. 1 and "
        "the statistical check are deterministic and were not model-generated."
    )
    return {"search": search, "handling": handling, "generation": generation}


def _methods_html(provenance: dict | None, screened: int, n_cited: int, topic: str) -> str:
    parts = _methods_paragraphs(provenance, screened, n_cited, topic, html.escape)
    return (
        '<section class="back-section">\n<h2>Methods</h2>\n'
        f'<p><span class="run-in">Search strategy.</span> {parts["search"]}</p>\n'
        f'<p><span class="run-in">Evidence handling.</span> {parts["handling"]}</p>\n'
        f'<p><span class="run-in">Generation.</span> {parts["generation"]}</p>\n</section>'
    )


def _assessment_paragraphs(
    cited: list[Paper],
    counts: dict,
    verification: dict | None,
    esc=lambda s: s,
) -> dict:
    """The Evidence assessment opening and its Limitations, before any markup.

    Shared by both renderers. The model used to add an `evidence_note` here; it
    is no longer part of the schema, because every tally it wrote could — and
    did — contradict the counts computed two lines above it. One article claimed
    "13 out of 20 sources" beside a line reading 9; another claimed "5 sources",
    "the majority is related" and "some are tangential" against a computed 3
    cited, all direct, none related, none background. Nothing countable in this
    section is model-written now (issue #54).
    """
    n = len(cited)
    if counts:
        direct, related, background = (
            counts.get("direct", 0), counts.get("related", 0), counts.get("tangential", 0)
        )
        # Agreement matters here: a one-source review printed "1 address the
        # review question directly" in the section that exists to be precise.
        opening = (
            f"Of the {n} source{'' if n == 1 else 's'} cited, "
            f"{direct} {'addresses' if direct == 1 else 'address'} the review question "
            f"directly, {related} {'is' if related == 1 else 'are'} related and "
            f"{background} {'provides' if background == 1 else 'provide'} background only"
        )
    else:
        opening = f"This review cites {n} source{'' if n == 1 else 's'}"
    span = _year_range(cited)
    if span:
        opening += f"; they were published in {span}"
    opening += ". The composition of the evidence base is shown in Fig. 1."

    limitations = [
        "This synthesis was prepared from abstracts alone. Effect estimates, "
        "methodological detail, and the limitations that authors report only in a full "
        "text were unavailable, so the strength of individual studies could not be "
        "appraised here."
    ]
    if counts and not counts.get("direct"):
        limitations.append(
            "No cited source studies the review question directly. The claims made above "
            "are extrapolated from adjacent populations or mechanisms and should be "
            "treated as provisional until directly relevant work is identified."
        )
    unverified = (verification or {}).get("unverified") or []
    if unverified:
        limitations.append(_unverified_sentence([esc(u) for u in unverified]))
    return {"opening": opening, "limitations": limitations}


def _assessment_html(
    cited: list[Paper],
    counts: dict,
    verification: dict | None,
) -> str:
    """Evidence assessment + Limitations — the journal-register replacement for the
    warning boxes: the same facts, stated in prose, in the back matter.

    Entirely deterministic. A legacy draft carrying `evidence_note` renders
    without it rather than reprinting a tally that may contradict the counts.
    """
    parts = _assessment_paragraphs(cited, counts, verification, html.escape)
    body = [
        "<p>" + parts["opening"] + "</p>",
        '<p><span class="run-in">Limitations.</span> ' + " ".join(parts["limitations"]) + "</p>",
    ]
    return '<section class="back-section">\n<h2>Evidence assessment</h2>\n' + "\n".join(body) + "\n</section>"


def _glossary_html(article: dict) -> str:
    entries = [
        e for e in (article.get("glossary") or [])
        if isinstance(e, dict) and e.get("term") and e.get("definition")
    ]
    if not entries:
        return ""
    items = "".join(
        f'<div class="gloss-row"><dt>{html.escape(e["term"])}</dt>'
        f'<dd>{html.escape(e["definition"])}</dd></div>'
        for e in entries
    )
    return (
        '<section class="back-section glossary">\n<h2>Glossary</h2>\n'
        f"<dl>{items}</dl>\n</section>"
    )


def _back_matter_html(cited: list[Paper], topic: str, article: dict, provenance: dict | None) -> str:
    linked = sum(1 for p in cited if p.link)
    model = (provenance or {}).get("model")
    contributions = (
        "Search planning, source curation and drafting were carried out by an automated "
        "pipeline (articlegen"
        + (f", {html.escape(model)}" if model else "")
        + "). No human author wrote or verified the text before publication of this draft."
    )
    return (
        '<section class="back-section">\n<h2>Additional information</h2>\n'
        f'<p><span class="run-in">Data availability.</span> No new data were generated. '
        f"All evidence cited is published and openly indexed; {linked} of the "
        f"{len(cited)} cited records resolve through the links in the reference list.</p>\n"
        f'<p><span class="run-in">Author contributions.</span> {contributions}</p>\n'
        '<p><span class="run-in">Competing interests.</span> None declared.</p>\n'
        f'<p><span class="run-in">Peer review.</span> This article has not been peer '
        "reviewed and is not a publication of record.</p>\n</section>"
    )


def _disclaimer_html(topic: str, article: dict) -> str:
    base = (
        "Machine-generated evidence review, written from the abstracts (not the full texts) "
        "of the journal articles listed in the references. Follow the source links before "
        "relying on any specific claim."
    )
    if _is_clinical(topic, article):
        base = (
            "<strong>Not medical or clinical advice.</strong> This is a machine-generated "
            "summary of journal <em>abstracts</em> (not full texts), for background only. "
            "It is not a substitute for professional judgement, primary sources, or "
            "clinical guidelines. Verify every claim, figure, and dose against the cited "
            "papers before acting on it."
        )
    return base


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def render_article(
    article: dict,
    papers: list[Paper],
    topic: str,
    curation: dict | None = None,
    verification: dict | None = None,
    provenance: dict | None = None,
) -> str:
    cited, cite_map = _citation_map(article, papers)
    valid_numbers = set(range(1, len(cited) + 1))
    labels = _display_relevance(cite_map, curation)
    counts = _relevance_counts(cite_map, curation)

    sections_html = []
    for section in article.get("sections", []):
        paragraphs = "\n".join(
            f"<p>{_prose(para, cite_map, valid_numbers)}</p>"
            for para in section.get("paragraphs", [])
        )
        sections_html.append(
            f'<section class="body-section">\n<h2>{html.escape(section["heading"])}</h2>\n'
            f"{paragraphs}\n</section>"
        )

    # Display items are interleaved the way a journal places them: the box after the
    # introduction, the figure after the first thematic section, the table before the
    # conclusions. Short articles get them appended in order instead.
    box = _box_html(article, papers, cite_map)
    figure = _figure_html(cited, labels)
    table = _table_html(cited, labels)
    body: list[str] = []
    pending = [item for item in (box, figure, table) if item]
    positions = {1: box, 2: figure, max(len(sections_html) - 1, 3): table}
    for i, section_html in enumerate(sections_html, start=1):
        body.append(section_html)
        item = positions.get(i)
        if item and item in pending:
            body.append(item)
            pending.remove(item)
    body.extend(pending)

    key_points = "\n".join(
        f"<li>{_prose(point, cite_map, valid_numbers)}</li>" for point in _key_points(article)
    )
    key_points_html = (
        '<aside class="key-points">\n<h2>Key points</h2>\n<ul>\n'
        f"{key_points}\n</ul>\n</aside>" if key_points else ""
    )

    keywords = [k for k in (article.get("keywords") or []) if k]
    keywords_html = (
        '<p class="keywords"><span class="meta-label">Keywords</span> '
        + "; ".join(html.escape(k) for k in keywords) + "</p>"
        if keywords else ""
    )

    refs_html = []
    for n, paper in enumerate(cited, start=1):
        title = html.escape(_titled(paper.title))
        title_html = (
            f'<a href="{html.escape(paper.link, quote=True)}">{title}</a>'
            if paper.link else title
        )
        venue = f' <em>{html.escape(paper.venue)}</em>' if paper.venue else ""
        cites = (
            f' <span class="ref-cites">Cited by {paper.citation_count:,}</span>'
            if paper.citation_count else ""
        )
        refs_html.append(
            f'<li id="ref-{n}"><span class="ref-authors">{html.escape(_reference_authors(paper))}</span> '
            f'{title_html}{venue} ({paper.year or "n.d."}).{cites}</li>'
        )

    span = _year_range(cited)
    meta_bits = [
        f"Generated {datetime.date.today().strftime('%d %B %Y').lstrip('0')}",
        f"{len(cited)} sources cited" + (f", {span}" if span else ""),
        "Abstract-derived synthesis",
        "Not peer reviewed",
    ]

    # Format first, THEN inject the stylesheet: the CSS is full of braces that
    # str.format would try to read as fields.
    return (
        _TEMPLATE.format(
            page_title=html.escape(article["title"]),
            title=html.escape(article["title"]),
            subject=html.escape(topic),
            meta_line=" &middot; ".join(html.escape(b) for b in meta_bits),
            abstract=_prose(_summary_text(article), cite_map, valid_numbers),
            keywords=keywords_html,
            key_points=key_points_html,
            body="\n\n".join(body),
            methods=_methods_html(provenance, len(papers), len(cited), topic),
            assessment=_assessment_html(cited, counts, verification),
            glossary=_glossary_html(article),
            references="\n".join(refs_html),
            additional=_back_matter_html(cited, topic, article, provenance),
            disclaimer=_disclaimer_html(topic, article),
        ).replace("__STYLE__", _CSS)
    )


_CSS = """
  :root, html[data-theme="light"] {
    --bg: #ffffff;
    --surface: #f7f7f5;
    --ink: #14171a;
    --ink-2: #3c4249;
    --muted: #6a7178;
    --accent: #17457f;
    --link: #1b5aa8;
    --rule: #dfdfda;
    --rule-strong: #b9bab5;
    --seg-direct: #184f95;
    --seg-related: #2a78d6;
    --seg-tangential: #86b6ef;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #14150f;
      --surface: #1e1f1c;
      --ink: #f2f1ea;
      --ink-2: #cfcec5;
      --muted: #9d9d94;
      --accent: #9dc4f5;
      --link: #86b6ef;
      --rule: #33342f;
      --rule-strong: #4c4d47;
      --seg-direct: #86b6ef;
      --seg-related: #3987e5;
      --seg-tangential: #184f95;
      color-scheme: dark;
    }
  }
  html[data-theme="dark"] {
    --bg: #14150f;
    --surface: #1e1f1c;
    --ink: #f2f1ea;
    --ink-2: #cfcec5;
    --muted: #9d9d94;
    --accent: #9dc4f5;
    --link: #86b6ef;
    --rule: #33342f;
    --rule-strong: #4c4d47;
    --seg-direct: #86b6ef;
    --seg-related: #3987e5;
    --seg-tangential: #184f95;
    color-scheme: dark;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: "Iowan Old Style", "Charter", Georgia, "Times New Roman", serif;
    font-size: 1.02rem;
    line-height: 1.62;
    text-rendering: optimizeLegibility;
    -webkit-font-smoothing: antialiased;
  }
  main { max-width: 40rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
  .sans, .meta-line, .subject-line, .keywords, .di-caption, .fig-legend, .key-points,
  .refs ol, .toolbar, .colophon, table, .meta-label {
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  }

  /* ---- masthead ---------------------------------------------------- */
  header.masthead { border-top: 3px solid var(--ink); padding-top: 0.9rem; margin-bottom: 2rem; }
  .article-type {
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--accent); margin: 0 0 0.9rem;
  }
  h1 {
    font-size: clamp(1.7rem, 4.2vw, 2.3rem);
    line-height: 1.22; font-weight: 700; letter-spacing: -0.005em;
    margin: 0 0 0.9rem;
  }
  .meta-line {
    font-size: 0.78rem; color: var(--muted); margin: 0 0 0.35rem;
    padding-bottom: 0.9rem; border-bottom: 1px solid var(--rule);
  }
  .subject-line { font-size: 0.78rem; color: var(--muted); margin: 0 0 0.9rem; }
  .meta-label {
    font-size: 0.68rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--muted); margin-right: 0.4rem;
  }

  /* ---- abstract & key points --------------------------------------- */
  .abstract { margin: 0 0 1.2rem; }
  .abstract p { margin: 0; font-size: 1.06rem; line-height: 1.6; color: var(--ink-2); }
  .abstract .run-in-head {
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--ink); margin-right: 0.5rem;
  }
  .keywords { font-size: 0.8rem; color: var(--muted); margin: 0 0 2rem; }
  aside.key-points {
    background: var(--surface); border: 1px solid var(--rule);
    border-left: 3px solid var(--accent);
    padding: 1.1rem 1.3rem 1.2rem; margin: 0 0 2.2rem; border-radius: 3px;
  }
  aside.key-points h2 {
    font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: var(--accent); margin: 0 0 0.7rem;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  }
  aside.key-points ul { margin: 0; padding-left: 1.1rem; }
  aside.key-points li { margin-bottom: 0.5rem; font-size: 0.95rem; line-height: 1.55; }
  aside.key-points li:last-child { margin-bottom: 0; }

  /* ---- body -------------------------------------------------------- */
  h2 {
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 1.02rem; font-weight: 700; letter-spacing: 0.01em;
    margin: 2.2rem 0 0.7rem; color: var(--ink);
  }
  p { margin: 0 0 1rem; }
  .body-section p + p { text-indent: 1.2em; }
  .run-in { font-weight: 700; font-style: italic; }
  a { color: var(--link); }
  sup.cite { font-size: 0.68em; line-height: 0; font-weight: 600; letter-spacing: 0.02em; }
  sup.cite a { color: var(--link); text-decoration: none; padding: 0 0.02em; }
  sup.cite a:hover { text-decoration: underline; }

  /* ---- display items ----------------------------------------------- */
  .display { margin: 1.8rem 0 2rem; }
  .di-caption {
    font-size: 0.8rem; line-height: 1.5; color: var(--muted); margin: 0.7rem 0 0;
  }
  .di-label { font-weight: 700; color: var(--ink); }
  aside.box {
    background: var(--surface); border: 1px solid var(--rule-strong);
    padding: 1.1rem 1.3rem 1.2rem; border-radius: 3px;
  }
  aside.box .di-caption { margin: 0 0 0.7rem; font-size: 0.92rem; color: var(--ink); }
  aside.box p { font-size: 0.95rem; line-height: 1.55; margin: 0 0 0.6rem; }
  aside.box p:last-child { margin-bottom: 0; }
  .box-cite { color: var(--muted); font-size: 0.85rem !important; }
  .box-why { font-style: italic; }
  figure.figure { margin: 1.8rem 0 2rem; padding: 1rem 0 0; border-top: 1px solid var(--rule); }
  .fig-svg { width: 100%; height: auto; display: block; }
  .fig-grid { stroke: var(--rule); stroke-width: 1; }
  .fig-axis { stroke: var(--rule-strong); stroke-width: 1; }
  .fig-tick { fill: var(--muted); font-size: 11px;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
  .fig-value { fill: var(--ink-2); font-size: 11px; font-weight: 600;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
  .fig-axis-title { fill: var(--muted); font-size: 11px; letter-spacing: 0.04em;
    font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
  .seg-direct { fill: var(--seg-direct); }
  .seg-related { fill: var(--seg-related); }
  .seg-tangential { fill: var(--seg-tangential); }
  .seg-cited { fill: var(--seg-related); }
  .fig-legend {
    display: flex; flex-wrap: wrap; gap: 0.3rem 1.1rem; list-style: none;
    margin: 0.6rem 0 0; padding: 0; font-size: 0.78rem; color: var(--muted);
  }
  .fig-legend li { display: flex; align-items: center; gap: 0.4rem; }
  .swatch {
    display: inline-block; width: 0.68rem; height: 0.68rem; border-radius: 2px;
    margin-right: 0.35rem; vertical-align: -0.05rem;
  }
  .swatch-direct { background: var(--seg-direct); }
  .swatch-related { background: var(--seg-related); }
  .swatch-tangential { background: var(--seg-tangential); }
  .table-scroll { overflow-x: auto; }
  table { width: 100%; min-width: 32rem; border-collapse: collapse; font-size: 0.82rem; }
  tbody td:nth-child(5) { white-space: nowrap; }
  thead th {
    text-align: left; font-weight: 700; color: var(--ink);
    border-top: 1px solid var(--rule-strong); border-bottom: 1px solid var(--rule-strong);
    padding: 0.45rem 0.5rem; white-space: nowrap;
  }
  tbody td { padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--rule); color: var(--ink-2); }
  tbody tr:last-child td { border-bottom: 1px solid var(--rule-strong); }
  .t-num { white-space: nowrap; font-variant-numeric: tabular-nums; }
  .t-venue { color: var(--muted); }

  /* ---- back matter -------------------------------------------------- */
  .back-section { margin-top: 2.2rem; }
  .back-section > h2:first-child, .refs h2 { margin-top: 0; }
  .back-section p { font-size: 0.92rem; line-height: 1.58; color: var(--ink-2); }
  .glossary dl { margin: 0; }
  .gloss-row { display: flex; gap: 0.75rem; padding: 0.4rem 0; border-bottom: 1px solid var(--rule); }
  .gloss-row dt { flex: 0 0 9.5rem; font-weight: 700; font-size: 0.92rem; }
  .gloss-row dd { margin: 0; font-size: 0.92rem; color: var(--ink-2); }
  .gloss-row:last-child { border-bottom: none; }
  .refs { margin-top: 2.4rem; border-top: 2px solid var(--ink); padding-top: 1.1rem; }
  .refs ol { margin: 0; padding-left: 1.5rem; font-size: 0.82rem; line-height: 1.5; }
  .refs li { margin-bottom: 0.55rem; color: var(--ink-2); }
  .refs li:target { background: var(--surface); border-radius: 2px; }
  .refs a { color: var(--link); text-decoration: none; }
  .refs a:hover { text-decoration: underline; }
  .ref-authors { color: var(--ink); }
  .ref-cites { color: var(--muted); }
  footer.colophon {
    margin-top: 2.4rem; padding-top: 1rem; border-top: 1px solid var(--rule);
    font-size: 0.78rem; line-height: 1.55; color: var(--muted);
  }

  /* ---- toolbar ------------------------------------------------------ */
  .toolbar { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 1rem 0 2rem; }
  .tool-btn {
    display: inline-flex; align-items: center; gap: 0.35rem;
    background: transparent; color: var(--ink-2);
    border: 1px solid var(--rule-strong); border-radius: 2px;
    padding: 0.35rem 0.7rem; font-size: 0.78rem; font-weight: 600;
    cursor: pointer; font-family: inherit;
  }
  .tool-btn:hover { border-color: var(--accent); color: var(--accent); }
  .share-toast { font-size: 0.78rem; color: var(--accent); align-self: center; display: none; }

  @media (max-width: 34rem) {
    .gloss-row { display: block; }
    .gloss-row dt { margin-bottom: 0.15rem; }
    .body-section p + p { text-indent: 0; }
  }
  @media print {
    body { font-size: 10.5pt; background: #fff; color: #000; }
    .toolbar { display: none; }
    a, sup.cite a { color: #000; }
  }
"""


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
<style>__STYLE__</style>
</head>
<body>
<main>
  <article>
  <header class="masthead">
    <p class="article-type">Evidence Review</p>
    <h1>{title}</h1>
    <p class="meta-line">{meta_line}</p>
    <p class="subject-line"><span class="meta-label">Subject</span>{subject}</p>

    <div class="toolbar">
      <button class="tool-btn" onclick="shareArticle()">Share</button>
      <button class="tool-btn" onclick="copyArticleLink()">Copy link</button>
      <button class="tool-btn" onclick="toggleArticleTheme()"><span id="themeIcon">&#9789;</span> Theme</button>
      <span id="shareToast" class="share-toast">Link copied</span>
    </div>

    <div class="abstract">
      <p><span class="run-in-head">Abstract</span>{abstract}</p>
    </div>
    {keywords}
  </header>

  {key_points}

  {body}

  {methods}

  {assessment}

  {glossary}

  <section class="refs">
    <h2>References</h2>
    <ol>
      {references}
    </ol>
  </section>

  {additional}

  <footer class="colophon">
    {disclaimer}
  </footer>
  </article>
</main>
<script>
function shareArticle() {{
  if (navigator.share) {{
    navigator.share({{ title: document.title, url: window.location.href }}).catch(function() {{}});
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
  icon.innerHTML = effective === 'dark' ? '&#9789;' : '&#9788;';
}}
document.addEventListener('DOMContentLoaded', updateArticleThemeIcon);
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def render_markdown(
    article: dict,
    papers: list[Paper],
    topic: str,
    curation: dict | None = None,
    verification: dict | None = None,
    provenance: dict | None = None,
) -> str:
    """Plain-Markdown version of the same journal-format article."""
    cited, cite_map = _citation_map(article, papers)
    labels = _display_relevance(cite_map, curation)
    counts = _relevance_counts(cite_map, curation)
    today = datetime.date.today().strftime("%d %B %Y").lstrip("0")
    span = _year_range(cited)

    def prose(text: str) -> str:
        return _plain_citations(
            _shift_markers_after_punctuation(_remap_citations(text, cite_map))
        )

    lines = [
        "**EVIDENCE REVIEW**",
        "",
        f"# {article['title']}",
        "",
        f"*Generated {today} · {len(cited)} sources cited"
        + (f", {span}" if span else "")
        + " · Abstract-derived synthesis · Not peer reviewed*",
        "",
        f"**Subject:** {topic}",
        "",
        f"**Abstract.** {prose(_summary_text(article))}",
        "",
    ]

    keywords = [k for k in (article.get("keywords") or []) if k]
    if keywords:
        lines += [f"**Keywords:** {'; '.join(keywords)}", ""]

    points = _key_points(article)
    if points:
        lines += ["## Key points", ""]
        lines += [f"- {prose(p)}" for p in points]
        lines.append("")

    sections = article.get("sections", [])
    box_md = _box_markdown(article, papers, cite_map)
    figure_md = _figure_markdown(cited, labels)
    table_md = _table_markdown(cited, labels)
    positions = {1: box_md, 2: figure_md, max(len(sections) - 1, 3): table_md}
    pending = [item for item in (box_md, figure_md, table_md) if item]

    for i, section in enumerate(sections, start=1):
        lines += [f"## {section['heading']}", ""]
        for para in section.get("paragraphs", []):
            lines += [prose(para), ""]
        item = positions.get(i)
        if item and item in pending:
            lines += [item, ""]
            pending.remove(item)
    for item in pending:
        lines += [item, ""]

    lines += _methods_markdown(provenance, len(papers), len(cited), topic)
    lines += _assessment_markdown(cited, counts, verification)

    glossary = [
        e for e in (article.get("glossary") or [])
        if isinstance(e, dict) and e.get("term") and e.get("definition")
    ]
    if glossary:
        lines += ["## Glossary", ""]
        lines += [f"- **{e['term']}** — {e['definition']}" for e in glossary]
        lines.append("")

    lines += ["## References", ""]
    for n, paper in enumerate(cited, start=1):
        venue = f" *{paper.venue}*" if paper.venue else ""
        link = f" <{paper.link}>" if paper.link else ""
        cites = f" Cited by {paper.citation_count:,}." if paper.citation_count else ""
        lines.append(
            f"{n}. {_reference_authors(paper)} {_titled(paper.title)}{venue} "
            f"({paper.year or 'n.d.'}).{cites}{link}"
        )
    lines.append("")

    lines += ["## Additional information", ""]
    linked = sum(1 for p in cited if p.link)
    model = (provenance or {}).get("model")
    lines += [
        f"- **Data availability.** No new data were generated; {linked} of {len(cited)} "
        "cited records resolve through the reference links.",
        "- **Author contributions.** Drafted by an automated pipeline (articlegen"
        + (f", {model}" if model else "") + "); no human author verified the text.",
        "- **Competing interests.** None declared.",
        "- **Peer review.** Not peer reviewed; not a publication of record.",
        "",
        "---",
        "",
        _markdown_disclaimer(topic, article),
        "",
    ]
    return "\n".join(lines)


def _box_markdown(article: dict, papers: list[Paper], cite_map: dict[int, int]) -> str:
    fs = article.get("featured_study") or {}
    idx = fs.get("source_index")
    if not (isinstance(idx, int) and 1 <= idx <= len(papers)):
        return ""
    paper = papers[idx - 1]
    ref = f" [{cite_map[idx]}]" if idx in cite_map else ""
    out = [f"> **Box 1 | Key study: {paper.title}**", ">",
           f"> {_short_author(paper)} ({paper.year or 'n.d.'})"
           + (f", {paper.venue}" if paper.venue else "") + ref
           + (f" <{paper.link}>" if paper.link else "")]
    if fs.get("why"):
        out.append(f"> *{fs['why']}*")
    if fs.get("method"):
        out.append(f"> **Method.** {fs['method']}")
    if fs.get("results"):
        out.append(f"> **Results.** {fs['results']}")
    return "\n".join(out)


def _table_markdown(cited: list[Paper], labels: dict[int, str]) -> str:
    if not cited:
        return ""
    rows = [
        "**Table 1 | Characteristics of the cited evidence.**",
        "",
        "| Ref. | Study | Year | Source | Relevance | Cited by |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for n, paper in enumerate(cited, start=1):
        relevance = RELEVANCE_LABELS.get(labels.get(n, ""), "—")
        cites = f"{paper.citation_count:,}" if paper.citation_count else "—"
        rows.append(
            f"| {n} | {_short_author(paper)} | {paper.year or 'n.d.'} | "
            f"{paper.venue or '—'} | {relevance} | {cites} |"
        )
    return "\n".join(rows)


def _figure_markdown(cited: list[Paper], labels: dict[int, str]) -> str:
    dated = [(n, p) for n, p in enumerate(cited, start=1) if p.year]
    if len(dated) < 2:
        return ""
    buckets = _year_buckets([p.year for _, p in dated])
    if not buckets:
        return ""
    lines = [
        "**Fig. 1 | Composition of the evidence base.** Cited sources by year of "
        "publication, segmented by how directly each addresses the review question.",
        "",
    ]
    for label, members in buckets:
        members_in = [n for n, p in dated if p.year in members]
        tally = {}
        for n in members_in:
            key = RELEVANCE_LABELS.get(labels.get(n, ""), "unlabelled")
            tally[key] = tally.get(key, 0) + 1
        detail = ", ".join(f"{v} {k.lower()}" for k, v in tally.items())
        lines.append(f"- {label}: {len(members_in)} ({detail})")
    return "\n".join(lines)


def _methods_markdown(provenance: dict | None, screened: int, n_cited: int, topic: str) -> list[str]:
    parts = _methods_paragraphs(provenance, screened, n_cited, topic)
    return [
        "## Methods",
        "",
        f"**Search strategy.** {parts['search']}",
        "",
        f"**Evidence handling.** {parts['handling']}",
        "",
        f"**Generation.** {parts['generation']}",
        "",
    ]


def _assessment_markdown(cited, counts, verification) -> list[str]:
    parts = _assessment_paragraphs(cited, counts, verification)
    lines = ["## Evidence assessment", "", parts["opening"], ""]
    lines += ["**Limitations.** " + " ".join(parts["limitations"]), ""]
    return lines


def _markdown_disclaimer(topic: str, article: dict) -> str:
    if _is_clinical(topic, article):
        return (
            "**Not medical or clinical advice.** Machine-generated summary of journal "
            "*abstracts* (not full texts), for background only — not a substitute for "
            "professional judgement, primary sources, or clinical guidelines. Verify "
            "every claim, figure, and dose against the cited papers."
        )
    return (
        "Machine-generated from the *abstracts* (not full texts) of the cited articles. "
        "Follow the source links before relying on any specific claim."
    )


# --------------------------------------------------------------------------
# review-queue index
# --------------------------------------------------------------------------

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
  :root, html[data-theme="light"] {{ --bg:#fff; --ink:#14171a; --muted:#6a7178; --accent:#17457f; --link:#1b5aa8; --rule:#dfdfda; --card:#f7f7f5; color-scheme: light; }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{ --bg:#14150f; --ink:#f2f1ea; --muted:#9d9d94; --accent:#9dc4f5; --link:#86b6ef; --rule:#33342f; --card:#1e1f1c; color-scheme: dark; }}
  }}
  html[data-theme="dark"] {{ --bg:#14150f; --ink:#f2f1ea; --muted:#9d9d94; --accent:#9dc4f5; --link:#86b6ef; --rule:#33342f; --card:#1e1f1c; color-scheme: dark; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,"Segoe UI",Helvetica,Arial,sans-serif; line-height:1.5; }}
  main {{ max-width:44rem; margin:0 auto; padding:2.5rem 1.25rem 5rem; }}
  .header-row {{ display:flex; align-items:baseline; justify-content:space-between;
    border-top:3px solid var(--ink); padding-top:0.8rem; margin-bottom:0.3rem; }}
  h1 {{ font-size:1.3rem; margin:0; letter-spacing:-0.01em; }}
  .theme-toggle-btn {{ background:transparent; border:1px solid var(--rule); color:var(--ink);
    border-radius:2px; padding:0.3rem 0.6rem; cursor:pointer; font-size:0.78rem; }}
  .sub {{ color:var(--muted); margin:0 0 2rem; font-size:0.8rem; }}
  ul {{ list-style:none; margin:0; padding:0; }}
  li {{ border-bottom:1px solid var(--rule); padding:0.9rem 0; }}
  li a {{ color:var(--ink); text-decoration:none; font-size:1.02rem; font-weight:600;
    font-family:"Iowan Old Style","Charter",Georgia,serif; }}
  li a:hover {{ color:var(--link); }}
  .meta {{ color:var(--muted); font-size:0.78rem; margin-top:0.3rem; }}
  .meta a {{ color:var(--link); text-decoration:none; }}
  .empty {{ color:var(--muted); }}
</style>
</head>
<body>
<main>
  <div class="header-row">
    <h1>Draft review queue</h1>
    <button class="theme-toggle-btn" onclick="toggleIndexTheme()"><span id="idxThemeIcon">&#9789;</span> Theme</button>
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
  icon.innerHTML = effective === 'dark' ? '&#9789;' : '&#9788;';
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

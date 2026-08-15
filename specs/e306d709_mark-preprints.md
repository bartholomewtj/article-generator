# Plan — mark preprints in the reference list and Table 1 (issue #144)

## What's wrong

A draft cited a Research Square preprint (DOI `10.21203/rs.3.rs-9924877/v1`) next
to a Cochrane review with nothing to tell them apart. The only difference on the
page was a blank journal cell in Table 1's Source column. The masthead's "Not peer
reviewed" is about *this* article, not its sources.

## What to build

Detect preprints in `articlegen/sources.py`, carry a flag on `Paper`, and print it
in two places in `articlegen/render.py` — the References entry and Table 1's Source
column — in both HTML and Markdown.

**Not in scope** (do not do these):

- Do not exclude, filter or down-rank preprints. Ranking, curation and the
  full-text path stay exactly as they are.
- Do not tell the writer model about the flag (`writer.py` line ~558 builds the
  "Venue: … | Citations: …" prompt line — leave it alone).
- Do not mark preprints in Box 1, Fig. 1 or the Methods prose.
- No CSS changes, no new HTML classes, no refactors.

---

## 1. `articlegen/sources.py` — detection

### 1a. Detection helper

Add just **above** `@dataclass class Paper` (currently line ~129, after
`_strip_title_markup`):

```python
# DOI prefixes owned by preprint servers. A prefix belongs to one registrant, so
# matching one is an identity check rather than a guess — which is what makes
# this safe as a fallback for the sources that publish no type metadata.
#
# 10.1101 needs the extra digit. Cold Spring Harbor Laboratory Press registered
# that prefix and uses it for BOTH bioRxiv/medRxiv postings (10.1101/2024.03.01.
# 583912, or an older bare 10.1101/123456) and its peer-reviewed journals
# (10.1101/gr.*, 10.1101/gad.*, 10.1101/cshperspect.*). A bare `10.1101` check
# would print "not peer reviewed" under every Genome Research paper — a false
# flag is a wrong warning printed in the article, which is worse than a miss.
_PREPRINT_DOI_RES = (
    re.compile(r"^10\.21203/"),          # Research Square
    re.compile(r"^10\.1101/\d"),         # bioRxiv / medRxiv (digit, not a journal code)
    re.compile(r"^10\.48550/arxiv\."),   # arXiv's own registered DOIs
)

_PREPRINT_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/", re.IGNORECASE)


def _looks_like_preprint(doi: str, url: str) -> bool:
    """True when the identifier itself says the record is a preprint posting.

    The fallback for sources that return no usable type metadata (issue #144).
    Identifier-only on purpose: a title or an abstract can say anything, and a
    venue string arrives too inconsistently to key a printed claim on.
    """
    normalised = _normalize_doi(doi)
    if normalised and any(rx.match(normalised) for rx in _PREPRINT_DOI_RES):
        return True
    return bool(url and _PREPRINT_URL_RE.search(url))
```

`_normalize_doi` is defined further down the module (line ~592). That is fine —
the name resolves when the function runs. **Do not move `_normalize_doi`**; a
relocation is diff noise on a file with settled history.

### 1b. `Paper`

- Append a new field **at the end** of the field list, after `full_text`:
  `is_preprint: bool = False`. Appending (not inserting) keeps every positional
  construction in the tests and `demo.py` valid.
- In `__post_init__`, after the existing title clean:

```python
        # The identifier fallback lives here for the same reason the title clean
        # does: one choke point, so a fifth search source inherits it. A parser
        # that already knows from the API's type metadata sets the flag True
        # before construction, and this never clears it.
        if not self.is_preprint:
            self.is_preprint = _looks_like_preprint(self.doi, self.url)
```

### 1c. Per-source type metadata

Use what each API actually reports, so detection does not lean entirely on DOI
prefixes:

- **OpenAlex** (`_openalex_page`, ~line 316): add `type` to `_OA_FIELDS` (line 92
  — it is a `select` list, so the field must be requested or it arrives absent),
  then pass `is_preprint=(item.get("type") == "preprint")`.
- **Europe PMC** (`search_europe_pmc`, ~line 444): `src` is already unpacked on
  line 443. Pass
  `is_preprint=(src == "PPR" or "preprint" in (item.get("pubType") or "").lower())`.
  Europe PMC files preprints under the `PPR` source id — that is the definitive
  tell; `pubType` is the belt-and-braces half.
- **arXiv** (`search_arxiv`, ~line 561): pass `is_preprint=True`. Comment why it
  is unconditional: even when the entry carries a `journal_ref`, the record we
  link and cite is the arXiv posting, not the journal's version of record.
- **Semantic Scholar**: change nothing. Leave `_SS_FIELDS` alone and add a short
  comment saying so — its `publicationTypes` enum has no preprint value, and
  `externalIds["ArXiv"]` is present on plenty of *published* papers, so keying on
  it would false-flag them. The DOI fallback covers Research Square, bioRxiv and
  arXiv-registered DOIs coming through this source.

### 1d. `_merge_duplicate` (~line 968)

The flag is **never OR'd across a merge**, and the comment must say why: identity
is first-seen-wins, arXiv is queried last precisely so a preprint loses to the
published version, and copying the flag over would relabel that published version
a preprint.

The one exception is when the merge *adopts* the duplicate's identifier. Change
the two existing lines:

```python
    if dup.doi and not kept.doi:
        kept.doi = dup.doi
        # Adopting an identifier adopts what it says about the record: if the
        # only DOI we now hold is a preprint-server one, that is what the
        # reference link points at.
        kept.is_preprint = kept.is_preprint or _looks_like_preprint(kept.doi, "")
    ...
    if dup.url and not kept.url:
        kept.url = dup.url
        kept.is_preprint = kept.is_preprint or _looks_like_preprint("", kept.url)
```

---

## 2. `articlegen/render.py` — display

### 2a. `_table_rows` (~line 491)

This function already owns the display strings both renderers print
(`paper.venue or "—"`, `"Full text"/"Abstract"`). Build the Source cell here so
HTML and Markdown cannot disagree:

```python
        # A preprint with no journal shows a blank Source cell, which was the
        # only tell the reader got (#144). Say it instead.
        venue = paper.venue or "—"
        if paper.is_preprint:
            venue = f"{paper.venue} (preprint)" if paper.venue else "Preprint"
```

and use that `venue` in the row dict. Also add `"preprint": bool(paper.is_preprint)`
to the row, so a later renderer can branch without re-reading the paper.

`_table_html` and `_table_markdown` need **no change** — both already print
`row["venue"]` (HTML escapes it; keep that).

### 2b. References — HTML (~line 1264-1279)

Inside the `for n, paper in enumerate(cited, start=1)` loop, add:

```python
        preprint = " (preprint, not peer reviewed)" if paper.is_preprint else ""
```

and place it after the year, before the cited-by span:

```python
            f'{title_html}{venue} ({paper.year or "n.d."}).{preprint}{cites}</li>'
```

Plain text, no `<span>` — an unstyled class earns nothing and the stylesheet stays
untouched.

### 2c. References — Markdown (~line 1773-1781)

Same string, same position:

```python
        preprint = " (preprint, not peer reviewed)" if paper.is_preprint else ""
        lines.append(
            f"{n}. {_reference_authors(paper)} {_titled(paper.title)}{venue} "
            f"({paper.year or 'n.d.'}).{preprint}{cites}{link}"
        )
```

Both outputs must carry the string **verbatim**: `(preprint, not peer reviewed)`.

---

## 3. Tests

### 3a. New test in `tests/test_offline.py`

Add `def test_preprints_are_marked_as_preprints() -> None:` near the other source
tests (after `test_candidate_papers_dedupe_by_doi`, ~line 1600), with a docstring
naming issue #144 and the Research Square case. Use the existing `check(...)`
helper. Cover:

**Identifier detection** (`sources._looks_like_preprint`):

- `10.21203/rs.3.rs-9924877/v1` → True (the real DOI from the issue).
- `https://doi.org/10.21203/rs.3.rs-1/v1` → True (resolver form, since detection
  runs through `_normalize_doi`).
- `10.1101/2024.03.01.583912` → True (medRxiv/bioRxiv).
- **Negative control, the one that matters:** `10.1101/gr.123456` → False, and
  `10.1101/cshperspect.a012345` → False. Same registrant, peer-reviewed journals.
- `10.48550/arXiv.2401.00001` → True (mixed case, so it pins the lowercasing).
- url `https://arxiv.org/abs/2401.00001` with no DOI → True.
- `10.1001/jamapsychiatry.2025.1317` → False; `("", "")` → False.

**The choke point:** `Paper(title="T", abstract="a", doi="10.21203/rs.3.rs-1/v1")`
comes back with `is_preprint is True` with no parser involved; a plain journal DOI
comes back False.

**Parsers**, using the fake-response pattern already in
`test_titles_arrive_without_markup` (swap `sources._get_with_retry`, restore it in
a `finally`):

- OpenAlex item with `"type": "preprint"` and an ordinary DOI → flagged (proves
  the type metadata path, not the DOI fallback).
- Europe PMC item with `"source": "PPR"` → flagged; an ordinary `"MED"` record →
  not flagged.
- arXiv: reuse the Atom sample from `test_arxiv_parsing` (~line 1344) → flagged.

**Rendering.** Build two cited papers — one preprint (Research Square DOI, blank
`venue`), one journal paper (`venue="Cochrane Database Syst Rev"`) — then:

- `render._table_html(cited, {})` contains `Preprint` in the preprint's row, and
  the journal row is unchanged.
- `render._table_markdown(cited, {})` likewise.
- `render.render_article(...)` (line 1171) output contains
  `(preprint, not peer reviewed)` exactly once.
- `render.render_markdown(...)` (line 1678) output contains it exactly once.
- Neither output attaches it to the journal paper — assert the count is 1, not
  merely that the string is present.

Check the real signatures of `render_article` / `render_markdown` before writing
the calls; the demo fixtures (`articlegen.demo.SAMPLE_ARTICLE` and friends) are the
cheapest article payload to pass in.

### 3b. Register it

Add `test_preprints_are_marked_as_preprints` to the tuple in `main()` (~line 4726),
next to `test_candidate_papers_dedupe_by_doi`. A test not in that tuple never runs.

### 3c. Run both suites

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. Judge by exit status, not by scanning output text. The
conformance fixtures build papers with `doi=f"10.1000/{i}"` and real venue names,
so none of them should start printing a preprint marker — if one does, the
detection is too loose.

---

## 4. Docs (required — CI gate)

`.github/workflows/docs-current.yml` fails a PR that touches `articlegen/**`
without touching `CLAUDE.md`. Do not edit `.github/`; just update the docs.

**`CLAUDE.md`:**

1. Add one row to the "Pinned by a test" invariant table:
   `| A preprint is labelled wherever it is listed | \`test_preprints_are_marked_as_preprints\` |`
   The test name must match the function exactly —
   `test_claude_md_still_describes_this_code` greps for it.
2. Add one bullet under **Sources and grounding** (4-6 lines, no more):
   preprints are detected from API type metadata where it exists (OpenAlex
   `type`, Europe PMC `PPR`, arXiv always) with an identifier fallback in
   `Paper.__post_init__`; `10.1101` needs a following digit because Cold Spring
   Harbor uses the same prefix for its journals; the flag is never copied across
   a `_merge_duplicate` because first-seen identity wins; and preprints are
   marked, never excluded or down-ranked.

**`docs/decisions.md`:** add a short entry under `## Grounding and provenance`
telling the story — the Research Square DOI cited beside a Cochrane review, the
blank Source cell being the only tell, why the `10.1101` prefix needed the extra
digit, and why the flag is not merged across duplicates.

Keep both edits factual. Every backticked filename, test name and ALLCAPS constant
in those two files is checked for existence by
`test_claude_md_still_describes_this_code`.

---

## 5. Files touched

| File | Change |
|---|---|
| `articlegen/sources.py` | `_PREPRINT_DOI_RES`, `_PREPRINT_URL_RE`, `_looks_like_preprint`, `Paper.is_preprint`, `__post_init__` fallback, `type` in `_OA_FIELDS`, three parser flags, two `_merge_duplicate` lines |
| `articlegen/render.py` | `_table_rows` Source cell + `preprint` key; preprint string in the HTML and Markdown reference loops |
| `tests/test_offline.py` | `test_preprints_are_marked_as_preprints` + registration in `main()` |
| `CLAUDE.md` | one invariant row, one bullet |
| `docs/decisions.md` | one entry |

Do not touch `drafts/`, `adws/`, `.github/`, `index.html`, `web.py`, `writer.py`,
`pipeline.py`.

## 6. Invariants to respect

- **Display items are built deterministically in `render.py`.** The marker is
  derived from the paper record — no model involvement, no prompt change.
- **No fabricated journal apparatus.** The marker states what the identifier
  already says. Nothing invents a journal, a version or a review status.
- **A false flag is worse than a miss** — hence the `10.1101/\d` narrowing and the
  negative controls in the test.
- The dedupe invariant (`test_candidate_papers_dedupe_by_doi`) and the title one
  (`test_titles_arrive_without_markup`) both live in the code being edited; both
  must stay green.

## 7. Commit message

```
Mark preprints in the reference list and Table 1 so a reader can tell them from peer-reviewed sources. Fixes #144
```

## 8. Git

Stay on `fix/quality-sweep-139-148`. Do not run any state-changing git command —
the workflow commits after the tests pass.

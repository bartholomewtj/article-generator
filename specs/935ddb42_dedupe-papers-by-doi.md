# Plan — Dedupe candidate papers by DOI (issue #139)

## What's wrong

Two of three recent runs cited one paper twice, as two separate references:

- `10.1001/jamapsychiatry.2025.1317` (Janik et al.)
- `10.1111/jan.16056` (N-PACT) — one copy carried JATS markup in its title.
  Markup stripping is already fixed separately (#140); this issue is the DOI.

`gather_evidence` dedupes on `_normalize_title(paper.title)` only. Any wording
difference between two sources' copies of the same record — a subtitle, a
different dash, leftover markup — produces two candidates. Each duplicate burns
a slot in the capped candidate pool (`max_papers`) and inflates the "N sources
cited" count in the masthead and Methods.

The four search parsers all carry a DOI, in different spellings:

| Source | Where | Typical form |
|---|---|---|
| Semantic Scholar | `externalIds["DOI"]` | `10.1001/JAMAPsychiatry.2025.1317` (mixed case) |
| OpenAlex | `item["doi"]` | `https://doi.org/10.1001/jamapsychiatry.2025.1317` |
| Europe PMC | `item["doi"]` | `10.1111/jan.16056` |
| arXiv | `<doi>` element | usually empty |

A DOI is a stable identifier and its prefix/suffix are case-insensitive for
lookup, so normalising the spelling gives a merge key that title text cannot.

## Files to touch

- `articlegen/sources.py` — the fix.
- `tests/test_offline.py` — new test + register it in `main()`.
- `CLAUDE.md` — one bullet + one invariant-table row (also satisfies the
  `docs-current` CI gate, which fails a PR touching `articlegen/**` that leaves
  this file alone).
- `docs/decisions.md` — the story, per the repo convention.

Do not touch `drafts/`, `adws/`, `.github/`, `render.py`, `web.py` or
`index.html`. Nothing downstream needs to change: fewer, richer candidates is
the whole visible effect.

## The one design trap — read this before writing code

The issue says "keep the record with the richer metadata". Taken literally
(swap the kept object for the richer one) that **breaks a documented
invariant**. From `CLAUDE.md`:

> arXiv is queried last and the order is load-bearing. Dedupe is
> first-seen-wins on the normalised title and a preprint usually shares its
> title with the published version, so querying it last is what keeps the
> peer-reviewed record and discards the preprint.

A preprint with a higher citation count would win a "richer record" contest and
replace the published version in the reference list. So:

**Keep first-seen identity; merge the duplicate's metadata into it field by
field.** The surviving record ends up richer than either copy, which is what
the issue actually wants, and the peer-reviewed record still wins. Say this in
a code comment — the next reader will otherwise "simplify" it back.

## Step 1 — `_normalize_doi` in `articlegen/sources.py`

Put it directly beside `_normalize_title` (around line 589), with the prefix
regex at module level next to the other compiled patterns.

```python
_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def _normalize_doi(doi: str) -> str:
    """One spelling for a DOI, so two records of one paper share a merge key.

    The four search sources spell the same DOI three ways — OpenAlex returns
    the resolver URL, Semantic Scholar returns mixed case, Europe PMC returns
    it bare — which is how one paper reached the reference list twice (#139).
    DOI prefixes and suffixes are case-insensitive for lookup, so lowercasing
    is safe.

    Anything that is not a DOI returns "" rather than itself: a junk value
    ("n/a", "unknown") repeated across two unrelated records would otherwise
    become a merge key and collapse two real papers into one.
    """
    text = _DOI_PREFIX_RE.sub("", (doi or "").strip()).strip()
    text = text.rstrip(".,;").lower()
    return text if text.startswith("10.") else ""
```

Leave `Paper.link` alone. It does its own `removeprefix` and works; changing
rendered URLs is not part of this issue.

## Step 2 — `_merge_duplicate` in `articlegen/sources.py`

Put it just above `gather_evidence`. It replaces the inline PMCID-merge block
currently at lines ~1042–1047 (that behaviour must survive — it is asserted by
`test_full_text_grounding`).

```python
def _merge_duplicate(kept: Paper, dup: Paper) -> None:
    """Fold a duplicate record's metadata into the copy already collected.

    The kept copy's *identity* is never swapped, only enriched. First-seen has
    to win: arXiv is queried last precisely so a preprint loses to the
    published version, and a preprint that happened to carry more metadata
    would otherwise take its place in the reference list.

    The abstract is filled only when the kept copy has none. `verify.py`
    checks statistics against the abstract shown to the writer, so pulling a
    different source's wording in under a record identified by the first
    source's title and venue would quietly change what a figure is checked
    against. Every parser already drops records without an abstract, so this
    branch is a guard, not a common path.
    """
    if dup.pmcid and not kept.pmcid:
        kept.pmcid, kept.is_open_access = dup.pmcid, dup.is_open_access
    if dup.abstract and not kept.abstract:
        kept.abstract = dup.abstract
    if dup.citation_count > kept.citation_count:
        kept.citation_count = dup.citation_count
    if kept.year is None and dup.year is not None:
        kept.year = dup.year
    if dup.doi and not kept.doi:
        kept.doi = dup.doi
    if dup.authors and not kept.authors:
        kept.authors = dup.authors
    if dup.venue and not kept.venue:
        kept.venue = dup.venue
    if dup.url and not kept.url:
        kept.url = dup.url
```

## Step 3 — the dedupe step in `gather_evidence`

Replace the two locals at lines ~977–978:

```python
    seen: set[str] = set()
    _first_by_title: dict[str, Paper] = {}
```

with:

```python
    by_title: dict[str, Paper] = {}
    by_doi: dict[str, Paper] = {}
```

Replace the collection loop (lines ~1034–1050) with:

```python
            for paper in results:
                # DOI first, title second. A DOI is a stable identifier; a
                # title is text, and any wording difference between two
                # sources' copies of one record used to produce two candidates
                # — two slots in the capped pool and two entries in a "N
                # sources cited" count that should have said one (#139).
                title_key = _normalize_title(paper.title)
                doi_key = _normalize_doi(paper.doi)
                if not title_key:
                    continue
                kept = by_doi.get(doi_key) if doi_key else None
                if kept is None:
                    kept = by_title.get(title_key)
                if kept is not None:
                    _merge_duplicate(kept, paper)
                    # Register the duplicate's own keys against the kept copy,
                    # so a third record matching either spelling merges too.
                    by_title.setdefault(title_key, kept)
                    if doi_key:
                        by_doi.setdefault(doi_key, kept)
                    continue
                by_title[title_key] = paper
                if doi_key:
                    by_doi[doi_key] = paper
                collected.append(paper)
```

Also update the block comment above the source tuple (lines ~994–999) — it says
"dedupe is first-seen-wins on the normalised title". Make it read "on the DOI,
falling back to the normalised title", keeping the rest of the paragraph
(arXiv last, preprint loses) exactly as it is. That sentence is still true and
still load-bearing.

**Same-title, different-DOI keeps merging by title, and that is deliberate** —
it is the preprint/published case the arXiv ordering depends on. "Distinct DOIs
never merge" means they never merge *on the DOI key*. Note it in the test.

## Step 4 — `_openalex_recency` (lines ~371–376)

Same bug, two lines up the file: the key is the raw `p.doi`. Change both to use
the normaliser.

```python
    seen = {(_normalize_doi(p.doi) or _normalize_title(p.title)) for p in papers}
    for paper in recent:
        key = _normalize_doi(paper.doi) or _normalize_title(paper.title)
```

`_normalize_doi` is defined lower in the module than `_openalex_recency`; that
is fine, the call happens at runtime. Nothing else changes here.

## Step 5 — test in `tests/test_offline.py`

Add `test_candidate_papers_dedupe_by_doi` next to
`test_titles_arrive_without_markup` (~line 1436) and register it in `main()` in
the same tuple entry (line ~4642). Copy the fake-search pattern from
`test_full_text_grounding` lines 3869–3886 — it swaps the four module-level
`search_*` functions and calls `gather_evidence(["q"], use_cache=False)` inside
a `try/finally` that restores them.

Cover all four things the issue asks for:

1. **`_normalize_doi` unit checks.** These four collapse to one string:
   `10.1001/jamapsychiatry.2025.1317`, `10.1001/JAMAPsychiatry.2025.1317`,
   `https://doi.org/10.1001/jamapsychiatry.2025.1317`,
   `doi: 10.1001/JAMAPsychiatry.2025.1317` (and a copy with surrounding
   whitespace). Plus: `""` → `""`, and junk (`"n/a"`) → `""`, with a comment
   saying why — a shared junk value must not become a merge key.

2. **Different casings/prefixes merge, keeping the richer metadata.** Fake
   OpenAlex to return the URL-form DOI on a thin record (no pmcid, 0 citations,
   `year=None`, a subtitle-bearing title) and Europe PMC to return the bare
   mixed-case DOI on a rich one (`pmcid="PMC55"`, `is_open_access=True`,
   `citation_count=12`, `year=2025`, a shorter title). Assert:
   - one record survives;
   - it kept the **first-seen** title (OpenAlex's) — this is the guard on the
     arXiv-last invariant, so say so in a comment;
   - `pmcid == "PMC55"` and `is_open_access`;
   - `citation_count == 12`; `year == 2025`.

3. **No-DOI records still dedupe by title.** Two `Paper`s, same title, both
   `doi=""` → one record out. (Belt and braces beside
   `test_full_text_grounding`, which covers the PMCID merge on that path.)

4. **Distinct DOIs never merge.** Two records, different DOIs *and* different
   titles → two records out. Then, in the same block, assert that two records
   with **different DOIs but the same title still merge**, with a comment: that
   is the preprint-versus-published case, and the whole arXiv-last ordering
   rule depends on it.

Call `sources.clear_search_cache()` before each `gather_evidence` call and use
`use_cache=False`, so a cached result from an earlier test cannot answer.

## Step 6 — docs

`CLAUDE.md`, **Sources and grounding**, a new bullet immediately after the
"Titles are stripped of publisher markup" one:

> - **Candidates are deduped by DOI first, then by title** (`_normalize_doi`,
>   `_merge_duplicate`). One paper reached the reference list twice because the
>   four sources spell a DOI three ways — resolver URL, mixed case, bare — and
>   the titles differed by a subtitle (#139). The kept copy's **identity is
>   never swapped, only enriched**: first-seen has to win, because the
>   arXiv-last ordering is what discards a preprint in favour of the published
>   version. A value that is not a DOI normalises to `""` rather than itself,
>   so a junk field shared by two unrelated records cannot merge them.

`CLAUDE.md`, invariant table, one new row:

> | One paper is one candidate, however its DOI is spelled | `test_candidate_papers_dedupe_by_doi` |

Both names must match the code exactly — `test_claude_md_still_describes_this_code`
checks that every backticked file, test and constant in `CLAUDE.md` and
`docs/decisions.md` still exists.

`docs/decisions.md`, under **Grounding and provenance**, a short entry
`### #139 — one paper, two references`: the two DOIs, that it hit two of three
runs, that the fix is a normalised-DOI key with a field-wise merge, and the one
thing worth carrying forward — a literal "keep the richer record" swap would
have let a preprint displace the published version, which is why the merge is
field-wise.

## Verify

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Judge both by exit status, not by scanning the output for words. Watch
specifically that `test_full_text_grounding`, `test_search_cache`,
`test_methods_names_only_sources_that_answered`,
`test_openalex_reaches_for_recent_work_as_well` and
`test_claude_md_still_describes_this_code` stay green — they all run through
the code being changed.

No live run is needed: this is pure logic, no model call, no new HTTP seam.

## Commit message

```
Dedupe candidate papers by DOI so one paper is cited once

Fixes #139
```

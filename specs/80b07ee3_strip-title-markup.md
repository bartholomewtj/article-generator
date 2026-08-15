# Plan — strip JATS/HTML markup from paper titles (issue #140)

## What's wrong

OpenAlex (and occasionally the others) pass the publisher's JATS markup straight
through in `title`. A real cited paper arrives as:

```
The <scp>Nurse-Police</scp> Assistance Crisis Team (<scp>N-PACT</scp>): A new role for nursing
```

Those tags reach three places that matter:

1. **Table 1 and the reference list** — the reader sees the raw tags.
2. **The writer's prompt** — the model is fed markup as if it were the title.
3. **Dedupe** — `sources._normalize_title` keeps letters and digits, so `scp`
   survives as a word. The tagged and untagged copies of one paper normalise
   differently and both get cited.

Europe PMC titles are already cleaned (`_strip_markup` at the parse site).
Semantic Scholar and OpenAlex titles are not cleaned at all; arXiv titles only
get whitespace collapsed.

## What to change

All edits are in three files: `articlegen/sources.py`, `tests/test_offline.py`,
`CLAUDE.md`. Nothing else. Do not touch `drafts/`, `adws/` or `.github/`.

### 1. `articlegen/sources.py` — new helper

Add **immediately above** the `@dataclass class Paper` block (just after the
`_OA_FIELDS` constant, around line 96), so it is defined before the class that
calls it:

```python
# Inline formatting tags the publishers' JATS leaves in a title. Named
# explicitly rather than matched as `<[^>]+>` (what `_strip_markup` does to
# abstracts): a real title like "Outcomes in adults aged <65 versus >80 years"
# contains a substring a generic tag pattern would eat whole, taking the visible
# text with it. Every tag listed here is character-level, so removing it never
# joins two words.
_TITLE_MARKUP_RE = re.compile(
    r"</?(?:scp|sc|i|b|u|em|strong|italic|bold|underline|monospace|sub|sup|span)\b[^>]*>",
    re.IGNORECASE,
)


def _strip_title_markup(title: str) -> str:
    """Remove publisher markup from a title, leaving the visible text intact.

    OpenAlex returns JATS tags inline ("The <scp>N-PACT</scp> team"), which
    reached Table 1, the reference list and the writer's prompt verbatim — and
    defeated dedupe, because `_normalize_title` kept "scp" as a word and the
    tagged and untagged copies of one paper no longer matched (issue #140).

    The tag goes without a replacement space, then whitespace is collapsed and
    the gaps the tags leave beside brackets and punctuation are closed, so
    "( N-PACT ):" reads "(N-PACT):" whichever way the publisher spaced it.
    """
    text = _TITLE_MARKUP_RE.sub("", title)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]:;,.])", r"\1", text)
    return text
```

`re` is already imported at module top — do not add an import.

### 2. `articlegen/sources.py` — apply it at the one choke point

Every paper from every scholarly API is built through `Paper(...)`, and
`Paper` is a plain (non-frozen) dataclass, so `__post_init__` is the single
choke point the issue asks for. Add it to the class, directly after the field
list and before the `author_line` property:

```python
    def __post_init__(self) -> None:
        # The one place a title is cleaned. Four search functions build Papers
        # and a fifth would be added without remembering to call this, so the
        # cleaning belongs to the object rather than to each parse site.
        self.title = _strip_title_markup(self.title)
```

Do **not** change the four parse sites, and in particular **leave
`title=_strip_markup(item.get("title") or "")` alone in `search_europe_pmc`**
(around line 409). Europe PMC titles carry general HTML, not just the inline
tags listed above, so that call still does work the new pass does not; the new
pass runs after it and is idempotent.

### 3. `tests/test_offline.py` — new test

Add `test_titles_arrive_without_markup` next to `test_europe_pmc_parsing` /
`test_arxiv_parsing`, and register it in the tuple inside `main()` beside
`test_arxiv_parsing` (around line 4571) — a test that is defined but not
registered never runs.

The test must cover:

```python
def test_titles_arrive_without_markup() -> None:
    """Publisher markup never reaches a Paper title (issue #140).

    OpenAlex passes JATS through, so a real cited title arrived as
    "The <scp>Nurse-Police</scp> ... (<scp>N-PACT</scp>): ...". The tags reached
    Table 1, the reference list and the writer's prompt, and they defeated
    dedupe: `_normalize_title` keeps "scp" as a word, so the tagged and untagged
    copies of one paper were cited as two references.
    """
    from articlegen.sources import Paper, _normalize_title, _strip_title_markup
    from articlegen import sources

    clean = "The Nurse-Police Assistance Crisis Team (N-PACT): A new role for nursing"

    # Both spacings the publisher may send: tags tight against the bracket, and
    # tags with the space the markup itself introduced.
    tight = ("The <scp>Nurse-Police</scp> Assistance Crisis Team "
             "(<scp>N-PACT</scp>): A new role for nursing")
    spaced = ("The <scp>Nurse-Police</scp> Assistance Crisis Team "
              "( <scp>N-PACT</scp> ): A new role for nursing")
    check("tags removed and spacing normalised", _strip_title_markup(tight) == clean)
    check("and the spaces the tags left are closed too",
          _strip_title_markup(spaced) == clean)

    # Case and attributes.
    check("uppercase tags go too", _strip_title_markup("A <SCP>MDMA</SCP> trial")
          == "A MDMA trial")
    check("attributes do not save a tag",
          _strip_title_markup('Effects of <i class="genus">Lactobacillus</i> on IBS')
          == "Effects of Lactobacillus on IBS")
    check("sub/sup go too",
          _strip_title_markup("Serum 25(OH)D<sub>3</sub> and CO<sub>2</sub>")
          == "Serum 25(OH)D3 and CO2")

    # Negative control: comparison operators are not markup. A generic
    # `<[^>]+>` sweep eats "<65 versus >" and the title loses its meaning.
    operators = "Outcomes in adults aged <65 versus >80 years"
    check("comparison operators survive", _strip_title_markup(operators) == operators)

    # The choke point: every Paper, whichever API built it.
    check("Paper cleans its own title", Paper(title=tight, abstract="a").title == clean)

    # Which is what restores dedupe.
    check("tagged and untagged copies now dedupe together",
          _normalize_title(Paper(title=tight, abstract="a").title)
          == _normalize_title(Paper(title=clean, abstract="a").title))

    # And through a real OpenAlex parse, since that is where it came from.
    payload = {"results": [{
        "id": "https://openalex.org/W1", "title": tight,
        "publication_year": 2024, "cited_by_count": 3,
        "abstract_inverted_index": {"An": [0], "abstract.": [1]},
        "authorships": [{"author": {"display_name": "Ann Ab"}}],
        "primary_location": {"source": {"display_name": "J Psychiatr Nurs"},
                             "landing_page_url": "https://example.org/1"},
        "doi": "10.1000/npact",
    }]}

    class FakeResp:
        def json(self):
            return payload

    real = sources._get_with_retry
    try:
        sources._get_with_retry = lambda url, params, headers: FakeResp()
        papers = sources._openalex_page("nurse police", limit=1)
    finally:
        sources._get_with_retry = real
    check("an OpenAlex record parses with a clean title", papers[0].title == clean)
```

Use the suite's existing `check(...)` helper (module-level, already imported in
that file) — do not use `assert`.

### 4. `CLAUDE.md`

The docs-current CI gate fails a PR touching `articlegen/**` that leaves this
file alone, and `test_claude_md_still_describes_this_code` checks that every
backticked test name, file and CONSTANT it mentions really exists. Two edits:

- In the invariants table, add a row:
  `| Titles carry no publisher markup | `test_titles_arrive_without_markup` |`
- In the **Sources and grounding** section, add a bullet:

  > **Titles are stripped of publisher markup in `Paper.__post_init__`** — the
  > one choke point, so a fifth search source gets it for free. OpenAlex passes
  > JATS through (`<scp>`, `<i>`, `<sub>`…), which printed raw in Table 1 and
  > the reference list and defeated dedupe, since `_normalize_title` kept `scp`
  > as a word and cited one paper twice (#140). `_TITLE_MARKUP_RE` lists the
  > tags by name instead of sweeping `<[^>]+>` like `_strip_markup` does to
  > abstracts: a title reading "adults aged <65 versus >80" would otherwise
  > lose the middle of itself. Europe PMC titles keep their `_strip_markup`
  > call as well — that one catches general HTML the named list does not.

Keep the backticks exactly as written; the guard test parses them.

## Verify

Both must be run, and both are judged by exit status:

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Expect `ALL PASS` and exit 0 from each. If `test_europe_pmc_parsing` or
`test_arxiv_parsing` moves, the new pass changed a title it should not have —
fix the tag list, not the test.

No network, no keys, no live run needed: this is pure parse-time logic.

## Out of scope

- Do not clean abstracts differently — `_strip_markup` and `_collapse` stay as
  they are.
- Do not touch author names, venues or `_normalize_title` itself.
- No renames, no refactors of the four parse sites.

## Commit message

```
Strip publisher markup tags from paper titles at parse time so references, Table 1 and dedupe see the plain text. Fixes #140
```

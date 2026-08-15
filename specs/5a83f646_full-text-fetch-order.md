# Plan — issue #143: full-text fetch order should favour direct + recent

## What's wrong

The full-text fetch loop walks `papers` in **rank order** and takes the first
five that are labelled `direct` or `related` and happen to be open access.
Rank order is `topic overlap → citation_weight + recency`, so the citation term
pulls old, heavily-cited papers to the top. On a real run the read subset came
out at median year 2019 / 122 citations while the abstract-only rest sat at
median 2023 — the five deep reads went to older work, and the newest directly
relevant syntheses got the standing "abstract-only, could not be appraised"
limitation printed about them.

The fix is ordering only: pick the same eligible set, attempt it in a better
order. No constant changes, no new fetches.

## Where the code is

The loop is **`articlegen/pipeline.py`**, lines ~366–418 inside
`generate_draft()`. It is not in `sources.py` — the issue text says
`sources.py`, and that is where the new **ordering helper** goes (it sits with
`FULLTEXT_PER_PAPER_CHARS` / `full_text_excerpts` / `fetch_full_text`, the rest
of the full-text machinery), but the loop that consumes it stays in
`pipeline.py`. Do not move the loop.

Facts worth having before you start:

- `curation["relevance"]` is `dict[int, str]`, **1-based** paper index →
  `"direct"` / `"related"` / `"tangential"` (`writer.curate_sources`, ~line 630).
  Unlabelled papers are simply absent from the dict.
- `Paper.year` is `int | None`.
- `fetched` (the list of 1-based indices) becomes
  `provenance["full_text_sources"]`, `pipeline.py` line 451.
- `sources.full_text_excerpts` iterates papers in **rank** order, not fetch
  order, so this change does not touch the excerpt budget. `FULLTEXT_TARGET`
  (5) × `FULLTEXT_PER_PAPER_CHARS` (12,000) = `FULLTEXT_TOTAL_CHARS` exactly.

## Change 1 — `articlegen/sources.py`: add the ordering helper

Put it directly **after `full_text_excerpts`** (i.e. after line ~932, before
`fetch_full_text`), so the three full-text functions stay together.

```python
# Which eligible sources get a deep read, and in what order. The set is the
# same as it always was (direct and related, never tangential); only the order
# changed. Rank order put citation weight ahead of everything, so the five deep
# reads went to old, heavily-cited papers: one measured run read a subset with
# median year 2019 and 122 citations while the abstract-only rest ran at median
# 2023 (#143). The article then prints "abstract-only, could not be appraised"
# about the most current directly-relevant work — the papers doing the most.
FULLTEXT_RELEVANCE_ORDER = ("direct", "related")


def full_text_order(papers: list[Paper], relevance: dict[int, str]) -> list[int]:
    """1-based indices to attempt full text for, best candidate first.

    Direct before related; newest first inside a tier; search rank breaks the
    remaining ties, which is the order the whole pipeline used before. A paper
    with no year sorts as if year 0 — an undated record is not evidence of
    being current. Tangential and unlabelled sources are absent from the
    result: they are never fetched, whether or not the target is met.
    """
    tier = {label: n for n, label in enumerate(FULLTEXT_RELEVANCE_ORDER)}
    ranked = []
    for index, paper in enumerate(papers, start=1):
        label = relevance.get(index)
        if label in tier:
            ranked.append((tier[label], -(paper.year or 0), index))
    return [index for _, _, index in sorted(ranked)]
```

That's the whole of change 1. Pure function, no I/O, no network.

## Change 2 — `articlegen/pipeline.py`: consume it

1. Extend the existing import on line 24:

   ```python
   from .sources import (DATABASE_NAMES, Paper, fetch_full_text, full_text_order,
                         gather_evidence, resolve_pmcid)
   ```

2. Replace the loop header at line 382 and drop the label test that the helper
   now owns. Current:

   ```python
   for index, paper in enumerate(papers, start=1):
       if len(fetched) >= FULLTEXT_TARGET:
           ...
       if requests_spent >= MAX_FULLTEXT_REQUESTS:
           ...
       if relevance.get(index) not in ("direct", "related"):
           continue
       eligible += 1
   ```

   New:

   ```python
   for index in full_text_order(papers, relevance):
       paper = papers[index - 1]
       if len(fetched) >= FULLTEXT_TARGET:
           ...
       if requests_spent >= MAX_FULLTEXT_REQUESTS:
           ...
       eligible += 1
   ```

   Keep both `break`s, `eligible`, `no_open_access`, `fetch_failed`, `stopped`
   and every `log(...)` call byte-identical. `eligible` must keep counting only
   the sources actually reached before a break, which it does if you leave
   `eligible += 1` at the top of the body.

3. Update the comment block above the loop (lines ~351–352 and ~370–373). Two
   places currently say "in rank order"; both are now wrong. Say direct before
   related, newest first within a tier, and keep the existing sentence about
   tangential sources being excluded even when the target goes unmet.

4. Line 451: store `sorted(fetched)` rather than `fetched`.

   ```python
   "full_text_sources": sorted(fetched),
   ```

   Fetch order is now relevance order, but `full_text_sources` is read as a set
   of source numbers (`render._full_text_count`, Methods, Table 1's Read
   column), and an ascending list is what every existing test and every draft
   on disk shows. Sorting keeps the provenance record stable while the fetch
   order changes underneath it.

## Change 3 — tests

### 3a. New test in `tests/test_offline.py`

Add `test_full_text_order_favours_direct_and_recent` immediately **after**
`test_pipeline_fetches_full_text` (~line 4334). Pure logic, no monkeypatching
needed — call the helper directly.

```python
def test_full_text_order_favours_direct_and_recent() -> None:
    """Deep reads go to the directly relevant and the current, in that order.

    Rank order sorts on topic overlap then citation weight, so the five full
    texts landed on old, heavily-cited papers: one measured run read a subset
    at median year 2019 / 122 citations against an abstract-only rest at median
    2023, and the article then printed the "could not be appraised" limitation
    about the newest directly-relevant syntheses (#143). Relevance tier first,
    then year, then search rank.
    """
    from articlegen.sources import Paper, full_text_order

    papers = [
        Paper(title="related new", abstract="a", year=2024),      # 1
        Paper(title="direct old", abstract="a", year=2011),       # 2
        Paper(title="tangential new", abstract="a", year=2025),   # 3
        Paper(title="direct new", abstract="a", year=2023),       # 4
        Paper(title="related old", abstract="a", year=2015),      # 5
        Paper(title="unlabelled", abstract="a", year=2026),       # 6
        Paper(title="direct undated", abstract="a"),              # 7
    ]
    relevance = {1: "related", 2: "direct", 3: "tangential",
                 4: "direct", 5: "related"}

    order = full_text_order(papers, relevance)
    check("direct-newest, direct-older, then related-newest",
          order == [4, 2, 7, 1, 5])
    check("tangential sources are never offered for fetch", 3 not in order)
    check("an unlabelled source is never offered either", 6 not in order)

    # Ties fall back to search rank, which is what the pipeline did before this
    # change — so an all-one-tier, all-one-year pool is untouched by it.
    same = [Paper(title=f"p{i}", abstract="a", year=2020) for i in range(1, 5)]
    check("equal tier and year keeps the incoming rank order",
          full_text_order(same, {i: "direct" for i in range(1, 5)}) == [1, 2, 3, 4])
    check("no labels means nothing is fetched",
          full_text_order(same, {}) == [])
```

Note the expected order: `4` (direct 2023), `2` (direct 2011), `7` (direct,
undated → sorts last in its tier), then `1` (related 2024), `5` (related 2015).

### 3b. Fix the one existing assertion the reorder moves

`test_pipeline_fetches_full_text`, line 4315. Its papers carry no year, and
relevance is `{1: direct, 2: tangential, 3: related, 4: direct}`, so the fetch
order becomes 1, 4, 3 (direct tier first, ties by rank):

```python
        check("direct sources are fetched before related, tangential never",
              fetched_pmcids == ["PMC1", "PMC4", "PMC3"])
```

Leave line 4318 alone — `full_text_sources == [1, 3, 4]` still holds because
provenance is now sorted.

Everything else stays green as-is. Check the reasoning rather than assuming:

- Line 4430 (`full_text_sources == [1, 2, 3, 4, 5]`): ten papers, all `direct`,
  all `year=None` → every sort key ties → stable sort preserves rank order.
- Line 4431 (`len(resolved) == 5`) and 4447: unchanged, same set of candidates.
- `tests/test_journal_conformance.py` line 315 passes a literal provenance and
  never runs the loop.

## Change 4 — docs

### `CLAUDE.md`

Required by `.github/workflows/docs-current.yml` (a PR touching `articlegen/**`
must touch this file) and by `test_claude_md_still_describes_this_code`, which
checks that every backticked file, `test_*` name and SHOUTY constant in
CLAUDE.md and `docs/decisions.md` actually exists. Everything you add below
does exist after the change, so both stay green.

1. Add one row to the "Pinned by a test" table in **Invariants**, next to the
   other full-text rows:

   | Deep reads go to direct and recent sources first | `test_full_text_order_favours_direct_and_recent` |

2. In **Sources and grounding**, amend the `FULLTEXT_TARGET` bullet (the one
   ending "**Tangential sources are never fetched**, even when the target goes
   unmet"). Add, in that bullet or as the next one:

   > **The fetch order is relevance then recency, not rank** (`full_text_order`).
   > Rank sorts on topic overlap then citation weight, so the five deep reads
   > went to old, heavily-cited work — a measured run read median year 2019 /
   > 122 citations against an abstract-only rest at median 2023, and the article
   > printed "abstract-only, could not be appraised" about the most current
   > directly-relevant syntheses (#143). Direct before related, newest first
   > inside a tier, search rank breaking ties. The eligible *set* is unchanged;
   > tangential and unlabelled sources are still never fetched.

3. Leave the read-subset skew bullet as it is — that line still describes what
   the log does, and it is now the measurement that tells you whether this
   worked.

### `docs/decisions.md`

Add a `### #143 — the deep reads went to the oldest papers` entry at the end of
the **Grounding and provenance** section (before `## Web app and deployment`,
~line 380). Keep it to the numbers and the reasoning: the measured skew line,
why rank order caused it (citation weight inside `_rank_score`), why the fix is
ordering rather than raising `FULLTEXT_TARGET` (the excerpt budget is already
exactly full at 5 × 12,000), and what to watch next (the skew line on the next
few real runs — if the read subset now runs *newer* than the abstract-only rest
that is the change working, not a new problem).

## Verify

Both suites, from the repo root. Judge by exit status.

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

No live run is needed: this touches no model id, no ceiling, no routing, and no
network call inside `sources.py`.

## Do not

- Do not change `FULLTEXT_TARGET` or `MAX_FULLTEXT_REQUESTS`.
- Do not change `_rank_score`, `gather_evidence`'s source order, or anything in
  the ranking pipeline — arXiv-last and first-seen-wins dedupe are load-bearing
  and unrelated.
- Do not fetch tangential or unlabelled sources, ever, even if the target goes
  unmet.
- Do not change the wording of any `log(...)` line in the fetch block, the
  exit-reason tallies, or `_read_subset_skew`.
- Do not touch `drafts/`, `adws/` or `.github/`.
- Do not run any state-changing git command.

## Commit message

```
Fetch full texts for directly relevant and recent sources first, so the deep reads stop landing on old highly-cited papers. Fixes #143
```

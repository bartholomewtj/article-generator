# Plan — full text via the `papers` CLI (paperfetch)

Closes #150 and #151 without writing a PDF parser in this repo.

## What this does

Today full text only ever comes from Europe PMC, via a PMCID. PMC is
biomedical, so every non-biomedical draft — and everything arXiv brings in —
is written from abstracts alone.

The `papers` console script (the separate private `paperfetch` project) already
runs a resolver ladder — cache → Europe PMC → Unpaywall → OpenAlex → Semantic
Scholar → preprint shortcuts → CKN queue — downloads the open-access PDF, and
extracts plain text to a file. articlegen shells out to it, reads that file,
and falls back to today's Europe PMC path when `papers` is absent or returns
nothing.

`papers` is optional. With it missing, behaviour is byte-for-byte what it is
today. The hosted Render backend does not have it and this change does not try
to give it one.

## Facts established while planning (do not re-derive)

`papers get <doi-or-title>` prints **one JSON object on stdout**. stderr may
carry a `resolved title -> {doi}` line. Exit codes: `0` for `status: "ok"`,
`1` for `no_doi` (and for a usage error such as `PAPERS_MAILTO` unset, which
prints a message to stderr and **no JSON**), `2` for `queued_ckn`,
`unreadable_pdf`, `retry`.

The `ok` record (from `papers/cli.py::_ok_record`):

```json
{"status": "ok", "doi": "...", "title": "...", "resolver": "unpaywall",
 "version": "...", "license": "...", "read": "C:\\Users\\...\\text.txt",
 "max_chars": 12000, "text_chars": 41234,
 "agent_next": "read_text; cite_doi_and_version; do_not_attach_pdf"}
```

`read` is an absolute path to a UTF-8 text file. `papers` requires
`PAPERS_MAILTO`; without it every call fails with exit 1 and no JSON.

The console script was **not** on PATH in this environment, but
`python -m papers` worked — which is exactly what `ARTICLEGEN_PAPERS_CMD`
is for.

## Files to touch

1. `articlegen/paperfetch.py` — new
2. `articlegen/sources.py` — `fetch_full_text`, one small extraction
3. `articlegen/pipeline.py` — the full-text loop and its log lines
4. `articlegen/render.py` — one Methods clause (see step 4; small, and required)
5. `tests/test_offline.py` — new test plus two one-line edits to existing tests
6. `README.md` — one short section
7. `CLAUDE.md` — module list, invariants, a line in Sources and grounding

---

## Step 1 — `articlegen/paperfetch.py` (new)

A thin, never-raising wrapper. Nothing in it may import the `papers` package,
touch the CKN queue, or write to `os.environ`.

```python
"""Full text via the `papers` CLI (the separate paperfetch project).

Optional. When `papers` is not installed, `available()` is False and the
pipeline behaves exactly as it did before this module existed.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess

# Resolved once per process. shutil.which is a PATH walk and the pipeline asks
# per paper.  None means "not looked yet".
_AVAILABLE: bool | None = None
_ARGV: list[str] = []
# The "not installed" line is worth saying once per process, not per paper.
_WARNED = False

DEFAULT_TIMEOUT = 120.0
```

**`_command() -> list[str]`**
`ARTICLEGEN_PAPERS_CMD`, split with `shlex.split(..., posix=False)` if set and
non-empty, else `[shutil.which("papers")]` when that is truthy, else `[]`.
Use `posix=False` so a Windows path with backslashes survives the split
(`shlex.split(r"C:\x\papers.exe get")` under posix mode eats the backslashes).
Cache the result in `_ARGV`.

**`available(log=None) -> bool`**
Returns `_AVAILABLE`, computing it once: True when `_command()` is non-empty
and — for the `ARTICLEGEN_PAPERS_CMD` case — no further checking (the operator
said what to run; a wrong value fails soft at the first call). On the first
False, if `log` is callable and `_WARNED` is False, emit exactly:

```
  papers CLI not installed; full text limited to Europe PMC
```

then set `_WARNED = True`.

**`fetch_via_papers(doi: str, timeout: float = DEFAULT_TIMEOUT, log=None) -> str`**

1. `doi` empty or `available()` False → `""`.
2. Build `argv = _command() + ["get", doi]`. Never a shell string, never
   `shell=True` — a DOI is attacker-influenced data (it comes from a scholarly
   API response) and must not reach a shell.
3. Environment: `env = dict(os.environ)`, then
   `env.setdefault("PAPERS_MAILTO", os.environ.get("OPENALEX_MAILTO") or os.environ.get("UNPAYWALL_EMAIL") or "")`
   and **drop the key if it is empty** (`if not env.get("PAPERS_MAILTO"): env.pop("PAPERS_MAILTO", None)`),
   so `papers` gives its own "set PAPERS_MAILTO" error rather than being handed
   a blank. Build a **copy**; never assign into `os.environ` — the key-leak
   guard is behavioural and this module inherits the same rule.
4. `subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
   timeout=timeout, env=env)` wrapped in
   `except (subprocess.TimeoutExpired, OSError, ValueError)` → log one line and
   return `""`. (`OSError` covers a bad `ARTICLEGEN_PAPERS_CMD` path.)
5. Parse `json.loads(proc.stdout)` — parse regardless of exit code, because a
   `queued_ckn` record arrives with exit 2. `json.JSONDecodeError` or a
   non-dict → log one line with the first ~200 chars of stdout/stderr and
   return `""`.
6. `record.get("status") != "ok"` → log `papers: <status> for <doi>` and
   return `""`. Every non-`ok` status (`queued_ckn`, `no_doi`,
   `unreadable_pdf`, `retry`) takes this branch; the caller then runs the
   Europe PMC path.
7. `path = record.get("read")`. Falsy, or the file is missing/unreadable →
   `""` (catch `OSError`). Read it with
   `open(path, encoding="utf-8", errors="ignore")`.
8. Return the text **unchanged and untruncated**. `sources.full_text_excerpts`
   owns truncation (12,000 chars per paper inside a 60,000 total) and it must
   stay the single place that decides.

**Nothing in this module raises into the pipeline.** Wrap the whole body so an
unexpected exception type still returns `""`; a full-text helper that can kill
a draft is worse than one that returns nothing.

Tests reset process state by setting `paperfetch._AVAILABLE = None`,
`paperfetch._ARGV = []`, `paperfetch._WARNED = False`. Say so in a comment so
the next reader does not add a public reset function for it.

## Step 2 — `articlegen/sources.py`

**2a. Extract the citation-bracket strip.** Today the
`re.sub(r"\[\s*\d+(?:\s*[,–—-]\s*\d+)*\s*\]", "", text)` at the end of
`_parse_fulltext_xml` is the only thing that stops a paper's own `[4]` markers
colliding with our SOURCE-index citation scheme. Text from `papers` needs the
same treatment. Lift the regex to a module constant and add:

```python
def _strip_citation_brackets(text: str) -> str:
    """Remove the paper's own bracketed citation numbers.

    They collide with the pipeline's [N] SOURCE-index scheme: a writer reading
    "improves outcomes [ 4 ]" may echo that number as if it were one of ours.
    Every full-text path runs through this, whichever fetcher produced it.
    """
```

Call it from `_parse_fulltext_xml` (unchanged behaviour) and from the new
`papers` branch below.

**2b. `fetch_full_text(paper, use_cache=True, log=lambda msg: None)`** — add the
`log` parameter (default keeps every existing caller working) and try `papers`
first:

```
doi = _normalize_doi(paper.doi)          # "" for junk values, already exists
if doi and paperfetch.available(log):
    key = f"papers:{doi}"
    cache hit on key and not expired -> return it (set paper.full_text_via if non-empty)
    text = _strip_citation_brackets(paperfetch.fetch_via_papers(doi, log=log))
    cache under key with _CACHE_TTL when text else _CACHE_FAILURE_TTL
    if text:
        paper.full_text_via = "papers"
        return text
# fall through, unchanged:
if not (paper.pmcid and paper.is_open_access): return ""
... existing Europe PMC fetch ...
if text: paper.full_text_via = "europe_pmc"
```

Notes that matter:

- The cache key is `papers:` + the **normalised** DOI, so the four spellings of
  one DOI share a slot and no DOI key can collide with a `PMC…` key.
- `_fulltext_cache` is already cleared by `clear_search_cache()`; nothing new
  to wire.
- Import as `from . import paperfetch` at module top — no circular import
  (`paperfetch` imports nothing from articlegen).
- `resolve_pmcid`, `_parse_fulltext_xml`, `full_text_excerpts`,
  `full_text_order`, ranking and the writer/verify excerpt contract are
  **unchanged**.

**2c. `Paper` gains one field**: `full_text_via: str = ""` beside `full_text`,
with a comment saying it records which fetcher produced the text and exists so
the pipeline log and the Methods sentence do not have to guess. Do not touch
`_merge_duplicate` for it — it is set after dedupe, never by search.

## Step 3 — `articlegen/pipeline.py`

In the full-text loop only. `papers` resolves a DOI on its own, so a paper with
a DOI is a candidate even with no PMCID and no `is_open_access` flag.

```python
via_papers = paperfetch.available(log)      # once, before the loop
...
for index in full_text_order(papers, relevance):
    ...target / cap checks unchanged...
    eligible += 1
    if via_papers and _normalize_doi-able doi:
        pass                      # papers will resolve it; no resolve_pmcid call
    elif not paper.pmcid and paper.doi:
        requests_spent += 1
        resolve_pmcid(paper, log=log)
    if not (via_papers and paper.doi) and not (paper.pmcid and paper.is_open_access):
        no_open_access += 1
        continue
    requests_spent += 1
    text = fetch_full_text(paper, log=log)
    ...
```

Express the gate however reads cleanest, but these four properties are the
requirement:

- A paper with a DOI is fetched when `papers` is available, whatever its
  `pmcid` / `is_open_access` say.
- When `papers` is not available, the loop is exactly today's: `resolve_pmcid`
  then the PMCID gate.
- `resolve_pmcid` is still called for a paper with a DOI but no PMCID **only
  when `papers` is unavailable** — with `papers` present it is redundant work
  against a shared quota.
- A DOI-less paper still goes down today's path (PMCID gate, no fetch without
  one), whether or not `papers` is available.

Every attempt still costs one `requests_spent`, so `MAX_FULLTEXT_REQUESTS`
(18) and `FULLTEXT_TARGET` (5) keep their meaning, and `no_open_access` /
`fetch_failed` / `stopped because` keep theirs: a paper `papers` could not
resolve returns `""` from `fetch_full_text` and lands in `fetch_failed`.

Import `from . import paperfetch` and add `paperfetch` to the module's imports
alongside `fetch_full_text`. Tests monkeypatch `pipeline.fetch_full_text`, so
keep it a module-level name — do **not** switch to `sources.fetch_full_text(...)`.

**Log line.** Count `sum(1 for i in fetched if papers[i-1].full_text_via == "papers")`
and the Europe PMC remainder, and append a breakdown only when both are
non-zero or when any came via `papers`:

```
  full text retrieved for 4 source(s): [1, 3, 4, 7] in 6 request(s) (3 via papers, 1 via Europe PMC)
```

Keep the existing prefix character-for-character up to `request(s)` —
`test_full_text_run_says_why_it_stopped` and the CLI both read these lines.

**Provenance.** Add `"full_text_via": {"papers": n, "europe_pmc": m}` to the
`provenance` dict next to `full_text_sources`. Derived from the papers that
were actually read; never a constant.

## Step 4 — `articlegen/render.py` (one clause, required)

`render.py` line ~838 hardcodes `"retrieved from Europe PMC"` in Methods. Once
text can come from Unpaywall, OpenAlex, Semantic Scholar or a preprint server
via `papers`, that sentence is a false provenance claim — the exact failure
mode #75 was about, and CLAUDE.md's "every provenance statement is derived,
never hardcoded" invariant.

Minimal, honest fix:

```python
via = (provenance.get("full_text_via") or {})
retrieved_from = ("retrieved from Europe PMC" if not via.get("papers")
                  else "retrieved from their open-access copies")
```

and interpolate `retrieved_from` in place of the literal. When every full text
came from Europe PMC the sentence is unchanged, so the fixtures and
`test_journal_conformance.py` keep passing — that suite asserts on
`"read alongside them"`, which stays. Make no other render change: do not name
Unpaywall, OpenAlex or `papers` in the article. A weaker true claim beats a
specific false one, and we do not record which rung of the ladder answered.

## Step 5 — `tests/test_offline.py`

All mocked. No network, no `papers` binary required, and the suite must pass on
a machine that has never heard of paperfetch.

New test `test_full_text_comes_from_the_papers_cli_when_it_is_there`, added to
the `main()` tuple next to `test_pipeline_fetches_full_text`. Use a fake
`subprocess.run` swapped onto `paperfetch.subprocess` (a small object with
`.run`, `.TimeoutExpired` = the real class) or monkeypatch
`paperfetch.subprocess.run` directly and restore it in a `finally`. Reset
`_AVAILABLE`/`_ARGV`/`_WARNED` and call `sources.clear_search_cache()` between
cases.

Cases — each is a `check(...)`:

1. **`ok` → text returned.** Fake `run` returns an `ok` JSON record whose
   `read` points at a real temp file containing `Body text with 441
   participants [3].` Assert the text comes back and that `[3]` was stripped
   (the shared bracket rule), and `paper.full_text_via == "papers"`.
2. **Cached by DOI.** A second `fetch_full_text` for a paper carrying the same
   DOI spelled as `https://doi.org/10.X/Y` runs the subprocess **once**.
3. **Every non-ok status falls through.** `queued_ckn` (exit 2), `no_doi`
   (exit 1), exit 1 with empty stdout, `subprocess.TimeoutExpired` raised,
   stdout `"not json"`, and an `ok` record whose `read` path does not exist.
   Each returns `""` from `fetch_via_papers`, and with a PMCID paper the
   Europe PMC branch still runs and produces its text (fake `_get_with_retry`,
   as `test_full_text_grounding` already does).
4. **Not on PATH → today's behaviour.** With `_command()` forced empty,
   `available()` is False, `subprocess.run` is never called, and
   `fetch_full_text` behaves exactly as before.
5. **`ARTICLEGEN_PAPERS_CMD="python -m papers"`** produces
   `["python", "-m", "papers", "get", "<doi>"]` as the argv the fake `run`
   received. Also assert argv is a **list**, never a string, and that
   `shell=True` is absent from the kwargs.
6. **Pipeline loop.** With `paperfetch.available` faked True, a paper with a
   DOI and **no** pmcid is passed to `fetch_full_text`; with it faked False,
   the same paper is skipped and counted in `no_open_access`. Assert the log
   contains `via papers` in the first case.
7. **No env leak.** Snapshot `dict(os.environ)` around a `fetch_via_papers`
   call and assert it is unchanged, and that the `env` kwarg the fake `run`
   received carries `PAPERS_MAILTO` derived from `OPENALEX_MAILTO`.

Two one-line edits to existing tests:

- `test_claude_md_still_describes_this_code`: add `paperfetch` to the
  `from articlegen import ...` line and to the `modules` tuple, so a constant
  named in CLAUDE.md that lives in the new module resolves.
- `test_per_request_api_key`: add `paperfetch` to its `modules` tuple, so the
  "never writes into os.environ" sweep covers the one new module that builds a
  subprocess environment.

Existing full-text tests must pass **unmodified** — that is the proof that a
machine without `papers` is unaffected. If one needs changing, `available()`
is leaking; fix the code, not the test.

## Step 6 — `README.md`

One short subsection under **Notes & limitations** (or directly after
**Install**), plain language:

- What it does: with the `papers` CLI installed, full text comes from any
  open-access copy, not just Europe PMC — so non-biomedical topics and arXiv
  papers stop being abstract-only.
- Install: `pip install -e` the paperfetch repo (private, separate), then set
  `PAPERS_MAILTO` to a real email address. Unpaywall, OpenAlex and Crossref
  require it and block made-up addresses.
- If `papers` is not on PATH, set `ARTICLEGEN_PAPERS_CMD="python -m papers"`.
- Optional: without it, everything works exactly as before, from Europe PMC
  only.
- The hosted backend on Render **does not have it** — paperfetch is private and
  not pip-installable from there yet, so the web app is still Europe PMC only.

Also update the two existing lines that state full text comes from Europe PMC
(README lines ~153 and ~241) so they say "when an open-access copy can be
retrieved" rather than naming Europe PMC as the only route.

## Step 7 — `CLAUDE.md`

Required — `.github/workflows/docs-current.yml` fails a PR that touches
`articlegen/**` without touching this file.

- Architecture block: add
  `paperfetch.py  optional: full text via the separate papers CLI (paperfetch)`.
- **Sources and grounding**, a new bullet: full text has two routes; `papers`
  first when it is installed and the paper has a DOI, Europe PMC by PMCID
  otherwise; `papers` is optional and absent on the hosted backend; the paper's
  own `[N]` brackets are stripped on **both** routes because they collide with
  the SOURCE-index scheme; `PAPERS_MAILTO` is required by `papers` and defaults
  from `OPENALEX_MAILTO`.
- Invariants table: one row —
  `Full text via the papers CLI never breaks the Europe PMC path` →
  `test_full_text_comes_from_the_papers_cli_when_it_is_there`.
- The "never fetch paywalled full text" line stays and still holds: `papers`
  fetches open access only and queues everything else for CKN, which this
  integration never touches.
- Setup/testing: mention `ARTICLEGEN_PAPERS_CMD`.

Any backticked constant added here must exist in a swept module — that is why
step 5 adds `paperfetch` to the sweep.

## Verify

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. Judge them by exit status, not by grepping the output for
the word "fail" — the suites print `FAIL ` prefixes as data.

Optional, only if `papers` is installed locally and `PAPERS_MAILTO` is set:

```
articlegen draft "machine learning emergency department triage" --model cli:opus
```

and confirm the log prints `via papers` and the article's Methods says full
texts were read. Costs real API credit — not required to call this done.

## Out of scope

Importing the `papers` package, vendoring paperfetch, any PDF parsing in
articlegen, the CKN queue, `Dockerfile` / `render.yaml`, excerpt sizes,
ranking, `full_text_order`, new pip dependencies.

## Known trade-offs, flagged not fixed

- **Wall clock.** `papers` downloads and parses a PDF. At the 120s default and
  `MAX_FULLTEXT_REQUESTS` = 18 the worst case is long. It is bounded, and every
  attempt still costs one request, so no new unbounded loop exists — but a
  local draft on a topic with poor open-access coverage will feel slower than
  it does today. If it becomes a problem, lower the timeout; do not raise the
  request cap.
- **Second machine, second cache.** `papers` keeps its own cache in
  `%USERPROFILE%\.paperfetch`, separate from articlegen's in-process
  `_fulltext_cache`. That is fine — one is per-process, the other survives runs.
- **No security exposure.** No key crosses this boundary, the DOI never reaches
  a shell, and `papers` fetches only open-access copies. Nothing here touches
  patient or clinical data.

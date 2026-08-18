# Open-Access Full-Text Fetch via `papers` CLI

## Summary

Previously, articlegen only retrieved open-access full text from Europe PMC via PMCIDs, leaving non-biomedical and arXiv papers abstract-only. This change integrates with the external `papers` CLI (from the `paperfetch` project) to fetch open-access full text by DOI across preprint servers and scholarly repositories (Unpaywall, OpenAlex, Semantic Scholar), while maintaining a graceful fallback to Europe PMC when `papers` is not installed or returns no text.

## Changes by File

- **`articlegen/paperfetch.py`** (new):
  - Implements `fetch_via_papers(doi, timeout, log)`: runs `papers get <doi>` via `subprocess.run` (without invoking a shell) and parses the JSON response. If `status == "ok"`, reads the UTF-8 text file specified in `read`. Returns `""` on timeouts, non-zero exits, missing files, or non-ok statuses (`queued_ckn`, `no_doi`, `unreadable_pdf`, `retry`). Never raises exceptions into the pipeline.
  - Implements `available(log)`: detects and caches whether `papers` executable or `ARTICLEGEN_PAPERS_CMD` is configured, logging a single notification if unavailable.
  - Passes inherited environment with `PAPERS_MAILTO` (falling back to `OPENALEX_MAILTO` or `UNPAYWALL_EMAIL`) without mutating `os.environ`.
  - Supports `ARTICLEGEN_PAPERS_CMD` (parsed via `shlex.split(..., posix=False)`) to configure command invocations such as `python -m papers`.

- **`articlegen/sources.py`**:
  - `fetch_full_text(paper, use_cache=True, log=...)`: tries `paperfetch.fetch_via_papers()` first when `paperfetch.available()` is true and paper has a DOI, caching under `papers:<normalized_doi>`. Falls back to Europe PMC via PMCID if `papers` is absent or returns empty text.
  - Added `full_text_via` field on `Paper` to record which fetcher provided the full text (`"papers"` or `"europe_pmc"`).
  - Extracted `_strip_citation_brackets()` from `_parse_fulltext_xml()` to strip bracketed in-text citation markers `[N]` on all full-text sources so they do not collide with articlegen's `[N]` source index scheme.

- **`articlegen/pipeline.py`**:
  - In `generate_draft()` full-text candidate loop, checks `paperfetch.available()`. When available, papers with DOIs are considered eligible without requiring `pmcid` or `is_open_access` flags ahead of time, bypassing redundant `resolve_pmcid()` calls.
  - Added `full_text_via` count dictionary to `provenance` (`{"papers": n, "europe_pmc": m}`).
  - Updated progress log to report the retrieval breakdown (e.g. `(3 via papers, 1 via Europe PMC)`).

- **`articlegen/render.py`**:
  - Updated `_methods_paragraphs()` to adapt the Methods section wording: uses `"retrieved from their open-access copies"` when any full texts were fetched via `papers`, and `"retrieved from Europe PMC"` when all came from Europe PMC.

- **`tests/test_offline.py`**:
  - Added `test_full_text_comes_from_the_papers_cli_when_it_is_there()` covering: successful retrieval and citation stripping, DOI cache deduplication, fallbacks on all non-ok statuses and errors, behavior when `papers` is not on PATH, `ARTICLEGEN_PAPERS_CMD` splitting, pipeline loop candidate filtering, and environment isolation.
  - Added `paperfetch` to module sweeps in `test_per_request_api_key()` and `test_claude_md_still_describes_this_code()`.

- **`README.md` & `CLAUDE.md`**:
  - Documented the optional `papers` CLI workflow, `PAPERS_MAILTO`, and `ARTICLEGEN_PAPERS_CMD`.
  - Added `paperfetch.py` to the architecture layout and invariant tables.
  - Noted that hosted Render backend remains Europe PMC-only.

- **`specs/e54dda88_papers-cli-full-text.md`**:
  - Added technical plan and requirements specification for the `papers` CLI full-text integration.

## How to Verify

Run the offline and journal conformance test suites:
```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```
Both suites pass with 0 exit code without network access or local `papers` installation.

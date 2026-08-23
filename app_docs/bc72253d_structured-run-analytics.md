# Structured Website Run Analytics

## Summary

Adds privacy-preserving, structured run logging to the web server endpoints (`/api/ideas`, `/api/draft`, and `/api/gallery`). Every incoming request emits exactly one JSON line (`{"kind": "run", ...}`) to `stderr` upon completion. An optional durable sink allows appending log records to a private, secret GitHub Gist (`ARTICLEGEN_ANALYTICS_GIST`) using the existing gist-scoped token (`ARTICLEGEN_GALLERY_TOKEN`).

Log lines enforce an explicit field allowlist (`RUN_FIELDS`) ensuring that no user topic, search prompt, query string, article text/HTML, API key, or visitor IP address is ever recorded.

## What Changed and Why

1. **Privacy-Preserving Run Analytics (`articlegen/web.py`)**:
   - Added `RUN_FIELDS` allowlist containing request metadata (status, timing, model, paying key mode (`visitor`, `public`, `none`), stateless flag, commit), ideas counters (`n_asked`, `n_ideas`, `guidance`), draft counters and classifications (`screened`, `cited`, `cited_direct`, `direct`, `related`, `tangential`, `full_text`, `full_text_via`, `named_added`, `named_queries`, `style_errors`, `style_rules`, `figures`, `unverified`, `misattributed`, `working_draft`), and gallery metadata (`backend`, `items`, `html_kb`).
   - Implemented `build_run_record()` and `draft_run_fields()`.
   - Instrumented `ArticleGenHandler` with `_note_run()` and `_emit_run()` hooked into `finally` blocks in `do_GET` and `do_POST`. Every request across `RUN_ENDPOINTS` (`/api/ideas`, `/api/draft`, `/api/gallery`) emits exactly one JSON line to `stderr`.

2. **Durable Secret Gist Append (`articlegen/gallery.py`)**:
   - Added `append_run(record: dict)` to append records to `articlegen-runs.jsonl` within the gist designated by `ARTICLEGEN_ANALYTICS_GIST`.
   - Uses an independent `_analytics_lock` so logging never queues behind gallery publication.
   - Synchronously reads, appends, and caps the log file at `ANALYTICS_MAX_LINES = 1000` (~400 KB) before issuing a `PATCH` request.
   - All gist writing errors are swallowed and log errors to `stderr` without failing client responses.

3. **Deployment & Configuration (`render.yaml`, `deploy/README.md`)**:
   - Added environment variable `ARTICLEGEN_ANALYTICS_GIST` to `render.yaml`.
   - Documented log structure, parsing examples (using `grep` and `jq`), and gist setup instructions in `deploy/README.md`.

4. **Project Memory & Decisions (`CLAUDE.md`, `docs/decisions.md`)**:
   - Added invariants in `CLAUDE.md` guaranteeing privacy (counts and fixed vocabulary only), one-line-per-endpoint emission, and non-blocking optional gist logging.
   - Added decision rationale in `docs/decisions.md` documenting allowlisting vs denylisting, stateless privacy considerations, synchronous free-tier sleep handling, and skipping public `/api/runs` endpoints.

5. **Tests (`tests/test_offline.py`)**:
   - `test_run_log_never_carries_the_topic`: verifies forbidden fields (topic, terms, keys, IPs, text sentinels) never appear in run records or `RUN_FIELDS`.
   - `test_every_endpoint_logs_one_run_line`: verifies all tracked endpoints emit exactly one JSON line on success and failure statuses (200, 400, 422, 500, 503).
   - `test_run_log_gist_is_optional_and_gist_scoped`: tests opt-in gist behavior, GitHub API payload format, capping at 1,000 lines, and silent failure when network errors occur.

## Files Touched

- `articlegen/web.py`
- `articlegen/gallery.py`
- `render.yaml`
- `deploy/README.md`
- `CLAUDE.md`
- `docs/decisions.md`
- `tests/test_offline.py`

## Verification

Run offline test suite:
```bash
python tests/test_offline.py
```
Run journal conformance suite:
```bash
python tests/test_journal_conformance.py
```

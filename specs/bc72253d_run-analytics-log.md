# Plan — one structured run log line per website request

## What this does

Every request to `/api/ideas`, `/api/draft` and `/api/gallery` writes **one JSON
line to stderr** saying how the run went: how long it took, which model, whose
key paid, and — for drafts — how much evidence was screened, cited, read in full
text, and how many prose/figure defects survived. Optionally the same line is
appended to a **private (secret) GitHub gist** so the history survives a Render
restart.

The point is to be able to answer "is the pipeline getting better?" without
reading logs by hand and without storing a single word of what anyone researched.

**Nothing about the content is logged.** No topic, no theme, no search terms, no
query strings, no article HTML or Markdown, no API key, no IP address. Only
counts, durations, status codes, fixed vocabulary (rule names, model ids) and
booleans.

## Constraints (read before coding)

- **Never log content.** The rule is enforced structurally: the record is built
  from an explicit allowlist of field names, anything else is dropped, and a
  test proves a payload full of topic text produces a line containing none of it.
  Note `provenance["queries"]` and `provenance["named_sources"]["queries"]` are
  *search terms* — log their **counts**, never the strings.
- **Analytics must never break a response.** All of it runs in a `finally`
  after the response has been written, wrapped in `try/except Exception`. A
  failed gist write costs one stderr note and nothing else.
- **Reuse the existing gist-scoped token.** `ARTICLEGEN_GALLERY_TOKEN` already
  exists on Render with `gist` scope only. Do not add a second token and do not
  ask for a broader scope.
- A GitHub **secret gist is unlisted, not access-controlled** — anyone with the
  URL can read it. That is acceptable *only because* no topic ever goes in it.
  Say so in the docs.
- Keys are already forbidden from `os.environ` (`test_per_request_api_key`
  sweeps `web.py` and `gallery.py`). Do not introduce any `os.environ[...] = `.

## Out of scope

Writing visitor articles to `drafts/` on the shared host; a public `/api/runs`
endpoint; Google Analytics or page-view tracking; `--long` in the web UI;
regenerating the demo Reviews in `drafts/`; committing the untracked
2026-08-22 drafts or `tools/compare_models.py`; logging topics even hashed.

---

## Files to touch

| File | Change |
|---|---|
| `articlegen/web.py` | Build and emit the run line; time every request; note fields from each handler. |
| `articlegen/gallery.py` | `append_run()` — optional private-gist sink, reusing `_github` and the gist token. |
| `tests/test_offline.py` | Three new tests (names below). |
| `deploy/README.md` | How to turn the gist on, how to read the log, the secret-gist caveat. |
| `render.yaml` | `ARTICLEGEN_ANALYTICS_GIST` with `sync: false` and a comment. |
| `CLAUDE.md` | New "Run analytics" bullets under **Web app**, invariant rows, env var in **Setup**. |
| `docs/decisions.md` | One entry under **Web app and deployment** with the reasoning. |

Do not touch `index.html`, `pipeline.py`, `render.py` (import only), or any
draft file.

---

## 1. `articlegen/web.py`

### 1a. The field allowlist

Add near the other module constants, with a comment saying why it is an
allowlist and not a denylist (a denylist grows a hole the first time a new field
is added):

```python
# Every key a run line may carry. The record is built by filtering against this
# set, so a field nobody thought about cannot reach the log. Nothing here is
# content: no topic, theme, search term, query, article text, key or address.
RUN_FIELDS = frozenset({
    # every endpoint
    "kind", "t", "endpoint", "method", "status", "ok", "ms",
    "model", "key", "commit", "stateless", "error",
    # /api/ideas
    "n_asked", "n_ideas", "guidance",
    # /api/draft
    "screened", "cited", "cited_direct", "direct", "related", "tangential",
    "full_text", "full_text_via", "named_added", "named_queries",
    "style_errors", "style_rules", "figures", "unverified", "misattributed",
    "working_draft",
    # /api/gallery
    "backend", "items", "html_kb",
})

RUN_ENDPOINTS = ("/api/ideas", "/api/draft", "/api/gallery")
```

### 1b. Pure builders (this is what the tests drive)

Both are module-level functions, not methods, so a test can call them with a
plain dict and a fake `Draft`.

```python
def build_run_record(endpoint, method, status, ms, extra=None) -> dict:
    """One run's log line. Only RUN_FIELDS survive."""
```

- Sets `kind="run"`, `t` = UTC now as `"%Y-%m-%dT%H:%M:%SZ"`, `endpoint`,
  `method`, `status`, `ok` = `status < 400`, `ms` = `int(ms)`.
- Merges `extra` **after filtering**: `{k: v for k, v in (extra or {}).items()
  if k in RUN_FIELDS}`.
- Adds `commit` from `_build_info().get("commit")` when present, and
  `stateless` = `STATELESS`.
- Returns the dict; never raises.

```python
def draft_run_fields(draft) -> dict:
    """Counts describing one finished draft. Never any of its text."""
```

Reads only:

- `screened` = `len(draft.papers)`
- `cited` = `len(draft.cited_refs)`
- `direct` / `related` / `tangential` = `draft.curation["counts"]` (default 0)
- `cited_direct` = cited indices whose `curation["relevance"][i] == "direct"`
  (same arithmetic `Draft.summary()` does)
- `full_text` = `len(draft.provenance.get("full_text_sources") or [])`
- `full_text_via` = `draft.provenance.get("full_text_via")` — the
  `{"papers": n, "europe_pmc": n}` dict, both ints
- `named_added` = `provenance["named_sources"]["added"]` (0 when absent);
  `named_queries` = **len** of that entry's `queries` list — never the strings
- `style_errors` = `len(style.errors(draft.style_report))`;
  `style_rules` = sorted unique rule names of those errors (fixed vocabulary
  from `style.py`, safe to log)
- `figures` = `draft.verification.get("total", 0)`,
  `unverified` / `misattributed` = lengths of those lists (**lengths only** —
  the lists hold sentence excerpts)
- `working_draft` = `bool(render._working_draft_sentence(draft.style_report,
  draft.verification))` — reuse that function so the log and the printed page
  can never disagree.

Wrap the body in `try/except Exception: return {}` so a shape change in `Draft`
cannot 500 a request that already succeeded.

Add `from .render import _working_draft_sentence` to the existing `render`
import line (web.py already imports `_draft_title` from there) and
`from .style import errors as style_errors`.

### 1c. Emitting

On `ArticleGenHandler`:

```python
_run_status = 0          # class-level defaults so a stray call is safe
_run_extra: dict | None = None

def _note_run(self, **fields) -> None:
    """Record fields for this request's run line. Unknown keys are dropped."""
```

- Creates `self._run_extra` if missing; stores only keys in `RUN_FIELDS`.

```python
def _emit_run(self, endpoint, method, started) -> None:
```

- Builds the record, writes `sys.stderr.write(json.dumps(record) + "\n")`.
  **Pure JSON, no `[web]`/`[run]` prefix** — the first key is `"kind": "run"`,
  so `grep '"kind": "run"' | jq` works on a raw Render log dump.
- Then, inside its own `try/except Exception`, calls
  `gallery.append_run(record)`. On failure write one
  `[web] run-log gist write failed: <ClassName>` line to stderr and continue.
- The whole method is wrapped so it cannot raise into the request path.

In `_send_json`, add `self._run_status = status` as the first statement.

**Timing wrapper.** Rename the current `do_POST` body to `_dispatch_post` and
make `do_POST`:

```python
def do_POST(self) -> None:
    started = time.time()
    self._run_status, self._run_extra = 0, {}
    try:
        self._dispatch_post()
    finally:
        if self.path in RUN_ENDPOINTS:
            self._emit_run(self.path, "POST", started)
```

Same shape in `do_GET` for `/api/gallery` (and `/api/gallery/`) only — a GET
list is one line with `items`, `backend`, no draft fields. `/api/diag`,
`/api/health` and `/api/drafts` stay unlogged; say so in a comment.

`ms` = `int((time.time() - started) * 1000)`.

### 1d. What each handler notes

Add a small module helper:

```python
def _key_mode(payload: dict) -> str:
    """Who is paying: 'visitor', 'public' (the host's key) or 'none'."""
```

— presence check only; never the key itself, never a prefix of it.

And record the resolved model name without a network call:

```python
try:
    resolved = llm.resolve_provider(model, api_key)[1]
except Exception:
    resolved = model
```

- **`_handle_ideas`**: right after `_credentials`, `self._note_run(key=...,
  model=resolved, n_asked=n, guidance=bool(guidance))`. On the empty-theme
  refusal note `error="missing_theme"`. On success note `n_ideas=len(ideas)`.
- **`_handle_draft`**: same key/model note after `_credentials`. Refusals note
  `error=` one of `"missing_topic"`, `"topic_too_long"`, `"bad_search_terms"`.
  `NoPapersFound` / `CurationFailed` note `error=type(exc).__name__`. On
  success note `**draft_run_fields(draft)` and re-note
  `model=draft.provenance.get("model")` (the model the pipeline actually
  resolved).
- **`_handle_publish_gallery`**: note `backend=gallery._backend()`,
  `html_kb=len(html.encode("utf-8")) // 1024` when `html` is a string (a byte
  count is not content), and `error="invalid_html"` / `"GalleryError"` /
  the exception class on the failure paths.
- **`_handle_get_gallery`**: note `backend=`, `items=len(items)`.
- **`_over_rate_limit`**: note `error="rate_limited"` when it refuses.
- **`_missing_key`**: note `error="missing_key"` when it refuses.
- **`_unexpected`**: note `error=type(exc).__name__` (class name only — the
  message can quote upstream text; the full detail already goes to
  `_log_stage`).

Payload validation failures in `_dispatch_post` (bad Content-Length, body too
large, invalid JSON) also note an `error` code — they are inside the wrapper, so
they already get a line.

---

## 2. `articlegen/gallery.py`

Append-only sink for the same record. Reuses `_github` and `_token`.

```python
# Optional run log. The gist id goes in ARTICLEGEN_ANALYTICS_GIST; the token is
# the same gist-scoped one the gallery uses. Create the gist as *secret*:
#   gh gist create --secret runs.jsonl
# Secret means unlisted, not access-controlled — which is safe here only
# because a run line carries no topic, key or address.
ANALYTICS_FILE = "articlegen-runs.jsonl"
ANALYTICS_MAX_LINES = 1000        # ~400 KB; a gist file over 1 MB stops
                                  # returning inline content from the API.
_analytics_lock = threading.Lock()   # separate from _lock: a run line must
                                     # never queue behind a gallery publish.


def analytics_gist() -> str:
    """The gist id to append run lines to, or '' when the sink is off."""


def analytics_enabled() -> bool:
    """True when both the gist id and the gist token are set."""


def append_run(record: dict) -> None:
    """Append one run line to the private gist. Never raises."""
```

`append_run`:

1. Return immediately when `not analytics_enabled()`.
2. Under `_analytics_lock`: `GET /gists/<id>`, read `ANALYTICS_FILE` via the
   existing `_gist_file_text` (handles the truncated-content fallback), split on
   newlines, drop blanks, append `json.dumps(record)`, keep the **last**
   `ANALYTICS_MAX_LINES`, `PATCH` the file back.
3. Wrap everything in `except Exception` and swallow — the caller already logs
   one line about the failure. A dropped analytics line is not worth a 500.

Read–modify–write is done inline (no thread, no buffer) on purpose: it happens
after the response body is written, the traffic ceiling is 120 requests/hour,
and a buffer loses lines every time Render sleeps the free instance after 15
minutes idle. The in-process lock is enough because Render runs one process;
say that in the docstring.

---

## 3. `tests/test_offline.py`

Three tests, in the file's existing style (`check(...)` calls, env saved and
restored in `finally`). Use these exact names — `CLAUDE.md` will cite them and
`test_claude_md_still_describes_this_code` checks they exist.

### `test_run_log_never_carries_the_topic`

The forbidden-fields guard. Build a fake `Draft`-shaped object (a small class or
`types.SimpleNamespace` with `papers`, `cited_refs`, `curation`, `verification`,
`provenance`, `style_report`) whose provenance queries, topic and article title
all contain distinctive sentinels (`"SENTINEL-TOPIC"`, `"SENTINEL-QUERY"`,
`"sk-or-v1-SENTINEL"`, `"203.0.113.9"`).

Assert:

- `web.RUN_FIELDS` contains none of `topic`, `theme`, `question`, `title`,
  `search_terms`, `queries`, `html`, `markdown`, `key`, `api_key`, `ip`,
  `client_ip`, `error_message`.
- `json.dumps(web.build_run_record("/api/draft", "POST", 200, 1234, extra))`
  contains **no sentinel**, where `extra` is `draft_run_fields(fake_draft)`
  merged with a raw payload dict (`{"topic": "SENTINEL-TOPIC", "key":
  "sk-or-v1-SENTINEL", "html": "<h1>x</h1>"}`) — proving the filter drops
  unknown keys rather than trusting the caller.
- `_note_run` on a bare handler instance
  (`web.ArticleGenHandler.__new__(web.ArticleGenHandler)`) also drops them.
- `draft_run_fields` returns the right counts: `screened`, `cited`,
  `cited_direct`, `direct`, `full_text`, `named_added`, `named_queries` (an
  **int**, and the query strings appear nowhere), `unverified`,
  `misattributed`, `working_draft`.
- `web.build_run_record(...)["ok"]` is `False` for status 500 and `True` for 200.

### `test_every_endpoint_logs_one_run_line`

Drive the handlers without a socket. Build a handler with
`web.ArticleGenHandler.__new__(web.ArticleGenHandler)` and set the attributes
the code path touches: `client_address = ("10.0.0.1", 1)`, a `headers` stub
(`{}`-like with `.get`), `path`, and replace `_send_json` with a recorder that
also sets `_run_status`. Capture stderr by swapping `sys.stderr` for an
`io.StringIO`.

Cover, monkeypatching `web.generate_ideas` / `web.generate_draft` /
`gallery.publish` at module level:

- ideas success, ideas with no theme (400), ideas raising (500)
- draft success (fake `Draft`), draft raising `NoPapersFound` (503/422)
- gallery publish success and `GalleryError` (503)

Assert for each: exactly **one** line starting `{` on stderr, it parses as JSON,
`kind == "run"`, `endpoint`/`status`/`ms`/`key` present, `ms >= 0`, `error` is
the expected token on failures, and no sentinel topic string appears.

Set `ARTICLEGEN_ANALYTICS_GIST` unset for this test so no GitHub call is
attempted; restore env in `finally`.

### `test_run_log_gist_is_optional_and_gist_scoped`

- With `ARTICLEGEN_ANALYTICS_GIST` unset: `gallery.analytics_enabled()` is
  `False`, and `append_run({...})` makes **zero** calls (patch
  `gallery._github` with a counter).
- With the id and `ARTICLEGEN_GALLERY_TOKEN` set and `_github` faked (same
  `_Resp`/`fake_request` pattern as `test_visitor_gallery`): one `GET` then one
  `PATCH` at `/gists/<id>`, the PATCH body's file content is newline-delimited
  JSON whose last line round-trips to the record, and the token travels as an
  `Authorization` header (assert `bool(headers["Authorization"])`, never the
  value).
- Seed the existing file with `ANALYTICS_MAX_LINES + 5` lines and assert the
  written file has exactly `ANALYTICS_MAX_LINES` lines with the newest last.
- A `_github` that raises `GalleryError` — and one that raises
  `RuntimeError` — must leave `append_run` returning `None`, not raising.
- `append_run` writes to `ANALYTICS_FILE`, not `GALLERY_INDEX_FILE`, and never
  touches `GALLERY_INDEX_GIST`.

---

## 4. `render.yaml`

After the `ARTICLEGEN_GALLERY_TOKEN` block:

```yaml
      # Optional run log. Set to the id of a *secret* gist you created with
      # `gh gist create --secret runs.jsonl`; run lines are appended there so
      # they survive a restart. Uses ARTICLEGEN_GALLERY_TOKEN (gist scope).
      # Unset: run lines still go to stderr, and only there.
      - key: ARTICLEGEN_ANALYTICS_GIST
        sync: false
```

## 5. `deploy/README.md`

New `## Run analytics` section after `## Configuration`:

- What a line looks like (paste one realistic example line — with a fake
  commit, no topic).
- Read it from Render: **Logs** tab, or
  `grep '"kind": "run"' render.log | jq -s 'map(select(.endpoint=="/api/draft"))'`.
- Turning the gist on: `gh gist create --secret runs.jsonl`, copy the id into
  `ARTICLEGEN_ANALYTICS_GIST` in the dashboard. **Secret means unlisted, not
  private** — anyone with the URL can read it, which is fine because a line
  holds no topic, key or address.
- What is deliberately absent, in one sentence, so nobody adds it back.

Add two rows to the config table:

| `ARTICLEGEN_ANALYTICS_GIST` | unset | Id of a secret gist to append run lines to. Uses the gallery's gist-scoped token. Absent: stderr only. |

## 6. `CLAUDE.md`

Under **Web app (`index.html` + `web.py`)**, add a bullet block:

- **Every website run writes one JSON line to stderr.** `/api/ideas`,
  `/api/draft` and `/api/gallery` each emit one `{"kind": "run", ...}` line with
  time, status, duration, model, whether a visitor or the host's key paid, and
  for drafts the screened/cited/direct counts, full-text count and route,
  named-sources added, style errors, unverified/misattributed figures and
  whether the page was branded a working draft. `RUN_FIELDS` is an **allowlist**
  — the record is filtered against it, so a field nobody thought about cannot
  reach the log. **No topic, theme, search term, query string, article text, API
  key or IP address is ever logged**, and `provenance["queries"]` is a search
  term, so only its length goes in. → `test_run_log_never_carries_the_topic`
- **Analytics never breaks a response.** The line is emitted from a `finally`
  after the body is written, and the optional gist write is swallowed. →
  `test_every_endpoint_logs_one_run_line`
- **The durable copy is an optional secret gist**
  (`ARTICLEGEN_ANALYTICS_GIST`), appended through `gallery.append_run` with the
  same gist-scoped token the gallery uses, trimmed to `ANALYTICS_MAX_LINES`.
  A secret gist is unlisted, not access-controlled — safe only because the line
  carries no content. →
  `test_run_log_gist_is_optional_and_gist_scoped`
- `working_draft` reuses `render._working_draft_sentence`, so the log and the
  printed page cannot disagree.

Add to the invariant table:

| A run line carries counts, never content | `test_run_log_never_carries_the_topic` |
| Every logged endpoint emits exactly one line, success or failure | `test_every_endpoint_logs_one_run_line` |
| The run-log gist is optional and cannot break a request | `test_run_log_gist_is_optional_and_gist_scoped` |

Add `ARTICLEGEN_ANALYTICS_GIST` to the optional env vars in **Setup / testing**.

**Guard-test rules to respect:** every backticked `path.py` must exist, every
backticked `` `test_x` `` must exist in the suites, and every backticked
`ALL_CAPS` name of 5+ characters must exist in a module or `index.html`. So only
name `RUN_FIELDS`, `RUN_ENDPOINTS`, `ANALYTICS_FILE`, `ANALYTICS_MAX_LINES`,
`ARTICLEGEN_ANALYTICS_GIST`, `ARTICLEGEN_GALLERY_TOKEN` — all of which this plan
creates.

## 7. `docs/decisions.md`

One entry at the end of `## Web app and deployment`, titled
`### Run analytics (August 2026)`, recording:

- Why stderr first: it works on every host, needs no token, and Render already
  keeps it. The gist is the durable copy, not the source of truth.
- Why an allowlist rather than a denylist of forbidden fields.
- Why counts and not content: the whole reason the shared host is stateless is
  that a topic is the sensitive part; a log of topics reintroduces exactly what
  `ARTICLEGEN_STATELESS` exists to prevent. Hashing does not help — a hash of a
  short topic string is trivially reversible by dictionary.
- Why the query **count** and not the queries: `provenance["queries"]` is
  derived from the topic and the idea card's search terms.
- Why no buffering: the free instance sleeps after 15 minutes idle, so a buffer
  loses the tail of every quiet period; two GitHub calls per run against a
  120/hour ceiling is nothing.
- Why a secret gist is acceptable (unlisted, and contentless) and why it is a
  `gist`-scoped token, not a `contents` one.
- Why there is no `/api/runs`: a public read endpoint is a second surface to
  secure for a file the owner can already read.

---

## Verify

```bash
python tests/test_offline.py            # must end ALL PASS
python tests/test_journal_conformance.py
```

Then a real local smoke (no key needed for the refusal paths):

```bash
articlegen web            # in one terminal
curl -s -X POST localhost:8000/api/ideas -d '{"theme":"delirium"}'
curl -s localhost:8000/api/gallery
```

Confirm on the server's stderr: exactly one `{"kind": "run", ...}` line per
request, and `grep -c delirium` over that output returns **0**.

With a key set, run one real draft through the web UI and check the line has
`screened`, `cited`, `full_text`, `style_errors` and `working_draft` populated
and matching what the CLI log said.

## Git

Branch `run-analytics`, then `gh pr create`. The PR touches `articlegen/**` and
`CLAUDE.md`, so `docs-current.yml` is satisfied. Do not write "does not close
#NNN" anywhere. No issue exists for this work — if you open one first, cite its
number in `docs/decisions.md`; otherwise cite no number rather than inventing
one.

Do **not** commit `drafts/2026-08-22-*`, the modified `drafts/index.html`, or
`tools/compare_models.py` — they are untracked/modified work from another
session and are out of scope. Stage files by name.

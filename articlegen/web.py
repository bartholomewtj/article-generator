"""HTTP server and JSON API for the web app.

Endpoints:
- GET  /api/drafts: list drafts on disk (local mode only; empty when shared)
- POST /api/ideas:  generate draft ideas from a theme
- POST /api/draft:  run the full evidence-grounded research & draft pipeline

Runs in two modes, because a laptop and a shared host want opposite things:

**Local** (`articlegen web`) — writes each draft into `drafts/` and rebuilds the
review queue, matching what the CLI does. This is the default.

**Shared** (`ARTICLEGEN_STATELESS=1`, what the public deployment sets) — renders
the article and returns it in the response, persisting nothing. On a shared host
a common `drafts/` directory would make every visitor's article readable by
every other visitor at a guessable URL, and list their topics in the queue index.
Someone researching something they'd rather not broadcast would have no way to
know. The browser keeps its own copies in localStorage either way.

The caller's API key arrives in the request body and is passed down the call
chain as an argument. It is never written to `os.environ`, never logged, and
never persisted — the environment is process-global and this server is threaded,
so an env-var handoff would let concurrent requests pick up each other's keys.
"""

from __future__ import annotations

import datetime
import glob
import json
import os
import re
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import llm
from .ideas import generate_ideas
from .pipeline import NoPapersFound, generate_draft
from .render import _draft_title, build_index, render_article, render_markdown
from .sources import gather_evidence

DRAFTS_DIR = "drafts"

# Models a caller may ask for by name. Anything else is ignored and the provider
# layer picks from the key it was given.
ALLOWED_MODELS = frozenset({
    llm.ANTHROPIC_DEFAULT_MODEL,
    llm.OPENROUTER_DEFAULT_MODEL,
})

# Shared hosts set this. Local runs leave it unset and keep writing to drafts/.
STATELESS = os.environ.get("ARTICLEGEN_STATELESS", "").strip().lower() in ("1", "true", "yes")

# Comma-separated origins allowed to call the API from a browser. Default "*"
# suits localhost; the deployment pins it to the GitHub Pages origin.
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ARTICLEGEN_ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

# Per-IP throttle. Every draft costs the caller LLM tokens but costs *us* calls
# against the shared OpenAlex / Semantic Scholar quotas, which are attached to
# this server's IP — one abusive client can get the whole deployment throttled.
RATE_LIMIT_WINDOW = 3600
RATE_LIMIT_MAX = int(os.environ.get("ARTICLEGEN_RATE_LIMIT", "20"))
_rate_lock = threading.Lock()
_rate_hits: dict[str, list[float]] = {}


def _rate_limited(client_ip: str) -> bool:
    """Sliding-window count of expensive requests from one address."""
    now = time.time()
    with _rate_lock:
        hits = [t for t in _rate_hits.get(client_ip, []) if now - t < RATE_LIMIT_WINDOW]
        if len(hits) >= RATE_LIMIT_MAX:
            _rate_hits[client_ip] = hits
            return True
        hits.append(now)
        _rate_hits[client_ip] = hits
        # Opportunistic sweep so the dict doesn't grow without bound.
        if len(_rate_hits) > 2048:
            for ip in [k for k, v in _rate_hits.items() if not v or now - v[-1] > RATE_LIMIT_WINDOW]:
                _rate_hits.pop(ip, None)
    return False


def _build_info() -> dict:
    """Which commit, from which branch, this process is actually running.

    Same reasoning as `/api/diag`: everything works locally, so questions about
    the *deployment* are otherwise unanswerable from outside. "Is the running
    backend the code I just merged?" and "which branch does the host deploy
    from?" both needed a dashboard login to answer, which meant a rename of the
    default branch could stop deploys without anything visible from here (#47).

    Render injects these; anywhere else they are simply absent, and the keys are
    omitted rather than reported as empty. Both values are public facts about a
    public repository.
    """
    info = {}
    commit = os.environ.get("RENDER_GIT_COMMIT", "").strip()
    branch = os.environ.get("RENDER_GIT_BRANCH", "").strip()
    if commit:
        info["commit"] = commit[:7]
    if branch:
        info["branch"] = branch
    return info


def _requested_model(payload: dict) -> str | None:
    """The caller's model, accepted only from a known list.

    The value reaches an LLM API, so it is matched against the models this
    project actually supports rather than forwarded as given. `None` means the
    provider layer decides from whichever key was supplied.
    """
    requested = (payload.get("model") or "").strip()
    return requested if requested in ALLOWED_MODELS else None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "article"


class ArticleGenHandler(SimpleHTTPRequestHandler):
    # SimpleHTTPRequestHandler defaults to HTTP/1.0, which has no keep-alive:
    # the server closes the connection after every response. Browsers and
    # reverse proxies pool connections, so they reuse one the server has
    # already hung up on and the request fails instantly — intermittently,
    # depending on whether that particular request drew a pooled or a fresh
    # connection. It looks like flaky networking and isn't: roughly every
    # other fetch from the deployed front end failed in ~140ms.
    #
    # curl hides the bug completely, because each invocation opens its own
    # connection. Only a connection-pooling client sees it.
    #
    # HTTP/1.1 requires an accurate Content-Length (or chunked) on every
    # response or the client hangs waiting for a body. _send_json sets it,
    # SimpleHTTPRequestHandler sets it for files and send_error, and
    # do_OPTIONS sends an explicit zero below.
    protocol_version = "HTTP/1.1"

    def log_message(self, format_str: str, *args) -> None:
        sys.stderr.write(f"[web] {format_str % args}\n")

    def _missing_key(self, api_key: str | None) -> bool:
        """Reject a keyless request in the caller's language, not the server's.

        Without this the provider layer raises "OPENROUTER_API_KEY environment
        variable is not set", which is true and useless to someone using the web
        app — they have no environment to set. A locally-run server with its own
        key configured needs no key in the request, so only fail when both are
        absent.
        """
        if api_key or any(
            os.environ.get(var)
            for var in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")
        ):
            return False
        self._send_json(
            {"error": "No API key set. Open Settings (⚙️) and paste an OpenRouter "
                      "key — create one at openrouter.ai/keys."},
            status=400,
        )
        return True

    def _over_rate_limit(self) -> bool:
        """Charge the throttle for a request that is about to do real work.

        Checked after validation, not before: a malformed request costs nothing
        upstream, and locking someone out for a typo in the form is a worse
        failure than the flood it would prevent.
        """
        if not _rate_limited(self.client_address[0]):
            return False
        self._send_json(
            {"error": f"Rate limit reached ({RATE_LIMIT_MAX} requests/hour). Try again later."},
            status=429,
        )
        return True

    def _cors_origin(self) -> str | None:
        """Echo the caller's origin when it's allowed. None means: send no header."""
        if ALLOWED_ORIGINS == ["*"]:
            return "*"
        origin = self.headers.get("Origin")
        return origin if origin in ALLOWED_ORIGINS else None

    def _send_cors_headers(self) -> None:
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            if origin != "*":
                self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        # Explicit zero: under HTTP/1.1 a response with neither Content-Length
        # nor chunked encoding leaves the client waiting for a body.
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path in ("/api/drafts", "/api/drafts/"):
            self._handle_get_drafts()
            return
        if self.path in ("/api/health", "/api/health/"):
            self._send_json({"ok": True, "stateless": STATELESS, **_build_info()})
            return
        if self.path in ("/api/diag", "/api/diag/"):
            self._handle_diag()
            return
        super().do_GET()

    def do_POST(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_json({"error": "Invalid Content-Length"}, status=400)
            return
        # A topic and a key are small; anything larger is not a real request.
        if content_length > 64 * 1024:
            self._send_json({"error": "Request body too large."}, status=413)
            return

        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            self._send_json({"error": "Invalid JSON payload"}, status=400)
            return
        if not isinstance(payload, dict):
            self._send_json({"error": "Invalid JSON payload"}, status=400)
            return

        if self.path == "/api/ideas":
            self._handle_ideas(payload)
        elif self.path == "/api/draft":
            self._handle_draft(payload)
        else:
            self._send_json({"error": "Endpoint not found"}, status=404)

    def _handle_get_drafts(self) -> None:
        if not os.path.exists(DRAFTS_DIR):
            self._send_json({"drafts": []})
            return

        html_files = [
            p for p in glob.glob(os.path.join(DRAFTS_DIR, "*.html"))
            if os.path.basename(p) != "index.html"
        ]
        html_files.sort(key=os.path.getmtime, reverse=True)

        results = []
        for path in html_files:
            name = os.path.basename(path)
            title = _draft_title(path)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat()
            md_name = name[:-5] + ".md"
            has_md = os.path.exists(os.path.join(DRAFTS_DIR, md_name))
            results.append({
                "filename": name,
                "title": title,
                "date": mtime,
                "html_url": f"/drafts/{name}",
                "md_url": f"/drafts/{md_name}" if has_md else None,
            })

        self._send_json({"drafts": results})

    def _handle_ideas(self, payload: dict) -> None:
        theme = (payload.get("theme") or "").strip()
        guidance = (payload.get("guidance") or "").strip()
        api_key = (payload.get("key") or "").strip() or None
        try:
            n = max(1, min(int(payload.get("n") or 6), 12))
        except (TypeError, ValueError):
            n = 6

        if not theme:
            self._send_json({"error": "Please provide a theme."}, status=400)
            return
        if self._missing_key(api_key) or self._over_rate_limit():
            return

        prompt_theme = theme
        if guidance:
            prompt_theme = f"{theme} — guidance: {guidance[:300]}"

        try:
            ideas = generate_ideas(prompt_theme, n=n, api_key=api_key,
                                   model=_requested_model(payload))
            self._send_json({"theme": theme, "ideas": ideas})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _handle_draft(self, payload: dict) -> None:
        topic = (payload.get("topic") or "").strip()
        style = (payload.get("style") or "").strip()
        api_key = (payload.get("key") or "").strip() or None

        if not topic:
            self._send_json({"error": "Please provide an article title/topic."}, status=400)
            return

        if len(topic) > 300:
            self._send_json({"error": "Topic is too long (300 characters max)."}, status=400)
            return
        if self._missing_key(api_key) or self._over_rate_limit():
            return

        try:
            draft = generate_draft(
                topic, style_note=style[:500], max_papers=20, api_key=api_key,
                model=_requested_model(payload), log=self._log_stage
            )
        except NoPapersFound as exc:
            # 503 when the upstream APIs are the problem: it's not the caller's
            # request that was unprocessable, and the distinction tells them
            # whether to reword the topic or simply try again.
            self._send_json({"error": str(exc)}, status=503 if exc.sources_failed else 422)
            return
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)
            return

        render_args = (
            draft.article, draft.papers, draft.topic,
            draft.curation, draft.verification, draft.provenance,
            draft.style_report,
        )
        article_html = render_article(*render_args)
        article_md = render_markdown(*render_args)

        response = {
            "ok": True,
            "title": draft.article.get("title", topic),
            "stem": f"{datetime.date.today().isoformat()}-{_slugify(topic)}",
            "sources_count": len(draft.cited_refs),
            "summary": draft.summary(),
            "html": article_html,
            "markdown": article_md,
        }

        if not STATELESS:
            # Local mode: mirror the CLI so `articlegen queue` sees the same drafts.
            os.makedirs(DRAFTS_DIR, exist_ok=True)
            html_name = f"{response['stem']}.html"
            md_name = f"{response['stem']}.md"
            with open(os.path.join(DRAFTS_DIR, html_name), "w", encoding="utf-8") as f:
                f.write(article_html)
            with open(os.path.join(DRAFTS_DIR, md_name), "w", encoding="utf-8") as f:
                f.write(article_md)
            build_index(DRAFTS_DIR)
            response["html_url"] = f"/drafts/{html_name}"
            response["md_url"] = f"/drafts/{md_name}"

        self._send_json(response)

    def _handle_diag(self) -> None:
        """Can this host reach the scholarly APIs at all?

        Needs no API key, because it exercises only the keyless half of the
        pipeline. Locally everything works, so when a deployment reports "no
        papers found" the question is whether *that host* is being refused —
        and there is no way to answer it from outside without asking the host.

        Two consequences of that follow. It bypasses the search cache, because a
        cached answer cannot tell you what the sources are doing right now. And
        it is therefore throttled like any other expensive endpoint: each call
        spends real requests against the same shared quota drafting depends on,
        and an unmetered probe is a way for anyone who finds the URL to exhaust
        the very quota the throttle exists to protect.
        """
        if self._over_rate_limit():
            return
        outcomes: list[dict] = []
        try:
            papers = gather_evidence(
                ["shift work sleep"], max_papers=3, per_query=3,
                topic="shift work sleep", outcomes=outcomes, use_cache=False,
            )
            count = len(papers)
        except Exception as exc:
            count, outcomes = 0, [{"source": "gather_evidence", "query": "",
                                   "count": 0, "error": f"{type(exc).__name__}: {exc}"}]
        self._send_json({
            "papers_found": count,
            "sources": outcomes,
            "openalex_mailto_set": bool(os.environ.get("OPENALEX_MAILTO")),
            "semantic_scholar_key_set": bool(os.environ.get("SEMANTIC_SCHOLAR_API_KEY")),
        })

    def _log_stage(self, message: str) -> None:
        """Pipeline progress to the server log. Never carries the caller's key."""
        sys.stderr.write(f"[draft] {message}\n")


def run_server(port: int = 8000, directory: str = ".") -> None:
    os.chdir(directory)
    handler = ArticleGenHandler
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    mode = "stateless (nothing written to disk)" if STATELESS else f"local (writing to {DRAFTS_DIR}/)"
    print(f"🚀 Article Generator running at http://localhost:{port}/  — {mode}")
    if ALLOWED_ORIGINS != ["*"]:
        print(f"   CORS restricted to: {', '.join(ALLOWED_ORIGINS)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()

"""Built-in HTTP server for local mobile web app.

Provides static file serving and JSON API endpoints:
- GET  /api/drafts: list all generated article drafts
- POST /api/ideas: generate draft ideas from theme
- POST /api/draft: run full evidence-grounded research & draft pipeline
"""

from __future__ import annotations

import datetime
import glob
import html
import json
import os
import re
import subprocess
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .ideas import generate_ideas
from .render import _draft_title, build_index, render_article, render_markdown
from .sources import gather_evidence
from .verify import check_statistics
from .writer import curate_sources, plan_queries, write_article

DRAFTS_DIR = "drafts"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "article"


class ArticleGenHandler(SimpleHTTPRequestHandler):
    def log_message(self, format_str: str, *args) -> None:
        sys.stderr.write(f"[web] {format_str % args}\n")

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/drafts" or self.path == "/api/drafts/":
            self._handle_get_drafts()
            return
        super().do_GET()

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            self._send_json({"error": "Invalid JSON payload"}, status=400)
            return

        if self.path == "/api/ideas":
            self._handle_ideas(payload)
        elif self.path == "/api/draft":
            self._handle_draft(payload)
        elif self.path == "/api/publish":
            self._handle_publish(payload)
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
        api_key = (payload.get("key") or "").strip()
        n = int(payload.get("n") or 6)

        if not theme:
            self._send_json({"error": "Please provide a theme."}, status=400)
            return

        if api_key:
            os.environ["GROQ_API_KEY"] = api_key

        prompt_theme = theme
        if guidance:
            prompt_theme = f"{theme} — guidance: {guidance[:300]}"

        try:
            ideas = generate_ideas(prompt_theme, n=n)
            self._send_json({"theme": theme, "ideas": ideas})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _handle_draft(self, payload: dict) -> None:
        topic = (payload.get("topic") or "").strip()
        style = (payload.get("style") or "").strip()
        api_key = (payload.get("key") or "").strip()

        if not topic:
            self._send_json({"error": "Please provide an article title/topic."}, status=400)
            return

        if api_key:
            os.environ["GROQ_API_KEY"] = api_key

        try:
            queries, core_entity = plan_queries(topic)
            papers = gather_evidence(queries, max_papers=20, topic=topic, core_entity=core_entity)
            if not papers:
                self._send_json({"error": "No academic papers with abstracts found for this topic. Please try another theme or retry in a minute."}, status=422)
                return

            curation = curate_sources(topic, papers)
            article = write_article(topic, papers, style_note=style, curation=curation)
            verification = check_statistics(article, papers)

            os.makedirs(DRAFTS_DIR, exist_ok=True)
            date_str = datetime.date.today().isoformat()
            stem = f"{date_str}-{_slugify(topic)}"
            html_filename = f"{stem}.html"
            md_filename = f"{stem}.md"

            html_path = os.path.join(DRAFTS_DIR, html_filename)
            md_path = os.path.join(DRAFTS_DIR, md_filename)

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(render_article(article, papers, topic, curation, verification))
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(render_markdown(article, papers, topic, curation, verification))

            build_index(DRAFTS_DIR)

            self._send_json({
                "ok": True,
                "title": article.get("title", topic),
                "stem": stem,
                "html_url": f"/drafts/{html_filename}",
                "md_url": f"/drafts/{md_filename}",
                "sources_count": len(article.get("references", [])),
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _handle_publish(self, payload: dict) -> None:
        try:
            # Stage the drafts folder
            subprocess.run(["git", "add", "drafts/"], check=True, capture_output=True, text=True)
            
            # Check if there are changes to commit
            status_res = subprocess.run(["git", "status", "--porcelain", "drafts/"], check=True, capture_output=True, text=True)
            if not status_res.stdout.strip():
                self._send_json({"ok": True, "message": "No new drafts to publish."})
                return

            # Commit the changes
            subprocess.run(["git", "commit", "-m", "publish new drafts"], check=True, capture_output=True, text=True)
            
            # Push to GitHub
            push_res = subprocess.run(["git", "push"], check=True, capture_output=True, text=True)
            
            self._send_json({"ok": True, "message": "Successfully published to GitHub Pages."})
        except subprocess.CalledProcessError as exc:
            self._send_json({"error": f"Git command failed: {exc.stderr}"}, status=500)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)


def run_server(port: int = 8000, directory: str = ".") -> None:
    os.chdir(directory)
    handler = ArticleGenHandler
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"🚀 Article Generator Mobile Web App running at http://localhost:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()

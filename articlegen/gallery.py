"""Public visitor gallery — opt-in persist of generated briefings.

Generating does not publish. A visitor has to tap Share to gallery. The
hosted backend is stateless and has no disk, so the durable copy is a
public GitHub gist. The token for that needs `gist` scope only — a leak
cannot rewrite the generator.

The index gist id is a public fact. The front end fetches it with no key,
so listing shared briefings does not wait on Render.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import threading
import uuid

GALLERY_DIR = "gallery"
GALLERY_INDEX_NAME = "index.json"

# Public gist that holds the gallery index. The front end hardcodes the same
# id — `test_gallery_index_id_matches_the_front_end` pins them together.
GALLERY_INDEX_GIST = "3b864ca05620472d2644c3e9c1fd6a03"
GALLERY_INDEX_FILE = "articlegen-gallery-index.json"

GALLERY_MAX = 50
GALLERY_MAX_HTML = 400 * 1024
GALLERY_MAX_TITLE = 300

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

_lock = threading.Lock()


class GalleryError(Exception):
    """Visitor-safe failure. The server log gets the cause separately."""


def gallery_enabled() -> bool:
    """True when this host can accept a Share to gallery request."""
    return _backend() != "off"


def analytics_gist() -> str:
    """The gist id to append run lines to, or '' when the sink is off."""
    return os.environ.get("ARTICLEGEN_ANALYTICS_GIST", "").strip()


def analytics_enabled() -> bool:
    """True when both the gist id and the gist token are set."""
    return bool(analytics_gist()) and bool(_token())


def append_run(record: dict) -> None:
    """Append one run line to the private gist. Never raises.

    Read-modify-write is executed synchronously under an in-process lock:
    traffic ceiling is low, and background buffers lose lines on free-tier sleep.
    """
    if not analytics_enabled():
        return
    try:
        gist_id = analytics_gist()
        line = json.dumps(record)
        with _analytics_lock:
            gist = _github("GET", f"/gists/{gist_id}")
            text = _gist_file_text(gist, ANALYTICS_FILE)
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            lines.append(line)
            if len(lines) > ANALYTICS_MAX_LINES:
                lines = lines[-ANALYTICS_MAX_LINES:]
            new_text = "\n".join(lines) + "\n"
            _github("PATCH", f"/gists/{gist_id}", {
                "files": {
                    ANALYTICS_FILE: {
                        "content": new_text,
                    }
                }
            })
    except Exception:
        pass


def _backend() -> str:
    if os.environ.get("ARTICLEGEN_GALLERY_TOKEN", "").strip():
        return "gist"
    stateless = os.environ.get("ARTICLEGEN_STATELESS", "").strip().lower() in (
        "1", "true", "yes",
    )
    return "off" if stateless else "local"


def _token() -> str:
    return os.environ.get("ARTICLEGEN_GALLERY_TOKEN", "").strip()


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:50] or "briefing"


def validate_html(html: str) -> str | None:
    """Why this HTML cannot be published, or None if it can."""
    if not html or not html.strip():
        return "Generate a briefing first."
    if len(html.encode("utf-8")) > GALLERY_MAX_HTML:
        return "This briefing is too large to share to the gallery."
    lowered = html.lower()
    if "<script" in lowered or "javascript:" in lowered:
        return "This page cannot be shared to the gallery."
    if "<h1" not in lowered:
        return "This page cannot be shared to the gallery."
    return None


def _clean_title(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    return t[:GALLERY_MAX_TITLE] or "Untitled briefing"


def list_items() -> list[dict]:
    """Newest first. Never raises for a missing store — that is an empty list."""
    if _backend() == "gist":
        try:
            return _gist_read_index()
        except GalleryError:
            return []
    return _local_read_index()


def publish(title: str, html: str) -> dict:
    """Add one briefing to the gallery. Raises GalleryError on refusal."""
    reason = validate_html(html)
    if reason:
        raise GalleryError(reason)
    item_title = _clean_title(title)
    backend = _backend()
    if backend == "off":
        raise GalleryError(
            "The public gallery is not configured on this host."
        )
    with _lock:
        if backend == "gist":
            return _gist_publish(item_title, html)
        return _local_publish(item_title, html)


def _new_local_id(title: str) -> str:
    day = datetime.date.today().isoformat()
    return f"{day}-{_slug(title)}-{uuid.uuid4().hex[:6]}"


def _item(id_: str, title: str, html_url: str, date: str | None = None) -> dict:
    return {
        "id": id_,
        "title": title,
        "date": date or datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "html_url": html_url,
    }


def _cap(items: list[dict]) -> tuple[list[dict], list[dict]]:
    if len(items) <= GALLERY_MAX:
        return items, []
    return items[:GALLERY_MAX], items[GALLERY_MAX:]


# --- local disk ----------------------------------------------------------

def _local_index_path() -> str:
    return os.path.join(GALLERY_DIR, GALLERY_INDEX_NAME)


def _local_read_index() -> list[dict]:
    path = _local_index_path()
    if not os.path.exists(path):
        return []
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def _local_write_index(items: list[dict]) -> None:
    os.makedirs(GALLERY_DIR, exist_ok=True)
    with open(_local_index_path(), "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, indent=2)
        f.write("\n")


def _local_publish(title: str, html: str) -> dict:
    ident = _new_local_id(title)
    os.makedirs(GALLERY_DIR, exist_ok=True)
    html_name = f"{ident}.html"
    with open(os.path.join(GALLERY_DIR, html_name), "w", encoding="utf-8") as f:
        f.write(html)
    item = _item(ident, title, f"/gallery/{html_name}")
    items = [item] + _local_read_index()
    kept, dropped = _cap(items)
    for old in dropped:
        old_name = os.path.basename(old.get("html_url") or "")
        if old_name:
            try:
                os.remove(os.path.join(GALLERY_DIR, old_name))
            except OSError:
                pass
    _local_write_index(kept)
    return item


# --- GitHub gist ---------------------------------------------------------

def _github(method: str, path: str, body: dict | None = None) -> dict:
    """One GitHub API call. The token is a header, never a log line."""
    import requests

    token = _token()
    if not token:
        raise GalleryError("The public gallery is not configured on this host.")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "articlegen-gallery",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = "https://api.github.com" + path
    try:
        resp = requests.request(
            method, url, headers=headers, json=body, timeout=30,
        )
    except requests.RequestException as exc:
        raise GalleryError(
            "Could not reach the gallery store. Try again in a moment."
        ) from exc
    if resp.status_code in (401, 403):
        raise GalleryError("The public gallery is not configured on this host.")
    if resp.status_code == 404:
        raise GalleryError("The public gallery is not configured on this host.")
    if resp.status_code >= 400:
        raise GalleryError(
            "Could not update the public gallery. Try again in a moment."
        )
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError as exc:
        raise GalleryError(
            "Could not update the public gallery. Try again in a moment."
        ) from exc


def _gist_file_text(gist: dict, filename: str) -> str:
    files = gist.get("files") or {}
    entry = files.get(filename) or {}
    text = entry.get("content")
    if text:
        return text
    raw = entry.get("raw_url")
    if not raw:
        return ""
    import requests
    try:
        resp = requests.get(raw, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        return ""


def _gist_read_index() -> list[dict]:
    gist = _github("GET", f"/gists/{GALLERY_INDEX_GIST}")
    text = _gist_file_text(gist, GALLERY_INDEX_FILE)
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else []


def _gist_write_index(items: list[dict]) -> None:
    _github("PATCH", f"/gists/{GALLERY_INDEX_GIST}", {
        "files": {
            GALLERY_INDEX_FILE: {
                "content": json.dumps({"items": items}, indent=2) + "\n",
            }
        }
    })


def _gist_raw_url(gist_id: str, filename: str = "article.html") -> str:
    return (
        f"https://gist.githubusercontent.com/bartholomewtj/"
        f"{gist_id}/raw/{filename}"
    )


def _gist_publish(title: str, html: str) -> dict:
    created = _github("POST", "/gists", {
        "description": f"articlegen-gallery: {title[:80]}",
        "public": True,
        "files": {"article.html": {"content": html}},
    })
    gist_id = created.get("id") or ""
    if not gist_id:
        raise GalleryError(
            "Could not update the public gallery. Try again in a moment."
        )
    item = _item(gist_id, title, _gist_raw_url(gist_id))
    items = [item] + _gist_read_index()
    kept, dropped = _cap(items)
    for old in dropped:
        old_id = old.get("id") or ""
        if old_id and old_id != GALLERY_INDEX_GIST:
            try:
                _github("DELETE", f"/gists/{old_id}")
            except GalleryError:
                pass
    _gist_write_index(kept)
    return item

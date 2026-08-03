import re

IDEAS_DIR = "ideas"
DRAFTS_DIR = "drafts"

def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "article"

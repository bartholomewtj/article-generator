---
title: ArticleGen
emoji: 📄
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Scientific reviews grounded in real abstracts
---

# ArticleGen — backend

This Space runs the research-and-draft pipeline behind
**[the Article Generator web app](https://bartholomewtj.github.io/article-generator/)**.
It is an API, not a page — open the link above to use it.

Source: <https://github.com/bartholomewtj/article-generator>

## What it does

Given a topic, it plans scholarly search queries, fetches real papers from
Semantic Scholar and OpenAlex, scores how directly each one addresses the exact
topic, writes a review citing only those abstracts, then checks the result:
prose against journal writing conventions, and every statistic against the
source abstracts it claims to come from. Both checks are deterministic code, not
a second model pass.

## Keys and data

- **Bring your own key.** You paste a free [Groq](https://console.groq.com/keys)
  key into the web app; it is sent with your request and used for that request.
  This Space stores no keys and has none of its own.
- **Nothing is kept.** The article is rendered, returned, and forgotten. There
  is no database and nothing is written to disk. Your drafts live in your own
  browser's storage.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | liveness |
| `POST` | `/api/ideas` | `{theme, guidance, key, n}` → article ideas |
| `POST` | `/api/draft` | `{topic, style, key}` → rendered HTML + Markdown |

Requests are rate-limited per IP, because the scholarly APIs meter against this
server's address rather than yours.

## Note

Articles are written from **abstracts**, not full texts, and are not peer
reviewed. Treat one as a well-sourced starting point and follow the source links
before relying on any specific claim.

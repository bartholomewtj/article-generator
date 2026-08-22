# Deploying the backend

The web app at `index.html` is a front end only. The pipeline runs in Python, so
something has to host it.

```
index.html on GitHub Pages  ──POST /api/draft──▶  this backend on Render
   (static, holds your key)                        (stateless, holds nothing)
```

[`render.yaml`](../render.yaml) declares the service, so setup is a few clicks
rather than a dozen dashboard fields. Render deploys straight from GitHub —
there's no workflow and no token for GitHub to hold.

## One-time setup

**1. Sign up** at <https://render.com> with your GitHub account. No card needed
for the free tier.

**2. New → Blueprint**, pick `bartholomewtj/article-generator`, and let it read
`render.yaml`. It'll show one web service named `articlegen-api` on the Free plan.

**3. Apply.** The first build takes a few minutes — it's installing the
dependencies into the image.

**4. Check the name it gave you.** The URL is `https://<service-name>.onrender.com`,
and that subdomain is global, so `articlegen-api` may already be taken. If Render
made you pick something else, two files need to agree with it:

- `name:` in [`render.yaml`](../render.yaml)
- `API_BASE` in [`index.html`](../index.html)

**5. Optional but worth it:** in the Render dashboard, set `OPENALEX_MAILTO` to
your email. It puts requests into OpenAlex's "polite pool", which gets better
rate limits.

## Checking it worked

```bash
curl https://articlegen-api.onrender.com/api/health
```

`{"ok": true, "stateless": true}` means it's up, and `stateless: true` confirms
it isn't writing articles to disk. Allow up to a minute if it's been idle.

Then open the web app, paste an OpenRouter key into Settings, and generate one article.
That's the only test that exercises the whole chain.

## Configuration

`render.yaml` sets these; override them in the dashboard if needed.

**Public generation** needs `ARTICLEGEN_PUBLIC_OPENROUTER_KEY` set as a
**secret** in the Render dashboard (not in git). Visitors can then draft without
pasting a key. That path always writes with GPT-5.6 Luna; a crafted request
cannot select Opus on this bill. You pay OpenRouter ~2c per briefing. The hourly
caps (`ARTICLEGEN_RATE_LIMIT` 20/IP, `ARTICLEGEN_RATE_LIMIT_TOTAL` 120 everyone)
are the spend cap — 120 Luna drafts is roughly $2.40. If the secret is unset,
visitors must paste their own key, as before.

Do not put the secret in `render.yaml`'s `value:`. `sync: false` means Render
asks for it; leaving it blank disables public generation.

| Variable | Default | What it does |
|---|---|---|
| `ARTICLEGEN_STATELESS` | `1` | Render and return; never write to disk. Leave on for any shared host. |
| `ARTICLEGEN_ALLOWED_ORIGINS` | the Pages origin | Comma-separated origins allowed to call the API from a browser. |
| `ARTICLEGEN_RATE_LIMIT` | `20` | Requests per hour per IP. |
| `ARTICLEGEN_RATE_LIMIT_TOTAL` | `120` | Requests per hour across **all** visitors. The scholarly APIs meter against this server's one egress IP, so the per-IP limit alone does not protect the quota. |
| `ARTICLEGEN_TRUST_PROXY` | auto on Render | Read the caller's address from the rightmost `X-Forwarded-For` entry. Turn on only behind a proxy that rewrites the header — otherwise any caller can pick their own rate-limit bucket. Render is detected automatically. |
| `ARTICLEGEN_SOURCE_PROBE` | `1` | Check the scholarly APIs are answering before the first paid LLM call. Set `0` to skip. |
| `OPENALEX_MAILTO` | unset | Your email; OpenAlex "polite pool". |
| `SEMANTIC_SCHOLAR_API_KEY` | unset | Recommended (free; without it the source refuses nearly every call, #148). Set as a *secret*. |
| `ARTICLEGEN_PUBLIC_OPENROUTER_KEY` | unset | Host-paid public drafts (Luna). Set as a *secret*. Absent: visitors must paste their own key. |
| `ARTICLEGEN_GALLERY_TOKEN` | unset | GitHub token with **gist** scope only. Lets Share to gallery persist briefings in a public gist so they show on the landing page. A `contents` token is the wrong scope — a leak could rewrite the repo. Absent: the Share to gallery button stays hidden. |
| `ARTICLEGEN_ANALYTICS_GIST` | unset | Id of a secret gist to append run lines to. Uses the gallery's gist-scoped token. Absent: stderr only. |

## Run analytics

Every request to `/api/ideas`, `/api/draft` and `/api/gallery` writes one JSON
line to stderr recording how the request went:

```json
{"kind": "run", "t": "2026-08-23T04:12:00Z", "endpoint": "/api/draft", "method": "POST", "status": 200, "ok": true, "ms": 41250, "stateless": true, "commit": "a1b2c3d", "key": "public", "model": "openai/gpt-5.6-luna", "screened": 40, "cited": 10, "cited_direct": 7, "direct": 14, "related": 18, "tangential": 8, "full_text": 4, "full_text_via": {"papers": 3, "europe_pmc": 1}, "named_added": 2, "named_queries": 2, "style_errors": 0, "style_rules": [], "figures": 6, "unverified": 0, "misattributed": 0, "working_draft": false}
```

No topic, theme, search term, query string, article text, API key or IP
address is ever logged: records contain counts, statuses, durations and
rule names only.

Read the log in the Render dashboard's **Logs** tab, or filter a downloaded log:

```bash
grep '"kind": "run"' render.log | jq -s 'map(select(.endpoint=="/api/draft"))'
```

### Durable history in a private gist

Render's live log clears on restart or redeploy. To keep a durable history,
create a secret gist and point the server at it:

```bash
gh gist create --secret runs.jsonl
```

Set the returned gist id as `ARTICLEGEN_ANALYTICS_GIST` in the Render
dashboard. The server appends each run line to `articlegen-runs.jsonl` in that
gist using `ARTICLEGEN_GALLERY_TOKEN` (reusing the same `gist`-scoped token).
Lines are capped at 1,000 (~400 KB).

**Secret gists are unlisted, not access-controlled** — anyone who knows the URL
can read the file. That is safe here only because the log contains counts and
fixed vocabulary, never user topics or personal data.

## Two things about the free tier

**It sleeps after 15 minutes idle** and takes up to a minute to wake. That hurts
less here than it normally would: the page is on GitHub Pages and loads
instantly, and the backend is only touched when someone clicks Generate — which
already takes 40–90 seconds behind a progress bar. A cold start extends a wait
the visitor is already committed to. The front end says as much if a request
can't get through.

**512 MB RAM and 0.1 CPU** is enough, because the pipeline is I/O-bound. It
spends nearly all its time waiting on the model provider and the scholarly APIs rather than
computing.

## Why stateless

With `ARTICLEGEN_STATELESS=1` the server renders each article, returns it, and
keeps nothing on disk. Turning it off on a shared host would put every visitor's
article into one `drafts/` directory, readable by any other visitor at a
guessable URL and listed by topic in the queue index — and nobody generating an
article would have any reason to expect that. Local runs (`articlegen web`)
leave it off, which is what makes `articlegen queue` work.

The public gallery is the one exception, and it is opt-in: Share to gallery
writes a public gist (not `drafts/`, not this repo). Generating does not
publish. The landing page lists that gist directly, so a sleeping Render does
not hide other people's briefings.

## Running the image locally

```bash
docker build -t articlegen .
docker run --rm -p 8000:8000 -e ARTICLEGEN_ALLOWED_ORIGINS=http://localhost:8085 articlegen
```

Then serve `index.html` from another origin and, in the browser console:

```js
localStorage.setItem('articlegen_api_base', 'http://127.0.0.1:8000'); location.reload();
```

That reproduces the hosted setup — separate origins, CORS in play — on one machine.

## Moving hosts later

The Dockerfile is host-neutral: it binds whatever `PORT` the host injects. Fly,
Cloud Run and Railway all run it unchanged. Only two things are Render-specific,
`render.yaml` and the `API_BASE` line in `index.html`.

Hugging Face Spaces was the original target and is a dead end for this. Free CPU
Spaces need a payment method on the account; without one the Space gets created
but stays pinned at `Quota exceeded for flavor cpu-basic (requested=1): current=0,
limit=0` and never starts. Verifying your email doesn't lift it.

Fly.io is the better free tier technically — a Sydney region and 1–3 second wake
against Render's ~50 seconds — but its docs are explicit that "all organizations
require a credit card on file", so it's ruled out on the same grounds.

# Deploying the backend

The web app at `index.html` is a front end only. The pipeline runs in Python, so
something has to host it. This directory holds what's needed to put it on a
[Hugging Face Space](https://huggingface.co/spaces) — free, no card, and it
tolerates the long requests a draft takes (roughly 40–90 seconds).

```
index.html on GitHub Pages  ──POST /api/draft──▶  this backend on a HF Space
   (static, holds your key)                          (stateless, holds nothing)
```

## One-time setup

**1. Create the Space.** At <https://huggingface.co/new-space>:

- Owner: your account · Name: `articlegen`
- SDK: **Docker** → *Blank*
- Visibility: **Public** (private Spaces can't be called from a browser)

**2. Make an access token.** <https://huggingface.co/settings/tokens> → *New
token* → type **Write**. Copy it.

**3. Give it to GitHub.** In the repo → Settings → Secrets and variables →
Actions → *New repository secret*:

- Name: `HF_TOKEN` · Value: the token

If your Space isn't `bartholomewtj/articlegen`, also add a *variable* (not a
secret) named `HF_SPACE` with your `owner/name`.

**4. Deploy.** Push to the default branch, or run the workflow by hand:

```bash
gh workflow run "Deploy backend to Hugging Face Space"
```

The first build takes a few minutes. Watch it on the Space's **Logs** tab.

**5. Point the front end at it.** If your Space URL differs from the default,
edit `API_BASE` in [`index.html`](../index.html):

```js
return 'https://<owner>-<space-name>.hf.space';
```

Note the URL form: `huggingface.co/spaces/owner/name` is the *page*, but the API
is served from `owner-name.hf.space`.

**6. Allow your origin.** The backend refuses browser calls from anywhere it
doesn't recognise. `ARTICLEGEN_ALLOWED_ORIGINS` in the [`Dockerfile`](../Dockerfile)
is set to `https://bartholomewtj.github.io` — change it if you serve the page
elsewhere. It's a comma-separated list.

## Checking it worked

```bash
curl https://<owner>-<space-name>.hf.space/api/health
```

`{"ok": true, "stateless": true}` means it's up, and `stateless: true` confirms
it isn't writing articles to disk.

Then open the web app, paste a Groq key into Settings, and generate one article
end to end. That's the only test that exercises the real pipeline.

## Configuration

Set these as Space *variables* (Settings → Variables and secrets) to override
the Dockerfile defaults. **None of them should ever be an API key** — the
backend deliberately has none of its own; visitors bring their own.

| Variable | Default | What it does |
|---|---|---|
| `ARTICLEGEN_STATELESS` | `1` | Render and return; never write to disk. Leave on for any shared host. |
| `ARTICLEGEN_ALLOWED_ORIGINS` | the Pages origin | Comma-separated origins allowed to call the API from a browser. |
| `ARTICLEGEN_RATE_LIMIT` | `20` | Requests per hour per IP. |
| `OPENALEX_MAILTO` | unset | Your email. Puts OpenAlex requests in its "polite pool" for better rate limits. |
| `SEMANTIC_SCHOLAR_API_KEY` | unset | Optional; raises Semantic Scholar's rate limit. Set as a *secret*, not a variable. |

## Why stateless

With `ARTICLEGEN_STATELESS=1` the server renders each article, returns it, and
keeps nothing. Turning it off on a shared host would put every visitor's article
into one `drafts/` directory, readable by any other visitor at a guessable URL
and listed by topic in the queue index — and nobody generating an article would
have any reason to expect that. Local runs (`articlegen web`) leave it off,
which is what makes `articlegen queue` work.

## Running the image locally

```bash
docker build -t articlegen .
docker run --rm -p 7860:7860 -e ARTICLEGEN_ALLOWED_ORIGINS=http://localhost:8085 articlegen
```

Then serve `index.html` from another origin and, in the browser console:

```js
localStorage.setItem('articlegen_api_base', 'http://127.0.0.1:7860'); location.reload();
```

That reproduces the hosted setup — separate origins, CORS in play — on one machine.

## Notes

- **Free Spaces sleep** after about 48 hours idle and take a moment to wake. The
  web app already says so when a request can't get through.
- **The Space holds no keys.** If you ever add one to make generation work
  without a visitor's key, it becomes a free LLM endpoint for anyone who finds
  it. Don't, unless you also add auth and a hard spend cap.

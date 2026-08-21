# articlegen

[![Tests](https://github.com/bartholomewtj/article-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/bartholomewtj/article-generator/actions/workflows/tests.yml)
[![Deployment health](https://github.com/bartholomewtj/article-generator/actions/workflows/health.yml/badge.svg)](https://github.com/bartholomewtj/article-generator/actions/workflows/health.yml)

Turn a topic into a **sourced evidence briefing** — the question, what the
evidence shows, what remains open, and three papers to open — as one
self-contained HTML page (plus Markdown) you can send as a link. Every claim is
cited to a real paper, and every figure is checked back against the source it
came from. Three stages: pick a question → research collated automatically →
briefing prepared for your review.

`articlegen draft --long` still writes the journal-style Review; that path is
kept for later, not deleted.

## 🚀 Live site

🔗 **[Open the site](https://bartholomewtj.github.io/article-generator/)**

📄 **[Read a finished article](https://bartholomewtj.github.io/article-generator/drafts/)**
— no key and no account needed. Generating is free on the public site (GPT-5.6
Luna, host-paid, rate-limited). Pasting your own OpenRouter key is optional.

---

## Use it from your phone (recommended)

1. **Open the site:** [https://bartholomewtj.github.io/article-generator/](https://bartholomewtj.github.io/article-generator/) (or run `articlegen web --open` locally).
2. **Type a theme:** Enter your topic (e.g. `renewable energy storage`) and optional audience/style notes. On the public site you do not need a key.
3. **Choose a draft:** Tap any generated **Draft Idea Card** to launch the evidence-grounded research pipeline.
4. **Read & Share:** View the rendered article and tap **Share**, **Copy Link**, or **QR Code**.

The public site writes with **GPT-5.6 Luna**. It is free to you; the host pays, and an hourly cap applies to everyone together. Settings still accepts an [OpenRouter API key](https://openrouter.ai/keys) if you want to use your own credit instead of the shared cap. A remembered key stays in the browser — see [Where your key is kept](#where-your-key-is-kept). The web app offers OpenRouter only; the CLI below also supports Anthropic and a Claude subscription.

**How it fits together.** The page is a front end only — the pipeline below is
the same Python that the CLI runs, on a small backend the page calls. There is
no second implementation: an article generated from your phone goes through the
same relevance gate, prose-style enforcement and statistic verification as one
generated from the terminal. The hosted backend keeps no articles: it renders,
returns, and forgets. Public generation uses a host-held OpenRouter key for Luna
only; a visitor key is sent per request and never stored. Your drafts live in
your own browser. See [`deploy/`](deploy/README.md) to host the backend yourself.

### Where your key is kept

The backend never stores your key. The browser does, and where it puts it
matters more than it looks:

- **Default — this tab only.** The key goes in `sessionStorage` and is gone when
  you close the tab. You paste it again next visit. Nothing persistent is left
  behind.
- **"Remember this key" — the whole domain.** The key goes in `localStorage`,
  which browsers scope to the **origin**, not to the path. Every GitHub Pages
  site published under `bartholomewtj.github.io` shares that one origin, so a
  remembered key is readable by any other project published there — including
  ones added years from now — and by anyone with push access to those repos.

This is a paid key with no daily cap, so a leak is a real bill. If you use the
hosted page on a shared or public machine, leave the box unticked, and revoke
the key at [openrouter.ai/keys](https://openrouter.ai/keys) if you have any
doubt. Running `articlegen web` locally avoids the shared origin entirely.

**Provider key setup:**

- **OpenRouter** (the default; **roughly 50c–$1 an article**): create a key at
  https://openrouter.ai/keys and set `OPENROUTER_API_KEY`.
- **Claude** (opt-in; **roughly $1–2 an article**): set `ANTHROPIC_API_KEY`.
- **Your Claude subscription** (opt-in; **no key and no per-article cost**): if
  you already pay for Claude and have
  [Claude Code](https://claude.com/claude-code) installed and signed in,
  `--model cli:opus` or `--model cli:sonnet` drafts through it. A Claude.ai
  subscription does not come with an API key, and this is the way to use one
  anyway. Command line only — see the caveats below.

**OpenRouter is used by default** — with an `OPENROUTER_API_KEY` set it runs
automatically, and it takes priority if an Anthropic key is also present. To use
another provider, set `ARTICLEGEN_PROVIDER=anthropic` (or `claude-cli`). Models:
`anthropic/claude-opus-5` on OpenRouter (CLI default), `openai/gpt-5.6-luna` on
the public web app, `claude-fable-5` on Anthropic, `cli:opus` on your
subscription, all overridable with `--model`.

**This block is the single place the defaults are described in prose.** Change a
default in `llm.py` and change it here; nowhere else should restate them. The
CLI default (`OPENROUTER_DEFAULT_MODEL`) and the public web default
(`OPENROUTER_PUBLIC_MODEL`) are two constants on purpose.

**Groq was removed.** It used to be the free default, on a 100,000 tokens/day
tier that allowed 4–7 articles. Its real cost was a 12,000 tokens/**minute**
ceiling that counted the reserved output as well as the prompt, so a Groq draft
could never be shown a single open-access full text — the abstracts had to be
trimmed to fit. Every draft is now grounded in full text where one exists. If
you want the same Llama model, `--model meta-llama/llama-3.3-70b-instruct`
reaches it through OpenRouter for well under a cent an article, untrimmed.

**About `cli:` — what you give up.** It costs nothing beyond the subscription
you already pay for, and it is the only option that needs no key. Two real
trade-offs. It runs on your machine only: the hosted web app cannot use it,
because a shared server has no Claude Code and no subscription to draw on. And
both API providers can *force* the model to return correctly-shaped data, which
this cannot — it can only ask. When a reply comes back as prose instead,
`articlegen` asks once more and then gives up on that article. It is the right
pick for drafting at your own desk, and the wrong one for anything automated.

**The public web app is the exception: generating there is free to the visitor.**
It writes with GPT-5.6 Luna on the host's key, at roughly **2c an article** to
the host, inside the hourly rate limits. A visitor key is optional.

**CLI and a pasted key still cost real money.** OpenRouter's CLI default is
Claude Opus 5, at roughly **50c–$1 an article**. The Anthropic default is Fable
5, at roughly **$1–2**. Those are per article, and a failed run still bills you.
Neither has a daily cap, which is the point — but it also means nothing stops a
bad afternoon costing $20.

Cheaper options on the CLI, if writing quality is not what you're trying to fix:

- `--model openai/gpt-5.6-luna` — the public-site model, a few cents an article.
- `--model meta-llama/llama-3.3-70b-instruct` — well under a cent an article.
- `--model anthropic/claude-sonnet-5` — a cheaper Claude than either default.
- `--model cli:opus` — free, on a Claude subscription you already pay for.

Any OpenRouter catalogue model works with `--model`.

Set a free `SEMANTIC_SCHOLAR_API_KEY`. Without it, Semantic Scholar's
shared keyless limit refuses effectively every call: measured over four
runs spanning an hour, the first query of every run came back HTTP 429 and
the source was then skipped for the rest of that run, so those drafts were
written on the other databases alone. `OPENALEX_MAILTO` is genuinely
optional — it puts OpenAlex requests in its "polite pool".

## The same workflow, locally

```
1. articlegen ideas "<theme>"      # briefing questions, pick one  ◀── you choose
2. articlegen draft "<title>"      # research + briefing, auto     ──▶ drafts/
3. review drafts/index.html                                        ◀── you review
```

Two human gates (choose a question, review the briefing); everything in between
is automatic. `draft --long` writes the parked Review instead. Under the hood,
the `draft` stage:

```
title ──▶ the model plans search queries
      ──▶ Semantic Scholar + OpenAlex + Europe PMC + arXiv return papers
          (with abstracts)
      ──▶ each source is labelled direct / related / background
      ──▶ the model writes the briefing, citing sources inline as [1], [2, 3]…
      ──▶ rendered to drafts/<date>-<slug>.html  +  .md, listed in drafts/index.html
```

- **A briefing you can send.** Article-type label **Evidence briefing**, the
  question, a short answer, 5–8 findings with citations, what remains open,
  three papers to open, superscript Vancouver citations, a **Methods** statement
  of the actual search, and standard back matter. `draft --long` is the parked
  journal-style Review (Box 1, Fig. 1, Key points, Introduction → Conclusions).
  Prose conventions live in [`docs/journal-style.md`](docs/journal-style.md).
- **Journal prose, checked rather than requested.** The house style is the
  register of a Nature Reviews or Science Review piece: active voice, tense that
  carries evidential weight (present for established knowledge, past for what one
  study found), findings attributed to their design, and hedging at the density
  corpus studies find in real research articles. `style.py` checks all of it
  deterministically after drafting — second person, contractions, boosters
  ("clearly", "striking"), claims of proof and under-hedging are errors — and any
  failures go back to the model once for a targeted revision.
- **Evidence-grounded, and honest about it.** The writer sees real abstracts —
  and, for the most relevant sources when an open-access copy can be
  retrieved, the full text too — and cites them; every superscript links to a
  numbered reference with a link back to the paper (DOI when available). Before
  writing, each source is scored for how *directly* it addresses the exact topic
  — so the article can say when direct evidence is thin instead of quietly
  substituting adjacent work. A deterministic check flags any statistic absent
  from the material the writer was actually shown, and Table 1 is built from
  the fetched records rather than written by the model. Clinical
  topics get a "not medical advice" disclaimer.
- **No fabricated apparatus.** No invented journal name, volume, DOI, received
  dates or affiliations. The masthead says "Not peer reviewed" and the back
  matter says a machine wrote it.
- **Self-contained.** One HTML file, inlined CSS and SVG, no external requests.
  Works offline, prints cleanly, and adapts to light or dark mode.

## Install

```bash
pip install -r requirements.txt      # or: pip install -e .
```

Set credentials for one provider:

```bash
export OPENROUTER_API_KEY=sk-or-v1-...  # OpenRouter — https://openrouter.ai/keys
# or
export ANTHROPIC_API_KEY=sk-ant-...   # Claude (or: ant auth login)
# or neither — draft on a Claude subscription with: --model cli:opus
```

The scholarly APIs work without keys, but Semantic Scholar's shared tier
refuses nearly every call — setting the [free API key](https://www.semanticscholar.org/product/api)
is the fix worth doing on any machine that runs drafts (a run without it still
works on the remaining databases, and Methods will say so):

```bash
export SEMANTIC_SCHOLAR_API_KEY=...
export OPENALEX_MAILTO=you@example.com  # optional, "polite pool"
```

## Use

```bash
# 1. Generate ideas from a broad theme; skim them and pick one
python -m articlegen ideas "renewable energy storage"

# 2. Research + draft the idea you picked (opens it when done)
python -m articlegen draft "Why gravity batteries could outlast lithium" --open

# 3. Review everything you've drafted from one page
python -m articlegen queue --open

# Preview the visual design instantly, with no API calls or network
python -m articlegen demo --open
```

Or, after `pip install -e .`, drop the `python -m`: `articlegen ideas "..."`.

Each `draft` run writes three things into `drafts/`:
`<date>-<slug>.html` (the styled article), `<date>-<slug>.md` (same content as
Markdown, for easy editing), and refreshes `index.html` (your review queue).

### Commands & options

| Command | Key options |
|---------|-------------|
| `ideas <theme>` | `-n` (how many, default 6), `-o` (output .md path) |
| `draft <title>` | `--open`, `--style "<audience/tone>"`, `--max-papers N` (default 40), `--name <stem>` |
| `queue` | `--open` |
| `demo` | `--open`, `-o` |

`--model` (default `claude-fable-5`) is global: `articlegen --model … draft "…"`.

## Notes & limitations

- Coverage depends on what the open scholarly APIs return; niche or very recent
  topics may surface fewer papers. Under heavy shared rate limits a run can come
  back empty — wait a minute and retry, or add the optional keys above.
- **Four databases are searched, and two of them are specialised.** Europe PMC
  covers biomedicine and arXiv covers computing, physics, engineering and
  statistics, so a given topic usually draws on one or the other rather than
  both. A clinical topic getting nothing from arXiv is normal. Papers found only
  on arXiv are preprints — the reference list labels them "arXiv preprint", and
  a preprint has not been peer reviewed.
- Search results are cached for 24 hours, so re-running the same topic is
  instant and costs nothing against those shared limits. This matters more than
  it sounds: the free tiers refuse often enough that a second attempt at the
  same query is likelier to fail than to find anything new.
- The article is AI-written from **abstracts, plus the open-access full texts**
  of the most relevant sources when an open-access copy can be retrieved. The
  Methods section and Table 1's Read column state exactly how deeply each
  source was read. Treat it as a well-sourced starting point: follow the source
  links before relying on any specific claim.

### Full text via the `papers` CLI (optional)

With the `papers` CLI installed (from the separate `paperfetch` project),
full text is retrieved from any open-access copy across Unpaywall, OpenAlex,
Semantic Scholar, and preprint servers — not just Europe PMC — so non-biomedical
topics and arXiv papers stop being abstract-only.

- **Install:** `pip install -e` the private `paperfetch` repository, then set
  `PAPERS_MAILTO=you@example.com` to a real email address (scholarly APIs require
  it and block made-up addresses; defaults to `OPENALEX_MAILTO` if unset).
- **Executable path:** If `papers` is not on your PATH, set
  `ARTICLEGEN_PAPERS_CMD="python -m papers"`.
- **Optional:** Without `papers`, articlegen behaves exactly as before,
  retrieving full text from Europe PMC only.
- **Hosted deployment:** The hosted backend on Render does not have `paperfetch`
  installed yet, so the public web app remains Europe PMC only.

## Layout

```
articlegen/
  cli.py        subcommands (ideas / draft / queue / demo / web)
  pipeline.py   the draft pipeline — every caller, CLI and web, runs this one
  web.py        HTTP server + JSON API behind the web front end
  llm.py        provider layer: OpenRouter or Claude, auto-detected from keys
  ideas.py      LLM call: theme -> shortlist of briefing questions
  writer.py     LLM calls: plan queries, write the briefing (write_article is --long)
  sources.py    Semantic Scholar + OpenAlex + Europe PMC + arXiv fetching,
                dedupe, ranking
  paperfetch.py optional: full text via the separate papers CLI (paperfetch)
  render.py     structured article -> journal-format HTML, Markdown, drafts/ index
  verify.py     deterministic check of every figure against the abstracts
  style.py      deterministic check of the prose against journal writing conventions
  demo.py       built-in sample for `articlegen demo`
docs/
  journal-style.md   the journal conventions we follow, and their sources
tests/
  test_offline.py             pure-logic tests (no keys, no network)
  test_journal_conformance.py the journal conventions, as assertions over
                              rendered fixtures — run both before shipping
```

## Tests

```bash
python tests/test_offline.py             # provider, citations, render blocks
python tests/test_journal_conformance.py # journal conventions over 5 fixtures
```

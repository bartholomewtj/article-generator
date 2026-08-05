# articlegen

A **three-stage workflow** for going from a vague interest to a review-ready
article: **generate ideas → research collated automatically → draft prepared for
your review** — as a self-contained single-page HTML file (plus Markdown),
grounded in real journal articles rather than the model's memory.

## 🚀 Live Working Article Generator
Open the working web app directly in your browser:
🔗 **[Live Article Generator Web Site](https://bartholomewtj.github.io/article-generator/)**

---

## Use it from your phone (recommended)

1. **Open the site:** [https://bartholomewtj.github.io/article-generator/](https://bartholomewtj.github.io/article-generator/) (or run `articlegen web --open` locally).
2. **Add a key:** Open Settings (⚙️) and paste a free [Groq API key](https://console.groq.com/keys). It stays in your browser and is sent only with the request you make.
3. **Type a theme:** Enter your topic (e.g. `renewable energy storage`) and optional audience/style notes.
4. **Choose a draft:** Tap any generated **Draft Idea Card** to launch the evidence-grounded research pipeline.
5. **Read & Share:** View the rendered article and tap **Share**, **Copy Link**, or **QR Code**.

**How it fits together.** The page is a front end only — the pipeline below is
the same Python that the CLI runs, on a small backend the page calls. There is
no second implementation: an article generated from your phone goes through the
same relevance gate, prose-style enforcement and statistic verification as one
generated from the terminal. The hosted backend keeps nothing: it renders your
article, returns it, and forgets it. Your drafts live in your own browser.
See [`deploy/`](deploy/README.md) to host the backend yourself.

**Provider key setup:**

- **Groq** (the default; free tier, fast inference): create a key at
  https://console.groq.com/keys and set `GROQ_API_KEY`.
- **OpenRouter** (opt-in; same model as Groq, no daily cap): create a key at
  https://openrouter.ai/keys and set `OPENROUTER_API_KEY`.
- **Claude** (opt-in; best writing quality, paid API): set `ANTHROPIC_API_KEY`.

**Groq is used by default** — with a `GROQ_API_KEY` set it runs
automatically, and it takes priority even if the other keys are also present.
To use another provider, set `ARTICLEGEN_PROVIDER=openrouter` (or `anthropic`).
Models: `llama-3.3-70b-versatile` on Groq,
`meta-llama/llama-3.3-70b-instruct` on OpenRouter, `claude-opus-5` on
Anthropic, all overridable with `--model`.

**Groq's free tier allows roughly 4–7 articles a day** (100,000 tokens/day; one
article costs 14–23k, and failed attempts still count). It's the right choice
for trying this out. Once that cap is the thing stopping you, OpenRouter runs
the *same* Llama 3.3 70B from prepaid credit with no daily allowance, for well
under a cent per article — it fixes the quota, not the writing. Claude is the
one to pick when the prose quality is what you want to improve; it also has no
daily cap. Any OpenRouter catalogue model works with `--model`, so
`--model anthropic/claude-sonnet-5` runs Claude billed through your OpenRouter
credit instead of a separate Anthropic account.

Optional extras: a `SEMANTIC_SCHOLAR_API_KEY` secret and an `OPENALEX_MAILTO`
environment variable raise the scholarly APIs' rate limits.

## The same workflow, locally

```
1. articlegen ideas "<theme>"      # generate ideas, pick one   ◀── you choose
2. articlegen draft "<title>"      # research + draft, auto      ──▶ drafts/ queue
3. review drafts/index.html                                      ◀── you review
```

Two human gates (choose an idea, review the draft); everything in between is
automatic. Under the hood, the `draft` stage:

```
title ──▶ the model plans search queries
      ──▶ Semantic Scholar + OpenAlex return papers (with abstracts)
      ──▶ each source is labelled direct / related / background
      ──▶ the model writes the review, citing sources inline as [1], [2, 3]…
      ──▶ rendered to drafts/<date>-<slug>.html  +  .md, listed in drafts/index.html
```

- **Formatted like a journal Review article.** Article-type label, a
  Nature-style unstructured abstract, a Key points box, superscript Vancouver
  citations that collapse runs (`…as reported¹,³–⁵`), numbered display items
  (**Box 1** for the key study, **Fig. 1** for the composition of the evidence
  base, **Table 1** for the cited records), a **Methods** statement of the actual
  search, and standard back matter — Evidence assessment with Limitations,
  Glossary, References, Data availability, Competing interests. The conventions
  and where each came from are documented in
  [`docs/journal-style.md`](docs/journal-style.md).
- **Journal prose, checked rather than requested.** The house style is the
  register of a Nature Reviews or Science Review piece: active voice, tense that
  carries evidential weight (present for established knowledge, past for what one
  study found), findings attributed to their design, and hedging at the density
  corpus studies find in real research articles. `style.py` checks all of it
  deterministically after drafting — second person, contractions, boosters
  ("clearly", "striking"), claims of proof and under-hedging are errors — and any
  failures go back to the model once for a targeted revision.
- **Evidence-grounded, and honest about it.** The writer only sees real
  abstracts and cites them; every superscript links to a numbered reference with
  a link back to the paper (DOI when available). Before writing, each source is
  scored for how *directly* it addresses the exact topic — so the article can say
  when direct evidence is thin instead of quietly substituting adjacent work. A
  deterministic check flags any statistic absent from the source abstracts, and
  Fig. 1 and Table 1 are built from the fetched records rather than written by
  the model. Clinical topics get a "not medical advice" disclaimer.
- **No fabricated apparatus.** No invented journal name, volume, DOI, received
  dates or affiliations. The masthead says "Not peer reviewed" and the back
  matter says a machine wrote it.
- **Self-contained.** One HTML file, inlined CSS and SVG, no external requests.
  Works offline, prints cleanly, and adapts to light or dark mode.

## Install

```bash
pip install -r requirements.txt      # or: pip install -e .
```

Set credentials for either provider:

```bash
export GROQ_API_KEY=gsk_...           # Groq — free key at https://console.groq.com/keys
# or
export OPENROUTER_API_KEY=sk-or-v1-...  # OpenRouter — https://openrouter.ai/keys
# or
export ANTHROPIC_API_KEY=sk-ant-...   # Claude (or: ant auth login)
```

The scholarly APIs need no key, but you can raise their rate limits:

```bash
export SEMANTIC_SCHOLAR_API_KEY=...   # optional
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
| `draft <title>` | `--open`, `--style "<audience/tone>"`, `--max-papers N`, `--name <stem>` |
| `queue` | `--open` |
| `demo` | `--open`, `-o` |

`--model` (default `claude-opus-5`) is global: `articlegen --model … draft "…"`.

## Notes & limitations

- Coverage depends on what the open scholarly APIs return; niche or very recent
  topics may surface fewer papers. Under heavy shared rate limits a run can come
  back empty — wait a minute and retry, or add the optional keys above.
- Search results are cached for 24 hours, so re-running the same topic is
  instant and costs nothing against those shared limits. This matters more than
  it sounds: the free tiers refuse often enough that a second attempt at the
  same query is likelier to fail than to find anything new.
- The article is AI-written from **abstracts**, not full texts. Treat it as a
  well-sourced starting point: follow the source links before relying on any
  specific claim.

## Layout

```
articlegen/
  cli.py       subcommands (ideas / draft / queue / demo / web)
  pipeline.py  the draft pipeline — every caller, CLI and web, runs this one
  web.py       HTTP server + JSON API behind the web front end
  llm.py       provider layer: Groq, OpenRouter or Claude, auto-detected from keys
  ideas.py     LLM call: theme -> shortlist of article ideas
  writer.py    LLM calls: plan queries, write the article (structured JSON)
  sources.py   Semantic Scholar + OpenAlex fetching, dedupe, ranking
  render.py    structured article -> journal-format HTML, Markdown, drafts/ index
  verify.py    deterministic check of every figure against the abstracts
  style.py     deterministic check of the prose against journal writing conventions
  demo.py      built-in sample for `articlegen demo`
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

# articlegen

A **three-stage workflow** for going from a vague interest to a review-ready
article: **generate ideas → research collated automatically → draft prepared for
your review** — as a self-contained single-page HTML file (plus Markdown),
grounded in real journal articles rather than the model's memory.

## Use it from your phone (recommended)

You can run the interactive **Mobile Web Site** (hosted on GitHub Pages or locally via `articlegen web`):

1. **Open the site on mobile:** Open `https://<user>.github.io/article-generator/` (or run `articlegen web --open` locally).
2. **Type a theme:** Enter your topic (e.g. `renewable energy storage`) and optional audience/style notes.
3. **Choose a draft:** Tap any generated **Draft Idea Card** to launch the automated evidence-grounded research pipeline.
4. **Read & Share:** View the rendered article and tap **Share** (native mobile share sheet), **Copy Link**, or **QR Code** to easily share with others.

Alternatively, you can use the **GitHub mobile app** issue workflow:

1. **Generate ideas:** Open a new issue titled `theme: <your theme>`. A bot comments back with numbered draft ideas.
2. **Pick one:** Reply with `draft 3` (or `draft "Your title"`).
3. **Review:** The bot researches, drafts, commits, and comments back with review links.

**One-time setup — add an AI provider key** (repo → Settings → Secrets and
variables → Actions):

- **Gemini** (the default; free tier, no card needed): create a key at
  https://aistudio.google.com/ and add it as a `GEMINI_API_KEY` secret.
- **Claude** (opt-in; best writing quality, paid API): add an
  `ANTHROPIC_API_KEY` secret.

**Gemini is used by default** — with a `GEMINI_API_KEY` set it runs
automatically, and it takes priority even if an `ANTHROPIC_API_KEY` is also
present. To use Claude instead, set a repository *variable*
`ARTICLEGEN_PROVIDER` = `anthropic` (or leave only the Anthropic key set).
Models: `gemini-2.5-flash` on Google, `claude-opus-4-8` on Anthropic, both
overridable with `--model`.

Optional extras: a `SEMANTIC_SCHOLAR_API_KEY` secret and an `OPENALEX_MAILTO`
repository *variable* raise the scholarly APIs' rate limits.

Only users with write access to the repo can trigger the workflows, so
strangers can't spend your API credits on a public repo.

## The same workflow, locally

```
1. articlegen ideas "<theme>"      # generate ideas, pick one   ◀── you choose
2. articlegen draft "<title>"      # research + draft, auto      ──▶ drafts/ queue
3. review drafts/index.html                                      ◀── you review
```

Two human gates (choose an idea, review the draft); everything in between is
automatic. Under the hood, the `draft` stage:

```
title ──▶ Claude plans search queries
      ──▶ Semantic Scholar + OpenAlex return papers (with abstracts)
      ──▶ Claude writes the article, citing sources inline as [1], [2, 3]…
      ──▶ rendered to drafts/<date>-<slug>.html  +  .md, listed in drafts/index.html
```

- **Evidence-grounded, and honest about it.** The writer only sees real
  abstracts and cites them; every `[n]` links to a Sources list with a link
  back to the paper (DOI when available). Before writing, each source is scored
  for how *directly* it addresses the exact topic — so the article can say when
  direct evidence is thin instead of quietly substituting adjacent work. Every
  draft carries a **Featured study** box (method + results of the single most
  relevant paper), an **Evidence quality** box (how many sources are directly
  on-topic, the date range), and a deterministic check that flags any statistic
  not found in the source abstracts as "verify against the full text." Clinical
  topics get a "not medical advice" disclaimer.
- **Readable.** House style aimed at a smart general audience — a hook, short
  sections, pull quotes, a "Key takeaways" box.
- **Self-contained.** One HTML file, inlined CSS, no external requests. Works
  offline, prints cleanly, and adapts to light or dark mode.

## Install

```bash
pip install -r requirements.txt      # or: pip install -e .
```

Set credentials for either provider:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # Claude (or: ant auth login)
# or
export GEMINI_API_KEY=...             # Gemini — free key at aistudio.google.com
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

`--model` (default `claude-opus-4-8`) is global: `articlegen --model … draft "…"`.

## Notes & limitations

- Coverage depends on what the open scholarly APIs return; niche or very recent
  topics may surface fewer papers. Under heavy shared rate limits a run can come
  back empty — wait a minute and retry, or add the optional keys above.
- The article is AI-written from **abstracts**, not full texts. Treat it as a
  well-sourced starting point: follow the source links before relying on any
  specific claim.

## Layout

```
articlegen/
  cli.py       subcommands (ideas / draft / queue / demo) + orchestration
  llm.py       provider layer: Claude or Gemini, auto-detected from keys
  ideas.py     LLM call: theme -> shortlist of article ideas
  writer.py    LLM calls: plan queries, write the article (structured JSON)
  sources.py   Semantic Scholar + OpenAlex fetching, dedupe, ranking
  render.py    structured article -> styled HTML, Markdown, and drafts/ index
  bot.py       GitHub Actions glue: ideas comment + `draft N` resolution
  demo.py      built-in sample for `articlegen demo`
.github/workflows/
  ideas.yml    'theme: ...' issue opened  -> ideas posted as a comment
  draft.yml    'draft N' comment          -> draft committed + review link
```

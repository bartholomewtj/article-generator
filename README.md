# articlegen

A **three-stage workflow** for going from a vague interest to a review-ready
article: **generate ideas → research collated automatically → draft prepared for
your review** — as a self-contained single-page HTML file (plus Markdown),
grounded in real journal articles rather than the model's memory.

## The workflow

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

- **Evidence-grounded.** The writer only sees real abstracts and is instructed
  to cite them and not invent sources. Every `[n]` links to a Sources list at
  the foot of the page, with a link back to the original paper (DOI when
  available).
- **Readable.** House style aimed at a smart general audience — a hook, short
  sections, pull quotes, a "Key takeaways" box.
- **Self-contained.** One HTML file, inlined CSS, no external requests. Works
  offline, prints cleanly, and adapts to light or dark mode.

## Install

```bash
pip install -r requirements.txt      # or: pip install -e .
```

Set your Anthropic credentials (either works):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or: ant auth login
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
  ideas.py     Claude call: theme -> shortlist of article ideas
  writer.py    Claude calls: plan queries, write the article (structured JSON)
  sources.py   Semantic Scholar + OpenAlex fetching, dedupe, ranking
  render.py    structured article -> styled HTML, Markdown, and drafts/ index
  demo.py      built-in sample for `articlegen demo`
```

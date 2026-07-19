# articlegen

Turn a topic or idea into a **readable, visually polished, single-page HTML
article** — grounded in real journal articles, not just the model's memory.

Give it a subject; it finds relevant peer-reviewed papers, has Claude write an
engaging popular-science piece that cites them, and renders everything into one
self-contained `.html` file you can open in any browser or print to PDF.

## How it works

```
topic ──▶ Claude plans search queries
       ──▶ Semantic Scholar + OpenAlex return papers (with abstracts)
       ──▶ Claude writes the article, citing sources inline as [1], [2, 3]…
       ──▶ rendered into a styled, self-contained single-page HTML file
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
# Basic
python -m articlegen "why do we dream?"

# Choose the output file and tune the audience
python -m articlegen "CRISPR gene editing" -o crispr.html --style "for high-school students"

# Preview the visual design instantly, with no API calls or network
python -m articlegen --demo "what your brain does while you sleep" -o demo.html
```

Or, after `pip install -e .`, just `articlegen "your topic"`.

### Options

| Flag | Description |
|------|-------------|
| `-o, --output` | Output HTML path (default: a slug of the topic) |
| `--style` | Free-text audience/tone note, e.g. `"skeptical, for practitioners"` |
| `--max-papers` | Max candidate papers fed to the writer (default 20) |
| `--model` | Claude model (default `claude-opus-4-8`) |
| `--demo` | Render a built-in sample — no API calls, to preview the design |

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
  cli.py       argument parsing + orchestration
  writer.py    Claude calls: plan queries, write the article (structured JSON)
  sources.py   Semantic Scholar + OpenAlex fetching, dedupe, ranking
  render.py    structured article -> self-contained styled HTML
  demo.py      built-in sample for --demo
```

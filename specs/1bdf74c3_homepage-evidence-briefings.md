# Plan — Reposition the public site around "a sourced evidence briefing you can send" (issue #152)

Branch `feat/152-homepage-evidence-briefings` already exists and is checked out.
Working tree is clean apart from an untracked log file.

## What this is

Positioning only. Nothing about the pipeline, the schema, the writer, or the
rendered article changes. Six files carry the change:

1. `index.html` — title, meta description, hero line, and three finished reviews
   linked straight from the landing view, above the key/setup card.
2. `articlegen/render.py` — `_INDEX_TEMPLATE` retitled from "Draft review queue".
3. `drafts/index.html` — hand-patched to match the new template (see the trap below).
4. `README.md` — live-site blurb matches the new job sentence.
5. `CLAUDE.md` — one paragraph, required by the docs CI gate because `articlegen/**`
   is touched.
6. `tests/test_offline.py` — one new test so the hardcoded featured links cannot rot.

## Traps — read these before editing

**Do not run `build_index("drafts")` on the real `drafts/` folder.** `build_index`
stamps each entry from the file's **mtime**, and this checkout has already
re-stamped four of the five drafts to `2026-08-15 15:49`. Regenerating would
overwrite the accurate committed dates (Aug 12 13:39 / Aug 13 20:54 / Aug 15 13:40 /
13:49 / 14:01) and collapse the newest-first ordering into a five-way tie. Patch the
two literal strings in `drafts/index.html` by hand instead — it is a generated
artefact, but it is also the only committed record of when each draft was written.

**Four existing assertions constrain the wording.** Breaking any of them fails
`tests/test_offline.py`:

- `test_first_visit_does_not_dead_end` (around lines 2528–2537) requires, in
  `index.html`: the literal `class="demo-band"`, the literal `href="drafts/"`, the
  substring `no key, no`, and
  `page.index('class="demo-band"') < page.index('id="setupCard"')`. Keep the demo
  band, and keep it above the setup card.
- The same test requires `README.md` to still contain both `Read a finished article`
  and `no account needed`. Reword the paragraph around those strings, not the
  strings themselves.
- `test_house_style_is_fixed_not_a_preference` (line 3924) bans `Wired`, `Quanta`,
  `ELI5` and **`Executive Briefing`** anywhere in `index.html`. "Evidence briefing"
  is a different string and is fine. Do not write "Executive Briefing" even inside
  an HTML comment.
- The AI-disclosure test (around line 3739) formats `render._INDEX_TEMPLATE` with
  `count=0, items=""`, then checks `idx-disclosure` appears before `<ul>` and that
  the text `No human author wrote or checked any of them` survives. Keep that
  paragraph verbatim and keep it above the list.

`_INDEX_TEMPLATE` is a `str.format` template — every literal brace in its CSS and
JS is already doubled (`{{`). Do not un-double anything while editing, and keep the
`{count}` and `{items}` placeholders.

`tests/test_journal_conformance.py` asserts nothing about the drafts index —
checked, it only covers rendered articles.

## 1. `index.html`

### 1a. Head (lines 9–10)

Replace:

```html
<title>Article Generator — Research-Grounded Articles on Mobile</title>
<meta name="description" content="Generate evidence-grounded science & tech articles from peer-reviewed literature right from your phone.">
```

with something on this line — the exact wording is not sacred, the job is:

```html
<title>ArticleGen — sourced evidence briefings you can send</title>
<meta name="description" content="Turn a topic into a sourced evidence briefing: a journal-style review of the published literature, written as one page you can send as a link.">
```

Leave the `ArticleGen` wordmark in the header (around line 547) alone.

### 1b. Hero (lines 563–564)

Replace:

```html
<h1 class="hero-title">Turn any theme into an evidence-grounded article</h1>
<p class="hero-subtitle">Grounded in real peer-reviewed journal abstracts. Simple, fast, and mobile-first.</p>
```

with one line naming the job, and a subtitle saying what the artefact is:

```html
<h1 class="hero-title">A sourced evidence briefing you can send</h1>
<p class="hero-subtitle">Pick a topic; get a journal-style review of the published
  literature on it — every claim cited to a real paper, every figure checked back
  against the source it came from, on one page you can share as a link.</p>
```

### 1c. Featured reviews — new block, above the demo band

Insert immediately after the hero subtitle and **before** the
`<a class="demo-band" href="drafts/">` element, so the landing view reads:

```
hero → featured reviews → demo band ("browse all") → setup card → theme box
```

Hardcode three links pointing at files that already exist in `drafts/`. No CMS, no
fetch, no JSON manifest — updating them when a new draft lands is a one-line edit,
and the new test in step 6 tells you when a link goes stale.

Use these three (newest, and the clearest titles):

| file | card title (shortened for the card) | one-line finding |
|---|---|---|
| `drafts/seclusion-restraint-cli.html` | Reducing seclusion and restraint in psychiatric inpatient care | Multicomponent programmes reduce both, but the supporting study designs are weak. |
| `drafts/co-responder-cli.html` | Police and clinician co-responder models in crisis care | Process-level effects are consistent; downstream outcomes are not. |
| `drafts/2026-08-12-safety-planning-ed-opus-5.html` | Safety planning after an emergency department visit | Associated with reduced suicidal behaviour in adults, but not in adolescents. |

The card titles above are shortened for the landing page; the full titles stay in
the files. Do not edit the drafts themselves.

Markup shape — plain anchors, no script. This view has to work with no key and
without any new JavaScript:

```html
<!-- Three finished reviews, linked straight at the files (#152). A stranger
     should see the output before being asked for anything. #111 put a link to
     the drafts index above the key prompt; an index is still one click away
     from the thing itself, so the reviews come first now.
     Hardcoded on purpose: no manifest, no fetch, no CMS. When a new draft is
     worth featuring, edit these anchors.
     test_the_landing_page_leads_with_finished_reviews checks the files exist. -->
<section class="featured">
  <h2 class="featured-label">Recent evidence briefings</h2>
  <a class="featured-card" href="drafts/seclusion-restraint-cli.html">
    <span class="featured-title">Reducing seclusion and restraint in psychiatric inpatient care</span>
    <span class="featured-take">Multicomponent programmes reduce both, but the supporting study designs are weak.</span>
  </a>
  <a class="featured-card" href="drafts/co-responder-cli.html">
    <span class="featured-title">Police and clinician co-responder models in crisis care</span>
    <span class="featured-take">Process-level effects are consistent; downstream outcomes are not.</span>
  </a>
  <a class="featured-card" href="drafts/2026-08-12-safety-planning-ed-opus-5.html">
    <span class="featured-title">Safety planning after an emergency department visit</span>
    <span class="featured-take">Associated with reduced suicidal behaviour in adults, but not in adolescents.</span>
  </a>
</section>
```

CSS: add a `.featured*` block next to `.demo-band` (index.html around line 500),
reusing the existing custom properties (`--card-bg`, `--card-border`, `--accent`,
`--muted`, `--ink`) so it themes with the rest of the page in both light and dark.
Keep it visually calmer than `.btn-primary` — these are the content, not a second
call to action. `.featured-label` should be small and uppercase like
`.demo-band-label`; `.featured-card` a bordered block with the title in `--ink` and
the finding in `--muted`, hover border `--accent`, matching `.demo-band:hover`.

### 1d. Demo band (lines 576–581)

Keep the element and its three required strings; re-point the copy so it reads as
"there are more of these", not as the only way in:

```html
<a class="demo-band" href="drafts/">
  <span class="demo-band-label">All published reviews</span>
  <span class="demo-band-text">Every briefing this has produced — no key, no
    account, nothing to set up.</span>
  <span class="demo-band-go">Browse all evidence reviews →</span>
</a>
```

`no key, no` is preserved on the second line; the assertion depends on it.

### 1e. Setup card

Content unchanged, and it stays where it is in the DOM (after the demo band).
Generating is now the second action, which the page order already says — no new
copy needed.

## 2. `articlegen/render.py` — `_INDEX_TEMPLATE`

Two literal strings, lines 1915 and 1955:

- `<title>Draft review queue</title>` → `<title>Evidence reviews</title>`
- `<h1>Draft review queue</h1>` → `<h1>Evidence reviews</h1>`

Also update the section comment around line 1907 (`# review-queue index`) to
`# published reviews index`, so the name in the code matches the page.

Optional and low risk: the `.sub` line at 1961 reads `{count} draft(s) · newest
first`. "review(s)" reads better on a public page and nothing asserts it. If you
change it, change only that literal — `{count}` stays.

Leave `build_index` itself alone. It already lists every `*.html` except
`index.html`, and the homepage cards must not be special-cased there.

## 3. `drafts/index.html` — hand-patch, do not regenerate

Apply exactly the same string edits to the committed artefact so the live site
matches the template:

```bash
sed -i 's|<title>Draft review queue</title>|<title>Evidence reviews</title>|; s|<h1>Draft review queue</h1>|<h1>Evidence reviews</h1>|' drafts/index.html
```

(If you also changed the `.sub` wording in the template, apply that substitution
here too.) Then confirm the dates and ordering survived:

```bash
grep -c 'class="meta"' drafts/index.html
grep -o 'Aug [0-9]*, 2026 [0-9:]*' drafts/index.html
```

The first must print `5`. The second must still print, in this order:
`Aug 15, 2026 14:01`, `Aug 15, 2026 13:49`, `Aug 15, 2026 13:40`,
`Aug 13, 2026 20:54`, `Aug 12, 2026 13:39`.

## 4. `README.md`

The opening paragraph and live-site blurb, lines 6–17. Keep the badges, keep the
"Use it from your phone" steps below (they are for people who already decided to
generate), and keep the two strings the test needs.

Suggested replacement for lines 6–17:

```markdown
Turn a topic into a **sourced evidence briefing** — a journal-style review of the
published literature, written as one self-contained HTML page (plus Markdown) that
you can send as a link. Every claim is cited to a real paper, and every figure is
checked back against the source it came from. Three stages: generate ideas →
research collated automatically → draft prepared for your review.

## 🚀 Live site

🔗 **[Open the site](https://bartholomewtj.github.io/article-generator/)**

📄 **[Read a finished article](https://bartholomewtj.github.io/article-generator/drafts/)**
— no key and no account needed. Generating your own needs an OpenRouter key
(roughly 50c–$1 an article); reading what it has already produced does not.
```

`Read a finished article` and `no account needed` both survive verbatim.

## 5. `CLAUDE.md`

`.github/workflows/docs-current.yml` fails a PR that touches `articlegen/**`
without touching `CLAUDE.md`, so this edit is required, not optional.

In the **What this is** section, add one short paragraph after the existing
description:

> The public site frames this as a **sourced evidence briefing you can send**; the
> artefact is unchanged — a journal-style Review. The GitHub Pages landing page
> links three finished reviews in `drafts/` directly, above the key prompt (#152,
> extending #111), and the generated drafts index is titled "Evidence reviews"
> rather than "Draft review queue".

Add nothing else. `test_claude_md_still_describes_this_code` resolves every
backticked path and every backticked ALL-CAPS constant in `CLAUDE.md` and
`docs/decisions.md`, so do not backtick a file or constant that does not exist.
`drafts/` and `drafts/index.html` are both safe.

Optionally add a short entry to `docs/decisions.md` recording why the drafts index
is patched by hand rather than regenerated (the mtime trap in this plan). Same
rule if you do: no invented paths or constants.

## 6. `tests/test_offline.py` — one new test

Nothing currently asserts the index heading, so the retitle breaks no test. But
three hardcoded `drafts/*.html` links on the public landing page will rot silently
the first time a draft is renamed, so add a cheap guard next to
`test_first_visit_does_not_dead_end` (after roughly line 2570):

```python
def test_the_landing_page_leads_with_finished_reviews() -> None:
    """A stranger sees the output before being asked for anything (#152).

    #111 put a link to the drafts index above the key prompt. An index is still
    one click away from the thing itself, so the landing page now links finished
    reviews directly. Those links are hardcoded — no manifest, no fetch — which
    means a renamed or deleted draft becomes a dead link on the public homepage
    and nothing else would notice.
    """
    import re as _re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    page = open(os.path.join(root, "index.html"), encoding="utf-8").read()

    featured = _re.findall(r'href="(drafts/[^"]+\.html)"', page)
    check("the landing page links finished reviews directly", 2 <= len(featured) <= 3)
    for rel in featured:
        check(f"the featured review exists on disk: {rel}",
              os.path.exists(os.path.join(root, rel)))
    check("the featured reviews come before the key prompt",
          bool(featured) and page.index(featured[0]) < page.index('id="setupCard"'))
    check("the head frames the output as a briefing, not an article generator",
          "Research-Grounded Articles on Mobile" not in page)
```

Register it the same way the file registers its other tests — check the bottom of
`tests/test_offline.py` and follow the existing pattern (each test is wrapped so
one crash does not abort the rest).

## Verify

```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. Judge them by exit status, not by scanning output for the word
"error".

Worth checking by eye as well:

```bash
grep -c "Executive Briefing" index.html
grep -n 'class="demo-band"\|id="setupCard"\|href="drafts/' index.html
grep -rn "Draft review queue" articlegen/render.py drafts/index.html
grep -n "Read a finished article\|no account needed" README.md
python -c "from articlegen import render; render._INDEX_TEMPLATE.format(count=0, items='')"
```

`Executive Briefing` must count 0. The `Draft review queue` grep must return
nothing. The last command proves the `str.format` braces in `_INDEX_TEMPLATE` are
still balanced after the edit.

Then open `index.html` in a browser (or run `articlegen web --open`) and click all
three featured links — relative `drafts/...` paths work both locally and under the
GitHub Pages path prefix.

## Out of scope

No rename of the repo, package, CLI, or the `ArticleGen` wordmark. No accounts,
analytics, or a CMS for the featured cards. No new drafts generated. No narrowing
of the pipeline to mental health — the featured examples are clinical only because
that is what `drafts/` holds today. No special-casing of homepage cards in
`build_index`.

## PR

Push `feat/152-homepage-evidence-briefings` and open a PR with `gh pr create`.
`articlegen/**` is touched and `CLAUDE.md` is edited, so the docs gate is satisfied
by the edit rather than an opt-out sentence.

The PR body should close #152. If you also mean #135 (more drafts in the index) to
be settled by this, close it; if you mean it to stay open, write "Refs #135, stays
open" and **never** "does not close #135" — GitHub's linked-issue parser matches
`close #NNN` and ignores the negation around it.

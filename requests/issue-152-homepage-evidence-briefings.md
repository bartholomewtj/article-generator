Reposition the public site around the job it does — a sourced evidence briefing someone can send — with published drafts shown first, per GitHub issue #152 (below, verbatim).
Where: index.html, articlegen/render.py (_INDEX_TEMPLATE, build_index), README.md, CLAUDE.md, drafts/*.html (existing files, link to them; do not create new ones), tests/test_offline.py and tests/test_journal_conformance.py (check for asserted index headings).
Done means: index.html <title>/meta/hero frame the output as an evidence briefing, two or three existing drafts/*.html reviews are linked directly from the landing page above the key/setup card, the drafts index template is retitled (e.g. "Evidence reviews") keeping the machine-written / not-peer-reviewed disclosure, README's live-site blurb matches the new job sentence, and the full test suite (including test_house_style_is_fixed_not_a_preference) is green.
Out of scope: renaming the repo/package/CLI or the ArticleGen wordmark; accounts, analytics, or a CMS for the featured cards; generating new drafts; narrowing the pipeline to mental health; the string "Executive Briefing" anywhere in index.html; special-casing homepage cards in build_index.

--- Issue #152 as written ---
Reposition the public site around the job it actually does: a sourced evidence briefing someone can send. Right now a stranger lands on "Turn any theme into an evidence-grounded article," which sounds like an essay mill, and the only no-key path is a link labelled "Open the published drafts →" that opens `drafts/index.html` titled **Draft review queue**.

#111 already put the demo band above the key prompt. #135 asked for more drafts in that index — that part is done (five reviews as of 15 Aug 2026). The remaining first-impression problem is framing, not inventory.

## What to change

**`index.html` (the GitHub Pages landing page)**

- `<title>` and meta description: evidence briefing / sourced review you can share. Drop "Article Generator — Research-Grounded Articles on Mobile."
- Hero: name the job in one line. Suggested shape (not sacred wording): a sourced briefing from a topic, written as a Review-shaped page, that you can send as a link.
- Put **two or three featured reviews on the landing page itself**, linking straight at the existing HTML files in `drafts/`. Do not make the stranger click through a queue index to see what this is.
  - Use the drafts we already have. They are all acute-care topics; that is fine. Do not generate new ones for this issue and do not lock the generator to health.
- Keep the key / setup card, but below the featured reviews. Generating your own is the second action, not the first.
- Leave the `ArticleGen` wordmark alone. This is positioning, not a rename.

**`articlegen/render.py` `_INDEX_TEMPLATE`** (and therefore `drafts/index.html` after the next `build_index`)

- The public `drafts/` folder *is* this template. "Draft review queue" is the right name for `articlegen queue` on a laptop and the wrong name for a hiring manager.
- Retitle to something that works for both audiences — e.g. "Evidence reviews" — and keep the machine-written / not-peer-reviewed disclosure.
- `build_index` already lists every `*.html` except `index.html`. Do not special-case the homepage cards here.

**`README.md`**

- The live-site blurb at the top should match the new job sentence. The "Use it from your phone" steps can stay; they are for people who already decided to generate.

## What not to do

- Do not rename the repo, the Python package, or the CLI.
- Do not add accounts, analytics, or a CMS for the featured cards. Hardcode two or three links. Updating them when a new draft is committed is an afternoon, not a feature.
- Do not narrow the pipeline to mental health. Featured examples may be clinical because that is what `drafts/` holds.
- Do not put the string `Executive Briefing` anywhere in `index.html` — `test_house_style_is_fixed_not_a_preference` bans it as a *register option*. "Evidence briefing" in the hero is a different string and is fine.

## Tests / docs

- If `articlegen/**` is touched, update `CLAUDE.md` (or write `Docs: n/a - …` on the PR). The "What this is" line can say the public site frames the output as an evidence briefing; the artefact is still a journal-style Review.
- No new behavioural test required unless the index heading is asserted somewhere. Check `test_offline.py` / `test_journal_conformance.py` before assuming it is not.
- `test_house_style_is_fixed_not_a_preference` must stay green.

## Related

- #111 (closed) — no free generate path; demo band added
- #135 (open) — more drafts in the index. Draft count is done; remaining work belongs here. Close #135 when this lands, or when you decide the queue title change is enough.

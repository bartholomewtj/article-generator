Put titles in the verify haystack, do not split hyphenated ranges, and run one statistics revision pass when flags remain, per GitHub issue #189 (below, verbatim).
Where: articlegen/verify.py (_paper_haystack, _FIGURE_RE), articlegen/pipeline.py (a revision pass after check_statistics, same shape as enforce_style), articlegen/writer.py if a new revise_statistics helper lives there, tests/test_offline.py, CLAUDE.md
Done means: a figure that appears only in a paper’s title is no longer †; `4.4-5.2` is one quantity, not `4.4` and `-5.2`; when unverified+misattributed > 0 the writer is asked once to drop the figure, turn it into words, or move the citation — no new numbers; a clean first write (organic-style 0/0) does not buy a pass; both suites green.
Out of scope: ignoring `95%` inside `95% CI` (follow-up if it recurs); asking the model to guess a new source or number; raising FULLTEXT_TARGET; fetching paywalled full text; changing the default model (#85); putting --long on the web UI; regenerating the public demo Reviews in drafts/.

--- Issue #189 as written ---
Fix the statistic check’s false splits, put titles in the haystack, and ask the writer to drop a flagged figure once.

Four Grok 4.6 briefings (21 Aug 2026) met the bar on #186: 3 of 4 branded working-draft on a ‡ pile. Organic came back 0/0. Hyphenated-range splitting recurred (`4.4-5.2` → `4.4‡` and `-5.2‡`). Title-only † and `95% CI` noise did not recur this batch.

## What to change (in order)

1. Put `paper.title` in `_paper_haystack`.
2. Do not extract a second figure from a hyphenated range.
3. If misattributed + unverified > 0 after the first write: one revision pass. Drop, reword, or recast the citation. No new numbers.

Refs #186, #142, #92, stays open until this lands.

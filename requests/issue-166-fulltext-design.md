Send the five deep reads to systematic reviews and trials first, not to the newest papers, per GitHub issue #166 (below, verbatim).
Where: articlegen/sources.py (full_text_order, FULLTEXT_RELEVANCE_ORDER, Paper), tests/test_offline.py (test_full_text_order_favours_direct_and_recent), CLAUDE.md
Done means: full_text_order ranks eligible sources by design weight then recency (direct systematic reviews/meta-analyses/Cochrane, then direct trials, then other direct, then related with the same design preference; recency and search rank as tie-breakers); design is detected from title/venue/type metadata already on Paper; tangential still never fetched; the existing order test is updated to the new rule and both suites are green; the read-subset skew log line still prints.
Out of scope: raising FULLTEXT_TARGET; inventing a quality-appraisal score; fetching paywalled full text; an extra LLM call to label design; putting --long on the web UI; regenerating drafts/.

--- Issue #166 as written ---
Send the five deep reads to systematic reviews and trials first, not to the newest papers.

#143 stopped sending full text to old, highly-cited work. Recency-first inside `direct` created the opposite skew: in the seclusion draft, Gaynes 2017 (the only systematic appraisal of adult acute settings) was abstract-only, while a 2024 Joint Crisis Plan pilot and a child/adolescent review were read in full. The load-bearing paper lost because it is nine years old.

## What to change

`full_text_order` should rank eligible sources by design weight, then recency:

1. Direct systematic reviews / meta-analyses / Cochrane
2. Direct trials
3. Other direct
4. Related, same design preference
5. Recency and search rank as tie-breakers

Detect design from title/venue/type metadata already on `Paper` — no extra LLM call. Tangential still never fetched.

Watch the existing read-subset skew log line. After this, median year of the read subset may be older than the abstract-only rest. That is the change working, if those older papers are the reviews and trials.

## What not to do

- Do not raise `FULLTEXT_TARGET` (excerpt budget is already full at 5 × 12,000).
- Do not invent a quality-appraisal score.
- Do not fetch paywalled full text.

Refs #143, stays open until this lands. Refs #84, stays open (coverage is a different question).

After curation, fetch papers the abstracts actually name, per GitHub issue #165 (below, verbatim).
Where: articlegen/pipeline.py (generate_draft, after curate_sources), articlegen/sources.py (gather_evidence, Paper, DOI/title dedupe), articlegen/writer.py (curate_sources), tests/test_offline.py, CLAUDE.md
Done means: a test pins that a DOI mentioned in a curated abstract is requested; named landmark papers from the two or three most-relevant abstracts (and any full text already fetched) are merged into the candidate pool via existing DOI/title dedupe, re-labelled only for the new records, then written; extra fetch capped (e.g. 8 named papers); Methods names the extra pass; both test suites green.
Out of scope: a fifth search API; chasing every nested citation in the full text; weakening the open-access constraint; putting --long on the web UI; regenerating drafts/; raising FULLTEXT_TARGET.

--- Issue #165 as written ---
After curation, fetch papers the abstracts actually name.

Search is one-shot: the model invents 2–4 queries, we fetch once, we write. Real reviews iterate. The seclusion draft planned `Safewards trial conflict containment acute mental health wards` and the Bowers cluster RCT still never carried the article at first hand. Load-bearing numbers arrived quoted inside other papers (#141, #142).

## What to change

After `curate_sources`, take the two or three most-relevant abstracts (and any full text already fetched) and pull named trials/reviews from them — DOI if present, title otherwise. Run one extra gather for those, merge into the candidate pool (existing DOI/title dedupe), re-label only the new records, then write.

Cap the extra fetch (e.g. 8 named papers) so a chatty review abstract cannot explode the pool.

## What not to do

- Do not add a fifth search API.
- Do not chase every nested citation in the full text. Named landmark papers in the top abstracts are the target.
- Do not weaken the open-access constraint.

## Done means

A topic whose planned query names a landmark trial includes that trial as a first-hand source when the APIs have it. Methods names the extra pass. A test pins that a DOI mentioned in a curated abstract is requested.

Refs #141, #142, stays open until this lands.

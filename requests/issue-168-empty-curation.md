If source labelling returns nothing, stop — do not write, per GitHub issue #168 (below, verbatim).
Where: articlegen/pipeline.py (generate_draft after curate_sources, NoPapersFound), articlegen/writer.py (curate_sources), tests/test_offline.py, CLAUDE.md
Done means: papers exist but relevance is empty is a hard failure, same family as NoPapersFound; the caller is told labelling failed and write_briefing / write_article is not called; the existing WARNING log line stays; both suites green.
Out of scope: retrying curation in a loop; falling back to treating every source as direct; putting --long on the web UI; regenerating drafts/.

--- Issue #168 as written ---
If source labelling returns nothing, stop. Do not write the briefing.

`curate_sources` swallows every exception and returns empty labels. `generate_draft` logs a warning and continues. The relevance gate is then off, no full text is fetched, and the model writes anyway. That is the quietest way this pipeline can go wrong.

## What to change

Treat "papers exist but `relevance` is empty" as a hard failure, same family as `NoPapersFound`. Tell the caller labelling failed and nothing was charged for the write (the curation call was). Do not call `write_briefing` / `write_article`.

Keep the existing log line; it is no longer the only signal.

## What not to do

- Do not retry curation in a loop.
- Do not fall back to treating every source as `direct`.

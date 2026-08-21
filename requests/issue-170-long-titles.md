--long titles must describe the question, not claim the result, per GitHub issue #170 (below, verbatim).
Where: articlegen/writer.py (_ARTICLE_SCHEMA title description, _WRITER_SYSTEM), tests/test_offline.py (test_real_articles_still_match_the_schema)
Done means: the Review-path schema text and prompt require a descriptive title (population + intervention/exposure + outcome, sentence case, no result claimed), same rule the briefing writer already has; test_real_articles_still_match_the_schema still passes; both suites green.
Out of scope: a regex title-ban in style.py; changing briefing titles; putting --long on the web UI; regenerating drafts/.

--- Issue #170 as written ---
`--long` titles must describe the question, not claim the result.

The briefing path already asks for a descriptive title. The Review path still asks for "the subject and the finding", which produced:

> Brief hospital admission by self-referral reduces involuntary care and self-harm without increasing total inpatient utilization in borderline personality disorder

That is a causal claim. The statistic checker never looks at titles. The rest of the pipeline is forbidden to assert that hard.

## What to change

In `_ARTICLE_SCHEMA` title description and `_WRITER_SYSTEM`, require a descriptive title: population + intervention/exposure + outcome, sentence case, no result claimed. Same rule the briefing writer already has.

A test: a title matching `\breduces\b|\bincreases\b|\bimproves\b` on the Review fixture is not required to fail the style checker (too crude), but the schema text and prompt must contain the prohibition, and `test_real_articles_still_match_the_schema` still passes.

## What not to do

- Do not add a regex title-ban in `style.py` unless a later draft shows the prompt is ignored. Measure first.

Count papers `queued_ckn` as paywalled, not as open-access-no-text, per GitHub issue #191 (below, verbatim).
Where: articlegen/pipeline.py (full-text loop tallies: no_open_access vs fetch_failed), articlegen/paperfetch.py if the status needs to travel back, tests/test_offline.py, CLAUDE.md
Done means: a `queued_ckn` (or equivalent not-OA) result increments no_open_access, not fetch_failed; the stop-reason line and read-subset-skew line still print; a run that hits target of 5 still says so; both suites green.
Out of scope: raising FULLTEXT_TARGET or MAX_FULLTEXT_REQUESTS; fetching paywalled full text; vendoring papers into Docker (#173); changing the default model (#85); putting --long on the web UI; regenerating the public demo Reviews in drafts/.

--- Issue #191 as written ---
When `papers` returns `queued_ckn`, tally it as no open-access copy, not as “open access but returned no text”.

Four Grok 4.6 local runs (21 Aug 2026) stopped on target of 5. Paywalled landmarks were logged as OA failures. Tesnières 2026 (the organic-causes review) stayed abstract-only; Cureus case reports got the deep reads.

Do not raise FULLTEXT_TARGET. After this lands, #84 can close: stop reason and skew are logged; leftover constraint is OA availability plus the hosted Europe PMC gap (#173).

Refs #84, stays open until this lands.

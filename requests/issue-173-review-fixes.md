Close the five blocking findings in `adws/adw_data/sessions/f89aa3ce/context_handoff/review.md` (and the matching "Not met" items 16–21). Spec remains `specs/f89aa3ce_hosted-paperfetch-oa.md`.
Where: CLAUDE.md:345 and :130, README.md:267-269, tests/test_offline.py (docstring of `test_queued_ckn_counts_as_no_open_access` plus negative `NOT_OA_STATUSES` checks), Dockerfile:35, docs/decisions.md (`@main` unpinned-on-purpose).
Done means: those five blocking items are fixed on disk; `no_oa` and `queued_ckn` still both count as not-OA; local `papers` stays the private package; both suites green.
Out of scope: pip install paperfetch-oa on this machine; landing-page rewrite; renaming `queued_ckn`; `--long` on the web UI; regenerating public demo Reviews.

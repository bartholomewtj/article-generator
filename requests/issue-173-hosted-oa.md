Accept `no_oa` in `NOT_OA_STATUSES` (keep `queued_ckn`) and install public `paperfetch-oa` in the Docker image from `https://github.com/bartholomewtj/paperfetch-oa.git`, per GitHub issue #173 (below, verbatim).
Where: articlegen/paperfetch.py, articlegen/sources.py, tests/test_offline.py, Dockerfile, render.yaml if a mailto env is needed for hosted `papers`.
Done means: `no_oa` and `queued_ckn` both count as not-OA; the hosted image installs `paperfetch-oa` from the public git URL with no GitHub credentials; both suites green; local `papers` stays the private package.
Out of scope: `pip install` paperfetch-oa on this machine; rewriting the landing page as "Europe PMC only"; fetching paywalled full text; renaming `queued_ckn`; putting `--long` on the web UI; regenerating the public demo Reviews in drafts/; restyling journal HTML.

--- Issue #173 as written ---
The hosted app still cannot fetch full text outside Europe PMC.

Locally, `papers` (paperfetch) pulls any open-access copy. Render cannot pip-install that private repo, so the public web path is Europe PMC only. Non-biomedical topics and arXiv papers stay abstract-only on the site that strangers use.

## Options (pick one, do not do both)

1. Vendor a minimal `papers get` into the Docker image, or make paperfetch installable without the private repo.
2. Stop implying the hosted path reads full text. Methods already reports what happened; the README and landing page should say the public app is Europe PMC only, and that `articlegen draft` locally is the full-text path.

(2) is honest and small. (1) is the real fix.

## What not to do

- Do not put GitHub credentials in the Render build to install a private package.
- Do not fetch paywalled full text.

Refs #84, stays open. This is the deploy half of that constraint.

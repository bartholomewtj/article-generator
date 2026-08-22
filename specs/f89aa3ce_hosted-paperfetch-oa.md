# Plan — hosted full text via paperfetch-oa, and `no_oa` as not-OA (#173)

## What we're doing and why

Two small changes that together give the hosted web app the same full-text
reach the CLI has:

1. **`no_oa` joins `queued_ckn` in `NOT_OA_STATUSES`.** The public
   `paperfetch-oa` CLI says `no_oa` where the private `paperfetch` says
   `queued_ckn`. Both mean the same thing: Unpaywall and the rest of the ladder
   found no open-access copy. Without this, every paywalled paper on the hosted
   backend would be logged as "open access but returned no text", which is the
   exact wrong count #191 fixed for the private CLI.
2. **The Docker image installs `paperfetch-oa` from its public git URL.** Render
   cannot install the private repo and we are not putting GitHub credentials in
   the build. `paperfetch-oa` is public (MIT, not on PyPI, installed straight
   from GitHub), so `pip install git+https://...` needs no credentials.

This is option (1) in issue #173 — the real fix, not the "say it's Europe PMC
only" fallback.

## Facts the builder needs (already checked — don't re-derive)

- `paperfetch-oa` lives at `https://github.com/bartholomewtj/paperfetch-oa.git`,
  package name `paperfetch-oa`, console script `papers` (`papers.cli:main`),
  `requires-python >=3.10`, one dependency (`pypdf>=5`). Same CLI contract as
  the private tool: `papers get <doi>` prints one JSON object on stdout with a
  `status` field and a `read` path on `ok`.
- Its statuses are `ok`, `no_oa`, `unreadable_pdf`, `retry`, `no_doi`. There is
  no `queued_ckn` — that status is private-only (CKN is the Queensland Health
  library, which the public tool deliberately does not touch).
- `papers get` **requires `PAPERS_MAILTO`** for any DOI that isn't already
  cached. Without it the CLI writes `set PAPERS_MAILTO to your email` to stderr,
  prints nothing on stdout and exits 1. `articlegen/paperfetch.py` then logs
  `papers returned invalid JSON for <doi> (...): 'set PAPERS_MAILTO to your
  email'` and returns `""`, and `sources.fetch_full_text` falls through to the
  Europe PMC route. So a missing mailto is a *degradation with a loud log line*,
  not a crash — but the hosted env must set it or the change buys nothing.
- `articlegen/paperfetch.py` already derives `PAPERS_MAILTO` from
  `OPENALEX_MAILTO` / `UNPAYWALL_EMAIL` when it is unset. Both are `sync: false`
  in `render.yaml`, i.e. possibly unset in the dashboard.
- `papers` caches under `Path.home()/.paperfetch` (a PDF and a text file per
  DOI). In the image that is `/home/appuser/.paperfetch`: writable, ephemeral.
- `python:3.12-slim` has **no git**, so `pip install git+https://...` needs git
  installed for the build.
- Docker 29.6.2 is available on this machine, so the image build can be verified
  locally before pushing.

## Files to touch

### 1. `articlegen/paperfetch.py`

- `NOT_OA_STATUSES = frozenset({"queued_ckn", "no_oa"})`.
- Update the comment above it so it explains both names in one place: private
  `paperfetch` says `queued_ckn`, public `paperfetch-oa` says `no_oa`, both mean
  Unpaywall (and the rest of the ladder) found no open-access copy. Keep the
  existing sentence that `unreadable_pdf`, `retry` and `no_doi` stay fetch
  failures — `retry` in particular means "Unpaywall was unreachable, we do not
  know", which is not a confirmed absence of open access.
- Update the `fetch_via_papers_with_status` docstring, which currently names
  only `queued_ckn`.
- **Do not rename `queued_ckn`** and do not drop it.

### 2. `articlegen/sources.py`

- The `Paper.full_text_not_oa` comment (~line 222) says "a not-OA status
  (`queued_ckn`)". Make it name both. No logic change — the code already tests
  membership of `NOT_OA_STATUSES`.

### 3. `tests/test_offline.py`

Extend the existing `test_queued_ckn_counts_as_no_open_access` (~line 6298).
**Keep the test name** — CLAUDE.md's invariant table cites it and
`test_claude_md_still_describes_this_code` checks that the name exists. Widen
the docstring to say it now covers both spellings.

Concretely, run the three existing blocks over both statuses instead of only
`queued_ckn`:

- `for status in ("queued_ckn", "no_oa"):`
  - `fetch_via_papers_with_status` returns `("", status)`; `fetch_via_papers`
    still returns a string.
  - a DOI-only `Paper` gets `full_text_not_oa is True`, empty body,
    `full_text_via == ""`.
  - a `draft_logs` run prints the stop-reason and read-subset-skew lines,
    `"1 had no open-access copy"`, and
    `"0 were open access but returned no text"`.
- `check("both not-OA spellings are in NOT_OA_STATUSES", {"queued_ckn", "no_oa"} <= set(paperfetch.NOT_OA_STATUSES))`
- Negative controls, so the set can't quietly grow: assert `"unreadable_pdf"`,
  `"retry"` and `"no_doi"` are **not** in `NOT_OA_STATUSES`. The existing
  timeout contrast block at the end of the test stays as it is.

Label each check with the status (`f"{status} sets full_text_not_oa"`) so a
failure names which spelling broke. Call `reset_paperfetch()` before each
fake-subprocess block, exactly as the current test does.

### 4. `Dockerfile`

Add one layer **after** the `requirements.txt` install and **before**
`COPY articlegen`, so a code change doesn't reinstall it:

```dockerfile
# Full text beyond Europe PMC (#173). The public OA-only sibling of the private
# `paperfetch`: same `papers get <doi>` contract, no CKN, no library pickup, and
# no credentials to install. It resolves Unpaywall / OpenAlex / Semantic Scholar
# / preprint copies, which is what makes non-biomedical and arXiv papers
# readable on the hosted path. git is a build-time need only, so it goes in the
# same layer and comes back out.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && pip install --no-cache-dir \
      "paperfetch-oa @ git+https://github.com/bartholomewtj/paperfetch-oa.git@main" \
 && apt-get purge -y --auto-remove git \
 && rm -rf /var/lib/apt/lists/*
```

Also, near the existing `OPENALEX_MAILTO` block at the bottom:

```dockerfile
# `papers` refuses every uncached DOI without a real contact address, so an
# empty value here means the hosted path falls back to Europe PMC. Set a real
# address at deploy time. Never a made-up one — the scholarly APIs block those.
ENV PAPERS_MAILTO=""
```

Notes:
- `@main` is deliberate: `paperfetch-oa` is our own repo and shared
  ladder/resolver changes land in both repos in the same session, so a pin would
  become a second chore. The cost is that a bad push to `paperfetch-oa` breaks
  this build — the Render deploy log and `/api/health` are how that shows up.
- Do **not** add a GitHub token, a `.netrc`, an SSH key or a private submodule.
  The URL is public and anonymous HTTPS is the whole point.
- Do **not** add `paperfetch-oa` to `requirements.txt` — that file is the
  runtime dependency list for local use too, and locally the `papers` command
  must stay the **private** package.

### 5. `render.yaml`

Add one env var to `envVars`, keeping the file's comment style:

```yaml
      # Contact address for `papers` (paperfetch-oa), which the image installs.
      # Unpaywall, OpenAlex and Crossref require it and block made-up addresses.
      # Unset means the full-text path degrades to Europe PMC only, with
      # "papers returned invalid JSON ... set PAPERS_MAILTO to your email" in
      # the log. Set a real address in the Render dashboard.
      - key: PAPERS_MAILTO
        sync: false
```

`OPENALEX_MAILTO` stays as it is; `articlegen/paperfetch.py` already falls back
to it, so setting either in the dashboard works — but naming `PAPERS_MAILTO`
explicitly is what makes the requirement visible in the repo.

### 6. `README.md` — the "Full text via the `papers` CLI (optional)" section (~line 260)

- Install bullet: say there are two packages — the private `paperfetch` locally,
  and the public `paperfetch-oa`
  (`pip install git+https://github.com/bartholomewtj/paperfetch-oa.git`) for a
  host or a machine that only needs open access. Add the line from the
  `paperfetch-oa` README: **do not install both side by side** — they both
  expose the `papers` command and a `papers` Python package.
- Replace the "Hosted deployment: ... does not have `paperfetch` installed yet,
  so the public web app remains Europe PMC only" bullet with what is true after
  this change: the hosted image installs `paperfetch-oa`, so the public web app
  reads open-access full text from the same ladder, minus the CKN/library
  routes; paywalled papers stay abstract-only everywhere and Methods says so.

### 7. `CLAUDE.md`

Required anyway by `.github/workflows/docs-current.yml` (the PR touches
`articlegen/**`). Edits:

- Invariant table row: change the `queued_ckn` miss row to name both spellings
  (`queued_ckn` / `no_oa`), keeping the guard test name
  `test_queued_ckn_counts_as_no_open_access` unchanged.
- In **Sources and grounding**, the bullet that mentions `NOT_OA_STATUSES`: add
  that the public `paperfetch-oa` spells the same miss `no_oa`, and that both
  count as no-open-access.
- In the **"Full text has two routes"** bullet: replace "`papers` is optional and
  absent on the hosted backend" with the new fact — the hosted image installs
  the public `paperfetch-oa` from git, local machines keep the private
  `paperfetch`, and the two must never be installed side by side because they
  share the `papers` command and package name.
- In **Deployment**: one line saying the backend image pip-installs
  `paperfetch-oa` from the public git URL at build time, with no credentials,
  and that `PAPERS_MAILTO` must be set in the Render dashboard or the path falls
  back to Europe PMC.
- Watch the doc gate: `test_claude_md_still_describes_this_code` resolves any
  backticked `*.py` / `*.md` / `*.yml` path against the repo and any backticked
  ALL-CAPS token against module source. `paperfetch-oa` and `no_oa` trip
  neither; don't backtick a filename that doesn't exist in this repo.

### 8. `docs/decisions.md`

Short entry for #173, in the file's existing voice: the hosted path was Europe
PMC only because the private repo can't be installed on Render; option (2)
(document the limit) was rejected in favour of the real fix; the public
`paperfetch-oa` split exists precisely so a public host can install it; and the
status-name difference (`queued_ckn` vs `no_oa`) is the seam that would
otherwise have re-created #191 on the hosted path. Note that git is installed
and purged in one layer, and that `@main` is unpinned on purpose.

## Verify

Judge each by exit status, not by scanning output for scary words.

1. `python tests/test_offline.py` — green.
2. `python tests/test_journal_conformance.py` — green (unchanged, but it's the
   pair we always run).
3. `docker build -t articlegen-173 .` — proves the git install works with no
   credentials on a clean image.
4. Smoke the CLI inside the image (needs network, a real address, one known-OA
   DOI):
   `docker run --rm -e PAPERS_MAILTO=bartholomew.jordan@gmail.com articlegen-173 papers get 10.1371/journal.pone.0000308`
   Expect one JSON object with `"status": "ok"` and a `read` path.
5. Same image, the not-OA path — a paywalled DOI should come back
   `"status": "no_oa"`, which is the status this change now counts correctly.
6. `docker run --rm articlegen-173 python -c "from articlegen import paperfetch; print(sorted(paperfetch.NOT_OA_STATUSES), paperfetch.available(print))"`
   — expect both statuses and `True`.

If Docker is unavailable in the builder's environment, say so in the PR rather
than skipping silently; steps 1–2 still gate the code change.

## Ship

Branch → commit → push → `gh pr create`. In the PR body, note that the docs gate
is satisfied by the CLAUDE.md edit, and write `Refs #173` — **not** "does not
close #173"; GitHub's parser ignores the negation. Say plainly whether the
Docker build was run. After merge, Render rebuilds on push to `main`; then set
`PAPERS_MAILTO` in the Render dashboard and check `GET /api/health` reports the
new commit.

## Out of scope (do not do these)

- `pip install` `paperfetch-oa` on this machine — it would shadow the private
  `papers` command that local drafts depend on. Docker only.
- Rewriting the landing page as "Europe PMC only" (that was issue option 2).
- Fetching paywalled full text, adding CKN / `miss` / `ingest` to the public
  path, or renaming `queued_ckn`.
- Putting `--long` on the web UI, regenerating the demo Reviews in `drafts/`,
  restyling journal HTML.
- Making `paperfetch.available()` require a mailto. It looks tempting, but six
  existing tests fake `shutil.which` with no mailto set and would need rewriting
  for no behaviour gain — the missing-mailto case already logs its own cause and
  falls back to Europe PMC.

## Risks to mention in the PR, not to fix here

- **Per-request latency.** With `papers` present on the hosted path, up to
  `MAX_FULLTEXT_REQUESTS` (18) DOIs each run a resolver ladder at up to
  `DEFAULT_TIMEOUT` (120s). Hosted drafts will get slower. If that bites, the
  lever is a shorter timeout on the hosted path — a separate issue.
- **Ephemeral cache growth.** `papers` keeps a PDF and a text file per DOI under
  `/home/appuser/.paperfetch`. The free instance sleeps after 15 minutes idle
  and restarts clean, so this should self-limit; watch it rather than pre-solve
  it.
- **Build coupling.** The hosted build now depends on a second GitHub repo being
  reachable and importable. A broken push to `paperfetch-oa` fails the Render
  build.

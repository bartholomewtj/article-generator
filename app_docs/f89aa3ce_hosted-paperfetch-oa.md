# Hosted paperfetch-oa for full text beyond Europe PMC (#173)

## What changed

The hosted web backend on Render now installs the public `paperfetch-oa` package to fetch open-access full text from Unpaywall, OpenAlex, Semantic Scholar and preprint servers—the same sources the local CLI reaches. Before this, the hosted path was limited to Europe PMC abstracts only because Render cannot install private GitHub repositories.

Two code changes and one new dependency:
1. Accept `no_oa` (public package's status) alongside `queued_ckn` (private package's status) in `NOT_OA_STATUSES`, so both mean "confirmed no open-access copy exists"
2. Install `paperfetch-oa` from its public GitHub URL in the Docker build; no credentials needed

## Why this matters

Non-biomedical topics and arXiv papers stay abstract-only on paywalled sources everywhere (that is correct). But they no longer stay abstract-only on open-access sources on the hosted app—matching the local experience. The change is invisible to end users (no UI changes, no new options); drafts from the hosted path just read more literature.

## Files that carry it

**Code (minimal):**
- `articlegen/paperfetch.py`: Added `"no_oa"` to `NOT_OA_STATUSES` frozenset; updated comments explaining both status names
- `articlegen/sources.py`: Comment on `Paper.full_text_not_oa` now names both spellings
- `tests/test_offline.py`: Extended `test_queued_ckn_counts_as_no_open_access` to cover both statuses (added negative controls and `no_oa` path validation)

**Infrastructure:**
- `Dockerfile`: Added layer that installs `paperfetch-oa` from `git+https://github.com/bartholomewtj/paperfetch-oa.git@main` using public HTTPS (no credentials), then purges `git` before the layer closes to keep the image slim
- `render.yaml`: Added `PAPERS_MAILTO` environment variable (required by paperfetch-oa for Unpaywall lookups; blank default, must be set in Render dashboard or full-text fetch degrades to Europe PMC)

**Documentation:**
- `CLAUDE.md`: Expanded the "Full text has two routes" section to explain that hosted runs `paperfetch-oa` (public, no CKN), local runs the private `paperfetch` (includes CKN ladder), and warned never to install both on the same machine; updated invariant row to name both status spellings
- `README.md`: Updated "Full text via the `papers` CLI" section to list both packages and their use cases; updated "Hosted deployment" bullet to explain the public package is now installed
- `docs/decisions.md`: Added reasoning for why option 1 (fix it with a public package) was chosen over option 2 (document the Europe-PMC-only limit); noted that `@main` is unpinned on purpose because this is our own repo and the cost of a pin would outweigh the benefit during active development

## How to use and verify

**Local development:** No change. Run `pip install -e .` after installing the private `paperfetch` package; never install `paperfetch-oa` on your dev machine (it would shadow the private `papers` command).

**Hosted deployment:** After merge, Render rebuilds the image on push to `main`. Set `PAPERS_MAILTO` to a real email address in the Render dashboard settings (required for Unpaywall/OpenAlex/Crossref calls). Check that `GET /api/health` reports the new commit.

**Testing the change:**
- `python tests/test_offline.py` passes (test extended to verify both `queued_ckn` and `no_oa` are treated identically as "no open access")
- `docker build -t articlegen-test .` verifies the git install works with no credentials on a clean image
- Inside the image: `papers get <doi>` returns JSON with status `ok` for OA papers or `no_oa` for paywalled ones

## What stayed the same

- The private `paperfetch` repo and its CKN ladder are untouched; local `articlegen draft` still uses it
- Methods section still reports what actually happened (how many full texts read, which databases searched)
- Paywalled papers remain abstract-only everywhere; no attempt to fetch paywalled content
- `queued_ckn` is not renamed; both spellings live side by side in `NOT_OA_STATUSES`
- The `papers` console command is identical on both packages; pipeline code needs no changes beyond accepting the second status name

## No assumptions, no speculation

This write-up is traced to the diff only. The new spec and issue request files (`specs/f89aa3ce_hosted-paperfetch-oa.md` and `requests/issue-173-hosted-oa.md`) carry the full story and builder notes; this summary is for the next reader to understand what shipped.

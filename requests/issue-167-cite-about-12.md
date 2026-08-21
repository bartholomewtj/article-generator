Cite about 12 sources; keep screening 40, per GitHub issue #167 (below, verbatim).
Where: articlegen/writer.py (_BRIEFING_SYSTEM, _WRITER_SYSTEM, write_briefing, write_article), tests/test_offline.py, CLAUDE.md
Done means: DEFAULT_MAX_PAPERS stays 40; the writer (briefing and --long) is instructed to cite a working set of about 12, preferring direct sources, related only when they earn a specific point; Methods shows screened vs cited as two different numbers on a healthy run; both suites green.
Out of scope: dropping the pool back to 20; truncating curation abstracts (CURATION_ABSTRACT_CHARS stays None); hiding uncited candidates from Table 1 (Table 1 is cited records; the screened count lives in Methods); putting --long on the web UI; regenerating drafts/.

--- Issue #167 as written ---
Cite about 12 sources. Keep screening 40.

The candidate pool is 40 so the relevance gate has something to throw away (#141). The shipped drafts still cite almost everything they screened: safety-planning 20/20, seclusion 17/20. That is inclusion, not curation. A briefing cannot carry 17 papers.

## What to change

- Screen `DEFAULT_MAX_PAPERS` (40). Leave that.
- Instruct the writer (briefing and `--long`) to cite a working set, about 12, preferring direct sources. Related only when they earn a specific point. Tangential already withheld.
- Methods should show screened vs cited as two different numbers on a healthy run.

## What not to do

- Do not drop the pool back to 20.
- Do not truncate curation abstracts (#117, closed).
- Do not hide uncited candidates from Table 1's story — Table 1 is cited records. The screened count lives in Methods.

Measure on the next few real runs: cited-of-screened should fall well below the 16–19 of 20 that prompted #141. If it does not, the problem is the prompt, not the cap.

Refs #141, stays open until this lands.

# Direct-Scaled Citation Ceiling, Topic Fidelity, and Full-Text Preference (#188)

## Overview

Addresses three failure modes identified across four measured briefing runs (issue #188):
1. **Thin-direct candidate pools padded citations up to 12:** When told "cite about 12", runs with few direct sources filled the list with related sources and weak primary studies.
2. **Question and title drift:** The generated `question` and `title` shifted away from the reader's topic by narrowing the population, adding clauses, or widening to match the retrieved literature.
3. **Unused full texts:** When open-access full texts were retrieved, the writer occasionally left deep-read sources uncited while padding with abstract-only case reports.

## Key Changes

### 1. Dynamic Cite Target (`articlegen/writer.py`, `articlegen/pipeline.py`)

- Added `MIN_CITED_SOURCES = 5` alongside `TARGET_CITED_SOURCES = 12`.
- Added pure function `cite_target(n_direct: int | None, shown: int) -> int`:
  - Returns `min(TARGET_CITED_SOURCES, n_direct + 2)`, floored at `MIN_CITED_SOURCES` (5), and capped at `shown`.
  - For unlabelled runs (`n_direct is None`), defaults to `TARGET_CITED_SOURCES` (12) capped at `shown`.
- Updated `_WORKING_SET_RULE`:
  - Changed instruction from "Cite about 12" to "Cite AT MOST 12 sources, and never more than two beyond the number labelled direct."
  - Emphasised that the ceiling is not a quota and that citing fewer is expected on thin evidence bases.
  - Capped related sources at at most two, permitted only when making a specific point no direct source makes.
- Updated `_writer_context()`:
  - Calculates the run's dynamic target via `cite_target(counts.get("direct") if counts else None, shown)`.
  - WORKING SET prompt block explicitly states the ceiling and direct count.
- Added pipeline logging in `generate_draft()` (`articlegen/pipeline.py`):
  - Emits `cite ceiling: <target> (<n_direct> direct of <shown> shown)`.

### 2. Topic Fidelity in Question and Title (`articlegen/writer.py`)

- Added `_TOPIC_FIDELITY_RULE` spliced into `_WRITER_SYSTEM`, `_BRIEFING_SYSTEM`, and their full-text variants. Instructs the model that the topic is fixed: it may polish clumsy phrasing, but may not add clauses, narrow populations, or broaden to retrieved content.
- Updated `_TITLE_RULE` to require that the title preserves the reader's topic, population, and scope.
- Updated `_BRIEFING_SCHEMA["properties"]["question"]["description"]` to specify restating the reader's topic as asked without added clauses or narrowed populations.
- Updated `_writer_context()` with a dedicated topic preamble stating that the reader's question must remain on-topic.

### 3. Full-Text Preference Prompting (`articlegen/writer.py`)

- In `_writer_context()`, when retrieved full-text excerpts are available and not omitted as tangential, a `DEEP READS` instruction is emitted naming the specific SOURCE numbers with full text (`SOURCE <i, ...>`).
- Directs the model to prefer deep-read sources over abstract-only case reports.

## Affected Files

- `articlegen/writer.py`: Added `MIN_CITED_SOURCES`, `cite_target()`, `_TOPIC_FIDELITY_RULE`; updated `_WORKING_SET_RULE`, `_TITLE_RULE`, `_BRIEFING_SCHEMA`, and `_writer_context()`.
- `articlegen/pipeline.py`: Added `cite_target` import and cite ceiling log line in `generate_draft()`.
- `tests/test_offline.py`: Updated `test_the_writer_cites_a_working_set` for the new "at most" phrasing; added `test_the_cite_ceiling_scales_with_the_direct_count`.
- `CLAUDE.md`: Added invariant rows and documentation for `cite_target` and full-text prompt preference.
- `docs/decisions.md`: Recorded decision context under `#188`.
- `specs/bf08f4f9_cap-cites-to-direct.md`: Implementation specification.

## Verification

Run offline logic and journal conformance test suites:

```bash
python tests/test_offline.py
python tests/test_journal_conformance.py
```

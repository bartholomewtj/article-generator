# Plan — issue #147: repair near-miss JSON on the `claude-cli` path

## What this fixes

`claude-cli` cannot be given a `response_format`, so the shape of its reply is
only ever requested, never enforced. Measured: 3 of 5 `write_article` calls on
`cli:opus` returned non-JSON at least once, and one run died after the single
retry with `Expecting ',' delimiter: line 1 column 4942` — a complete, well
formed article object with one comma missing deep inside it, thrown away over a
syntax slip.

The fix is a **deterministic** repair pass. After the existing brace-matching
extraction fails to parse, try three narrow textual fixes, and accept the result
only if it then parses **and** is a dict. No LLM call repairs JSON — a model
asked to fix its own output rewrites it, and we would lose the article we were
trying to save.

Nothing else changes: the retry-once behaviour stays, refusals stay non-retried
(same model, same answer), and the `gemini-cli` path is not touched.

## Files to change

1. `articlegen/llm.py` — add the repair functions, call them from
   `_claude_cli_generate`.
2. `tests/test_offline.py` — extend `test_claude_cli_provider`.
3. `CLAUDE.md` — the `claude-cli` bullet says "Three defences"; repair makes it
   four.
4. `docs/decisions.md` — short entry under `## Providers` recording the measured
   failure (optional but in keeping with the repo's convention).

Do not touch `drafts/`, `adws/`, `.github/`, or the `gemini-cli` path.

## 1. `articlegen/llm.py`

Add two module-level functions in the **claude cli** section, directly after
`_extract_json_object` (around line 298) and before `_CLI_JSON_DEMAND`.

### `_repair_json_text(text: str) -> str`

One string-aware left-to-right pass that rebuilds the text. Reuse the same
scanner shape as `_extract_json_object`: track `in_string` and `escaped`, flip
`in_string` on an unescaped `"`.

While **inside** a string literal:

- a bare newline becomes `\n` (two characters), a bare carriage return becomes
  `\r`. That is the whole of it — a bare tab is the same class of slip but is
  deliberately left out, because the issue names newlines and a wider sweep is a
  wider chance of mangling something that would have parsed.
- everything else is copied through unchanged, including braces, brackets and
  escaped quotes.

While **outside** a string literal:

- **Trailing comma.** On a `,`, look ahead past whitespace. If the next
  non-whitespace character is `}` or `]`, drop the comma.
- **Missing comma at a value boundary.** After emitting a *closing* token — the
  `"` that ends a string, or a `}` or `]` — look ahead past whitespace. If the
  next non-whitespace character is an *opening* token (`"`, `{` or `[`), insert
  a `,`. This covers the three shapes the issue names (`"…" "…"`, `} {`, `] [`)
  and their cross-combinations (`} "`, `" {`, `] {` …) with one uniform rule.

That rule is safe on valid JSON, and this is the reason to prefer it to a
special case per shape: **in a valid document a value can only be followed by
`,`, `:`, `}`, `]` or end-of-input**, never by `"`, `{` or `[`. So the pass is a
no-op on anything that already parses. Pin that with a test (below).

Keep numbers, `true`/`false`/`null` out of the boundary rule — a missing comma
after a bare number (`{"a": 1 "b": 2}`) is not the measured shape, and detecting
the end of a number token adds scanning state for no evidence.

### `_repair_json(text: str) -> dict | None`

```
candidate = _repair_json_text(text)
try:
    obj = json.loads(candidate)
except json.JSONDecodeError:
    return None
return obj if isinstance(obj, dict) else None
```

The `isinstance` half is the acceptance rule from the issue and is load-bearing:
`[1, 2,]` repairs into perfectly valid JSON that is not an article, and every
caller of `generate_json` expects a mapping.

Both functions get a docstring saying **why** the repair is deterministic and
why the dict check is not optional.

### Wiring it into `_claude_cli_generate` (lines 445–464)

Two call sites, both after a failed `json.loads`, before the decision that
follows:

```python
envelope, cleaned = _run(preamble + prompt + _CLI_JSON_DEMAND)
try:
    return json.loads(cleaned)
except json.JSONDecodeError as exc:
    repaired = _repair_json(cleaned)
    if repaired is not None:
        print(f"[articlegen] claude-cli {model} returned near-miss JSON; "
              f"repaired deterministically ({exc})", file=sys.stderr, flush=True)
        return repaired
    print(f"[articlegen] claude-cli {model} replied with non-JSON; retrying once",
          file=sys.stderr, flush=True)

envelope, cleaned = _run(_CLI_JSON_RETRY + preamble + prompt + _CLI_JSON_DEMAND)
try:
    return json.loads(cleaned)
except json.JSONDecodeError as exc:
    repaired = _repair_json(cleaned)
    if repaired is not None:
        print(... same line ..., file=sys.stderr, flush=True)
        return repaired
    raise RuntimeError(
        ... existing message, with "repair did not help" added ...
    ) from exc
```

Three details that matter:

- **`is not None`, never a truth test.** A repaired `{}` is falsy and would fall
  through to a retry that has nothing left to do.
- **Repair runs before each retry decision, never in place of one.** A reply
  that repair cannot fix still gets its one retry, exactly as now.
- **Log the decoder's message.** The operator should be able to see which slip
  was repaired without re-running anything; that is how #147 was measured in the
  first place.

`json.loads` on the untouched text stays the first thing tried, so a valid reply
never reaches the repair code and its behaviour is byte-identical to today's.

Leave the refusal branch (`envelope.get("is_error")`, line 419) alone — it
raises before any of this, which is the existing rule.

## 2. `tests/test_offline.py`

Extend `test_claude_cli_provider` (line 2722) in its `-- prose replies --`
section, after the existing `_extract_json_object` checks around line 2838. Do
not add a new entry to the `main()` roster — this is the guard test for this
path already, and CLAUDE.md names it.

Add, in the repo's `check("sentence", condition)` style:

```python
# -- deterministic repair (#147) ---------------------------------------
# 3 of 5 write_article calls on cli:opus returned non-JSON at least once,
# and one run died after its retry on "Expecting ',' delimiter: line 1
# column 4942" — a complete article object one comma short.
check("a missing comma between two values is repaired",
      llm._repair_json('{"a": "one" "b": "two"}') == {"a": "one", "b": "two"})
check("and the same slip between two objects in an array",
      llm._repair_json(
          '{"sections": [{"heading": "H1"} {"heading": "H2"}]}')
      == {"sections": [{"heading": "H1"}, {"heading": "H2"}]})
check("a trailing comma before } or ] is dropped",
      llm._repair_json('{"a": [1, 2,], "b": 3,}') == {"a": [1, 2], "b": 3})
check("a bare newline inside a string is escaped",
      llm._repair_json('{"a": "line one\nline two"}')
      == {"a": "line one\nline two"})
# The acceptance rule is parses AND dict. This repairs into valid JSON
# that no caller of generate_json can use.
check("a repair that yields a list is refused",
      llm._repair_json('[1, 2,]') is None)
# A refusal is prose. There is nothing in it to salvage, and inventing a
# dict from an apology would hand the pipeline a fake article.
check("a refusal does not repair into anything",
      llm._repair_json("I'm sorry, I can't help with that.") is None)
check("neither does a YAML reply",
      llm._repair_json("core_entity: safety planning\nqueries:\n  - a") is None)
# The pass is a no-op on anything that already parses: in valid JSON a
# value is only ever followed by , : } ] or the end.
_valid = '{"a": "x, y", "b": [1, 2], "c": {"d": "has } and \\" quote"}}'
check("valid JSON passes through the repair untouched",
      llm._repair_json_text(_valid) == _valid)
```

Then an end-to-end check that the run does **not** spend its retry on a
near-miss — the actual point of the issue. Model it on the existing
`yaml_then_json` block (lines 2840–2867): a fake `subprocess.run` that appends
to a `calls` list and returns a `result` of `'{"article": "body" "title": "T"}'`.

```python
check("a near-miss reply is repaired on the first call, no retry spent",
      out == {"article": "body", "title": "T"} and len(near_miss_calls) == 1)
```

And one that an unfixable reply still fails after exactly two calls: a fake that
returns prose both times, expecting `RuntimeError` and `len(calls) == 2`.

Restore `subprocess.run` and `shutil.which` in a `finally` in every block, as
the surrounding tests do.

## 3. `CLAUDE.md`

Rewrite lines 419–424 (the `claude-cli` bullet). Current text:

> - **`claude-cli` enforces no response schema**, unlike the API paths. Three
>   defences, all load-bearing: the format demand is repeated at the *end* of the
>   user prompt, a fenced or prose-wrapped object is recovered by string-aware
>   brace matching, and an unparseable reply is retried once. A **refusal** is not
>   retried: same model, same answer. Suppress MCP servers with
>   `--strict-mcp-config` and an empty `--mcp-config`, or pay a 10x prompt tax.

Replacement (keep the file's ~79-column wrap and its voice):

> - **`claude-cli` enforces no response schema**, unlike the API paths. Four
>   defences, all load-bearing: the format demand is repeated at the *end* of the
>   user prompt, a fenced or prose-wrapped object is recovered by string-aware
>   brace matching, a near-miss is repaired deterministically — trailing commas,
>   a missing comma at a value boundary, bare newlines inside strings — and
>   accepted **only if it then parses to a dict**, and an unparseable reply is
>   retried once. Repair runs before each retry decision, never instead of one,
>   and never as an LLM call: a model asked to fix its own JSON rewrites it, and
>   the near-miss it was meant to save is what gets lost (#147). A **refusal** is
>   not retried: same model, same answer. Suppress MCP servers with
>   `--strict-mcp-config` and an empty `--mcp-config`, or pay a 10x prompt tax.

`test_claude_md_still_describes_this_code` checks backticked file paths,
`` `test_*` `` names and `` `SHOUTY_CONSTANTS` ``. The replacement introduces
none of those, so it passes as written — but do not backtick a helper name that
does not exist.

## 4. `docs/decisions.md` (short, optional)

Under `## Providers`, a `###` entry of a few lines: the measured 3-of-5 rate, the
`column 4942` failure, why repair is deterministic rather than a second model
call, and why acceptance is "parses **and** is a dict". Keep it to the story —
the invariant lives in CLAUDE.md.

## Verify

```
python tests/test_offline.py
python tests/test_journal_conformance.py
```

Both must exit 0. Judge them by exit status, not by scanning the output for the
word "error". No live run is needed: nothing here touches a model id, an output
ceiling, the routing or `sources.py`.

## Guard rails

- `_extract_json_object` keeps its current behaviour and signature — the
  `gemini-cli` path (line 581) calls it too.
- `json.loads` on the untouched reply stays the first attempt, so a valid reply
  is unaffected and a top-level list still returns as it does today. The dict
  requirement applies to the **repair** path only.
- No git state changes: no branch, commit, push or reset.

## Commit message

```
Repair near-miss JSON from claude-cli instead of failing the draft

Fixes #147
```

"""Provider layer: one `generate_json()` call, backed by Anthropic (Claude) or Google (Gemini).

Provider resolution, in priority order:
1. The model name, when given: `claude-*` -> Anthropic, `gemini-*` -> Google.
2. ARTICLEGEN_PROVIDER env var ("anthropic" or "google").
3. Whichever API key is present: GEMINI_API_KEY / GOOGLE_API_KEY, then ANTHROPIC_API_KEY.
4. Fallback: Gemini (the default provider).

Gemini is the default: with only a GEMINI_API_KEY set it's used automatically,
and it wins when both providers' keys are present. Claude is opt-in — set
ARTICLEGEN_PROVIDER=anthropic, pass a `claude-*` --model, or run with only an
Anthropic key.
"""

from __future__ import annotations

import json
import os
import sys
import time

ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"
GOOGLE_DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_PROVIDER = "google"

# Cache the model we've confirmed this key can use, so we discover at most once
# per process (a draft run makes two Gemini calls).
_RESOLVED_GOOGLE_MODEL: str | None = None


def resolve_provider(model: str | None = None) -> tuple[str, str]:
    """Return (provider, model). `model` may be empty -> use the provider's default."""
    if model:
        if model.startswith("claude"):
            return "anthropic", model
        if model.startswith(("gemini", "models/gemini")):
            return "google", model

    forced = os.environ.get("ARTICLEGEN_PROVIDER", "").strip().lower()
    if forced in ("anthropic", "google"):
        provider = forced
    elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        provider = "google"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        provider = "anthropic"
    else:
        provider = DEFAULT_PROVIDER  # Gemini by default

    default = GOOGLE_DEFAULT_MODEL if provider == "google" else ANTHROPIC_DEFAULT_MODEL
    return provider, model or default


def generate_json(
    prompt: str,
    schema: dict,
    *,
    system: str | None = None,
    model: str | None = None,
    deep: bool = False,
) -> dict:
    """Run one structured-output generation and return the parsed JSON object.

    `deep=True` is for the long article call: bigger output budget and, on
    Anthropic, streaming + adaptive thinking at high effort.
    """
    provider, model = resolve_provider(model)
    print(f"[articlegen] using provider={provider} model={model}", file=sys.stderr, flush=True)
    if provider == "google":
        return _google_generate(prompt, schema, system, model, deep)
    return _anthropic_generate(prompt, schema, system, model, deep)


# ---------------------------------------------------------------- anthropic

def _anthropic_generate(prompt, schema, system, model, deep) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    if deep:
        with client.messages.stream(
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": schema},
            },
            **kwargs,
        ) as stream:
            response = stream.get_final_message()
    else:
        response = client.messages.create(
            max_tokens=8000,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            **kwargs,
        )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# ---------------------------------------------------------------- google

def _gemini_schema(node):
    """Translate our JSON Schema subset to what Gemini's response_schema accepts:
    drop `additionalProperties`, turn ["string","null"] unions into nullable types."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key == "additionalProperties":
                continue
            out[key] = _gemini_schema(value)
        type_value = out.get("type")
        if isinstance(type_value, list):
            non_null = [t for t in type_value if t != "null"]
            out["type"] = non_null[0] if non_null else "string"
            if "null" in type_value:
                out["nullable"] = True
        return out
    if isinstance(node, list):
        return [_gemini_schema(item) for item in node]
    return node


_UNAVAILABLE_HINTS = (
    "not_found", "not found", "no longer available",
    "not available", "is not supported", "does not exist",
)


def _is_model_unavailable(exc) -> bool:
    if getattr(exc, "code", None) == 404:
        return True
    text = str(getattr(exc, "message", "") or exc).lower()
    return any(hint in text for hint in _UNAVAILABLE_HINTS)


_TRANSIENT_HINTS = (
    "high demand", "overloaded", "unavailable", "try again",
    "resource_exhausted", "rate limit", "deadline",
)


def _is_transient(exc) -> bool:
    if getattr(exc, "code", None) in (429, 500, 502, 503, 504):
        return True
    text = str(getattr(exc, "message", "") or exc).lower()
    return any(hint in text for hint in _TRANSIENT_HINTS)


def _generate_once(client, model, prompt, config, tries: int = 5):
    """Call Gemini, retrying transient overload/rate-limit errors with backoff.
    Model-unavailable errors are re-raised immediately so the caller can rediscover."""
    delay = 4.0
    for attempt in range(tries):
        try:
            return client.models.generate_content(model=model, contents=prompt, config=config)
        except Exception as exc:
            if _is_model_unavailable(exc):
                raise
            if _is_transient(exc) and attempt < tries - 1:
                print(
                    f"[articlegen] transient error from Gemini (attempt {attempt + 1}/{tries}), "
                    f"retrying in {delay:.0f}s: {exc}",
                    file=sys.stderr, flush=True,
                )
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            raise


def _rank_google_model(name: str) -> tuple:
    n = name.lower()
    return ("flash" in n, "latest" in n, n)  # prefer flash, then 'latest', then newest by name


def _discover_google_model(client) -> str | None:
    """Pick a currently-available generateContent Gemini model for this key."""
    global _RESOLVED_GOOGLE_MODEL
    if _RESOLVED_GOOGLE_MODEL:
        return _RESOLVED_GOOGLE_MODEL
    try:
        models = list(client.models.list())
    except Exception:
        return None

    bad = ("embedding", "aqa", "imagen", "vision", "tts", "image-generation", "learnlm")
    candidates = []
    for m in models:
        name = (getattr(m, "name", "") or "")
        actions = [a.lower() for a in (getattr(m, "supported_actions", None) or [])]
        low = name.lower()
        if "gemini" not in low or any(b in low for b in bad):
            continue
        if actions and "generatecontent" not in actions:
            continue
        candidates.append(name)
    if not candidates:
        return None
    _RESOLVED_GOOGLE_MODEL = max(candidates, key=_rank_google_model)
    return _RESOLVED_GOOGLE_MODEL


def _build_google_config(types, system, schema, deep, thinking_budget):
    # Disable thinking (budget 0) for these schema-constrained calls: on 2.5 flash,
    # thinking under structured output can run away and truncate into invalid JSON.
    kwargs = dict(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=_gemini_schema(schema),
        max_output_tokens=65535 if deep else 16384,
    )
    if thinking_budget is not None:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
    return types.GenerateContentConfig(**kwargs)


def _finish_reason(response) -> str:
    try:
        fr = response.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return ""
    return getattr(fr, "name", str(fr or ""))


def _parse_google_response(response) -> dict:
    reason = _finish_reason(response)
    text = (response.text or "").strip()
    if not text:
        feedback = getattr(response, "prompt_feedback", None)
        raise RuntimeError(
            f"Gemini returned no text (finish_reason={reason}, prompt_feedback={feedback})."
        )
    if text.startswith("```"):  # strip an accidental markdown fence
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        if reason == "MAX_TOKENS":
            raise RuntimeError(
                "Gemini's reply was cut off at the output-token limit, so the JSON is "
                "incomplete. Try again, or narrow the request."
            ) from exc
        raise RuntimeError(f"Gemini returned invalid JSON (finish_reason={reason}): {exc}") from exc


def _google_generate(prompt, schema, system, model, deep) -> dict:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "The Google backend needs the google-genai package: pip install google-genai"
        ) from exc

    client = genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment
    config = _build_google_config(types, system, schema, deep, thinking_budget=0)
    target = _RESOLVED_GOOGLE_MODEL or model

    try:
        response = _generate_once(client, target, prompt, config)
    except Exception as exc:
        message = str(getattr(exc, "message", "") or exc).lower()
        if _is_model_unavailable(exc):
            alt = _discover_google_model(client)
            if not alt or alt == target:
                raise RuntimeError(
                    f"Gemini model {target!r} is unavailable and no working alternative "
                    f"was found for this API key. Set --model explicitly. ({exc})"
                ) from exc
            print(f"[articlegen] model {target!r} unavailable; using {alt!r}", file=sys.stderr, flush=True)
            response = _generate_once(client, alt, prompt, config)
        elif "thinking" in message:
            # This model won't accept disabled thinking; retry with default thinking.
            print("[articlegen] model rejected thinking_budget=0; retrying with default thinking",
                  file=sys.stderr, flush=True)
            config = _build_google_config(types, system, schema, deep, thinking_budget=None)
            response = _generate_once(client, target, prompt, config)
        else:
            raise

    return _parse_google_response(response)

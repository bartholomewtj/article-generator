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

ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"
GOOGLE_DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_PROVIDER = "google"


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


def _google_generate(prompt, schema, system, model, deep) -> dict:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "The Google backend needs the google-genai package: pip install google-genai"
        ) from exc

    client = genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY from the environment
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=_gemini_schema(schema),
        max_output_tokens=65535 if deep else 8192,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    if not response.text:
        feedback = getattr(response, "prompt_feedback", None)
        raise RuntimeError(f"Gemini returned no text (prompt_feedback={feedback}).")
    return json.loads(response.text)

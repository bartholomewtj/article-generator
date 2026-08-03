"""Provider layer: one `generate_json()` call, backed by Groq or Anthropic (Claude).

Provider resolution, in priority order:
1. The model name, when given: `claude-*` -> Anthropic, `llama*`/`mixtral*`/`groq*` -> Groq.
2. An explicitly passed `api_key`, by its prefix: `sk-ant-` -> Anthropic, `gsk_` -> Groq.
3. ARTICLEGEN_PROVIDER env var ("anthropic" or "groq").
4. Whichever API key is present: GROQ_API_KEY, then ANTHROPIC_API_KEY.
5. Fallback: Groq (the default provider).

Keys are passed **per call**, never through `os.environ`. The server handles
concurrent requests on different threads, and the environment is process-global:
setting a caller's key there lets one request's pipeline pick up another's key
several seconds later. `api_key=None` falls back to the environment, which is
what the CLI wants and what a single-user local run has always done.

Groq is the default provider: with GROQ_API_KEY set it's used automatically.
Claude is opt-in — set ARTICLEGEN_PROVIDER=anthropic, pass a `claude-*` --model, or run with only an Anthropic key.
"""

from __future__ import annotations

import json
import os
import sys
import time

GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_PROVIDER = "groq"

_RESOLVED_GROQ_MODEL: str | None = None


def resolve_provider(model: str | None = None, api_key: str | None = None) -> tuple[str, str]:
    """Return (provider, model). `model` may be empty -> use the provider's default."""
    if model:
        if model.startswith("claude"):
            return "anthropic", model
        if model.startswith(("llama", "mixtral", "gemma", "deepseek", "qwen", "groq")):
            return "groq", model

    forced = os.environ.get("ARTICLEGEN_PROVIDER", "").strip().lower()
    if api_key and api_key.startswith("sk-ant-"):
        provider = "anthropic"
    elif api_key and api_key.startswith("gsk_"):
        provider = "groq"
    elif forced in ("anthropic", "groq"):
        provider = forced
    elif os.environ.get("GROQ_API_KEY"):
        provider = "groq"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        provider = "anthropic"
    else:
        provider = DEFAULT_PROVIDER  # Groq by default

    default = GROQ_DEFAULT_MODEL if provider == "groq" else ANTHROPIC_DEFAULT_MODEL
    return provider, model or default


def generate_json(
    prompt: str,
    schema: dict,
    *,
    system: str | None = None,
    model: str | None = None,
    deep: bool = False,
    api_key: str | None = None,
) -> dict:
    """Run one structured-output generation and return the parsed JSON object.

    `deep=True` is for the long article call: bigger output budget and, on
    Anthropic, streaming + adaptive thinking at high effort.

    `api_key` overrides the environment for this call only — see the module
    docstring for why the server must never route keys through `os.environ`.
    """
    provider, model = resolve_provider(model, api_key)
    print(f"[articlegen] using provider={provider} model={model}", file=sys.stderr, flush=True)
    if provider == "groq":
        return _groq_generate(prompt, schema, system, model, deep, api_key)
    return _anthropic_generate(prompt, schema, system, model, deep, api_key)


# ---------------------------------------------------------------- anthropic

def _anthropic_generate(prompt, schema, system, model, deep, api_key=None) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
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


# ---------------------------------------------------------------- groq

def _clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return text


def _groq_generate(
    prompt: str, schema: dict, system: str | None, model: str, deep: bool, api_key: str | None = None
) -> dict:
    api_key = api_key or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is not set. "
            "Get a free key at https://console.groq.com/keys and set GROQ_API_KEY."
        )

    system_instruction = (
        (system or "") +
        "\n\nIMPORTANT: You must respond ONLY with a valid JSON object matching this schema. "
        "Do NOT enclose in backticks or markdown fences. Do NOT output any conversational text or commentary.\n"
        f"JSON Schema:\n{json.dumps(schema)}"
    )

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt},
    ]

    text_response = ""
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            max_completion_tokens=8000 if not deep else 16000,
        )
        text_response = completion.choices[0].message.content or ""
    except ImportError:
        import requests
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 8000 if not deep else 16000,
        }
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=120)
        res.raise_for_status()
        data = res.json()
        text_response = data["choices"][0]["message"]["content"] or ""

    cleaned = _clean_json_text(text_response)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Groq returned invalid JSON: {exc}\nRaw response:\n{text_response[:500]}") from exc

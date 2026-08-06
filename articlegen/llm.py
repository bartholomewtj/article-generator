"""Provider layer: one `generate_json()` call, backed by Groq, Anthropic (Claude) or OpenRouter.

Provider resolution, in priority order:
1. The model name, when given: a `vendor/model` slug -> OpenRouter, `claude-*` ->
   Anthropic, `llama*`/`mixtral*`/`groq*` -> Groq. The slash is checked first
   because OpenRouter re-sells the other providers' models under names like
   `anthropic/claude-sonnet-5`, which must not route to Anthropic directly.
2. An explicitly passed `api_key`, by its prefix: `sk-ant-` -> Anthropic,
   `gsk_` -> Groq, `sk-or-` -> OpenRouter.
3. ARTICLEGEN_PROVIDER env var ("anthropic", "groq" or "openrouter").
4. Whichever API key is present: GROQ_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY.
5. Fallback: Groq (the default provider).

Keys are passed **per call**, never through `os.environ`. The server handles
concurrent requests on different threads, and the environment is process-global:
setting a caller's key there lets one request's pipeline pick up another's key
several seconds later. `api_key=None` falls back to the environment, which is
what the CLI wants and what a single-user local run has always done.

Groq is the default provider: with GROQ_API_KEY set it's used automatically.
Claude is opt-in — set ARTICLEGEN_PROVIDER=anthropic, pass a `claude-*` --model, or run with only an Anthropic key.
OpenRouter is opt-in the same way, and is the option to reach for when Groq's
free daily cap is the binding constraint: it is prepaid credit rather than a
quota, so a run never fails because the day's allowance is spent.
"""

from __future__ import annotations

import json
import os
import sys
import time

GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
# Claude Fable 5 is the top of the Claude 5 family, above Opus in capability.
# `claude-opus-5` and `claude-opus-4-8` still work if you pass them with
# --model. Keep this in step with the Settings dropdown in index.html: the web
# app sends a model name, and web.ALLOWED_MODELS is built from the constants
# here, so a stale name there is quietly dropped rather than honoured.
ANTHROPIC_DEFAULT_MODEL = "claude-fable-5"
# The same Llama 3.3 70B the Groq default uses, so switching to OpenRouter
# changes what meters the run, not what writes it. At roughly $0.10/$0.32 per
# million tokens an article costs well under a cent, and OpenRouter bills
# prepaid credit rather than a daily allowance — which is the whole reason to
# use it. Pass any other catalogue slug with --model (e.g.
# `anthropic/claude-sonnet-5`) when the writing quality matters more.
OPENROUTER_DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"
DEFAULT_PROVIDER = "groq"

# Groq's free tier meters tokens per minute, and it counts the *reserved* output
# against that budget as well as the prompt. The article call used to reserve
# 16000 output tokens against a 12000 TPM limit, which cannot succeed no matter
# how short the prompt is:
#
#   413 ... on tokens per minute (TPM): Limit 12000, Requested 20916
#
# So the reservation has to fit inside the limit with room for the prompt. A
# 1600-word article in JSON runs about 2500-3000 tokens, so 5000 is generous.
GROQ_FREE_TPM = 12000
GROQ_DEEP_OUTPUT = 5000
GROQ_OUTPUT = 4000

# Rough English average. Used only to size a prompt before sending it, where
# being approximately right in the safe direction is what matters.
CHARS_PER_TOKEN = 4


def prompt_budget_chars(model: str | None = None, api_key: str | None = None) -> int | None:
    """How many characters of source material this provider can take, or None for no limit.

    Anthropic's and OpenRouter's limits are far above anything this pipeline
    produces, so only Groq needs trimming. OpenRouter meters prepaid credit
    rather than tokens per minute, so the same Llama 3.3 70B that has to be
    trimmed on Groq's free tier can take the full source payload here.
    """
    provider, _ = resolve_provider(model, api_key)
    if provider != "groq":
        return None
    # Everything except the sources — system prompt, instructions, schema — runs
    # to roughly 1500 tokens; leave that plus the output reservation. The margin
    # matters because CHARS_PER_TOKEN is an estimate: technical abstracts full of
    # long words and numbers tokenize worse than plain English, and being over
    # the limit costs the whole run rather than a bit of quality.
    overhead_tokens = 1500
    safety_margin_tokens = 1500
    spare = GROQ_FREE_TPM - GROQ_DEEP_OUTPUT - overhead_tokens - safety_margin_tokens
    return max(spare, 1000) * CHARS_PER_TOKEN


_PROVIDER_DEFAULT_MODELS = {
    "groq": GROQ_DEFAULT_MODEL,
    "anthropic": ANTHROPIC_DEFAULT_MODEL,
    "openrouter": OPENROUTER_DEFAULT_MODEL,
}


def resolve_provider(model: str | None = None, api_key: str | None = None) -> tuple[str, str]:
    """Return (provider, model). `model` may be empty -> use the provider's default."""
    if model:
        # Checked before the `claude` prefix: OpenRouter re-sells other
        # providers' models as `vendor/model`, and `anthropic/claude-sonnet-5`
        # sent to Anthropic's own SDK is a 404. The slash is what makes a name
        # an OpenRouter slug; no direct provider's model id contains one.
        if "/" in model:
            return "openrouter", model
        if model.startswith("claude"):
            return "anthropic", model
        if model.startswith(("llama", "mixtral", "gemma", "deepseek", "qwen", "groq")):
            return "groq", model

    forced = os.environ.get("ARTICLEGEN_PROVIDER", "").strip().lower()
    if api_key and api_key.startswith("sk-ant-"):
        provider = "anthropic"
    elif api_key and api_key.startswith("sk-or-"):
        provider = "openrouter"
    elif api_key and api_key.startswith("gsk_"):
        provider = "groq"
    elif forced in _PROVIDER_DEFAULT_MODELS:
        provider = forced
    elif os.environ.get("GROQ_API_KEY"):
        provider = "groq"
    elif os.environ.get("ANTHROPIC_API_KEY"):
        provider = "anthropic"
    elif os.environ.get("OPENROUTER_API_KEY"):
        provider = "openrouter"
    else:
        provider = DEFAULT_PROVIDER  # Groq by default

    return provider, model or _PROVIDER_DEFAULT_MODELS[provider]


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
    if provider == "openrouter":
        return _openrouter_generate(prompt, schema, system, model, deep, api_key)
    return _anthropic_generate(prompt, schema, system, model, deep, api_key)


# ---------------------------------------------------------------- anthropic

# Claude Opus 5 (and the Fable/Mythos tier above it) runs safety classifiers
# that can decline a request outright: a normal HTTP 200 with stop_reason
# "refusal" and no text. The topics here are clinical and user-supplied, so a
# false positive is possible, and it used to cost the whole run (issue #45).
# The server-side fallback re-runs a declined request on Anthropic's
# recommended substitute model, routed by refusal category, inside the same
# call. "default" rather than a pinned model name, so nothing here needs
# migrating when a fallback model is deprecated. Models without these
# classifiers don't take the parameter, so it is attached by model prefix.
_REFUSAL_FALLBACK_MODELS = ("claude-opus-5", "claude-fable", "claude-mythos")
_REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _refusal_fallback_kwargs(model: str) -> dict:
    if not model.startswith(_REFUSAL_FALLBACK_MODELS):
        return {}
    return {"betas": [_REFUSAL_FALLBACK_BETA], "fallbacks": "default"}


def _anthropic_generate(prompt, schema, system, model, deep, api_key=None) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    kwargs.update(_refusal_fallback_kwargs(model))
    if system:
        kwargs["system"] = system

    if deep:
        with client.beta.messages.stream(
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
        # `max_tokens` caps thinking *and* the reply together, and on Claude
        # Opus 5 adaptive thinking is on whenever the parameter is omitted — so
        # the ceiling that was ample for a bare JSON reply on Opus 4.8 can now
        # truncate one mid-object. The curation call in particular grades twenty
        # sources at once.
        response = client.beta.messages.create(
            max_tokens=16000,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            **kwargs,
        )

    if response.stop_reason == "refusal":
        # A safety classifier declined. This arrives as a normal 200 with no
        # text block, so without this check the generator below raises
        # StopIteration and the caller reports an empty, baffling failure.
        # On models with the server-side fallback attached, reaching here
        # means the fallback model declined too, not that no retry happened.
        detail = getattr(response, "stop_details", None)
        category = getattr(detail, "category", None) or "unspecified"
        raise RuntimeError(
            f"The model declined this request ({category}). Rephrase the topic, "
            "or generate it with Groq instead."
        )
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "The model hit its output limit before finishing the JSON. Try a "
            "narrower topic, or --max-papers with a smaller number."
        )

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise RuntimeError(f"The model returned no text (stop_reason={response.stop_reason}).")
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
            max_completion_tokens=GROQ_DEEP_OUTPUT if deep else GROQ_OUTPUT,
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
            "max_tokens": GROQ_DEEP_OUTPUT if deep else GROQ_OUTPUT,
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


# ---------------------------------------------------------------- openrouter

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# No tokens-per-minute ceiling to fit inside, unlike Groq — OpenRouter bills
# prepaid credit — so the reservation only has to be big enough for the reply.
# A 1600-word article in JSON runs about 2500-3000 tokens, but reasoning models
# (claude-fable-5, claude-sonnet-5) think inside `max_tokens` too, and a
# truncated reply is invalid JSON, not a short one: at 8000 the revision pass
# hit the ceiling on every reasoning-model run and was discarded. Same trap,
# same fix as the Anthropic path's shallow-call ceiling.
OPENROUTER_DEEP_OUTPUT = 16000
OPENROUTER_OUTPUT = 8000


def _openrouter_generate(
    prompt: str, schema: dict, system: str | None, model: str, deep: bool, api_key: str | None = None
) -> dict:
    import requests

    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY environment variable is not set. "
            "Create a key at https://openrouter.ai/keys and set OPENROUTER_API_KEY."
        )

    # Belt and braces, exactly as on the Groq path: `response_format` is the
    # real constraint, but OpenRouter fronts many providers and the weaker ones
    # treat a schema as a hint, so the schema goes in the prompt too.
    system_instruction = (
        (system or "") +
        "\n\nIMPORTANT: You must respond ONLY with a valid JSON object matching this schema. "
        "Do NOT enclose in backticks or markdown fences. Do NOT output any conversational text or commentary.\n"
        f"JSON Schema:\n{json.dumps(schema)}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "articlegen", "strict": True, "schema": schema},
        },
        # Without this, OpenRouter may route to a provider that ignores
        # `response_format` entirely and answers in prose — a failure that looks
        # like the model being bad at instructions rather than a routing choice.
        "provider": {"require_parameters": True},
        "temperature": 0.2,
        "max_tokens": OPENROUTER_DEEP_OUTPUT if deep else OPENROUTER_OUTPUT,
    }

    def _post(body):
        return requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                # Attribution headers; optional, and they carry no user content.
                "HTTP-Referer": "https://github.com/bartholomewtj/article-generator",
                "X-Title": "articlegen",
            },
            json=body,
            timeout=180,
        )

    res = _post(payload)

    # `require_parameters` demands every sent parameter, not just
    # `response_format` — and reasoning models (e.g. anthropic/claude-sonnet-5)
    # expose no `temperature` at all, so its mere presence 404s with "No
    # endpoints found". Retry without it rather than give up `require_parameters`,
    # which is what actually protects the JSON output.
    if res.status_code == 404 and "temperature" in payload:
        retry = {k: v for k, v in payload.items() if k != "temperature"}
        res = _post(retry)

    if res.status_code == 401:
        raise RuntimeError("OpenRouter rejected the key. Check it at https://openrouter.ai/keys.")
    if res.status_code == 402:
        raise RuntimeError(
            "OpenRouter reports insufficient credit for this request. "
            "Top up at https://openrouter.ai/credits, or use a cheaper --model."
        )
    if res.status_code == 429:
        raise RuntimeError("OpenRouter is rate-limiting this key. Wait a moment and retry.")
    if res.status_code >= 400:
        raise RuntimeError(f"OpenRouter returned HTTP {res.status_code}: {res.text[:300]}")

    data = res.json()
    # A 200 can still carry an error body — an upstream provider refusing, or no
    # provider matching `require_parameters` for this model.
    if isinstance(data.get("error"), dict):
        message = data["error"].get("message") or "unspecified error"
        raise RuntimeError(f"OpenRouter could not complete the request: {message}")

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenRouter returned no choices: {json.dumps(data)[:300]}")
    if choices[0].get("finish_reason") == "length":
        raise RuntimeError(
            "The model hit its output limit before finishing the JSON. Try a "
            "narrower topic, or --max-papers with a smaller number."
        )

    text_response = (choices[0].get("message") or {}).get("content") or ""
    cleaned = _clean_json_text(text_response)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OpenRouter returned invalid JSON: {exc}\nRaw response:\n{text_response[:500]}"
        ) from exc

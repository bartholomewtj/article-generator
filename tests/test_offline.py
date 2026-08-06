"""Offline smoke tests — no network, no API keys required.

Run with:  python tests/test_offline.py   (exits non-zero on failure)

These cover the pure logic that a fresh session can verify immediately:
provider resolution, citation renumbering,
statistic verification, source ranking, and the render blocks. The LLM calls
and scholarly-API fetches are NOT exercised here (they need keys/network) —
verify those with a live `theme:` issue on GitHub.
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable when run as `python tests/test_offline.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILURES: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("OK   " if cond else "FAIL ") + name)
    if not cond:
        FAILURES.append(name)


def test_provider_resolution() -> None:
    for var in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "ARTICLEGEN_PROVIDER"):
        os.environ.pop(var, None)
    from articlegen.llm import resolve_provider, GROQ_DEFAULT_MODEL, ANTHROPIC_DEFAULT_MODEL

    check("no keys -> groq default", resolve_provider() == ("groq", GROQ_DEFAULT_MODEL))
    os.environ["ANTHROPIC_API_KEY"] = "x"
    check("only anthropic -> anthropic", resolve_provider() == ("anthropic", ANTHROPIC_DEFAULT_MODEL))
    os.environ["GROQ_API_KEY"] = "y"
    check("both keys -> groq wins", resolve_provider()[0] == "groq")
    check("claude-* model name forces anthropic", resolve_provider("claude-opus-5")[0] == "anthropic")
    check("superseded claude-* names still route",
          resolve_provider("claude-opus-4-8")[0] == "anthropic")
    check("llama-* model name forces groq", resolve_provider("llama-3.3-70b-versatile")[0] == "groq")
    os.environ["ARTICLEGEN_PROVIDER"] = "anthropic"
    check("provider override respected", resolve_provider()[0] == "anthropic")
    for var in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "ARTICLEGEN_PROVIDER"):
        os.environ.pop(var, None)


def test_per_request_api_key() -> None:
    """Keys must travel as arguments, never through the process environment.

    The web server is threaded; an env-var handoff lets one request's pipeline
    pick up another request's key several seconds later, and bill it.
    """
    for var in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "ARTICLEGEN_PROVIDER"):
        os.environ.pop(var, None)
    from articlegen.llm import resolve_provider

    check("gsk_ key -> groq", resolve_provider(None, "gsk_abc")[0] == "groq")
    check("sk-ant- key -> anthropic", resolve_provider(None, "sk-ant-abc")[0] == "anthropic")
    check("sk-or- key -> openrouter", resolve_provider(None, "sk-or-v1-abc")[0] == "openrouter")
    check(
        "explicit model still beats the key prefix",
        resolve_provider("claude-opus-5", "gsk_abc")[0] == "anthropic",
    )

    # The whole point: a passed key must not leak into the environment.
    import inspect
    from articlegen import ideas, llm, web, writer

    for fn in (
        llm.generate_json, ideas.generate_ideas, writer.plan_queries,
        writer.curate_sources, writer.write_article, writer.revise_prose,
    ):
        check(f"{fn.__name__} accepts api_key", "api_key" in inspect.signature(fn).parameters)

    src = inspect.getsource(llm) + inspect.getsource(web)
    check("no module assigns into os.environ", 'os.environ["GROQ_API_KEY"] =' not in src)
    check("groq key still falls back to the environment",
          "os.environ.get(\"GROQ_API_KEY\")" in inspect.getsource(llm._groq_generate))


def test_openrouter_routing() -> None:
    """OpenRouter is the escape hatch from Groq's daily cap — it must not steal
    the other providers' traffic, and must not hand their own model ids back to
    them prefixed.

    The slash is the whole discriminator: OpenRouter re-sells Claude as
    `anthropic/claude-sonnet-5`, which routed to Anthropic's SDK would 404.
    """
    for var in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "ARTICLEGEN_PROVIDER"):
        os.environ.pop(var, None)
    from articlegen.llm import (
        OPENROUTER_DEFAULT_MODEL, prompt_budget_chars, resolve_provider,
    )

    check("vendor/model slug -> openrouter",
          resolve_provider("meta-llama/llama-3.3-70b-instruct")[0] == "openrouter")
    check("a resold claude slug stays on openrouter",
          resolve_provider("anthropic/claude-sonnet-5")[0] == "openrouter")
    check("and keeps the slug as given",
          resolve_provider("anthropic/claude-sonnet-5")[1] == "anthropic/claude-sonnet-5")
    check("bare claude name still goes direct to anthropic",
          resolve_provider("claude-opus-5")[0] == "anthropic")
    check("bare llama name still goes direct to groq",
          resolve_provider("llama-3.3-70b-versatile")[0] == "groq")

    os.environ["OPENROUTER_API_KEY"] = "sk-or-v1-x"
    check("openrouter key alone selects it", resolve_provider()[0] == "openrouter")
    check("and supplies its default model", resolve_provider()[1] == OPENROUTER_DEFAULT_MODEL)
    os.environ["GROQ_API_KEY"] = "gsk_x"
    check("groq still wins when both keys are set", resolve_provider()[0] == "groq")
    os.environ.pop("GROQ_API_KEY", None)
    os.environ["ARTICLEGEN_PROVIDER"] = "openrouter"
    check("provider override accepts openrouter", resolve_provider()[0] == "openrouter")

    # Groq trims the source payload to fit a 12k tokens/minute ceiling that
    # OpenRouter does not have; trimming there would cost breadth for nothing.
    check("openrouter takes the full source payload",
          prompt_budget_chars("meta-llama/llama-3.3-70b-instruct") is None)
    for var in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "ARTICLEGEN_PROVIDER"):
        os.environ.pop(var, None)


def test_openrouter_request_shape() -> None:
    """The request has to pin structured output, or the article comes back as prose."""
    import inspect
    from articlegen import llm

    src = inspect.getsource(llm._openrouter_generate)
    check("asks for a json_schema response", '"type": "json_schema"' in src)
    check("in strict mode", '"strict": True' in src)
    check("and only routes to providers that honour it", '"require_parameters": True' in src)
    check("reads the key from OPENROUTER_API_KEY", 'os.environ.get("OPENROUTER_API_KEY")' in src)
    check("names the out-of-credit case", "402" in src)
    check("checks for an error body behind a 200", 'data.get("error")' in src)
    check("treats a truncated reply as an error", '"length"' in src)
    # Reasoning models (anthropic/claude-sonnet-5) expose no `temperature`, and
    # `require_parameters` demands every sent parameter — so sending it 404s
    # with "No endpoints found". The retry drops temperature, not the schema.
    check("retries a parameter 404 without temperature",
          'res.status_code == 404 and "temperature" in payload' in src)
    check("but never gives up require_parameters", src.count('"require_parameters"') == 1)


def test_refusal_fallbacks() -> None:
    """Opus 5's safety classifiers can decline a clinical topic outright.

    The server-side fallback re-runs a declined request on Anthropic's
    recommended substitute model inside the same call, so a false positive
    doesn't cost the whole run (issue #45). Models without those classifiers
    reject the parameter, so it must only be attached where they fire.
    """
    import inspect
    from articlegen import llm

    kwargs = llm._refusal_fallback_kwargs("claude-opus-5")
    check("opus 5 opts into the server-side fallback", kwargs.get("fallbacks") == "default")
    check("and sends the matching beta header", kwargs.get("betas") == [llm._REFUSAL_FALLBACK_BETA])
    check("fable gets the fallback too", "fallbacks" in llm._refusal_fallback_kwargs("claude-fable-5"))
    check("opus 4.8 does not take the parameter", llm._refusal_fallback_kwargs("claude-opus-4-8") == {})
    check("haiku does not either", llm._refusal_fallback_kwargs("claude-haiku-4-5") == {})

    src = inspect.getsource(llm._anthropic_generate)
    check("anthropic calls go through the beta endpoint",
          "client.beta.messages" in src and "client.messages." not in src)
    check("both call paths attach the fallback kwargs", "_refusal_fallback_kwargs(" in src)


def test_pipeline_is_shared() -> None:
    """Both entry points must run the same pipeline.

    The web handler used to have its own copy that skipped the prose-style gate
    and never built provenance, so web-generated articles came out without the
    enforced hedging and with an incomplete Methods section.
    """
    import inspect
    from articlegen import cli, pipeline, web

    cmd_draft_src = inspect.getsource(cli.cmd_draft)
    handler_src = inspect.getsource(web.ArticleGenHandler._handle_draft)

    for name, src in (("cli.cmd_draft", cmd_draft_src), ("web._handle_draft", handler_src)):
        check(f"{name} calls generate_draft", "generate_draft(" in src)
        for stage in ("plan_queries(", "curate_sources(", "write_article("):
            check(f"{name} does not re-run {stage[:-1]}", stage not in src)

    check("pipeline enforces style", "enforce_style(" in inspect.getsource(pipeline.generate_draft))
    check("pipeline builds provenance", '"queries": queries' in inspect.getsource(pipeline.generate_draft))


def test_draft_summary() -> None:
    from articlegen.pipeline import Draft
    from articlegen.sources import Paper

    papers = [Paper(title=f"P{i}", abstract="a", year=2020) for i in range(1, 6)]
    clean = Draft(
        topic="t",
        article={"references": [1, 2, 3]},
        papers=papers,
        curation={"relevance": {1: "direct", 2: "direct", 3: "related"}},
        verification={"unverified": []},
        style_report={"issues": [], "stats": {}},
    )
    check("counts cited sources", clean.summary().startswith("3 sources cited"))
    check("counts direct sources", "2 directly on-topic" in clean.summary())
    check("clean prose reported", "prose style clean" in clean.summary())

    messy = Draft(
        topic="t",
        article={"references": [1, 2]},
        papers=papers,
        curation={"relevance": {1: "related", 2: "tangential"}},
        verification={"unverified": ["42%"]},
        style_report={
            "issues": [{"severity": "error", "rule": "boosters", "detail": "clearly"}],
            "stats": {},
        },
    )
    summary = messy.summary()
    check("unverified figures flagged", "1 figure(s) not found" in summary)
    check("no direct source flagged", "no directly on-topic source found" in summary)
    check("style issues flagged", "prose-style issue(s)" in summary)

    out_of_range = Draft(topic="t", article={"references": [1, 99, "x"]}, papers=papers)
    check("ignores out-of-range references", out_of_range.summary().startswith("1 sources cited"))


def test_rate_limit() -> None:
    from articlegen import web

    original_max = web.RATE_LIMIT_MAX
    web.RATE_LIMIT_MAX = 3
    web._rate_hits.clear()
    try:
        allowed = [not web._rate_limited("10.0.0.1") for _ in range(4)]
        check("first N requests allowed", allowed[:3] == [True, True, True])
        check("request over the limit is blocked", allowed[3] is False)
        check("a different address is unaffected", not web._rate_limited("10.0.0.2"))
    finally:
        web.RATE_LIMIT_MAX = original_max
        web._rate_hits.clear()

    # /api/diag deliberately bypasses the search cache so it reports what the
    # sources are doing right now, which makes every call spend real quota. It
    # therefore has to be metered like drafting is: unmetered, it was a way for
    # anyone with the URL to exhaust the quota the limiter exists to protect.
    import inspect

    source = inspect.getsource(web.ArticleGenHandler._handle_diag)
    check("/api/diag is charged against the rate limit",
          "_over_rate_limit" in source)
    check("/api/diag probes live rather than serving a cached answer",
          "use_cache=False" in source)


def test_keepalive_connection_reuse() -> None:
    """Several requests must survive on ONE connection.

    The server ran on http.server's default HTTP/1.0 for a while, which closes
    the connection after every response. Browsers and reverse proxies pool
    connections, so they kept reusing sockets the server had already hung up on
    and roughly every other request to the deployed backend failed in ~140ms.
    curl never caught it — each invocation opens a fresh connection, so only a
    pooling client reproduces it.
    """
    import http.client
    import threading
    from http.server import ThreadingHTTPServer
    from articlegen.web import ArticleGenHandler

    check("handler speaks HTTP/1.1", ArticleGenHandler.protocol_version == "HTTP/1.1")

    server = ThreadingHTTPServer(("127.0.0.1", 0), ArticleGenHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        statuses, closes = [], []
        for _ in range(3):
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            resp.read()
            statuses.append(resp.status)
            # will_close is the assertion that matters. Python's http.client
            # transparently reconnects when the server hangs up, so simply
            # issuing three requests passes under HTTP/1.0 too and proves
            # nothing — a browser's connection pool is what breaks. This asks
            # the server directly whether it intends to keep the socket open.
            closes.append(resp.will_close)
        conn.close()
        check("three requests succeed", statuses == [200, 200, 200])
        check("server keeps the connection open", closes == [False, False, False])

        # OPTIONS must not strand a pooling client waiting for a body.
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("OPTIONS", "/api/draft")
        resp = conn.getresponse()
        resp.read()
        opt_status, opt_len = resp.status, resp.getheader("Content-Length")
        conn.request("GET", "/api/health")
        follow = conn.getresponse()
        follow.read()
        check("OPTIONS returns 204", opt_status == 204)
        check("OPTIONS declares Content-Length: 0", opt_len == "0")
        check("connection still usable after OPTIONS", follow.status == 200)
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_substance_checks() -> None:
    """Thin, repetitive prose must fail even when the register is perfect.

    Every other rule in style.py is a prohibition. A model optimising only
    against prohibitions writes vague hedged filler, because asserting nothing
    breaks no rule — a real draft passed clean at 803 words with one number in
    it, hedging at 0.69/sentence (three times the floor) using four stock
    phrases. These rules fail a draft for saying too little.
    """
    from articlegen.style import check_style, errors, revision_brief, SUBSTANCE_RULES

    def rules(article):
        return {i["rule"] for i in errors(check_style(article))}

    filler = (
        "The evidence suggests that these effects may be significant, although the "
        "magnitude may vary. It appears that the risk may be higher among some workers. "
        "The evidence suggests that these strategies may be effective in some settings. "
        "It appears that this approach may be beneficial, although the evidence may be limited. "
    )
    thin = {"sections": [{"heading": h, "paragraphs": [filler * 2]}
                         for h in ("Introduction", "Effects", "Conclusions")]}
    found = rules(thin)
    check("too-few-sections flagged", "too-few-sections" in found)
    check("hedge-monotony flagged", "hedge-monotony" in found)
    check("under-length is only a warning, not an error", "under-length" not in found)

    # Verbatim recycling across sections, which the register rules never noticed.
    # Padded past MIN_SENTENCES_FOR_VARIETY, below which repetition counts are noise.
    line = ("a range of strategies can be used to mitigate these effects including "
            "sleep hygiene education and flexible scheduling for affected staff")
    padding = " ".join(f"Investigators in cohort {i} recorded a distinct outcome." for i in range(8))
    recycled = {"sections": [
        {"heading": "Introduction", "paragraphs": [line + ". " + padding]},
        {"heading": "Conclusions", "paragraphs": [line + ". A different closing thought here."]},
    ]}
    check("recycled-phrasing flagged", "recycled-phrasing" in rules(recycled))

    # A varied, specific draft must stay clean. Written out rather than looped:
    # a loop produces near-identical sections, which these rules rightly reject.
    good = {"sections": [
        {"heading": "Introduction", "paragraphs": [
            "Rotating rosters are the dominant scheduling pattern in acute hospital "
            "nursing, and their health consequences have been studied for three "
            "decades. Whether any intervention reliably offsets those consequences "
            "remains unresolved."]},
        {"heading": "Mechanisms", "paragraphs": [
            "Circadian misalignment is the account most often advanced, resting "
            "largely on preclinical work in which light exposure was manipulated "
            "directly. Human evidence for the pathway is indirect."]},
        {"heading": "Interventions", "paragraphs": [
            "A 12-week randomised trial reported a 62% reduction in insomnia "
            "symptoms among rotating-shift nurses. A later cohort study of "
            "fixed-night staff did not reproduce that finding, and investigators "
            "attributed the discrepancy to how rapidly each roster rotated."]},
        {"heading": "Populations", "paragraphs": [
            "Across three cohorts the direction of effect held, though its "
            "magnitude differed considerably and the confidence intervals were "
            "wide. No controlled study has enrolled workers over 55."]},
        {"heading": "Conclusions", "paragraphs": [
            "Roster design plausibly matters more than any individual sleep "
            "intervention, but no trial has compared the two directly. An "
            "adequately powered comparison would settle most of what is uncertain."]},
    ]}
    check("a specific, varied draft passes", not (rules(good) & SUBSTANCE_RULES))

    # The abstract, key points and Introduction written as one paragraph three
    # times. Paraphrased too loosely for the 8-word recycled-phrasing rule, which
    # is exactly how a real shipped draft slipped through: its Introduction
    # repeated 38% of the abstract's 6-word runs and its key points 24%.
    abstract = (
        "Night shift work has been linked to adverse health outcomes, including "
        "metabolic, immune and cardiovascular impairments. The disruption of "
        "circadian rhythms, particularly in shift workers, has been increasingly "
        "associated with these outcomes. This review explores the impact of "
        "artificial light on the health of night shift workers, with a focus on "
        "the circadian system and its health implications."
    )
    echoed = {
        "abstract": abstract,
        "key_points": [
            "The disruption of circadian rhythms, particularly in shift workers, "
            "has been increasingly associated with these outcomes. [1]",
            "Artificial light has been linked to adverse health outcomes, including "
            "metabolic, immune and cardiovascular impairments. [2]",
        ],
        "sections": [{"heading": "Introduction", "paragraphs": [
            "This review explores the impact of artificial light on the health of "
            "night shift workers, with a focus on the circadian system and its "
            "health implications. The disruption of circadian rhythms, particularly "
            "in shift workers, has been increasingly associated with these outcomes."]}],
    }
    check("echoed-abstract flagged", "echoed-abstract" in rules(echoed))
    check("echoed-abstract is a substance rule", "echoed-abstract" in SUBSTANCE_RULES)

    # Sources cited only ever in a bundle have had nothing said about them.
    bundled = dict(good)
    bundled["sections"] = list(good["sections"])
    bundled["sections"][2] = {"heading": "Interventions", "paragraphs": [
        "Several studies report benefit from roster redesign [1, 2, 3, 4]. The "
        "direction of effect was consistent across them [1, 2, 3, 4]. One review "
        "considered the same question [5]."]}
    check("bundled-citations flagged", "bundled-citations" in rules(bundled))

    solo = dict(bundled)
    solo["sections"] = list(bundled["sections"])
    solo["sections"][2] = {"heading": "Interventions", "paragraphs": [
        "A randomised trial in rotating-shift nurses reported fewer insomnia "
        "symptoms [1]. A fixed-night cohort did not reproduce it [2]. A third "
        "cohort found the effect only in workers under 40 [3]. A pooled analysis "
        "reached no conclusion [4]. Together these suggest roster speed matters "
        "[1, 2, 3, 4]."]}
    check("citing sources individually clears bundled-citations",
          "bundled-citations" not in rules(solo))

    # The curated sample is the calibration reference: these rules must never
    # reject it, or they are measuring the wrong thing.
    from articlegen.demo import SAMPLE_ARTICLE
    check("the curated demo sample still passes",
          not (rules(SAMPLE_ARTICLE) & SUBSTANCE_RULES))

    # The brief must invert when the fix requires adding material, not rewording.
    brief = revision_brief(check_style(thin))
    check("substance brief asks for sources", "SOURCES" in brief)
    check("substance brief does not forbid new numbers",
          "do not introduce new claims or numbers" not in brief)

    # Register faults only — enough sections that no substance rule fires, so
    # this tests which brief is chosen rather than how many sections there are.
    register_only = dict(good)
    register_only["sections"] = list(good["sections"])
    register_only["sections"][0] = {
        "heading": "Introduction",
        "paragraphs": ["You should note that this clearly proves the point!"],
    }
    reg_brief = revision_brief(check_style(register_only))
    check("register-only brief still forbids new numbers",
          "do not introduce new claims or numbers" in reg_brief)


def test_groq_token_budget() -> None:
    """Prompts must fit Groq's free-tier tokens-per-minute limit.

    Groq counts the reserved output against TPM as well as the prompt, so
    reserving 16000 output tokens against a 12000 limit failed every article
    call regardless of prompt size:

        413 ... on tokens per minute (TPM): Limit 12000, Requested 20916
    """
    from articlegen import llm
    from articlegen.writer import _format_sources
    from articlegen.sources import Paper

    check("deep output reservation fits the free tier",
          llm.GROQ_DEEP_OUTPUT < llm.GROQ_FREE_TPM)
    check("standard output reservation fits too", llm.GROQ_OUTPUT < llm.GROQ_FREE_TPM)

    budget = llm.prompt_budget_chars(model=llm.GROQ_DEFAULT_MODEL)
    check("groq gets a finite prompt budget", isinstance(budget, int) and budget > 0)
    check("anthropic is unlimited",
          llm.prompt_budget_chars(model=llm.ANTHROPIC_DEFAULT_MODEL) is None)
    check("reservation plus prompt stays under the limit",
          llm.GROQ_DEEP_OUTPUT + budget / llm.CHARS_PER_TOKEN < llm.GROQ_FREE_TPM)

    # 20 papers with long abstracts — the shape that produced the 413.
    papers = [
        Paper(title=f"Study {i}", abstract="word " * 400, year=2024, venue="Journal")
        for i in range(1, 21)
    ]
    unbounded = _format_sources(papers)
    trimmed = _format_sources(papers, None, budget)
    check("an unbounded prompt really does exceed the budget", len(unbounded) > budget)
    check("the trimmed prompt fits", len(trimmed) <= budget)
    check("trimming keeps every paper rather than dropping them",
          trimmed.count("SOURCE ") == len(papers))

    # Only when shortening every abstract still cannot fit does it drop papers.
    tiny = _format_sources(papers, None, 1500)
    check("a tiny budget still yields something usable", 0 < tiny.count("SOURCE ") < len(papers))
    check("a tiny budget is still respected", len(tiny) <= 1500)

    check("no budget means no trimming", _format_sources(papers, None, None) == unbounded)


def test_source_failures_are_distinguishable() -> None:
    """An API refusing must not be reported as the topic having no literature.

    Every failure used to collapse to an empty list, so a rate-limited API
    produced "no papers found for this topic" — sending the user off to reword
    a query that was fine.
    """
    from articlegen import sources
    from articlegen.pipeline import NoPapersFound

    real = (sources.search_semantic_scholar, sources.search_openalex,
            sources.search_europe_pmc)
    refuse = lambda msg: lambda q, limit=15: (_ for _ in ()).throw(
        sources.SearchFailure(msg))
    try:
        # Every source refuses. The cache is cleared between phases because both
        # use the same query, and a cached refusal would otherwise answer for
        # the source the second phase is trying to prove works.
        sources.clear_search_cache()
        sources.search_semantic_scholar = refuse("HTTP 429 after 3 attempts")
        sources.search_openalex = refuse("HTTP 403")
        sources.search_europe_pmc = refuse("HTTP 503 after 3 attempts")
        outcomes: list[dict] = []
        papers = sources.gather_evidence(["x"], outcomes=outcomes)
        check("no papers when all refuse", papers == [])
        check("every failure recorded", len([o for o in outcomes if o["error"]]) == 3)
        check("the reason is kept", any("429" in o["error"] for o in outcomes))

        # Two sources down, one fine — the run must survive.
        sources.clear_search_cache()
        sources.search_openalex = lambda q, limit=15: [
            sources.Paper(title=f"P{i}", abstract="a") for i in range(3)]
        outcomes = []
        papers = sources.gather_evidence(["x"], outcomes=outcomes)
        check("one working source is enough", len(papers) == 3)
        check("the failed sources are still recorded",
              any(o["error"] for o in outcomes) and any(not o["error"] for o in outcomes))
    finally:
        sources.clear_search_cache()
        (sources.search_semantic_scholar, sources.search_openalex,
         sources.search_europe_pmc) = real

    check("NoPapersFound carries the distinction",
          NoPapersFound("x", sources_failed=True).sources_failed is True)
    check("and defaults to a topic problem", NoPapersFound("x").sources_failed is False)


def test_front_end_models_match_the_allowlist() -> None:
    """Every model the Settings dropdown offers must be one the server accepts.

    The model ids live in two places — `llm.py` and the PROVIDERS map in
    index.html — and nothing links them. `web._requested_model` silently drops a
    name that isn't on the allowlist, so a stale front end doesn't error: it just
    quietly stops honouring the provider the user picked. This catches the drift
    instead of leaving it to be noticed in a bill.
    """
    import re

    from articlegen.web import ALLOWED_MODELS

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
        page = f.read()

    offered = re.findall(r"^\s*model: '([^']+)'", page, re.MULTILINE)
    check("the front end offers a model at all", len(offered) >= 2)
    for model in offered:
        check(f"index.html offers {model}, which the server accepts",
              model in ALLOWED_MODELS)


def test_search_cache() -> None:
    """A repeated query must not cost a second call against the shared quota.

    The scholarly APIs meter against this server's IP and refuse constantly, so
    the same topic searched twice in a day is far likelier to fail the second
    time than to return anything new. Caching is what makes a demo repeatable.
    """
    from articlegen import sources

    real = (sources.search_semantic_scholar, sources.search_openalex,
            sources.search_europe_pmc)
    calls = {"n": 0, "fail": 0}
    try:
        sources.clear_search_cache()

        def counting(q, limit=15):
            calls["n"] += 1
            return [sources.Paper(title=f"{q}-paper", abstract="a", year=2024)]

        def failing(q, limit=15):
            calls["fail"] += 1
            raise sources.SearchFailure("HTTP 429 after 3 attempts")

        sources.search_semantic_scholar = counting
        sources.search_openalex = failing
        sources.search_europe_pmc = failing

        first: list[dict] = []
        got_first = sources.gather_evidence(["topic a"], outcomes=first)
        second: list[dict] = []
        got_second = sources.gather_evidence(["topic a"], outcomes=second)

        check("the same query is fetched once, not twice", calls["n"] == 1)
        check("the cached run returns the same papers", got_first == got_second)
        check("the first run is not marked cached",
              all(not o["cached"] for o in first))
        check("the second run is served from cache",
              all(o["cached"] for o in second))

        # A refusal is cached too, so a rate-limited source is not re-attempted
        # by every request that arrives while the limit is still in force.
        check("a refusal is cached, not retried", calls["fail"] == 2)
        check("and is still reported as a failure",
              sum(1 for o in second if o["error"]) == 2)

        # A different query is a different key — the cache must not answer for
        # a topic nobody searched.
        sources.gather_evidence(["topic b"], outcomes=[])
        check("a new query still fetches", calls["n"] == 2)

        sources.clear_search_cache()
        sources.gather_evidence(["topic a"], outcomes=[])
        check("clearing the cache forces a fresh fetch", calls["n"] == 3)
    finally:
        sources.clear_search_cache()
        (sources.search_semantic_scholar, sources.search_openalex,
         sources.search_europe_pmc) = real


def test_polite_pool_identification() -> None:
    """We must identify ourselves, and respect a cool-off the server asks for.

    Requests' default "python-requests/x.y" arriving from a cloud provider's
    shared egress IP is the profile CDNs throttle first, and a fixed 2s/4s
    backoff ignores a server that just told us exactly when to come back.
    """
    from articlegen import sources

    real = os.environ.get("OPENALEX_MAILTO")
    try:
        os.environ.pop("OPENALEX_MAILTO", None)
        ua = sources._user_agent()
        check("user-agent names the project", "articlegen/" in ua)
        check("and is not the requests default", "python-requests" not in ua)
        check("no mailto when unconfigured", "mailto:" not in ua)

        os.environ["OPENALEX_MAILTO"] = "you@example.com"
        check("mailto rides in the header when set",
              "mailto:you@example.com" in sources._user_agent())
    finally:
        os.environ.pop("OPENALEX_MAILTO", None)
        if real is not None:
            os.environ["OPENALEX_MAILTO"] = real

    class FakeResp:
        def __init__(self, retry_after=None):
            self.headers = {} if retry_after is None else {"Retry-After": retry_after}

    check("a short Retry-After wins over the backoff",
          sources._retry_delay(FakeResp("10"), 2.0) == 10.0)
    check("but never shortens it",
          sources._retry_delay(FakeResp("1"), 4.0) == 4.0)
    check("no header falls back to the backoff",
          sources._retry_delay(FakeResp(), 2.0) == 2.0)
    check("an HTTP-date form falls back too",
          sources._retry_delay(FakeResp("Wed, 21 Oct 2026 07:28:00 GMT"), 2.0) == 2.0)
    check("a cool-off past the cap gives up instead of waiting",
          sources._retry_delay(FakeResp("600"), 2.0) is None)
    check("a connection error has no response to read",
          sources._retry_delay(None, 2.0) == 2.0)


def test_europe_pmc_parsing() -> None:
    """Europe PMC records parse into Papers without trusting any field.

    Real records have string years, absent DOIs/journals, and HTML inside the
    abstract. The markup matters beyond cosmetics: verify.py checks statistics
    by substring presence in the abstract, so a figure adjacent to a tag would
    be reported unverifiable if tags were left in.
    """
    from articlegen import render, sources

    payload = {"resultList": {"result": [
        {   # the full-featured record
            "id": "38000001", "source": "MED",
            "title": "A <i>trial</i> of something",
            "abstractText": "<h4>Background</h4>Depression affects 20% of adults.<h4>Results</h4>Improved.",
            "pubYear": "2026", "citedByCount": 7, "doi": "10.1000/xyz",
            "authorString": "Kim SH, Jang G",
            # The real shape: Europe PMC gives surname and initials separately,
            # and `fullName` surname-first — the opposite of OpenAlex.
            "authorList": {"author": [
                {"fullName": "Kim SH", "lastName": "Kim", "initials": "SH", "firstName": "Su Hyun"},
                {"fullName": "Jang G", "lastName": "Jang", "initials": "G", "firstName": "Geunsoo"},
            ]},
            "journalInfo": {"journal": {"title": "J Affect Disord"}},
        },
        {   # sparse: book chapter — no journal, no doi, bad year
            "id": "PPR000002", "source": "PPR",
            "title": "Sparse record",
            "abstractText": "An abstract.",
            "pubYear": "n.d.",
        },
        {   # no abstract despite the filter — must be dropped, like the others do
            "id": "38000003", "source": "MED",
            "title": "No abstract", "pubYear": "2025",
        },
    ]}}

    class FakeResp:
        def json(self):
            return payload

    real = sources._get_with_retry
    try:
        sources._get_with_retry = lambda url, params, headers: FakeResp()
        papers = sources.search_europe_pmc("depression", limit=3)
    finally:
        sources._get_with_retry = real

    check("abstract-less record dropped", len(papers) == 2)
    full, sparse = papers
    check("markup stripped from the abstract", "<h4>" not in full.abstract)
    check("statistics survive stripping adjacent tags",
          "Depression affects 20% of adults." in full.abstract)
    check("markup stripped from the title", full.title == "A trial of something")
    check("string year becomes int", full.year == 2026)
    # Europe PMC names arrive surname-first; the renderer takes the last token as
    # the surname, so they are normalised to given-name-first at parse time.
    # Passing `fullName` through printed "SH, K." for "Kim SH" in every reference.
    check("authors are normalised to given-name-first", full.authors == ["S H Kim", "G Jang"])
    check("and render as a correct reference line",
          render._reference_authors(full) == "Kim, S. H. & Jang, G.")
    check("and as a correct short form", render._short_author(full) == "Kim & Jang")
    check("a consortium author survives without a surname",
          sources._europe_pmc_author({"collectiveName": "GBD 2019 Collaborators"})
          == "GBD 2019 Collaborators")
    check("a record with only fullName still yields a name",
          sources._europe_pmc_author({"fullName": "Lee K"}) == "Lee K")
    check("dotted initials are split too",
          sources._europe_pmc_author({"lastName": "Kim", "initials": "S.H."}) == "S H Kim")
    check("firstName is used when initials are absent",
          sources._europe_pmc_author({"lastName": "Kim", "firstName": "Su Hyun"}) == "Su Hyun Kim")
    check("journal title found", full.venue == "J Affect Disord")
    check("europepmc url built from source+id", full.url.endswith("/MED/38000001"))
    check("unparseable year becomes None", sparse.year is None)
    check("missing doi/journal tolerated", sparse.doi == "" and sparse.venue == "")
    check("source is named in DATABASE_NAMES", "europe_pmc" in sources.DATABASE_NAMES)

    import inspect
    check("gather_evidence queries europe_pmc",
          '"europe_pmc"' in inspect.getsource(sources.gather_evidence))


def test_methods_names_only_sources_that_answered() -> None:
    """The Methods section must not claim a database that returned nothing.

    `_DATABASES` was a hardcoded constant, so every article stated that both
    Semantic Scholar and OpenAlex had been searched — including while one of
    them was 429ing every call. That made the claim false in every article the
    pipeline produced, in the one section that exists to state what was actually
    done. It survived the first fix as a fallback for drafts whose provenance
    carried no `databases`, which reintroduced exactly the same false claim on
    that path, so there is now no fallback at all: an unrecorded search says so.
    """
    from articlegen import sources
    from articlegen.render import render_article, render_markdown
    from articlegen.sources import DATABASE_NAMES, Paper

    papers = [Paper(title="P", abstract="a", year=2024, source="OpenAlex")]
    article = {
        "title": "T", "abstract": "A" * 200, "keywords": [], "evidence_note": "",
        "featured_study": {"source_index": 1, "why": "w", "method": "m", "results": "r"},
        "sections": [{"heading": "Introduction", "paragraphs": ["Prose [1]."]},
                     {"heading": "Conclusions", "paragraphs": ["More [1]."]}],
        "key_points": [], "glossary": [], "references": [1],
    }

    only_openalex = render_article(article, papers, "t", None, {},
                                   {"databases": ["OpenAlex"], "queries": ["q"]})
    check("names the source that answered", "OpenAlex" in only_openalex)
    check("does not name the silent source", "Semantic Scholar" not in only_openalex)

    # Three databases must read "A, B and C", not "A and B and C" — the join
    # was only ever exercised with two until Europe PMC was added.
    from articlegen.render import _join_list
    check("one name joins to itself", _join_list(["A"]) == "A")
    check("two names join with 'and'", _join_list(["A", "B"]) == "A and B")
    check("three names join as a list", _join_list(["A", "B", "C"]) == "A, B and C")

    three = render_article(article, papers, "t", None, {},
                           {"databases": ["A", "B", "C"], "queries": ["q"]})
    check("Methods lists three databases grammatically",
          "from A, B and C" in three and "A and B and C" not in three)

    both = render_article(article, papers, "t", None, {},
                          {"databases": list(DATABASE_NAMES.values()), "queries": ["q"]})
    check("names both when both answered",
          "OpenAlex" in both and "Semantic Scholar" in both)

    # Drafts written before provenance carried `databases` must still render —
    # and must name no database at all rather than guessing at a plausible pair.
    legacy = render_article(article, papers, "t", None, {}, {"queries": ["q"]})
    check("legacy drafts without `databases` still render", "Candidate records" in legacy)
    check("an unrecorded search names no database",
          "OpenAlex" not in legacy and "Semantic Scholar" not in legacy
          and "Europe PMC" not in legacy)
    check("and says so instead of guessing",
          "databases searched were not recorded" in legacy)

    legacy_md = render_markdown(article, papers, "t", None, {}, {"queries": ["q"]})
    check("markdown makes the same admission",
          "databases searched were not recorded" in legacy_md
          and "OpenAlex" not in legacy_md)

    # A source that refuses once is not retried for the remaining queries:
    # three tries with backoff is ~10s, and the limits are per-minute.
    real = (sources.search_semantic_scholar, sources.search_openalex,
            sources.search_europe_pmc)
    calls = {"ss": 0, "oa": 0, "ep": 0}
    try:
        sources.clear_search_cache()

        def failing_ss(q, limit=15):
            calls["ss"] += 1
            raise sources.SearchFailure("HTTP 429 after 3 attempts")

        def working_oa(q, limit=15):
            calls["oa"] += 1
            return [Paper(title=f"{q}-{calls['oa']}", abstract="a", year=2024)]

        def failing_ep(q, limit=15):
            calls["ep"] += 1
            raise sources.SearchFailure("HTTP 503 after 3 attempts")

        sources.search_semantic_scholar = failing_ss
        sources.search_openalex = working_oa
        sources.search_europe_pmc = failing_ep
        outcomes: list[dict] = []
        got = sources.gather_evidence(["q1", "q2", "q3"], outcomes=outcomes)

        check("each failing source is tried once, not per query",
              calls["ss"] == 1 and calls["ep"] == 1)
        check("the working source is still tried every query", calls["oa"] == 3)
        check("the run still succeeds on one source", len(got) == 3)
        check("skips are recorded, not silent",
              sum(1 for o in outcomes if "skipped" in o["error"]) == 4)
        answered = {o["source"] for o in outcomes if o["count"]}
        check("only the answering source counts as answered", answered == {"openalex"})
    finally:
        sources.clear_search_cache()
        (sources.search_semantic_scholar, sources.search_openalex,
         sources.search_europe_pmc) = real


def test_groq_json_cleaning() -> None:
    from articlegen.llm import _clean_json_text
    check("clean simple fence", _clean_json_text("```json\n{\"a\": 1}\n```") == '{"a": 1}')
    check("clean raw json", _clean_json_text('{"b": 2}') == '{"b": 2}')


def test_citation_renumbering() -> None:
    from articlegen.render import _citation_map, _remap_citations
    from articlegen.sources import Paper

    papers = [Paper(title=f"P{i}", abstract="a", year=2000 + i) for i in range(1, 21)]
    article = {"references": [6, 7, 18, 8, 15]}
    cited, m = _citation_map(article, papers)
    check("cited papers in references order", [p.title for p in cited] == ["P6", "P7", "P18", "P8", "P15"])
    check("map renumbers source indices", m == {6: 1, 7: 2, 18: 3, 8: 4, 15: 5})
    check("remap single marker", _remap_citations("x [18] y", m) == "x [3] y")
    check("remap combined marker", _remap_citations("a [7, 8] b", m) == "a [2, 4] b")
    # The dropped marker takes its leading space with it — leaving it produced
    # "z  w" here and a stranded full stop ("…the market .") in a real article.
    check("remap drops unknown marker without leaving a gap",
          _remap_citations("z [99] w", m) == "z w")


def test_journal_citation_style() -> None:
    """Superscript markers after the punctuation, runs of 3+ collapsed to a range."""
    from articlegen.render import (
        _link_citations, _plain_citations, _shift_markers_after_punctuation,
    )

    check("marker moves after the full stop",
          _shift_markers_after_punctuation("a claim [1].") == "a claim.[1]")
    check("marker moves after a semicolon",
          _shift_markers_after_punctuation("first [2]; second") == "first;[2] second")
    check("marker hugs the preceding word",
          _shift_markers_after_punctuation("evidence [3] is thin") == "evidence[3] is thin")

    valid = set(range(1, 8))
    single = _link_citations("x.[3]", valid)
    check("single marker becomes a superscript link",
          '<sup class="cite">' in single and 'href="#ref-3"' in single)
    pair = _link_citations("x.[1, 3]", valid)
    check("pair is comma-joined, not ranged", ">1</a>,<a" in pair)
    run = _link_citations("x.[2, 3, 4]", valid)
    check("run of three collapses to a range", ">2</a>–<a" in run and ">4</a>" in run)
    check("unsorted markers are ordered", _link_citations("x.[5, 2]", valid).index(">2<")
          < _link_citations("x.[5, 2]", valid).index(">5<"))
    check("marker with no matching source is left alone",
          _link_citations("x.[99]", valid) == "x.[99]")
    check("markdown collapses runs too", _plain_citations("x.[2, 3, 4]") == "x.[2–4]")


def test_reference_formatting() -> None:
    from articlegen.render import _format_author, _reference_authors, _short_author
    from articlegen.sources import Paper

    check("author -> surname, initial", _format_author("Susanne Diekelmann") == "Diekelmann, S.")
    check("particle stays with the surname", _format_author("Hans Van Dongen") == "Van Dongen, H.")
    check("middle name becomes a second initial",
          _format_author("Hans P Van Dongen") == "Van Dongen, H. P.")
    check("mononym survives", _format_author("Aristotle") == "Aristotle")

    two = Paper(title="T", abstract="a", authors=["Susanne Diekelmann", "Jan Born"])
    many = Paper(title="T", abstract="a", authors=["Lulu Xie", "Hongyi Kang", "Qiwu Xu", "et al."])
    four = Paper(title="T", abstract="a", authors=["A One", "B Two", "C Three", "D Four"])
    check("two authors joined with an ampersand",
          _reference_authors(two) == "Diekelmann, S. & Born, J.")
    check("trailing 'et al.' collapses the list", _reference_authors(many) == "Xie, L. et al.")
    check("author line always closes with a stop",
          _reference_authors(Paper(title="T", abstract="a", authors=["Borelli"])) == "Borelli."
          and _reference_authors(Paper(title="T", abstract="a", authors=[])) == "Unknown authors.")
    check("more than three authors collapses too", _reference_authors(four) == "One, A. et al.")
    check("short form for tables", _short_author(two) == "Diekelmann & Born")
    check("short form collapses many", _short_author(many) == "Xie et al.")

    # Corporate/consortium authors pass through whole (issue #62): a digit or an
    # organisational word marks a name no initials should be invented from.
    check("consortium with a digit is not split",
          _format_author("GBD 2019 Collaborators") == "GBD 2019 Collaborators")
    check("organisational word is not split",
          _format_author("WHO Expert Committee") == "WHO Expert Committee")
    check("a person named after none of the org words still splits",
          _format_author("Sofia Network") == "Sofia Network"
          and _format_author("Sofia Networks") == "Networks, S.")
    corporate = Paper(title="T", abstract="a", authors=["GBD 2019 Collaborators"])
    check("corporate reference line survives intact",
          _reference_authors(corporate) == "GBD 2019 Collaborators.")
    check("corporate short form survives intact",
          _short_author(corporate) == "GBD 2019 Collaborators")


def test_prose_style_check() -> None:
    """The style gate must catch magazine register and pass real journal prose."""
    from articlegen.style import check_style, errors, revision_brief

    magazine = {
        "abstract": "Ever wondered what your brain does at night? It's incredible.",
        "sections": [{"heading": "The night shift", "paragraphs": [
            "The last two decades have dramatically inverted that picture.",
            "Scientists have definitively proven that sleep matters, and in order to "
            "understand why, we ran through the literature ourselves.",
        ]}],
        "key_points": ["Sleep clearly matters!"],
    }
    found = {i["rule"] for i in check_style(magazine)["issues"]}
    for rule in ("rhetorical-question", "second-person", "contraction", "booster",
                 "overclaim", "first-person", "exclamation", "wordiness"):
        check(f"style catches {rule}", rule in found)

    brief = revision_brief(check_style(magazine))
    check("revision brief locates and quotes each offence",
          "[abstract]" in brief and "Offending text:" in brief
          and "Addresses the reader directly" in brief)

    from articlegen import demo
    demo_report = check_style(demo.SAMPLE_ARTICLE)
    check("demo prose passes the style gate", not errors(demo_report))
    check("style stats are reported",
          demo_report["stats"]["sentences"] > 20
          and demo_report["stats"]["hedges_per_sentence"] > 0)

    # The reviewing frame journals themselves use is allowed; other first person is not.
    allowed = {"sections": [{"heading": "H", "paragraphs": [
        "Here we review the evidence for clearance during sleep."]}]}
    denied = {"sections": [{"heading": "H", "paragraphs": [
        "Our results show that clearance increases during sleep."]}]}
    check("'here we review' is permitted",
          not any(i["rule"] == "first-person" for i in check_style(allowed)["issues"]))
    check("'our results' is not",
          any(i["rule"] == "first-person" for i in check_style(denied)["issues"]))

    long_sentence = {"sections": [{"heading": "H", "paragraphs": [
        "This sentence " + "goes on and on " * 15 + "without stopping."]}]}
    check("long sentences are flagged",
          any(i["rule"] == "long-sentence" for i in check_style(long_sentence)["issues"]))

    # Density rules need enough prose to mean anything.
    thin = {"sections": [{"heading": "H", "paragraphs": ["A flat claim about a thing."]}]}
    check("density rules stay quiet on short drafts",
          not any(i["rule"] == "under-hedged" for i in check_style(thin)["issues"]))
    # Flat, unhedged assertion at the length where density figures start to mean
    # something (the gate needs both a sentence count and a word count).
    flat = (
        "The compound binds the receptor and increases the rate of clearance in "
        "every model tested. The effect is dose dependent across the full range "
        "studied. Uptake rises with temperature in each preparation examined. "
        "The pathway drives waste removal from the interstitial space. Levels of "
        "the metabolite fall after a single treatment. The response is linear "
        "throughout the measured interval. Binding saturates at the highest dose "
        "administered. Efflux doubles overnight in every animal studied. The "
        "volume of the interstitial space expands during rest. Transport slows "
        "with age in all cohorts examined. Flow returns to baseline by morning "
        "in each experiment. The mechanism accounts for the whole of the observed "
        "difference between the groups."
    )
    unhedged = {"sections": [{"heading": "H", "paragraphs": [flat] * 3}]}
    report = check_style(unhedged)
    check("under-hedged prose is flagged",
          any(i["rule"] == "under-hedged" for i in report["issues"]))


def test_rules_do_not_reject_real_journal_prose() -> None:
    """The register rules must not fire on genuinely published writing.

    Every rule here is a guess about what journal prose looks like, and the guesses
    have been wrong in ways no synthetic fixture could reveal. Checked against real
    abstracts, an earlier version of the first-person rule flagged five of eight,
    because its allowlist required "we" immediately followed by an approved verb —
    so "we also review", "we searched", "we aimed to" all read as a human author
    intruding. Three more false positives were pure clinical notation: "Axis I",
    "I2 = 70.6%" (the meta-analysis heterogeneity statistic) and "US $16.3 million"
    all matched a first-person pronoun.

    `tests/real_abstracts.json` is a frozen corpus of real abstracts, stored rather
    than fetched so the suite stays offline and deterministic. Two entries carry a
    documented `expect_register_errors` — one rhetorical "we", and one genuine
    author-voice "we hope" that the house style bans on purpose, which doubles as a
    positive control that the rule still bites.
    """
    import json

    from articlegen.style import check_style, errors

    register = {"first-person", "second-person", "contraction", "booster",
                "overclaim", "rhetorical-question", "exclamation"}
    path = os.path.join(os.path.dirname(__file__), "real_abstracts.json")
    corpus = json.load(open(path, encoding="utf-8"))
    check("corpus is a usable size", len(corpus) >= 12)

    unexpected = []
    for entry in corpus:
        article = {"sections": [{"heading": "Introduction",
                                 "paragraphs": [entry["abstract"]]}]}
        fired = sorted({i["rule"] for i in errors(check_style(article))} & register)
        if fired != entry["expect_register_errors"]:
            unexpected.append((entry["title"][:50], fired, entry["expect_register_errors"]))
    if unexpected:
        for title, fired, expected in unexpected:
            print(f"      {title}: fired {fired}, expected {expected}")
    check(f"register rules match expectations on {len(corpus)} real abstracts",
          not unexpected)

    check("every documented exception carries a reason",
          all(e.get("note") for e in corpus if e["expect_register_errors"]))

    # The corpus must not be so permissive that the rules stop working. These are
    # the things the house style genuinely bans.
    for text, expected in [
        ("We believe this is the most important question.", "first-person"),
        ("Our findings show a clear benefit.", "first-person"),
        ("You should note the risk before prescribing.", "second-person"),
        ("This clearly proves the point.", "booster"),
        ("It doesn't replicate.", "contraction"),
    ]:
        fired = {i["rule"] for i in errors(check_style(
            {"sections": [{"heading": "Introduction", "paragraphs": [text]}]}))}
        check(f"still catches {expected}: {text[:34]!r}", expected in fired)

    # Clinical notation that must never read as a first-person pronoun.
    for text in ("Axis I comorbidity was recorded in most participants.",
                 "Heterogeneity was substantial (I2 = 70.6%).",
                 "Costs reached US $16.3 million by 2030.",
                 "A Phase I trial enrolled 40 participants."):
        fired = {i["rule"] for i in errors(check_style(
            {"sections": [{"heading": "Introduction", "paragraphs": [text]}]}))}
        check(f"not first person: {text[:38]!r}", "first-person" not in fired)


def test_health_reports_which_build_is_running() -> None:
    """The deployment must be able to say what it is running, and from where.

    `/api/diag` exists because a deployment's behaviour is undiagnosable from
    outside; the same was true of its *identity*. "Is the running backend the
    code I merged?" and "which branch does this host deploy from?" both needed a
    dashboard login, which is what made renaming the default branch risky — the
    deploy could stop silently and nothing observable would say so (#47).
    """
    from articlegen import web

    for var in ("RENDER_GIT_COMMIT", "RENDER_GIT_BRANCH"):
        os.environ.pop(var, None)
    check("no build keys off Render", web._build_info() == {})

    os.environ["RENDER_GIT_COMMIT"] = "0123456789abcdef0123456789abcdef01234567"
    os.environ["RENDER_GIT_BRANCH"] = "main"
    info = web._build_info()
    check("the commit is reported short", info.get("commit") == "0123456")
    check("the deploying branch is reported", info.get("branch") == "main")

    os.environ["RENDER_GIT_BRANCH"] = ""
    check("an empty value is omitted, not reported blank",
          "branch" not in web._build_info())
    for var in ("RENDER_GIT_COMMIT", "RENDER_GIT_BRANCH"):
        os.environ.pop(var, None)

    import inspect
    src = inspect.getsource(web.ArticleGenHandler.do_GET)
    check("health carries it", "_build_info()" in src)


def test_openalex_reaches_for_recent_work_as_well() -> None:
    """The evidence pool skewed old, and ranking alone could not fix it.

    OpenAlex's relevance ordering returns old, heavily-cited work: measured over
    three topics the median year of a 20-paper page was 2006-2016, with 13-18 of
    20 published before 2015 (issue #38). Ranking only reorders what it is given,
    and a bigger page makes it worse — one page of 50 returned *more* pre-2015
    work, because it goes deeper into the same ordering.

    So the source now issues a second, date-filtered query over the same terms
    and merges. Live, that moved the median to 2018-2020 and tripled the count of
    2020-or-later papers while leaving the pre-2015 count untouched — recent work
    reaches the pool without a cutoff excluding foundational work.
    """
    from articlegen import sources
    from articlegen.sources import Paper

    calls = []

    def fake_page(query, limit, from_year=None):
        calls.append({"query": query, "limit": limit, "from_year": from_year})
        if from_year:
            return [Paper(title="Recent study", abstract="a", year=from_year + 3,
                          doi="10.1/recent"),
                    Paper(title="Shared study", abstract="a", year=from_year + 1,
                          doi="10.1/shared")]
        return [Paper(title="Old classic", abstract="a", year=1998, doi="10.1/old"),
                Paper(title="Shared study", abstract="a", year=from_year or 2020,
                      doi="10.1/shared")]

    real = sources._openalex_page
    try:
        sources._openalex_page = fake_page
        papers = sources.search_openalex("sleep", limit=10)
    finally:
        sources._openalex_page = real

    check("both a plain and a dated query are issued", len(calls) == 2)
    check("the plain query carries no date filter", calls[0]["from_year"] is None)
    check("the companion query does", isinstance(calls[1]["from_year"], int))
    import datetime as _dt
    check("and reaches back a sensible window",
          0 < _dt.date.today().year - calls[1]["from_year"] <= 15)
    check("both use the same search terms", calls[0]["query"] == calls[1]["query"])

    titles = [p.title for p in papers]
    check("the old classic is kept", "Old classic" in titles)
    check("recent work is added", "Recent study" in titles)
    check("the overlap is deduplicated", titles.count("Shared study") == 1)

    # If the companion query refuses, the relevance results must still stand.
    def half_failing(query, limit, from_year=None):
        if from_year:
            raise sources.SearchFailure("HTTP 429")
        return [Paper(title="Only result", abstract="a", year=2001)]

    attempts = []

    def half_failing_counted(query, limit, from_year=None):
        attempts.append(from_year)
        if from_year:
            raise sources.SearchFailure("HTTP 429")
        return [Paper(title="Only result", abstract="a", year=2001)]

    try:
        sources._recency_query_refused = False
        sources._openalex_page = half_failing_counted
        survived = sources.search_openalex("sleep", limit=10)
        # A second query in the same run must not re-attempt the dead one: the
        # limits are per-minute, so retrying costs three tries and ~10s each.
        sources.search_openalex("sleep again", limit=10)
    finally:
        sources._openalex_page = real
        sources._recency_query_refused = False
    check("a refused recency query does not lose the plain results",
          [p.title for p in survived] == ["Only result"])
    check("and is not retried for the rest of the run",
          sum(1 for a in attempts if a) == 1)


def test_display_items_are_selected_once_for_both_formats() -> None:
    """HTML and Markdown must not each decide what a display item contains.

    Box 1, Fig. 1 and Table 1 are the parts a model cannot fabricate, so both
    renderers have to show the same facts. They used to compute those facts
    independently — the same index validation, field picking, relevance
    labelling and year bucketing written twice — which is a correctness risk,
    not just duplication: the two could disagree and nothing would notice
    (issue #46). Selection now lives in one place; the renderers only format.
    """
    import inspect

    from articlegen import demo, render

    cited, cite_map = render._citation_map(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS)
    labels = render._display_relevance(cite_map, demo.SAMPLE_CURATION)

    # Both renderers must go through the shared selectors.
    for fn, selector in (
        (render._box_html, "_box_parts"), (render._box_markdown, "_box_parts"),
        (render._table_html, "_table_rows"), (render._table_markdown, "_table_rows"),
        (render._figure_html, "_figure_series"), (render._figure_markdown, "_figure_series"),
    ):
        check(f"{fn.__name__} uses {selector}", selector in inspect.getsource(fn))

    # And the facts they carry must actually agree.
    rows = render._table_rows(cited, labels)
    check("a row per cited source", len(rows) == len(cited))
    table_html = render._table_html(cited, labels)
    table_md = render._table_markdown(cited, labels)
    for row in rows:
        for value in (str(row["year"]), row["study"], row["cited_by"]):
            if value == "—":
                continue
            check(f"both tables carry {value[:26]!r}",
                  value in table_md and (value in table_html or html_escaped(value, table_html)))

    series = render._figure_series(cited, labels)
    check("the figure has data to plot", series is not None)
    fig_md = render._figure_markdown(cited, labels)
    for (label, _), tally in zip(series["buckets"], series["counts"]):
        check(f"markdown figure reports bucket {label}",
              f"- {label}: {sum(tally.values())}" in fig_md)

    box = render._box_parts(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, cite_map)
    check("the featured study resolves", box is not None)
    box_html, box_md = (
        render._box_html(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, cite_map),
        render._box_markdown(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, cite_map),
    )
    check("both boxes name the same study",
          box["paper"].title in box_md and html_escaped(box["paper"].title, box_html))
    check("both boxes carry the method", box["method"][:40] in box_md)

    # A bad index must fail the same way in both, not render half a box.
    broken = dict(demo.SAMPLE_ARTICLE, featured_study={"source_index": 999})
    check("an out-of-range featured study yields nothing",
          render._box_parts(broken, demo.SAMPLE_PAPERS, cite_map) is None
          and render._box_html(broken, demo.SAMPLE_PAPERS, cite_map) == ""
          and render._box_markdown(broken, demo.SAMPLE_PAPERS, cite_map) == "")


def html_escaped(value: str, haystack: str) -> bool:
    import html as _h
    return value in haystack or _h.escape(value) in haystack


def test_failed_style_gate_is_visible_in_the_article() -> None:
    """A draft that failed the prose check must not look like one that passed.

    The gate ran, the revision was attempted, and if it did not clear the errors
    the article shipped with no sign of it — a reader had no way to tell a clean
    draft from one carrying five unfixed errors (issue #53). The house style puts
    warnings in the Limitations paragraph rather than in callout boxes, so that
    is where this goes, next to the unverified-figure warning.
    """
    from articlegen import render
    from articlegen.sources import Paper

    papers = [Paper(title="P1", abstract="a", year=2024, doi="10.1/a")]
    counts = {"direct": 1, "related": 0, "tangential": 0}
    clean = {"issues": [], "stats": {}}
    failed = {"issues": [
        {"rule": "echoed-abstract", "severity": "error", "where": "Introduction",
         "detail": "d", "excerpt": ""},
        {"rule": "echoed-abstract", "severity": "error", "where": "key points",
         "detail": "d", "excerpt": ""},
        {"rule": "bundled-citations", "severity": "error", "where": "whole article",
         "detail": "d", "excerpt": ""},
        {"rule": "under-length", "severity": "warning", "where": "whole article",
         "detail": "d", "excerpt": ""},
    ], "stats": {}}

    ok = render._assessment_html(papers, counts, {"unverified": []}, clean)
    check("a clean draft says nothing about the check",
          "automated check of the writing" not in ok)

    bad = render._assessment_html(papers, counts, {"unverified": []}, failed)
    check("a failed draft says so", "automated check of the writing" in bad)
    check("in the reader's terms, not the rule's",
          "repeats the abstract rather than adding to it" in bad
          and "echoed-abstract" not in bad)
    check("the same rule twice is one fault to a reader",
          bad.count("repeats the abstract") == 1)
    check("faults are joined readably", " and " in bad)
    check("warnings do not trigger it",
          "under-length" not in bad and "under length" not in bad)
    check("it says the revision was tried", "revision was attempted" in bad)
    check("and lands in Limitations, not a callout box",
          "Limitations." in bad and "⚠" not in bad)

    md = "\n".join(render._assessment_markdown(papers, counts, {"unverified": []}, failed))
    check("markdown carries the same warning", "automated check of the writing" in md)

    # An absent report is not the same as a clean one, but it must not crash or
    # invent a warning — legacy drafts have no style report at all.
    legacy = render._assessment_html(papers, counts, {"unverified": []}, None)
    check("a missing report warns about nothing",
          "automated check of the writing" not in legacy)

    # The pipeline must actually hand it over, or none of this is reachable.
    import inspect
    from articlegen import cli, web
    for name, src in (("cli", inspect.getsource(cli.cmd_draft)),
                      ("web", inspect.getsource(web.ArticleGenHandler._handle_draft))):
        check(f"{name} passes the style report to the renderer",
              "draft.style_report" in src)


def test_evidence_assessment_is_wholly_deterministic() -> None:
    """Nothing countable in the Evidence assessment may be model-written.

    The section exists to state honestly how good the evidence is, and the
    model's `evidence_note` repeatedly contradicted the counts printed two lines
    above it: one article claimed "13 out of 20 sources" beside a computed 9;
    another claimed "5 sources", "the majority is related" and "some are
    tangential" against a computed 3 cited, all direct, none related, none
    background. The field is gone from the schema (issue #54).

    Legacy drafts that still carry one must render without it rather than
    reprinting a tally that may be wrong.
    """
    from articlegen import render, writer
    from articlegen.sources import Paper

    check("evidence_note is out of the schema",
          "evidence_note" not in writer._ARTICLE_SCHEMA["properties"])
    check("and is not required", "evidence_note" not in writer._ARTICLE_SCHEMA["required"])
    check("the writer is told not to state counts",
          "Do NOT state counts or tallies" in writer._WRITER_SYSTEM)

    papers = [Paper(title="P1", abstract="a", year=2024, doi="10.1/a")]
    counts = {"direct": 1, "related": 0, "tangential": 0}
    legacy = render._assessment_html(papers, counts, {"unverified": []})
    check("a legacy note is not rendered", "13 out of 20" not in legacy)
    check("the deterministic opening survives", "Of the 1 source cited" in legacy)

    # Number agreement: the section that exists to be precise printed
    # "1 address the review question directly".
    check("singular subject takes a singular verb", "1 addresses the review question" in legacy)
    check("singular 'source', not 'sources'", "1 sources cited" not in legacy)
    check("singular related reads 'is related'",
          "0 are related" in legacy)

    one_each = render._assessment_html(
        papers, {"direct": 0, "related": 1, "tangential": 1}, {"unverified": []})
    check("one related reads 'is related'", "1 is related" in one_each)
    check("one background reads 'provides'", "1 provides background only" in one_each)

    plural = render._assessment_html(
        papers * 3, {"direct": 2, "related": 3, "tangential": 0}, {"unverified": []})
    check("plurals still read correctly",
          "Of the 3 sources cited, 2 address" in plural and "3 are related" in plural)

    md = "\n".join(render._assessment_markdown(papers, counts, {"unverified": []}))
    check("markdown agrees with the html", "Of the 1 source cited, 1 addresses" in md)


def test_house_style_is_fixed_not_a_preference() -> None:
    """There is one register, and the front end must not offer alternatives to it.

    The Tone selector used to fold a choice into the `style_note` the writer is
    given, defaulting to "Engaging Science Journalism (Wired/Quanta style)" —
    while `style.py` deterministically bans second person, contractions,
    boosters and rhetorical questions, which is precisely that register. Three
    of its four options asked for prose the checker then rejected, so the
    setting could only make the output worse.

    `docs/journal-style.md` defines the register and `style.py` enforces it, so
    the tone is part of the house style rather than something a reader picks.
    The selector is gone and the label is a constant.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "index.html")
    html = open(path, encoding="utf-8").read()

    check("the tone selector is gone", 'id="prefTone"' not in html)
    check("and no tone map survives it", "toneMap" not in html)
    for banned in ("Wired", "Quanta", "ELI5", "Executive Briefing"):
        check(f"no alternative register is offered: {banned}", banned not in html)

    # The writer is still told the register explicitly; it just isn't selectable.
    check("the tone label is a single constant", html.count("const TONE_LABEL") == 1)
    check("and it names the academic register",
          "Formal Academic & Technical" in html)
    check("styleGuidance still sends a tone", "'Tone: ' + p.toneLabel" in html)
    check("which now resolves to the constant", "toneLabel: TONE_LABEL" in html)

    # The other three preferences are untouched.
    for keep in ("prefLength", "prefDepth", "prefLang"):
        check(f"{keep} still offered", f'id="{keep}"' in html)


def test_register_rules_are_scoped_to_the_synthesis_voice() -> None:
    """The register rules model one voice, and the corpus proves which.

    `tests/style_corpus.json` is 20 high-cited abstracts stratified across
    article type (primary / systematic review / narrative review) and domain
    (clinical psychiatry / neuroscience / health services), 20 distinct journals.

    Each is labelled by the voice it is written in. A primary trial report says
    "we randomly assigned patients" because those authors ran the trial; a
    synthesis speaks about other people's work. `articlegen` only ever writes the
    second, so banning the first is correct — but it means primary-research
    abstracts are *not* a negative control for the first-person rule, which is
    the trap the older corpus had to paper over with per-entry exceptions.

    The separation is clean, and that is the assertion: every investigator-voice
    entry fires a register rule, no synthesis-voice entry does.
    """
    import json

    from articlegen.style import check_style, errors

    register = {"first-person", "second-person", "contraction", "booster",
                "overclaim", "rhetorical-question", "exclamation"}
    path = os.path.join(os.path.dirname(__file__), "style_corpus.json")
    corpus = json.load(open(path, encoding="utf-8"))

    check("corpus is 20 articles", len(corpus) == 20)
    check("every type/domain cell is represented",
          len({(e["type"], e["domain"]) for e in corpus}) == 9)
    check("drawn from many journals, not one house style",
          len({e["journal"] for e in corpus}) >= 15)

    mismatched = []
    for entry in corpus:
        article = {"sections": [{"heading": "Introduction",
                                 "paragraphs": [entry["abstract"]]}]}
        fired = sorted({i["rule"] for i in errors(check_style(article))} & register)
        if fired != entry["expect_register_errors"]:
            mismatched.append((entry["title"][:48], fired, entry["expect_register_errors"]))
    for title, fired, expected in mismatched:
        print(f"      {title}: fired {fired}, expected {expected}")
    check("register rules match expectations on all 20", not mismatched)

    synthesis = [e for e in corpus if e["register"] == "synthesis"]
    investigator = [e for e in corpus if e["register"] == "investigator"]
    check("the corpus carries both voices", synthesis and investigator)
    check("no synthesis-voice abstract trips a register rule",
          all(not e["expect_register_errors"] for e in synthesis))
    check("every investigator-voice abstract does",
          all(e["expect_register_errors"] for e in investigator))


def test_hedging_floor_is_calibrated_against_body_prose() -> None:
    """The hedging floor is validated — against body prose, not abstracts.

    #56 recorded that `MIN_HEDGES_PER_SENTENCE = 0.20` had never been checked
    against the register it polices: abstracts run at a median of 0.031, but
    they compress and assert, and 18 of the 20 in `style_corpus.json` are too
    short for the density gate to apply at all.

    `body_prose_measurements.json` closes that gap: the body paragraphs of 18
    open-access reviews (Lancet, Lancet Psychiatry, BMJ, PLoS, Frontiers…),
    abstract and references excluded. They hedge at a **median of 0.22** — the
    0.20 floor is very nearly the median of published review prose. The guess
    was right; it had simply been compared with the wrong text type.

    Only the measurements are stored, not the articles: the statistics are the
    evidence, and the repo has no business carrying other people's full texts.
    """
    import json
    import statistics

    from articlegen import style

    path = os.path.join(os.path.dirname(__file__), "body_prose_measurements.json")
    corpus = json.load(open(path, encoding="utf-8"))
    check("body-prose corpus is a usable size", len(corpus) >= 15)
    check("every entry is identifiable", all(e.get("pmcid") for e in corpus))
    check("drawn from several journals", len({e["journal"] for e in corpus}) >= 10)
    check("covers all three domains", len({e["domain"] for e in corpus}) == 3)

    hedges = [e["hps"] for e in corpus]
    median = statistics.median(hedges)
    check(f"body prose hedges near the floor (median {median:.3f})",
          abs(median - style.MIN_HEDGES_PER_SENTENCE) < 0.05)
    check("which is why the floor stands", style.MIN_HEDGES_PER_SENTENCE == 0.20)

    # Unlike abstracts, real body prose is long enough to be judged at all.
    check("all of it clears the density gate",
          all(e["sentences"] > style.MIN_SENTENCES_FOR_DENSITY
              and e["body_words"] > style.MIN_WORDS_FOR_DENSITY for e in corpus))

    # And it uses many distinct hedges, which is what hedge-monotony assumes.
    distinct = [e["distinct"] for e in corpus]
    check(f"body prose varies its hedges (median {statistics.median(distinct):.0f} distinct)",
          statistics.median(distinct) >= 8)
    check("so demanding variety is fair once there are enough hedges",
          style.MIN_HEDGES_FOR_MONOTONY >= 8)

    passive = [e["passive"] for e in corpus]
    check("the passive threshold clears review prose too",
          sum(1 for p in passive if p > style.MAX_PASSIVE_RATIO) == 0)


def test_density_thresholds_are_documented_against_the_corpus() -> None:
    """The density thresholds are house preferences, not measurements — say so.

    Measured over the 20-article corpus: hedging runs at a median of 0.03 markers
    per sentence and 17 of 20 sit below the 0.20 floor, half using no hedge at
    all. `docs/journal-style.md` §15 cites corpus work reporting one marker every
    two to three sentences, but that figure is for *whole research articles*,
    where the Discussion carries most of the hedging — not for abstracts, which
    compress and assert.

    So this test does not assert that the floor is right. It pins the measured
    distribution, so that changing a threshold without re-measuring fails here,
    and records that abstracts cannot calibrate a rule aimed at body prose (18 of
    20 are too short for the density gate to even apply).
    """
    import json
    import statistics

    from articlegen import style

    path = os.path.join(os.path.dirname(__file__), "style_corpus.json")
    corpus = json.load(open(path, encoding="utf-8"))
    hedges = [e["measured"]["hedges_per_sentence"] for e in corpus]
    passive = [e["measured"]["passive_ratio"] for e in corpus]
    sentence_words = [e["measured"]["mean_sentence_words"] for e in corpus]

    check("published abstracts hedge far below the floor",
          statistics.median(hedges) < style.MIN_HEDGES_PER_SENTENCE / 2)
    check("most of the corpus would fail the hedging floor",
          sum(1 for h in hedges if h < style.MIN_HEDGES_PER_SENTENCE) >= 15)
    check("and most are too short for the density gate to apply",
          sum(1 for e in corpus
              if e["measured"]["sentences"] > style.MIN_SENTENCES_FOR_DENSITY
              and e["measured"]["words"] > style.MIN_WORDS_FOR_DENSITY) <= 4)

    # These two are calibrated: real prose sits comfortably inside them, so they
    # flag genuine outliers rather than the norm.
    check("the passive ratio threshold clears real prose",
          sum(1 for p in passive if p > style.MAX_PASSIVE_RATIO) <= 3)
    check("mean sentence length matches the 15-30 guidance",
          sum(1 for w in sentence_words if 15 <= w <= 30) >= 17)

    # A measured corpus is the guard the docs promise; keep the recorded stats
    # honest by recomputing one of them.
    entry = corpus[0]
    report = style.check_style(
        {"sections": [{"heading": "Introduction", "paragraphs": [entry["abstract"]]}]})
    check("recorded stats still match a fresh run",
          round(report["stats"]["passive_ratio"], 3) == entry["measured"]["passive_ratio"])


def test_statistic_verification() -> None:
    from articlegen.verify import check_statistics
    from articlegen.sources import Paper

    papers = [Paper(title="P1", abstract="the effect was 0.53 overall and 12% responded", year=2010)]
    article = {
        "abstract": "s", "evidence_note": "",
        "featured_study": {"source_index": 1, "why": "", "method": "", "results": "RR 4.91"},
        "sections": [{"heading": "H", "paragraphs": ["fell 0.53 [1] but SMD -0.90 [1]"]}],
        "key_points": ["12% responded [1]"], "references": [1],
    }
    v = check_statistics(article, papers)
    check("flags absent figure 4.91", "4.91" in v["unverified"])
    check("flags absent figure -0.90", "-0.90" in v["unverified"])
    check("passes present figure 0.53", "0.53" not in v["unverified"])
    check("passes present figure 12%", "12%" not in v["unverified"])

    legacy = {
        "standfirst": "SMD -0.77 headline", "evidence_note": "",
        "sections": [{"heading": "H", "paragraphs": ["x"], "pull_quote": "and 8.88 more"}],
        "key_takeaways": ["12% responded [1]"], "references": [1],
    }
    v_legacy = check_statistics(legacy, papers)
    check("pre-journal-format drafts are still checked",
          "-0.77" in v_legacy["unverified"] and "8.88" in v_legacy["unverified"])


def test_ranking() -> None:
    from articlegen.sources import Paper, _rank_score

    terms = {"schizophrenia", "light"}
    on_topic = Paper(title="Light therapy in schizophrenia", abstract="light schizophrenia trial", year=2020, citation_count=50)
    famous = Paper(title="A review of depression", abstract="depression mood", year=2011, citation_count=5000)
    check("on-topic outranks famous off-topic", _rank_score(on_topic, terms) > _rank_score(famous, terms))


def _sample_draft():
    from articlegen.sources import Paper

    papers = [
        Paper(title=f"Study {i}", abstract="a", year=2000 + i, authors=[f"Ann A{'bcdef'[i - 1]}"],
              venue=f"Journal {i}", citation_count=100 * i, doi=f"10/{i}")
        for i in range(1, 6)
    ]
    article = {
        "title": "Bright light therapy in schizophrenia",
        "abstract": "A summary paragraph of the evidence.",
        "keywords": ["schizophrenia", "light therapy"],
        "evidence_note": "Only one source is directly on schizophrenia [1].",
        "featured_study": {"source_index": 2, "why": "Best trial.", "method": "RCT, n=40.",
                           "results": "Improved."},
        "sections": [
            {"heading": "Introduction", "paragraphs": ["Claim [1] and [2]."]},
            {"heading": "Trial evidence", "paragraphs": ["More [2]."]},
            {"heading": "Conclusions", "paragraphs": ["Unresolved [1]."]},
        ],
        "key_points": ["Point [1]."],
        "glossary": [{"term": "Lux", "definition": "A unit of illuminance."}],
        "references": [1, 2, 3],
    }
    curation = {
        "relevance": {1: "direct", 2: "related", 3: "tangential"},
        "most_relevant_index": 2,
        "counts": {"direct": 1, "related": 1, "tangential": 1},
    }
    verification = {"unverified": ["-0.90", "4.91"], "total": 5}
    # `databases` names the sources that actually answered. A real run always
    # records it; nothing is inferred when it is absent (see
    # test_methods_names_only_sources_that_answered).
    provenance = {
        "queries": ["light therapy schizophrenia"],
        "databases": ["Semantic Scholar Graph API", "OpenAlex"],
        "model": "test-model",
    }
    return article, papers, curation, verification, provenance


def test_recency_actually_counts() -> None:
    """Recency must be able to outweigh citation count, within reason.

    It used to be `year / 1000`, spanning 0.02 across two decades while the
    citation term spans 0-4 — arithmetically a rounding error. A real search
    returned a median paper year of 2013 with only 2 of 20 papers from 2020 or
    later, which pushes the writer towards broad old reviews that carry fewer
    specific findings than recent trials.
    """
    from articlegen.sources import Paper, _rank_score, RECENCY_HALF_LIFE

    now = 2026
    terms: set[str] = set()
    old_famous = Paper(title="A", abstract="a", year=2003, citation_count=2750)
    recent_solid = Paper(title="B", abstract="b", year=2025, citation_count=100)
    check("a recent solid paper beats an old famous one",
          _rank_score(recent_solid, terms, now) > _rank_score(old_famous, terms, now))

    # But citations must still count — not merely "newest wins".
    recent_ignored = Paper(title="C", abstract="c", year=2026, citation_count=0)
    recent_cited = Paper(title="D", abstract="d", year=2026, citation_count=500)
    check("among equally recent papers, citations still decide",
          _rank_score(recent_cited, terms, now) > _rank_score(recent_ignored, terms, now))

    # And topic relevance still dominates both — it's the primary sort key.
    off_topic_new = Paper(title="unrelated", abstract="unrelated", year=2026, citation_count=9999)
    on_topic_old = Paper(title="shift work sleep", abstract="shift work sleep",
                         year=2005, citation_count=1)
    topic_terms = {"shift", "work", "sleep"}
    check("topic relevance still outranks recency and fame",
          _rank_score(on_topic_old, topic_terms, now) > _rank_score(off_topic_new, topic_terms, now))

    # Beyond the half-life the recency bonus is spent, not negative.
    ancient = Paper(title="E", abstract="e", year=now - RECENCY_HALF_LIFE - 30, citation_count=10)
    older_still = Paper(title="F", abstract="f", year=now - RECENCY_HALF_LIFE - 60, citation_count=10)
    check("recency decays to zero rather than going negative",
          _rank_score(ancient, terms, now) == _rank_score(older_still, terms, now))

    check("a missing year does not crash or win",
          _rank_score(Paper(title="G", abstract="g", year=None), terms, now)[1] >= 0)


def test_render_blocks() -> None:
    from articlegen.render import render_article, render_markdown, _is_clinical

    article, papers, curation, verification, provenance = _sample_draft()
    topic = "sunlight for schizophrenia"
    h = render_article(article, papers, topic, curation, verification, provenance)
    md = render_markdown(article, papers, topic, curation, verification, provenance)

    check("html article-type label", "Evidence Review" in h)
    check("html abstract run-in head", 'class="run-in-head">Abstract' in h)
    check("html keywords printed", 'class="keywords"' in h and "schizophrenia" in h)
    check("html key points box", 'class="key-points"' in h and "Key points" in h)
    check("html Box 1 for the featured study", "Box 1 |" in h and "Study 2" in h)
    check("html Table 1 of cited evidence", "Table 1 |" in h and "<table>" in h)
    check("html Fig. 1 of the evidence base", "Fig. 1 |" in h and "<svg" in h)
    check("html methods states the search", "Methods" in h and "light therapy schizophrenia" in h)
    check("html names the databases", "OpenAlex" in h and "Semantic Scholar" in h)
    check("html limitations replace warning boxes",
          "Limitations." in h and "could not be located" in h and "-0.90" in h)
    check("html no emoji warnings", "⚠" not in h)
    check("html glossary", "Glossary" in h and "Lux" in h)
    check("html back matter", "Competing interests" in h and "Data availability" in h)
    check("html references are Vancouver-style",
          '<span class="ref-authors">Ab, A.</span>' in h
          and ">Study 1.</a> <em>Journal 1</em> (2001)." in h)
    check("html clinical disclaimer", "Not medical or clinical advice" in h)
    check("html has no magazine furniture",
          "pull" not in h and "kicker" not in h and "standfirst" not in h)

    check("md abstract", "**Abstract.**" in md)
    check("md key points", "## Key points" in md)
    check("md Box 1", "**Box 1 | Key study:" in md)
    check("md Table 1", "**Table 1 |" in md and "| Ref. | Study |" in md)
    check("md Fig. 1", "**Fig. 1 |" in md)
    check("md methods", "## Methods" in md and "**Search strategy.**" in md)
    check("md evidence assessment", "## Evidence assessment" in md and "**Limitations.**" in md)
    check("md additional information", "## Additional information" in md)
    check("md clinical disclaimer", "Not medical or clinical advice" in md)
    check("clinical detection on", _is_clinical(topic, article))
    check("clinical detection off",
          not _is_clinical("gravity batteries", {"title": "Storage", "abstract": "x"}))


def test_display_item_placement() -> None:
    """Display items interleave with the body and every one is emitted exactly once."""
    from articlegen.render import render_article

    article, papers, curation, verification, provenance = _sample_draft()
    h = render_article(article, papers, "sunlight for schizophrenia", curation, verification, provenance)
    check("each display item appears once",
          h.count("Box 1 |") == 1 and h.count("Fig. 1 |") == 1 and h.count("Table 1 |") == 1)
    check("figure precedes box in the body", h.index("Fig. 1 |") < h.index("Box 1 |"))
    check("table sits in the back matter, after Methods",
          h.index("Table 1 |") > h.index("<h2>Methods"))
    check("table precedes the reference list", h.index("Table 1 |") < h.index("References"))
    check("key points sit before the conclusions",
          h.index("<h2>Introduction") < h.index("Key points") < h.index("<h2>Conclusions"))

    # A one-section article still gets all three, appended rather than interleaved.
    short = dict(article, sections=[{"heading": "Introduction", "paragraphs": ["Only [1]."]}])
    h_short = render_article(short, papers, "topic", curation, None, provenance)
    check("short articles keep every display item",
          all(k in h_short for k in ("Box 1 |", "Fig. 1 |", "Table 1 |")))


def test_legacy_draft_fields() -> None:
    """Drafts written against the pre-journal schema still render."""
    from articlegen.render import render_article
    from articlegen.sources import Paper

    papers = [Paper(title="Old study", abstract="a", year=2011, authors=["Ann Old"])]
    legacy = {
        "title": "An older draft", "standfirst": "The old deck line.",
        "evidence_note": "", "featured_study": {},
        "sections": [{"heading": "H", "paragraphs": ["Text [1]."], "pull_quote": "quote"}],
        "key_takeaways": ["Old point [1]."], "references": [1],
    }
    h = render_article(legacy, papers, "legacy topic")
    check("standfirst is used as the abstract", "The old deck line." in h)
    check("key_takeaways render as key points", "Old point" in h and "Key points" in h)
    check("pull quote is dropped", "quote" not in h)


def test_demo_and_index() -> None:
    import tempfile
    from articlegen import demo
    from articlegen.render import render_article, render_markdown, build_index

    h = render_article(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, "Sample topic",
                       demo.SAMPLE_CURATION, None, demo.SAMPLE_PROVENANCE)
    md = render_markdown(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, "Sample topic",
                         demo.SAMPLE_CURATION, None, demo.SAMPLE_PROVENANCE)
    check("demo html renders the display items",
          all(k in h for k in ("Box 1 |", "Fig. 1 |", "Table 1 |")))
    check("demo markdown renders", md.startswith("**EVIDENCE REVIEW**"))
    check("demo sections run Introduction -> Conclusions",
          demo.SAMPLE_ARTICLE["sections"][0]["heading"] == "Introduction"
          and demo.SAMPLE_ARTICLE["sections"][-1]["heading"].startswith("Conclusions"))
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "2026-01-01-x.html"), "w", encoding="utf-8") as f:
            f.write(h)
        idx = build_index(d)
        check("index builds", os.path.exists(idx))


def test_web_server() -> None:
    import json
    from io import BytesIO
    from articlegen.web import ArticleGenHandler

    class DummyRequest:
        def makefile(self, *args, **kwargs):
            return BytesIO(b"GET /api/drafts HTTP/1.1\r\nHost: localhost\r\n\r\n")

    class FakeSocket:
        def __init__(self):
            self.rfile = BytesIO(b"GET /api/drafts HTTP/1.1\r\nHost: localhost\r\n\r\n")
            self.wfile = BytesIO()

        def sendall(self, data):
            self.wfile.write(data)

        def makefile(self, mode, *args, **kwargs):
            if "r" in mode:
                return self.rfile
            return self.wfile

    sock = FakeSocket()
    handler = ArticleGenHandler(sock, ("127.0.0.1", 8000), None)
    output = sock.wfile.getvalue().decode("utf-8")
    check("web handler GET /api/drafts returns 200 OK", "200 OK" in output and "application/json" in output)


def test_ungrounded_citations_leave_no_trace() -> None:
    """A model does cite SOURCE numbers it was never given. The marker is
    dropped — but it used to leave its leading space behind, stranding the
    sentence's full stop as "…the market ." in a shipped article."""
    from articlegen.render import _remap_citations, _shift_markers_after_punctuation

    def rendered(text, mapping):
        return _shift_markers_after_punctuation(_remap_citations(text, mapping))

    check("a dropped marker takes its space with it",
          rendered("ahead of the market [15].", {1: 1}) == "ahead of the market.")
    check("kept markers still hug their word",
          rendered("a claim [1].", {1: 1}) == "a claim.[1]")
    check("dropping one of a bundle keeps the rest",
          rendered("both agree [1, 9].", {1: 1}) == "both agree.[1]")
    check("a dropped marker mid-sentence closes up",
          rendered("dropped [9] here [2].", {2: 2}) == "dropped here.[2]")


def test_full_text_grounding() -> None:
    """Full-text mode: fetch only what is truly open access, show a bounded
    excerpt, tell the model the truth about its inputs, and verify statistics
    against exactly what was shown — never against text the writer did not see.
    """
    from articlegen import render, sources, verify, writer
    from articlegen.sources import Paper, full_text_excerpts

    # -- search carries the fetchability facts ------------------------------
    payload = {"resultList": {"result": [
        {"id": "1", "source": "MED", "title": "OA paper", "abstractText": "An abstract.",
         "pubYear": "2026", "pmcid": "PMC123", "isOpenAccess": "Y", "inEPMC": "Y"},
        {"id": "2", "source": "MED", "title": "OA elsewhere only", "abstractText": "A.",
         "pubYear": "2026", "pmcid": "PMC124", "isOpenAccess": "Y", "inEPMC": "N"},
    ]}}

    class FakeResp:
        def __init__(self, data=None, text=""):
            self._data, self.text = data, text
        def json(self):
            return self._data

    real = sources._get_with_retry
    try:
        sources._get_with_retry = lambda url, params, headers: FakeResp(payload)
        papers = sources.search_europe_pmc("q", limit=2)
    finally:
        sources._get_with_retry = real
    check("pmcid captured from the search", papers[0].pmcid == "PMC123")
    check("in-EPMC open access marks fetchable", papers[0].is_open_access)
    check("OA hosted elsewhere is not fetchable", not papers[1].is_open_access)

    # -- JATS parsing -------------------------------------------------------
    jats = """<article><body>
      <sec><title>Methods</title><p>We enrolled 441 participants [ 3 ] over two years.</p></sec>
      <sec><title>Results</title><p>Readmission fell (OR 0.66) [2, 5].</p></sec>
      <sec><title>Acknowledgements</title><p>We thank everyone.</p></sec>
    </body></article>"""
    text = sources._parse_fulltext_xml(jats)
    check("sections flattened in order", text.index("enrolled") < text.index("Readmission"))
    check("back matter dropped", "thank" not in text)
    check("the paper's own citation brackets are stripped",
          "[ 3 ]" not in text and "[2, 5]" not in text)
    check("statistics survive the stripping", "OR 0.66" in text)

    # -- fetch gating and cache --------------------------------------------
    calls = []
    try:
        sources._get_with_retry = (
            lambda url, params, headers: (calls.append(url), FakeResp(text=jats))[1])
        sources.clear_search_cache()
        no_pmcid = Paper(title="n", abstract="a")
        check("no PMCID -> no fetch", sources.fetch_full_text(no_pmcid) == "")
        oa = Paper(title="o", abstract="a", pmcid="PMC9", is_open_access=True)
        first = sources.fetch_full_text(oa)
        again = sources.fetch_full_text(oa)
        check("OA paper fetches and parses", "enrolled 441" in first)
        check("second fetch is served from cache", again == first and len(calls) == 1)
    finally:
        sources._get_with_retry = real
        sources.clear_search_cache()

    # -- dedupe enrichment: the kept copy learns the duplicate's PMCID ------
    dup_title = "The same study twice"
    oa_copy = Paper(title=dup_title, abstract="a", pmcid="PMC77", is_open_access=True)
    plain_copy = Paper(title=dup_title, abstract="a")
    reals = (sources.search_semantic_scholar, sources.search_openalex, sources.search_europe_pmc)
    try:
        sources.search_semantic_scholar = lambda q, limit=15: []
        sources.search_openalex = lambda q, limit=15: [plain_copy]
        sources.search_europe_pmc = lambda q, limit=15: [oa_copy]
        merged = sources.gather_evidence(["q"], use_cache=False)
    finally:
        (sources.search_semantic_scholar, sources.search_openalex,
         sources.search_europe_pmc) = reals
    check("dedupe keeps one copy", len(merged) == 1)
    check("which inherits the duplicate's PMCID",
          merged[0].pmcid == "PMC77" and merged[0].is_open_access)

    # -- excerpt budgeting: the shared writer/verifier contract -------------
    big = "x" * (sources.FULLTEXT_PER_PAPER_CHARS + 5000)
    ranked = [Paper(title=f"t{i}", abstract="a", full_text=big) for i in range(7)]
    ranked.insert(1, Paper(title="no ft", abstract="a"))
    ex = full_text_excerpts(ranked)
    check("papers without full text are skipped", 2 not in ex)
    check("per-paper cap applies", len(ex[1]) == sources.FULLTEXT_PER_PAPER_CHARS)
    check("total budget bounds the set",
          sum(len(v) for v in ex.values()) <= sources.FULLTEXT_TOTAL_CHARS)
    check("rank order decides who is left abstract-only",
          1 in ex and max(ex) < len(ranked))

    # -- payload formatting -------------------------------------------------
    two = [Paper(title="ft", abstract="A1.", full_text="Full body text 12.5% here."),
           Paper(title="ab", abstract="A2.")]
    shown = full_text_excerpts(two)
    block = writer._format_sources(two, None, None, shown)
    check("full text rides along under its source", "Full text (open access" in block
          and "Full body text 12.5% here." in block)
    check("abstract-only sources say so", "no open-access full text" in block)
    budgeted = writer._format_sources(two, None, 5000, shown)
    check("a char budget (Groq) drops the excerpts", "Full body text" not in budgeted)

    # -- the system prompt tells the truth about its inputs -----------------
    for old, new in writer._FULLTEXT_SUBSTITUTIONS:
        check(f"substitution target still present: {old[:40]}…", old in writer._WRITER_SYSTEM)
        check(f"and replaced in the full-text variant: {new[:40]}…",
              new in writer._WRITER_SYSTEM_FULLTEXT
              and old not in writer._WRITER_SYSTEM_FULLTEXT)

    # -- verification checks the shown excerpt, not the unseen tail ---------
    tail_figure = "the unseen tail says 77.7%"
    paper = Paper(title="t", abstract="Abstract only.",
                  full_text="Shown text reports 12.5% improvement. "
                            + "y" * sources.FULLTEXT_PER_PAPER_CHARS + tail_figure)
    art = {"abstract": "It improved by 12.5% but also 77.7%.", "sections": [],
           "key_points": [], "references": []}
    result = verify.check_statistics(art, [paper])
    check("figure in the shown excerpt verifies", "12.5%" not in result["unverified"])
    check("figure only in the unseen tail stays unverified",
          "77.7%" in result["unverified"])

    # -- Methods and Table 1 report what happened ---------------------------
    prov_ft = {"queries": ["q"], "databases": ["Europe PMC"], "model": "m",
               "full_text_sources": [1, 3]}
    parts = render._methods_paragraphs(prov_ft, 10, 2, "topic")
    check("Methods reports full texts read", "full texts of 2 sources were retrieved"
          in parts["handling"] and "read alongside them" in parts["handling"])
    parts_abs = render._methods_paragraphs({"queries": ["q"], "databases": ["Europe PMC"]},
                                           10, 2, "topic")
    check("abstracts-only Methods wording unchanged",
          "full texts were not retrieved" in parts_abs["handling"])
    ft_cited = [Paper(title="a", abstract="x", full_text="body", year=2020),
                Paper(title="b", abstract="x", year=2021)]
    table = render._table_html(ft_cited, {1: "direct", 2: "related"})
    check("Table 1 grows a Read column in full-text mode",
          "<th>Read</th>" in table and "Full text" in table and "Abstract" in table)
    plain_table = render._table_html(
        [Paper(title="a", abstract="x", year=2020)], {1: "direct"})
    check("no Read column when everything is abstract-only",
          "<th>Read</th>" not in plain_table)
    md = render._table_markdown(ft_cited, {1: "direct", 2: "related"})
    check("markdown table matches", "Read |" in md and "Full text |" in md)


def test_pipeline_fetches_full_text() -> None:
    """The pipeline stage itself: fetch only direct/related sources, respect the
    cap, record provenance, and skip the whole step on Groq (whose token budget
    cannot fit a full text)."""
    from articlegen import pipeline
    from articlegen.sources import Paper

    papers = [Paper(title=f"p{i}", abstract="a", pmcid=f"PMC{i}", is_open_access=True)
              for i in range(1, 5)]
    article = {"title": "t", "abstract": "x", "keywords": [], "sections": [],
               "key_points": [], "glossary": [], "references": [1]}
    curation = {"relevance": {1: "direct", 2: "tangential", 3: "related", 4: "direct"},
                "most_relevant_index": 1,
                "counts": {"direct": 2, "related": 1, "tangential": 1}}
    fetched_pmcids: list[str] = []

    saved = (pipeline.plan_queries, pipeline.gather_evidence, pipeline.curate_sources,
             pipeline.write_article, pipeline.fetch_full_text, pipeline.enforce_style,
             pipeline.prompt_budget_chars)
    try:
        pipeline.plan_queries = lambda topic, **kw: (["q"], "core")
        def fake_gather(queries, **kw):
            kw.get("outcomes", []).append(
                {"source": "europe_pmc", "query": "q", "count": 4, "error": "", "cached": False})
            return papers
        pipeline.gather_evidence = fake_gather
        pipeline.curate_sources = lambda topic, p, **kw: curation
        pipeline.write_article = lambda topic, p, **kw: dict(article)
        pipeline.fetch_full_text = (
            lambda p, use_cache=True: (fetched_pmcids.append(p.pmcid), "body text")[1])
        pipeline.enforce_style = lambda a, **kw: (a, {"issues": [], "stats": {}})

        pipeline.prompt_budget_chars = lambda model=None, api_key=None: None
        draft = pipeline.generate_draft("topic")
        check("direct and related sources are fetched, tangential is not",
              fetched_pmcids == ["PMC1", "PMC3", "PMC4"])
        check("papers carry their full text", draft.papers[0].full_text == "body text")
        check("provenance records which sources were read in full",
              draft.provenance["full_text_sources"] == [1, 3, 4])

        for p in papers:
            p.full_text = ""
        fetched_pmcids.clear()
        pipeline.prompt_budget_chars = lambda model=None, api_key=None: 30000  # Groq
        draft = pipeline.generate_draft("topic")
        check("Groq's token budget disables the full-text step entirely",
              fetched_pmcids == [] and draft.provenance["full_text_sources"] == [])
    finally:
        (pipeline.plan_queries, pipeline.gather_evidence, pipeline.curate_sources,
         pipeline.write_article, pipeline.fetch_full_text, pipeline.enforce_style,
         pipeline.prompt_budget_chars) = saved


def main() -> int:
    for fn in (
        test_provider_resolution, test_per_request_api_key,
        test_openrouter_routing, test_openrouter_request_shape,
        test_refusal_fallbacks,
        test_pipeline_is_shared, test_draft_summary, test_rate_limit,
        test_keepalive_connection_reuse, test_substance_checks,
        test_groq_token_budget, test_source_failures_are_distinguishable,
        test_search_cache, test_front_end_models_match_the_allowlist,
        test_polite_pool_identification, test_europe_pmc_parsing,
        test_ungrounded_citations_leave_no_trace,
        test_full_text_grounding, test_pipeline_fetches_full_text,
        test_methods_names_only_sources_that_answered,
        test_groq_json_cleaning,
        test_citation_renumbering, test_journal_citation_style, test_reference_formatting,
        test_prose_style_check, test_rules_do_not_reject_real_journal_prose,
        test_health_reports_which_build_is_running,
        test_openalex_reaches_for_recent_work_as_well,
        test_display_items_are_selected_once_for_both_formats,
        test_failed_style_gate_is_visible_in_the_article,
        test_evidence_assessment_is_wholly_deterministic,
        test_house_style_is_fixed_not_a_preference,
        test_register_rules_are_scoped_to_the_synthesis_voice,
        test_hedging_floor_is_calibrated_against_body_prose,
        test_density_thresholds_are_documented_against_the_corpus,
        test_statistic_verification, test_ranking, test_recency_actually_counts, test_render_blocks,
        test_display_item_placement, test_legacy_draft_fields,
        test_demo_and_index, test_web_server,
    ):
        print(f"\n# {fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'ALL PASS'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

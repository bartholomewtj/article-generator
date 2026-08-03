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
    check("claude-* model name forces anthropic", resolve_provider("claude-opus-4-8")[0] == "anthropic")
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
    check(
        "explicit model still beats the key prefix",
        resolve_provider("claude-opus-4-8", "gsk_abc")[0] == "anthropic",
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

    real_ss, real_oa = sources.search_semantic_scholar, sources.search_openalex
    try:
        # Both sources refuse.
        sources.search_semantic_scholar = lambda q, limit=15: (_ for _ in ()).throw(
            sources.SearchFailure("HTTP 429 after 3 attempts"))
        sources.search_openalex = lambda q, limit=15: (_ for _ in ()).throw(
            sources.SearchFailure("HTTP 403"))
        outcomes: list[dict] = []
        papers = sources.gather_evidence(["x"], outcomes=outcomes)
        check("no papers when both refuse", papers == [])
        check("both failures recorded", len([o for o in outcomes if o["error"]]) == 2)
        check("the reason is kept", any("429" in o["error"] for o in outcomes))

        # One source down, the other fine — the run must survive.
        sources.search_openalex = lambda q, limit=15: [
            sources.Paper(title=f"P{i}", abstract="a") for i in range(3)]
        outcomes = []
        papers = sources.gather_evidence(["x"], outcomes=outcomes)
        check("one working source is enough", len(papers) == 3)
        check("the failed source is still recorded",
              any(o["error"] for o in outcomes) and any(not o["error"] for o in outcomes))
    finally:
        sources.search_semantic_scholar, sources.search_openalex = real_ss, real_oa

    check("NoPapersFound carries the distinction",
          NoPapersFound("x", sources_failed=True).sources_failed is True)
    check("and defaults to a topic problem", NoPapersFound("x").sources_failed is False)


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


def test_methods_names_only_sources_that_answered() -> None:
    """The Methods section must not claim a database that returned nothing.

    `_DATABASES` was a hardcoded constant, so every article stated that both
    Semantic Scholar and OpenAlex had been searched — including while Semantic
    Scholar's keyless tier was 429ing every call. That made the claim false in
    every article the pipeline produced, in the one section that exists to state
    what was actually done.
    """
    from articlegen import sources
    from articlegen.render import render_article
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

    both = render_article(article, papers, "t", None, {},
                          {"databases": list(DATABASE_NAMES.values()), "queries": ["q"]})
    check("names both when both answered",
          "OpenAlex" in both and "Semantic Scholar" in both)

    # Drafts written before provenance carried `databases` must still render.
    legacy = render_article(article, papers, "t", None, {}, {"queries": ["q"]})
    check("legacy drafts without `databases` still render", "Candidate records" in legacy)

    # A source that refuses once is not retried for the remaining queries:
    # three tries with backoff is ~10s, and the limits are per-minute.
    real_ss, real_oa = sources.search_semantic_scholar, sources.search_openalex
    calls = {"ss": 0, "oa": 0}
    try:
        def failing_ss(q, limit=15):
            calls["ss"] += 1
            raise sources.SearchFailure("HTTP 429 after 3 attempts")

        def working_oa(q, limit=15):
            calls["oa"] += 1
            return [Paper(title=f"{q}-{calls['oa']}", abstract="a", year=2024)]

        sources.search_semantic_scholar = failing_ss
        sources.search_openalex = working_oa
        outcomes: list[dict] = []
        got = sources.gather_evidence(["q1", "q2", "q3"], outcomes=outcomes)

        check("the failing source is tried once, not per query", calls["ss"] == 1)
        check("the working source is still tried every query", calls["oa"] == 3)
        check("the run still succeeds on one source", len(got) == 3)
        check("skips are recorded, not silent",
              sum(1 for o in outcomes if "skipped" in o["error"]) == 2)
        answered = {o["source"] for o in outcomes if o["count"]}
        check("only the answering source counts as answered", answered == {"openalex"})
    finally:
        sources.search_semantic_scholar, sources.search_openalex = real_ss, real_oa


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
    check("remap drops unknown marker", _remap_citations("z [99] w", m) == "z  w")


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
        Paper(title=f"Study {i}", abstract="a", year=2000 + i, authors=[f"Ann A{i}"],
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
    provenance = {"queries": ["light therapy schizophrenia"], "model": "test-model"}
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
          '<span class="ref-authors">A1, A.</span>' in h
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
    check("box precedes figure precedes table",
          h.index("Box 1 |") < h.index("Fig. 1 |") < h.index("Table 1 |"))
    check("table precedes the reference list", h.index("Table 1 |") < h.index("References"))

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


def main() -> int:
    for fn in (
        test_provider_resolution, test_per_request_api_key,
        test_pipeline_is_shared, test_draft_summary, test_rate_limit,
        test_keepalive_connection_reuse, test_substance_checks,
        test_groq_token_budget, test_source_failures_are_distinguishable,
        test_polite_pool_identification,
        test_methods_names_only_sources_that_answered,
        test_groq_json_cleaning,
        test_citation_renumbering, test_journal_citation_style, test_reference_formatting,
        test_prose_style_check,
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

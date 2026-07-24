"""Offline smoke tests — no network, no API keys required.

Run with:  python tests/test_offline.py   (exits non-zero on failure)

These cover the pure logic that a fresh session can verify immediately:
provider resolution, Gemini schema translation, citation renumbering,
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
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ARTICLEGEN_PROVIDER"):
        os.environ.pop(var, None)
    from articlegen.llm import resolve_provider, GOOGLE_DEFAULT_MODEL, ANTHROPIC_DEFAULT_MODEL

    check("no keys -> gemini default", resolve_provider() == ("google", GOOGLE_DEFAULT_MODEL))
    os.environ["ANTHROPIC_API_KEY"] = "x"
    check("only anthropic -> anthropic", resolve_provider() == ("anthropic", ANTHROPIC_DEFAULT_MODEL))
    os.environ["GEMINI_API_KEY"] = "y"
    check("both keys -> gemini wins", resolve_provider()[0] == "google")
    check("claude-* model name forces anthropic", resolve_provider("claude-opus-4-8")[0] == "anthropic")
    os.environ["ARTICLEGEN_PROVIDER"] = "anthropic"
    check("provider override respected", resolve_provider()[0] == "anthropic")
    for var in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "ARTICLEGEN_PROVIDER"):
        os.environ.pop(var, None)


def test_gemini_schema_translation() -> None:
    from google.genai import types
    from articlegen.llm import _gemini_schema
    from articlegen.writer import _ARTICLE_SCHEMA, _CURATE_SCHEMA, _QUERY_SCHEMA

    for name, schema in (("article", _ARTICLE_SCHEMA), ("curate", _CURATE_SCHEMA), ("query", _QUERY_SCHEMA)):
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=_gemini_schema(schema)
        )
        check(f"gemini accepts {name} schema", cfg.response_schema is not None)
    check("additionalProperties stripped", "additionalProperties" not in str(_gemini_schema(_ARTICLE_SCHEMA)))


def test_model_discovery() -> None:
    import articlegen.llm as llm
    from types import SimpleNamespace as NS

    class FakeClient:
        def __init__(self, items):
            self.models = NS(list=lambda: items)

    catalog = [
        NS(name="models/gemini-2.0-flash", supported_actions=["generateContent"]),
        NS(name="models/gemini-flash-latest", supported_actions=["generateContent"]),
        NS(name="models/gemini-2.5-pro", supported_actions=["generateContent"]),
        NS(name="models/text-embedding-004", supported_actions=["embedContent"]),
    ]
    llm._RESOLVED_GOOGLE_MODEL = None
    pick = llm._discover_google_model(FakeClient(catalog))
    check("discovery prefers a flash model", pick is not None and "flash" in pick)
    check("discovery excludes embedding", "embedding" not in (pick or ""))

    class Err(Exception):
        def __init__(self, code=None, message=""):
            self.code, self.message = code, message
            super().__init__(message)

    check("404 -> model unavailable", llm._is_model_unavailable(Err(code=404)))
    check("503 -> transient", llm._is_transient(Err(code=503, message="high demand")))
    check("400 -> neither", not llm._is_transient(Err(code=400)) and not llm._is_model_unavailable(Err(code=400)))


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


def test_statistic_verification() -> None:
    from articlegen.verify import check_statistics
    from articlegen.sources import Paper

    papers = [Paper(title="P1", abstract="the effect was 0.53 overall and 12% responded", year=2010)]
    article = {
        "standfirst": "s", "evidence_note": "",
        "featured_study": {"source_index": 1, "why": "", "method": "", "results": "RR 4.91"},
        "sections": [{"heading": "H", "paragraphs": ["fell 0.53 [1] but SMD -0.90 [1]"], "pull_quote": None}],
        "key_takeaways": ["12% responded [1]"], "references": [1],
    }
    v = check_statistics(article, papers)
    check("flags absent figure 4.91", "4.91" in v["unverified"])
    check("flags absent figure -0.90", "-0.90" in v["unverified"])
    check("passes present figure 0.53", "0.53" not in v["unverified"])
    check("passes present figure 12%", "12%" not in v["unverified"])


def test_ranking() -> None:
    from articlegen.sources import Paper, _rank_score

    terms = {"schizophrenia", "light"}
    on_topic = Paper(title="Light therapy in schizophrenia", abstract="light schizophrenia trial", year=2020, citation_count=50)
    famous = Paper(title="A review of depression", abstract="depression mood", year=2011, citation_count=5000)
    check("on-topic outranks famous off-topic", _rank_score(on_topic, terms) > _rank_score(famous, terms))


def test_render_blocks() -> None:
    from articlegen.render import render_article, render_markdown, _is_clinical
    from articlegen.sources import Paper

    papers = [Paper(title=f"Study {i}", abstract="a", year=2000 + i, authors=[f"A{i}"], doi=f"10/{i}") for i in range(1, 6)]
    article = {
        "title": "Bright light therapy in schizophrenia", "standfirst": "S",
        "evidence_note": "Only one source is directly on schizophrenia [1].",
        "featured_study": {"source_index": 2, "why": "Best trial.", "method": "RCT, n=40.", "results": "Improved."},
        "sections": [{"heading": "H", "paragraphs": ["Claim [1] and [2]."], "pull_quote": "pq"}],
        "key_takeaways": ["Point [1]."], "references": [1, 2],
    }
    curation = {"relevance": {1: "direct", 2: "related"}, "most_relevant_index": 2, "counts": {"direct": 1, "related": 1, "tangential": 0}}
    verification = {"unverified": ["-0.90", "4.91"], "total": 5}
    h = render_article(article, papers, "sunlight for schizophrenia", curation, verification)
    md = render_markdown(article, papers, "sunlight for schizophrenia", curation, verification)
    check("html featured box", 'class="featured"' in h and "Study 2" in h)
    check("html evidence box", 'class="evidence"' in h and "directly on-topic" in h)
    check("html flags unverified figures", "could not be located" in h and "-0.90" in h)
    check("html clinical disclaimer", "Not medical or clinical advice" in h)
    check("md featured + method", "Featured study" in md and "*Method:*" in md)
    check("md evidence quality section", "## Evidence quality" in md)
    check("md clinical disclaimer", "Not medical or clinical advice" in md)
    check("clinical detection on", _is_clinical("sunlight for schizophrenia", article))
    check("clinical detection off", not _is_clinical("gravity batteries", {"title": "Storage", "standfirst": "x"}))


def test_demo_and_index() -> None:
    import tempfile
    from articlegen import demo
    from articlegen.render import render_article, render_markdown, build_index

    h = render_article(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, "Sample topic")
    md = render_markdown(demo.SAMPLE_ARTICLE, demo.SAMPLE_PAPERS, "Sample topic")
    check("demo html renders featured", 'class="featured"' in h)
    check("demo markdown renders", md.startswith("# What Your Brain Does While You Sleep"))
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "2026-01-01-x.html"), "w") as f:
            f.write(h)
        idx = build_index(d)
        check("index builds", os.path.exists(idx))


def test_bot_parsing() -> None:
    from articlegen.bot import parse_command, build_ideas_comment, latest_ideas

    check("draft number", parse_command("draft 2") == ("2", "", None))
    check("draft quoted title", parse_command('draft "My Title" style: playful') == ("My Title", "playful", None))
    check("draft gibberish errors", parse_command("draft looks good")[2] is not None)
    ideas = [{"title": "T1", "angle": "a", "search_terms": ["x"]},
             {"title": "T2", "angle": "b", "search_terms": ["y"]}]
    comment = build_ideas_comment("theme", ideas)
    found = latest_ideas([{"body": comment}])
    check("ideas marker round-trips", found is not None and found["titles"] == ["T1", "T2"])


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
        test_provider_resolution, test_gemini_schema_translation, test_model_discovery,
        test_citation_renumbering, test_statistic_verification, test_ranking,
        test_render_blocks, test_demo_and_index, test_bot_parsing, test_web_server,
    ):
        print(f"\n# {fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'ALL PASS'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

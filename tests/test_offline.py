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
        test_provider_resolution, test_per_request_api_key, test_groq_json_cleaning,
        test_citation_renumbering, test_journal_citation_style, test_reference_formatting,
        test_prose_style_check,
        test_statistic_verification, test_ranking, test_render_blocks,
        test_display_item_placement, test_legacy_draft_fields,
        test_demo_and_index, test_web_server,
    ):
        print(f"\n# {fn.__name__}")
        fn()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'ALL PASS'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic prose-style check against journal writing conventions.

`verify.py` checks that the *numbers* in a draft are grounded. This checks that
the *prose* reads like a journal article rather than a magazine feature — the
conventions are specific enough to test, so we test them instead of hoping the
model followed the prompt:

- no second person, contractions, rhetorical questions or exclamations
- no booster/hype vocabulary ("clearly", "dramatically", "groundbreaking")
- no absolute claims of proof from observational evidence
- first person only in the reviewing frame journals actually use ("here we review")
- hedging present at roughly the density corpus studies report for research
  articles — about one hedge every two to three sentences
- sentences of a readable length, and not wall-to-wall nominalisation

Everything here is a regex over the draft's own text. Like `verify.py`, it is
deliberately not an LLM pass: a model asked "is this journal style?" will agree
with itself. `docs/journal-style.md` records where each convention comes from.

`cli.cmd_draft` runs this after `write_article` and, when it finds errors, sends
them back to the model once for a targeted revision.
"""

from __future__ import annotations

import re
import statistics

# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------

# Boosters and hype. Journals hedge claims to the evidence; these do the opposite,
# asserting confidence that a cited abstract cannot support.
_BOOSTERS = (
    "clearly", "obviously", "undoubtedly", "unquestionably", "certainly",
    "dramatically", "dramatic", "remarkable", "remarkably", "striking",
    "strikingly", "stunning", "staggering", "astonishing", "incredible",
    "revolutionary", "groundbreaking", "ground-breaking", "game-changing",
    "game-changer", "breakthrough", "unprecedented", "massive", "huge",
    "of course", "needless to say", "it goes without saying",
)

# Claims of proof. Even a randomized trial "shows" or "indicates"; almost nothing
# in an abstract-derived review "proves" anything.
_ABSOLUTES = (
    "proves", "proven", "proved that", "definitively", "conclusively",
    "beyond doubt", "without doubt", "categorically", "irrefutable",
)

# Hedges, from the standard epistemic-marker categories (modal, lexical, adverbial,
# adjectival, nominal) used in corpus studies of research articles.
_HEDGES = (
    "may", "might", "could", "appears", "appear", "appeared", "seems", "seem",
    "suggests", "suggest", "suggested", "indicates", "indicate", "indicated",
    "likely", "unlikely", "probably", "possibly", "perhaps", "presumably",
    "potentially", "apparently", "relatively", "largely", "broadly", "generally",
    "typically", "often", "commonly", "frequently", "consistent with",
    "is thought", "are thought", "reportedly", "estimated", "approximately",
    "tends to", "tend to", "in part", "partly", "to some extent", "plausible",
    "plausibly", "possible", "probable", "assumption", "possibility",
    "remains unclear", "remains unresolved", "not established", "uncertain",
    "cannot be", "could not be", "would be expected",
)

_CONTRACTIONS = (
    "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't",
    "can't", "cannot've", "won't", "wouldn't", "couldn't", "shouldn't",
    "hasn't", "haven't", "hadn't", "it's", "that's", "there's", "here's",
    "we're", "they're", "you're", "i'm", "let's", "we've", "they've",
    "we'll", "they'll", "you'll", "we'd", "they'd",
)

_WORDY = {
    "utilize": "use",
    "utilise": "use",
    "in order to": "to",
    "due to the fact that": "because",
    "a number of": "several",
    "at this point in time": "now",
    "in the event that": "if",
}

# The one first-person frame journals do use — Nature asks for "Here we show" or
# its equivalent. Anything else in the first person implies a human author.
_ALLOWED_FIRST_PERSON = re.compile(
    r"\b(?:here\s+)?we\s+(?:review|reviewed|consider|considered|summarize|summarise|"
    r"summarized|summarised|describe|described|argue|argued|focus|focused|focussed|"
    r"report|reported|show|showed|examine|examined|assess|assessed|discuss|discussed)\b",
    re.IGNORECASE,
)
_FIRST_PERSON = re.compile(r"\b(I|me|my|mine|we|us|our|ours)\b", re.IGNORECASE)
_SECOND_PERSON = re.compile(r"\b(you|your|yours|yourself)\b", re.IGNORECASE)

# Crude passive detector: "was reported", "are associated". Over-counts slightly,
# which is why it only ever produces a warning at a high ratio.
_PASSIVE = re.compile(
    r"\b(?:is|are|was|were|been|being|be)\s+(?:\w+ly\s+)?\w+(?:ed|en)\b", re.IGNORECASE
)
_NOMINALISATION = re.compile(r"\b\w{4,}(?:tion|sion|ment|ance|ence|ity|ism)s?\b", re.IGNORECASE)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")
_ABBREV = re.compile(r"\b(et al|e\.g|i\.e|cf|vs|Fig|Dr|approx|no)\.", re.IGNORECASE)

LONG_SENTENCE_WORDS = 45
MIN_HEDGES_PER_SENTENCE = 0.20   # ~1 hedge per 5 sentences; corpora report 1 per 2-3
MAX_NOMINALISATION_RATE = 0.11   # nominalised nouns as a share of all words
MAX_PASSIVE_RATIO = 0.55         # share of sentences containing a passive
MIN_SENTENCES_FOR_DENSITY = 12   # below this, density figures are noise
MIN_WORDS_FOR_DENSITY = 250


def _sentences(text: str) -> list[str]:
    protected = _ABBREV.sub(lambda m: m.group(0).replace(".", "\x00"), text)
    parts = _SENTENCE_SPLIT.split(protected)
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


def _strip_citations(text: str) -> str:
    return re.sub(r"\[\d+(?:\s*,\s*\d+)*\]", "", text)


def prose_blocks(article: dict) -> list[tuple[str, str]]:
    """(where, text) for every piece of model-written prose we hold to the style."""
    blocks: list[tuple[str, str]] = []
    summary = article.get("abstract") or article.get("standfirst") or ""
    if summary:
        blocks.append(("abstract", summary))
    for section in article.get("sections", []):
        heading = section.get("heading", "section")
        for para in section.get("paragraphs", []):
            blocks.append((heading, para))
    for point in article.get("key_points") or article.get("key_takeaways") or []:
        blocks.append(("key points", point))
    if article.get("evidence_note"):
        blocks.append(("evidence note", article["evidence_note"]))
    featured = article.get("featured_study") or {}
    for field in ("why", "method", "results"):
        if featured.get(field):
            blocks.append((f"featured study/{field}", featured[field]))
    return blocks


def _excerpt(text: str, match_start: int, width: int = 60) -> str:
    start = max(0, match_start - width // 2)
    snippet = text[start:start + width].strip()
    return f"…{snippet}…" if start else f"{snippet}…"


def _find(pattern: str, text: str) -> re.Match | None:
    return re.search(pattern, text, re.IGNORECASE)


def check_style(article: dict) -> dict:
    """Return {'issues': [...], 'stats': {...}}.

    Each issue is {'rule', 'severity', 'where', 'detail', 'excerpt'}. Severity is
    'error' for things no journal would print, 'warning' for matters of degree.
    """
    issues: list[dict] = []
    all_sentences: list[str] = []
    total_words = 0
    total_hedges = 0
    total_nominalisations = 0
    passive_sentences = 0

    def add(rule, severity, where, detail, excerpt=""):
        issues.append({"rule": rule, "severity": severity, "where": where,
                       "detail": detail, "excerpt": excerpt})

    for where, raw in prose_blocks(article):
        text = _strip_citations(raw)
        lower = text.lower()
        sentences = _sentences(text)
        all_sentences.extend(sentences)
        words = re.findall(r"[A-Za-z][\w'-]*", text)
        total_words += len(words)

        if "?" in text:
            add("rhetorical-question", "error", where,
                "Journal prose states; it does not ask the reader questions.",
                _excerpt(text, text.index("?")))
        if "!" in text:
            add("exclamation", "error", where, "Exclamation marks do not appear in journal prose.",
                _excerpt(text, text.index("!")))

        m = _SECOND_PERSON.search(text)
        if m:
            add("second-person", "error", where,
                f"Addresses the reader directly ({m.group(0)!r}).", _excerpt(text, m.start()))

        for contraction in _CONTRACTIONS:
            if re.search(rf"\b{re.escape(contraction)}\b", lower):
                add("contraction", "error", where,
                    f"Contraction {contraction!r}; journals write it out.",
                    _excerpt(text, lower.index(contraction)))
                break

        for booster in _BOOSTERS:
            m = _find(rf"\b{re.escape(booster)}\b", text)
            if m:
                add("booster", "error", where,
                    f"Hype/booster vocabulary ({booster!r}) asserts more confidence "
                    "than a cited abstract supports.", _excerpt(text, m.start()))
                break

        for absolute in _ABSOLUTES:
            m = _find(rf"\b{re.escape(absolute)}\b", text)
            if m:
                add("overclaim", "error", where,
                    f"Claim of proof ({absolute!r}); evidence indicates or supports, "
                    "it rarely proves.", _excerpt(text, m.start()))
                break

        # First person outside the reviewing frame implies a human author.
        for m in _FIRST_PERSON.finditer(text):
            window = text[max(0, m.start() - 8):m.end() + 30]
            if _ALLOWED_FIRST_PERSON.search(window):
                continue
            add("first-person", "error", where,
                f"First person ({m.group(0)!r}) outside the 'here we review' frame.",
                _excerpt(text, m.start()))
            break

        for phrase, better in _WORDY.items():
            if phrase in lower:
                add("wordiness", "warning", where,
                    f"{phrase!r} — prefer {better!r}.", _excerpt(text, lower.index(phrase)))
                break

        for sentence in sentences:
            sentence_words = re.findall(r"[A-Za-z][\w'-]*", sentence)
            if len(sentence_words) > LONG_SENTENCE_WORDS:
                add("long-sentence", "warning", where,
                    f"{len(sentence_words)}-word sentence; split it.", _excerpt(sentence, 0, 70))
            if _PASSIVE.search(sentence):
                passive_sentences += 1

        for hedge in _HEDGES:
            total_hedges += len(re.findall(rf"\b{re.escape(hedge)}\b", lower))
        total_nominalisations += len(_NOMINALISATION.findall(text))

    n_sentences = len(all_sentences)
    lengths = [len(re.findall(r"[A-Za-z][\w'-]*", s)) for s in all_sentences]
    stats = {
        "sentences": n_sentences,
        "words": total_words,
        "hedges": total_hedges,
        "hedges_per_sentence": round(total_hedges / n_sentences, 3) if n_sentences else 0.0,
        "mean_sentence_words": round(statistics.mean(lengths), 1) if lengths else 0.0,
        "nominalisation_rate": round(total_nominalisations / total_words, 3) if total_words else 0.0,
        "passive_ratio": round(passive_sentences / n_sentences, 3) if n_sentences else 0.0,
    }

    # Density checks need a reasonable amount of real prose before they mean
    # anything — a dozen four-word stubs carry no information about hedging.
    if n_sentences >= MIN_SENTENCES_FOR_DENSITY and total_words >= MIN_WORDS_FOR_DENSITY:
        if stats["hedges_per_sentence"] < MIN_HEDGES_PER_SENTENCE:
            add("under-hedged", "error", "whole article",
                f"{total_hedges} hedges across {n_sentences} sentences "
                f"({stats['hedges_per_sentence']} per sentence). Research articles hedge "
                "roughly once every two to three sentences; claims here are stated with "
                "more certainty than the evidence carries.")
        if stats["nominalisation_rate"] > MAX_NOMINALISATION_RATE:
            add("nominalisation", "warning", "whole article",
                f"{stats['nominalisation_rate']:.0%} of words are nominalised nouns; "
                "prefer verbs ('evaluated', not 'conducted an evaluation').")
        if stats["passive_ratio"] > MAX_PASSIVE_RATIO:
            add("passive-voice", "warning", "whole article",
                f"{stats['passive_ratio']:.0%} of sentences are passive; Nature and Science "
                "both ask for the active voice where it is available.")

    return {"issues": issues, "stats": stats}


def errors(report: dict) -> list[dict]:
    return [i for i in report["issues"] if i["severity"] == "error"]


def format_report(report: dict) -> str:
    """Human-readable summary for the CLI log."""
    stats = report["stats"]
    lines = [
        f"  {stats['sentences']} sentences, mean {stats['mean_sentence_words']} words; "
        f"{stats['hedges_per_sentence']} hedges/sentence; "
        f"{stats['passive_ratio']:.0%} passive; "
        f"{stats['nominalisation_rate']:.0%} nominalised"
    ]
    for issue in report["issues"]:
        mark = "!" if issue["severity"] == "error" else "-"
        lines.append(f"  {mark} [{issue['rule']}] {issue['where']}: {issue['detail']}")
        if issue["excerpt"]:
            lines.append(f"      {issue['excerpt']}")
    return "\n".join(lines)


def revision_brief(report: dict) -> str:
    """The instruction sent back to the model when the prose misses the house style."""
    problems = errors(report) or report["issues"]
    lines = ["The draft breaks these journal-prose conventions. Fix each one:"]
    for issue in problems:
        lines.append(f"- [{issue['where']}] {issue['detail']}")
        if issue["excerpt"]:
            lines.append(f"  Offending text: {issue['excerpt']}")
    lines.append(
        "Rewrite ONLY what is needed to fix these. Keep every citation marker exactly "
        "where it is, keep the section headings, and do not introduce new claims or "
        "numbers."
    )
    return "\n".join(lines)

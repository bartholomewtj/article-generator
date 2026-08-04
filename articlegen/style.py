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

import collections
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

# Substance floors.
#
# Every rule above this point is a prohibition — don't under-hedge, don't use
# boosters, don't claim proof. A model optimising only against prohibitions
# writes vague, hedged, contentless prose, because asserting nothing is the
# safest way to break no rule. A real draft came back at 803 words across four
# sections with exactly one number in it, having passed every check, hedging at
# 0.69/sentence — three times the floor — using four stock phrases.
#
# These pull the other way: they fail a draft for saying too little. They were
# calibrated against the curated sample in demo.py, which must keep passing.
MIN_BODY_WORDS = 900             # informational only; see the note at the check
MIN_SECTIONS = 5                 # the writer prompt asks for 5-7
MAX_HEDGE_SHARE = 0.40           # no single hedge may be this much of the total
MAX_OPENER_REPEATS = 2           # same three-word sentence opening, at most twice
REPEATED_PHRASE_WORDS = 8        # a shared run this long is recycled text
MIN_SENTENCES_FOR_VARIETY = 10   # below this, repetition counts are noise

# The abstract, the key points and the Introduction are three different jobs, and
# the commonest failure mode is writing them as three renderings of one paragraph
# — paraphrased closely enough that the 8-word `recycled-phrasing` rule misses it.
# Measured as the share of a block's 6-word runs that also occur in the abstract,
# the separation is wide: the curated sample in demo.py scores 0% (Introduction)
# and 2.4% (key points), while a real draft that read as pure repetition scored
# 39% and 23%. The threshold sits well clear of both.
ECHO_GRAM_WORDS = 6
MAX_ABSTRACT_ECHO = 0.12
MIN_GRAMS_FOR_ECHO = 25          # ~30 words; below this the ratio is noise

# A source cited only ever inside a bundle ("[1, 4]") has had nothing said about
# it individually. A bundle asserts that studies agree; it has to be earned by
# first reporting what each one found.
MAX_NEVER_SOLO_SHARE = 0.34
MIN_SOURCES_FOR_SOLO_CHECK = 4


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

    # Which hedges, not just how many. The density rule alone is satisfiable by
    # repeating one stock phrase, and that is exactly what happens.
    body_text = " ".join(_strip_citations(t) for _, t in prose_blocks(article)).lower()
    hedge_counts = {
        h: len(re.findall(rf"\b{re.escape(h)}\b", body_text)) for h in _HEDGES
    }
    hedge_counts = {h: n for h, n in hedge_counts.items() if n}
    top_hedge, top_hedge_n = max(hedge_counts.items(), key=lambda kv: kv[1], default=("", 0))

    stats = {
        "sentences": n_sentences,
        "words": total_words,
        "hedges": total_hedges,
        "distinct_hedges": len(hedge_counts),
        "commonest_hedge": top_hedge,
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

    # ---------------------------------------------------------------- substance
    # These fail a draft for saying too little, rather than for saying it wrongly.

    n_sections = len(article.get("sections") or [])
    if n_sections and n_sections < MIN_SECTIONS:
        add("too-few-sections", "error", "whole article",
            f"{n_sections} sections; a Review runs {MIN_SECTIONS}-7. Add sections that "
            "develop distinct aspects of the question rather than restating the same one.")

    # Warning, not error, and deliberately so. Calibrating against the curated
    # sample in demo.py showed length does not discriminate: the good sample runs
    # 773 words and the thin, repetitive draft that prompted these rules ran 803.
    # What separated them was hedge variety (8 distinct hedges vs one phrase at
    # 50%) and verbatim recycling. Failing a draft for brevity would reject the
    # known-good sample while passing the bad one, so length only informs.
    if total_words and total_words < MIN_BODY_WORDS:
        add("under-length", "warning", "whole article",
            f"{total_words} words of body prose, against the {MIN_BODY_WORDS}-1600 a Review "
            "typically carries. If this is thin rather than merely concise, the remedy is "
            "more evidence reported in more detail — specific findings, designs and "
            "populations from the sources — not more words about the same points.")

    if total_hedges and top_hedge_n / total_hedges > MAX_HEDGE_SHARE and total_hedges >= 4:
        add("hedge-monotony", "error", "whole article",
            f"'{top_hedge}' accounts for {top_hedge_n} of {total_hedges} hedges "
            f"({top_hedge_n / total_hedges:.0%}). Hedging should track how strong each "
            "piece of evidence actually is — 'in a single small trial', 'consistently "
            "across cohorts' — not repeat one stock phrase to meet a quota.")

    if n_sentences >= MIN_SENTENCES_FOR_VARIETY:
        openers = collections.Counter(
            " ".join(s.split()[:3]).lower().strip(".,;:") for s in all_sentences
        )
        for opener, count in openers.items():
            if count > MAX_OPENER_REPEATS and len(opener.split()) == 3:
                add("repeated-opener", "error", "whole article",
                    f"{count} sentences open '{opener}...'. Vary how sentences begin; "
                    "identical openings read as filler.", opener)
                break

        repeat = _repeated_phrase(all_sentences)
        if repeat:
            add("recycled-phrasing", "error", "whole article",
                f"The phrase '{repeat}' appears more than once verbatim. Each section "
                "should carry information the others do not; if a point has been made, "
                "develop it rather than restate it.", repeat)

    for where, share in _abstract_echoes(article):
        add("echoed-abstract", "error", where,
            f"{share:.0%} of this text repeats wording from the abstract. The abstract "
            "is the standalone summary; the key points carry specific findings and the "
            "Introduction sets up the question. Say something here the abstract does "
            "not.")

    never_solo, n_cited = _never_cited_alone(article)
    if never_solo:
        listed = ", ".join(f"[{n}]" for n in never_solo)
        add("bundled-citations", "error", "whole article",
            f"{len(never_solo)} of {n_cited} cited sources ({listed}) never appear on "
            "their own — only bundled with others behind a general claim, so the review "
            "never says what they individually did or found. Give each its own "
            "treatment: design, population, and result.")

    return {"issues": issues, "stats": stats}


def _grams(text: str, n: int = ECHO_GRAM_WORDS) -> list[str]:
    words = re.findall(r"[A-Za-z][\w']*", _strip_citations(text).lower())
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def _abstract_echoes(article: dict) -> list[tuple[str, float]]:
    """(where, overlap) for blocks that mostly re-word the abstract.

    Catches the close-paraphrase case that `_repeated_phrase` misses: the same
    paragraph rewritten as the key points and again as the Introduction.
    """
    abstract = article.get("abstract") or article.get("standfirst") or ""
    if not abstract:
        return []
    reference = set(_grams(abstract))
    if not reference:
        return []

    candidates: list[tuple[str, str]] = []
    points = article.get("key_points") or article.get("key_takeaways") or []
    if points:
        candidates.append(("key points", " ".join(points)))
    for section in article.get("sections") or []:
        if section.get("heading", "").strip().lower().startswith("introduction"):
            candidates.append(("Introduction", " ".join(section.get("paragraphs") or [])))

    flagged = []
    for where, text in candidates:
        grams = _grams(text)
        if len(grams) < MIN_GRAMS_FOR_ECHO:
            continue
        share = sum(1 for g in grams if g in reference) / len(grams)
        if share > MAX_ABSTRACT_ECHO:
            flagged.append((where, share))
    return flagged


def _never_cited_alone(article: dict) -> tuple[list[int], int]:
    """Cited sources that only ever appear inside a multi-source citation bundle."""
    text = " ".join(raw for _, raw in prose_blocks(article))
    markers = re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", text)
    if not markers:
        return [], 0

    cited: set[int] = set()
    solo: set[int] = set()
    for marker in markers:
        numbers = [int(n) for n in marker.split(",")]
        cited.update(numbers)
        if len(numbers) == 1:
            solo.add(numbers[0])

    if len(cited) < MIN_SOURCES_FOR_SOLO_CHECK:
        return [], len(cited)
    never_solo = sorted(cited - solo)
    if len(never_solo) / len(cited) <= MAX_NEVER_SOLO_SHARE:
        return [], len(cited)
    return never_solo, len(cited)


def _repeated_phrase(sentences: list[str]) -> str:
    """The longest run of words that appears verbatim more than once, if any.

    Catches a Conclusions section that restates an earlier one word for word —
    which reads as padding and which none of the register rules notice.
    """
    seen: dict[str, int] = {}
    for sentence in sentences:
        words = re.findall(r"[A-Za-z][\w'-]*", sentence.lower())
        for i in range(len(words) - REPEATED_PHRASE_WORDS + 1):
            phrase = " ".join(words[i:i + REPEATED_PHRASE_WORDS])
            seen[phrase] = seen.get(phrase, 0) + 1
    repeated = [p for p, n in seen.items() if n > 1]
    return max(repeated, key=len) if repeated else ""


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


# Failures that can only be fixed by adding grounded material, not by rewording.
SUBSTANCE_RULES = frozenset({
    "under-length", "too-few-sections", "recycled-phrasing",
    "hedge-monotony", "repeated-opener", "echoed-abstract", "bundled-citations",
})


def revision_brief(report: dict) -> str:
    """The instruction sent back to the model when the prose misses the house style."""
    problems = errors(report) or report["issues"]
    needs_substance = any(i["rule"] in SUBSTANCE_RULES for i in problems)

    lines = ["The draft breaks these journal-prose conventions. Fix each one:"]
    for issue in problems:
        lines.append(f"- [{issue['where']}] {issue['detail']}")
        if issue["excerpt"]:
            lines.append(f"  Offending text: {issue['excerpt']}")

    if needs_substance:
        # A register fix is a rewording; a thinness fix is not. Telling the model
        # "do not introduce new claims or numbers" here would forbid the only
        # thing that can work, so the instruction inverts — with the sources
        # supplied alongside, so the additions stay grounded.
        lines.append(
            "This draft is too thin or too repetitive, which rewording alone cannot fix. "
            "Go back to the SOURCES below and pull in specific material you left out: "
            "what each study actually did, in whom, and what it found. Report figures "
            "that appear in an abstract, attribute findings to their design and "
            "population, and say where studies disagree. Every section must carry "
            "something the others do not. Keep every existing citation marker attached "
            "to the claim it supports, and cite any newly used source by its SOURCE "
            "number. Do NOT state a number that appears in no abstract."
        )
    else:
        lines.append(
            "Rewrite ONLY what is needed to fix these. Keep every citation marker exactly "
            "where it is, keep the section headings, and do not introduce new claims or "
            "numbers."
        )
    return "\n".join(lines)

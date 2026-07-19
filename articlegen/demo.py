"""A built-in sample so `articlegen --demo` can render the design without any API calls.

The prose here is illustrative and the citations map to the sample sources below;
it exists to exercise the renderer, not as a real piece of journalism.
"""

from .sources import Paper

SAMPLE_PAPERS = [
    Paper(
        title="The memory function of sleep",
        abstract="Sleep consolidates newly encoded memories via hippocampal replay.",
        year=2010,
        authors=["Susanne Diekelmann", "Jan Born"],
        venue="Nature Reviews Neuroscience",
        citation_count=3200,
        doi="10.1038/nrn2762",
        source="demo",
    ),
    Paper(
        title="Sleep-dependent memory consolidation",
        abstract="A review of behavioral and physiological evidence linking sleep to memory.",
        year=2005,
        authors=["Robert Stickgold"],
        venue="Nature",
        citation_count=2100,
        doi="10.1038/nature04286",
        source="demo",
    ),
    Paper(
        title="Sleep drives metabolite clearance from the adult brain",
        abstract="During sleep the glymphatic system clears metabolic waste including amyloid-beta.",
        year=2013,
        authors=["Lulu Xie", "Hongyi Kang", "Qiwu Xu", "et al."],
        venue="Science",
        citation_count=2800,
        doi="10.1126/science.1241224",
        source="demo",
    ),
    Paper(
        title="Interindividual differences in the effects of sleep deprivation",
        abstract="People differ reliably and heritably in vulnerability to sleep loss.",
        year=2004,
        authors=["Hans Van Dongen", "David Dinges"],
        venue="Sleep",
        citation_count=900,
        doi="10.1093/sleep/27.3.423",
        source="demo",
    ),
]

SAMPLE_ARTICLE = {
    "title": "What Your Brain Does While You Sleep",
    "standfirst": (
        "Far from switching off, the sleeping brain runs a nightly maintenance shift — "
        "filing memories and hosing out its own waste."
    ),
    "evidence_note": (
        "All four cited sources study sleep and the brain directly; the memory and "
        "clearance findings are well replicated, though the clearance work [3] is "
        "largely from animal models."
    ),
    "featured_study": {
        "source_index": 3,
        "why": "The first direct demonstration that sleep clears brain waste.",
        "method": "Two-photon imaging and tracer injection in sleeping vs. waking mice.",
        "results": "Interstitial space expanded ~60% in sleep, roughly doubling clearance of amyloid-beta.",
    },
    "sections": [
        {
            "heading": "The night shift",
            "paragraphs": [
                "For most of history sleep looked like a nuisance — hours of nothing, "
                "a gap in the day. The last two decades of neuroscience have inverted "
                "that picture. The sleeping brain is not idle; it is busy doing work it "
                "cannot do while you are awake [1].",
                "Two of those jobs stand out: locking in what you learned during the "
                "day, and clearing away the molecular debris that accumulates while you "
                "think [1, 3].",
            ],
            "pull_quote": "The sleeping brain is not idle; it is busy.",
        },
        {
            "heading": "Filing the day away",
            "paragraphs": [
                "While you sleep, the hippocampus appears to replay the day's "
                "experiences, gradually handing them off to the cortex for long-term "
                "storage [1]. Behavioral studies back this up: people who sleep after "
                "learning a task remember it markedly better than those kept awake [2].",
            ],
            "pull_quote": None,
        },
        {
            "heading": "Taking out the trash",
            "paragraphs": [
                "Memory is only half the story. During sleep the brain's glymphatic "
                "system opens up and flushes out metabolic waste — including amyloid-"
                "beta, the protein implicated in Alzheimer's disease [3]. It is a kind "
                "of nightly plumbing that daytime brains are too busy to run.",
            ],
            "pull_quote": None,
        },
        {
            "heading": "Why some of us fare worse",
            "paragraphs": [
                "Not everyone pays the same price for a bad night. People differ "
                "reliably — and heritably — in how badly sleep loss degrades their "
                "attention and judgment [4]. Your friend who swears they are fine on "
                "five hours may, occasionally, be telling the truth.",
            ],
            "pull_quote": None,
        },
    ],
    "key_takeaways": [
        "Sleep actively consolidates memories rather than passively resting the brain [1, 2].",
        "The glymphatic system clears brain waste, including amyloid-beta, during sleep [3].",
        "Vulnerability to sleep deprivation varies between people and is partly genetic [4].",
    ],
    "references": [1, 2, 3, 4],
}

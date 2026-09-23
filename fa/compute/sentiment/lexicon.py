"""Headline sentiment: VADER augmented with a financial lexicon (VADER alone mis-scores 'beat', 'miss', 'downgrade', 'guidance cut').

Scores are in [-1, 1]. Financial terms override VADER's general-English valence.
"""
from __future__ import annotations

import re
from functools import lru_cache

FIN_LEXICON: dict[str, float] = {
    # positive
    "beat": 2.0, "beats": 2.0, "tops": 1.5, "surge": 2.0, "surges": 2.0, "soar": 2.2, "soars": 2.2, "rally": 1.8, "rallies": 1.8, "record": 1.2,
    "upgrade": 2.2, "upgrades": 2.2, "upgraded": 2.2, "outperform": 1.8, "overweight": 1.5, "raise": 1.2, "raises": 1.5, "raised": 1.5, "hike": 0.8,
    "buyback": 1.2, "dividend": 0.6, "growth": 0.8, "profit": 1.0, "profitable": 1.2, "strong": 1.2, "bullish": 2.0, "breakout": 1.5,
    "expands": 0.8, "wins": 1.2, "contract": 0.4, "approval": 1.5, "approved": 1.5, "partnership": 0.8, "guidance raised": 2.5, "above expectations": 2.0,
    "accelerating": 1.2, "momentum": 0.6, "rebound": 1.2, "recovers": 1.0, "all-time high": 1.5, "buy": 1.0, "undervalued": 1.2,
    # negative
    "miss": -2.0, "misses": -2.0, "missed": -2.0, "plunge": -2.5, "plunges": -2.5, "tumble": -2.0, "tumbles": -2.0, "slump": -1.8, "slides": -1.5,
    "sinks": -2.0, "drop": -1.2, "drops": -1.2, "falls": -1.2, "downgrade": -2.2, "downgrades": -2.2, "downgraded": -2.2, "underperform": -1.8,
    "underweight": -1.5, "cut": -1.2, "cuts": -1.5, "lowers": -1.5, "lowered": -1.5, "guidance cut": -2.5, "below expectations": -2.0, "warning": -1.8,
    "warns": -1.8, "lawsuit": -1.5, "investigation": -1.5, "probe": -1.5, "recall": -1.8, "layoffs": -1.2, "bankruptcy": -3.0, "default": -2.5,
    "dilution": -1.5, "offering": -0.8, "secondary": -0.6, "short seller": -1.5, "fraud": -3.0, "restatement": -2.0, "delisting": -2.5,
    "bearish": -2.0, "selloff": -2.0, "sell-off": -2.0, "crash": -3.0, "weak": -1.2, "decline": -1.2, "declines": -1.2, "loss": -1.2, "losses": -1.4,
    "overvalued": -1.2, "sell": -1.0, "halted": -1.5, "delay": -1.0, "delays": -1.0, "shortfall": -1.8, "antitrust": -1.2, "tariff": -0.8, "tariffs": -0.8,
}


@lru_cache(maxsize=1)
def _analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    a = SentimentIntensityAnalyzer()
    a.lexicon.update({k: v for k, v in FIN_LEXICON.items() if " " not in k})
    return a


_PHRASES = {k: v for k, v in FIN_LEXICON.items() if " " in k}


def score(text: str | None) -> float | None:
    if not text:
        return None
    t = re.sub(r"\s+", " ", str(text)).strip()
    if not t:
        return None
    base = _analyzer().polarity_scores(t)["compound"]
    low = t.lower()
    bonus = sum(v for k, v in _PHRASES.items() if k in low)
    if bonus:
        base = max(-1.0, min(1.0, base + bonus / 4.0))
    return float(base)

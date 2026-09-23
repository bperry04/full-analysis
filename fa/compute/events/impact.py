"""Label events, news and narrative items with their likely effect on THIS stock.

Macro releases have no fixed sign for a stock: a hot CPI is bad for a long-duration growth name, mixed for a bank,
nearly irrelevant for a utility. We combine (a) what a strong/weak print does to rates, the dollar, oil and risk appetite
with (b) this name's measured sensitivities (rolling betas to TLT/UUP/USO/HYG/SPY) and its profile (bank, growth, …).
Output is always conditional — "if hotter than consensus: negative" — because the print is unknown in advance.
"""
from __future__ import annotations

import math
import re
from typing import Any

# event pattern -> (channel effects when the print is STRONG/above consensus). Channels: rates, growth, usd, oil, risk
# +1 = rises. A strong inflation print pushes rates up and risk appetite down; strong growth lifts growth & rates.
MACRO_RULES: list[tuple[str, dict[str, int], str]] = [
    (r"cpi|consumer price|pce|ppi|producer price|inflation", {"rates": 1, "risk": -1, "usd": 1}, "inflation"),
    (r"jobless|unemployment rate|claims|layoffs|challenger", {"rates": -0.6, "growth": -0.8, "usd": -0.3}, "labor_inverse"),   # higher number = weaker labor
    (r"nonfarm|non-farm|payroll|adp|jolts|employment|average hourly", {"rates": 0.6, "growth": 0.8, "usd": 0.3}, "labor"),
    (r"gdp|ism|pmi|industrial production|durable|retail sales|factory orders|manufacturing", {"growth": 1, "rates": 1}, "activity"),
    (r"fomc|fed interest rate|federal funds|rate decision|minutes", {"rates": 1, "risk": -1, "usd": 1}, "fed"),
    (r"consumer confidence|michigan|sentiment", {"growth": 1, "risk": 1}, "sentiment"),
    (r"housing|home sales|building permits|mortgage", {"growth": 1, "rates": 1}, "housing"),
    (r"crude|oil inventor|eia|opec", {"oil": -1}, "oil"),                # a big inventory BUILD (strong print) pushes oil down
    (r"trade balance|exports|imports|tariff", {"usd": 1, "growth": -1}, "trade"),
    (r"auction|bond|treasury", {"rates": -1}, "auction"),               # a STRONG auction (high bid-to-cover) pushes yields down
    (r"speaks|speech|testif|remarks", {"rates": 0}, "fedspeak"),
]


def _sens(sens: dict | None, sym: str, scale: float = 3.0) -> float:
    """Regression beta to an ETF squashed to (-1, 1): a raw β of -3 to TLT on a high-vol name would otherwise swamp every rule."""
    try:
        b = float(((sens or {}).get("univariate") or {}).get(sym, {}).get("beta") or 0.0)
        return math.tanh(b / scale)
    except (TypeError, ValueError):
        return 0.0


def stock_channels(sensitivity: dict | None, profile_tags: list[str] | None, beta_mkt: float | None) -> dict[str, float]:
    """How a +1 move in each channel maps to this stock's return (sign & rough magnitude)."""
    tags = set(profile_tags or [])
    b_tlt = _sens(sensitivity, "TLT")             # >0: likes falling yields (long-duration growth)
    b_usd = _sens(sensitivity, "UUP")
    b_oil = _sens(sensitivity, "USO")
    b_hyg = _sens(sensitivity, "HYG")
    b_spy = beta_mkt if beta_mkt is not None else 1.0
    rates = -b_tlt                                   # rates up = bond prices down
    if "bank" in tags or "insurer" in tags:
        rates += 0.4                                  # banks earn more on higher rates (NII) — overrides the duration effect
    if "high_growth" in tags or "cash_burning" in tags:
        rates -= 0.3                                  # long-duration cash flows
    if "utility" in tags or "reit" in tags:
        rates -= 0.3
    growth = 0.3 + 0.3 * max(b_spy - 1, 0)           # cyclicals / high beta benefit more from growth
    if "bank" in tags:
        growth += 0.2
    risk = math.tanh(b_spy / 2) if b_spy else 0.5
    return {"rates": rates, "growth": growth, "usd": b_usd, "oil": b_oil, "risk": risk, "credit": b_hyg}


def macro_event_impact(label: str, channels: dict[str, float], importance: int) -> dict[str, Any] | None:
    rule = next((r for r in MACRO_RULES if re.search(r[0], label, flags=re.I)), None)
    if rule is None:
        return None
    _, effects, kind = rule
    score = sum(w * channels.get(ch, 0.0) for ch, w in effects.items())       # effect on the stock if the print is STRONG
    mag = abs(score) * (importance / 5)
    if mag < 0.08:
        verdict_strong, verdict_weak = "mostly neutral", "mostly neutral"
    else:
        verdict_strong = "negative" if score < 0 else "positive"
        verdict_weak = "positive" if score < 0 else "negative"
    drivers = [f"{ch} {'↑' if w > 0 else '↓'} × stock β {channels.get(ch, 0.0):+.2f}" for ch, w in effects.items() if w]
    why = {
        "inflation": "hot inflation → higher rates, weaker risk appetite",
        "labor": "strong jobs → higher rates but firmer growth",
        "labor_inverse": "more claims / higher unemployment → weaker labor → lower rates, softer growth",
        "activity": "strong activity → firmer growth, somewhat higher rates",
        "fed": "hawkish outcome → higher rates, lower risk appetite",
        "sentiment": "confident consumers → growth and risk appetite",
        "housing": "strong housing → growth, rate pressure",
        "oil": "large inventory build → lower oil",
        "trade": "wider deficit / tariffs → stronger dollar, softer growth",
        "auction": "strong demand at auction → lower yields",
        "fedspeak": "tone-dependent; usually low impact",
    }[kind]
    return {"kind": kind, "if_strong": verdict_strong, "if_weak": verdict_weak, "magnitude": round(min(mag, 1.0), 2), "why": why,
            "channels": drivers, "note": "conditional on the print vs consensus; the outcome is unknown in advance", "strong_means": "above consensus", "weak_means": "below consensus"}


def company_event_impact(ev: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any] | None:
    t = ev.get("type")
    if t == "earnings":
        mv = ctx.get("implied_move") or ctx.get("hist_move")
        return {"kind": "earnings", "if_strong": "positive", "if_weak": "negative", "magnitude": round(min((mv or 0.05) * 5, 1.0), 2),
                "why": f"binary event; options imply ±{(ctx.get('implied_move') or 0) * 100:.1f}% and history averages ±{(ctx.get('hist_move') or 0) * 100:.1f}%" if ctx.get("implied_move") or ctx.get("hist_move") else "binary event",
                "channels": ["EPS/revenue vs consensus", "guidance", "post-earnings drift"], "note": "beat + raised guidance tends to drift higher for weeks (PEAD)"}
    if t == "ex_dividend":
        return {"kind": "dividend", "if_strong": "mostly neutral", "if_weak": "mostly neutral", "magnitude": 0.1, "why": "price opens lower by the dividend; no signal", "channels": [], "note": ""}
    if t == "opex":
        mp = ctx.get("max_pain")
        return {"kind": "opex", "if_strong": "mostly neutral", "if_weak": "mostly neutral", "magnitude": 0.2, "why": f"dealer hedging can pin price near max pain{f' (${mp:.0f})' if mp else ''} into expiry; volatility often expands after",
                "channels": ["gamma", "max pain"], "note": ""}
    if t in ("10-K due", "10-Q due"):
        return {"kind": "filing", "if_strong": "mostly neutral", "if_weak": "mostly neutral", "magnitude": 0.1, "why": "filing itself is not a catalyst unless it contains new disclosures", "channels": [], "note": ""}
    if t == "fomc":
        return None          # handled by the macro rule
    return None


NARRATIVE_IMPACT = {
    "m&a": ("depends on price paid; acquirer usually dips, target jumps", "mixed"), "capacity": ("investment ahead of demand — positive if demand holds, negative if it does not", "mixed"),
    "strategy": ("execution risk vs. new opportunity", "mixed"), "capital_return": ("buybacks/dividends support the price", "positive"),
    "demand": ("backlog and orders are the clearest revenue signal", "positive"), "product": ("new products expand the opportunity set", "positive"),
    "contract": ("new revenue visibility", "positive"), "guidance": ("guidance moves the stock more than the quarter itself", "mixed"),
    "financing": ("dilution / new debt is usually negative", "negative"), "legal": ("legal and regulatory overhangs compress multiples", "negative"),
    "management": ("leadership change is negative when abrupt, positive when it fixes a problem", "mixed"), "macro": ("policy exposure", "mixed"),
    "earnings": ("results vs expectations", "mixed"), "analyst": ("rating changes move the stock for days", "mixed"), "stock_move": ("price action already happened", "mixed"), "other": ("", "mixed"),
}


def narrative_impact(item: dict[str, Any]) -> dict[str, Any]:
    why, default = NARRATIVE_IMPACT.get(item.get("kind", "other"), ("", "mixed"))
    s = item.get("sentiment")
    if s is not None and abs(s) >= 0.25:
        verdict = "likely positive" if s > 0 else "likely negative"
    elif default == "positive":
        verdict = "likely positive"
    elif default == "negative":
        verdict = "likely negative"
    else:
        verdict = "mixed / depends"
    return {"verdict": verdict, "why": why}

"""Qualitative drivers — what the company is actually doing — assembled from news clusters, 8-K material-event
filings, segment / capital-allocation facts and the catalyst calendar, and sorted into the horizon they bear on.

These are NOT scored (news sentiment already is); they are context shown next to the quantitative drivers, each with
its source link so the claim can be checked.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

# kind -> (regex on headline, default horizon, label)
KINDS: list[tuple[str, str, str, str]] = [
    ("m&a", r"\b(acqui\w*|merger|takeover|buyout|to buy\b|agrees to buy|divest\w*|spin-?off|sells? (its|the) .* (unit|division|business))", "long", "M&A / portfolio"),
    ("capacity", r"\b(factory|fab|plant|facility|data cent(er|re)s?|capacity|expansion|breaks ground|invest(s|ing)? \$|capex|new campus|hiring)", "long", "Capacity & investment"),
    ("strategy", r"\b(strategy|roadmap|long-?term|pivot|restructur\w*|transformation|reorganiz\w*|exit(s|ing)? (the )?\w+ (market|business))", "long", "Strategy"),
    ("capital_return", r"\b(buyback|repurchase|dividend|special dividend|capital return)", "long", "Capital return"),
    ("demand", r"\b(backlog|bookings|demand|order book|pipeline|sold out|shortage|orders? (surge|jump|grow))", "medium", "Demand & backlog"),
    ("product", r"\b(launch\w*|unveil\w*|introduc\w*|debut\w*|new (product|model|chip|service|platform|version)|rollout|ships?|generation)", "medium", "Product"),
    ("contract", r"\b(contract|order|partnership|agreement|collaborat\w*|wins?|selected by|supply deal|customer|deploy\w*|multi-?year)", "medium", "Contracts & partnerships"),
    ("guidance", r"\b(guidance|outlook|forecast|raises|cuts|lowers|expects|sees|targets? \d)", "medium", "Guidance"),
    ("financing", r"\b(offering|convertible|notes offering|raises \$|debt|loan|credit facility|dilution|shelf|at-the-market)", "medium", "Financing / dilution"),
    ("legal", r"\b(lawsuit|sued|probe|investigation|antitrust|regulator\w*|fine[sd]?|settlement|recall|fda|sec charges|doj|ftc|subpoena|delist\w*|short seller|auditor)", "medium", "Legal / regulatory"),
    ("management", r"\b(ceo|cfo|coo|cto|chief \w+ officer|executive|board|resign\w*|appoint\w*|steps down|names .* as|hires|departure)", "medium", "Management"),
    ("macro", r"\b(tariff\w*|china|export (control|ban|curb)|sanction\w*|trade war|supply chain|rates?|fed\b)", "medium", "Macro / policy exposure"),
    ("earnings", r"\b(earnings|quarter\w*|results|revenue|eps|beat\w*|miss\w*|reports? q[1-4]|fiscal)", "short", "Earnings"),
    ("analyst", r"\b(upgrade\w*|downgrade\w*|price target|initiat\w* (coverage|at)|overweight|underweight|rating to|reiterat\w*)", "short", "Analyst actions"),
    ("stock_move", r"\b(shares? (jump|surge|soar|plunge|tumble|fall|rise|drop|rally|slide)\w*|stock (jumps|surges|falls|drops|soars|plunges)|record high|52-week)", "short", "Price action"),
]

ITEM_8K = {
    "1.01": ("m&a", "long", "Entry into a material definitive agreement"), "1.02": ("contract", "medium", "Termination of a material agreement"),
    "1.03": ("legal", "medium", "Bankruptcy or receivership"), "2.01": ("m&a", "long", "Completion of acquisition or disposition"),
    "2.02": ("earnings", "short", "Results of operations (earnings release)"), "2.03": ("financing", "medium", "New direct financial obligation (debt)"),
    "2.04": ("financing", "medium", "Triggering event accelerating an obligation"), "2.05": ("strategy", "long", "Exit or disposal activities / restructuring"),
    "2.06": ("strategy", "long", "Material impairment"), "3.01": ("legal", "medium", "Delisting notice / listing standard"),
    "3.02": ("financing", "medium", "Unregistered sale of equity (dilution)"), "3.03": ("financing", "medium", "Modification of shareholder rights"),
    "4.01": ("legal", "medium", "Change in auditor"), "4.02": ("legal", "medium", "Non-reliance on prior financials (restatement)"),
    "5.01": ("management", "long", "Change in control"), "5.02": ("management", "medium", "Officer / director departure or appointment"),
    "5.03": ("management", "medium", "Bylaw / fiscal-year change"), "5.07": ("management", "medium", "Shareholder vote results"),
    "7.01": ("guidance", "medium", "Regulation FD disclosure"), "8.01": ("strategy", "medium", "Other material event"),
}
IMPORTANT_ITEMS = {"1.01", "1.03", "2.01", "2.03", "2.05", "2.06", "3.01", "3.02", "4.01", "4.02", "5.01", "5.02"}


NOISE = re.compile(r"trending stock|facts to know|should you buy|best stocks|stocks to (watch|buy)|top \d+|investment ideas|highlights:|"
                   r"\bvs\.?\b.*\bstock\b|here's why|what you need to know|motley fool|zacks|is it too late|bull case|bear case|could (soar|double)", re.I)


def classify(title: str, summary: str = "") -> tuple[str, str, str]:
    text = f"{title} {summary or ''}".lower()
    for kind, rx, horizon, label in KINDS:
        if re.search(rx, text):
            return kind, horizon, label
    return "other", "medium", "Company news"


def _ts(x: Any) -> datetime | None:
    try:
        t = pd.Timestamp(x)
        if pd.isna(t):
            return None
        return (t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")).to_pydatetime()
    except Exception:
        return None


def build(symbol: str, name: str | None, news_items: pd.DataFrame | None, filings: pd.DataFrame | None, segments: dict | None,
          metrics: dict | None, events: dict | None, analysts: dict | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []

    # ---- news clusters (one per story), last 60 days
    if news_items is not None and not news_items.empty:
        for r in news_items.to_dict("records"):
            ts = _ts(r.get("published"))
            if ts is None or (now - ts).days > 60:
                continue
            title = str(r.get("title", ""))
            if NOISE.search(title):
                continue                    # listicles / opinion churn are not "what the company is doing"
            kind, horizon, label = classify(title, str(r.get("summary", "") or ""))
            age_d = (now - ts).total_seconds() / 86400
            weight = float(r.get("weight") or 0.5)
            breadth = float(np.log1p(float(r.get("cluster_size") or 1)))
            imp = weight * (1 + breadth) * (1.0 if age_d <= 7 else 0.7 if age_d <= 30 else 0.4)
            if kind == "other":
                imp *= 0.5                  # specific, classifiable events outrank generic coverage
            if kind in ("stock_move",) and age_d > 3:
                continue
            if kind == "earnings" and age_d > 10:
                horizon = "medium"
            items.append({"kind": kind, "label": label, "horizon": horizon, "title": str(r.get("title", ""))[:160], "detail": None,
                          "date": ts.date().isoformat(), "source": str(r.get("publisher") or r.get("source") or "news"), "url": r.get("url"),
                          "sentiment": float(r["sentiment"]) if r.get("sentiment") is not None and not pd.isna(r.get("sentiment")) else None,
                          "importance": float(imp), "origin": "news"})

    # ---- 8-K material events, last 180 days
    if filings is not None and not filings.empty:
        f = filings[filings["form"].astype(str).str.startswith("8-K")]
        for r in f.to_dict("records"):
            d = _ts(r.get("filed"))
            if d is None or (now - d).days > 180:
                continue
            codes = [c.strip() for c in str(r.get("items") or "").split(",") if c.strip() and c.strip() != "9.01"]
            if not codes:
                continue
            for code in codes:
                kind, horizon, label = ITEM_8K.get(code, ("strategy", "medium", f"8-K item {code}"))
                if code == "2.02" and (now - d).days > 14:
                    continue                    # routine earnings 8-Ks age out fast
                if code in ("7.01",) and (now - d).days > 30:
                    continue
                imp = 1.6 if code in IMPORTANT_ITEMS else 0.9
                imp *= 1.0 if (now - d).days <= 30 else 0.7
                items.append({"kind": kind, "label": label, "horizon": horizon, "title": f"8-K · {label}", "detail": f"filed {d.date().isoformat()} (item {code})",
                              "date": d.date().isoformat(), "source": "SEC EDGAR", "url": r.get("url"), "sentiment": None, "importance": imp, "origin": "filing"})

    # ---- what the numbers say the company is doing
    m = metrics or {}
    def mv(k):
        x = (m.get(k) or {}).get("value") if isinstance(m.get(k), dict) else getattr(m.get(k), "value", None)
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else x
    capex_da, capex_pct, rnd_pct = mv("capex_to_da"), mv("capex_pct_rev"), mv("rnd_pct_rev")
    if capex_da is not None and capex_da > 1.3:
        items.append(_fact("capacity", "long", "Investing ahead of depreciation", f"capex is {capex_da:.1f}x D&A ({capex_pct:.1%} of revenue) — the business is expanding its asset base", 1.2))
    elif capex_da is not None and capex_da < 0.7:
        items.append(_fact("capacity", "long", "Under-investing vs depreciation", f"capex is only {capex_da:.1f}x D&A — harvesting the asset base", 1.0))
    if rnd_pct is not None and rnd_pct > 0.12:
        items.append(_fact("strategy", "long", "R&D-heavy", f"R&D is {rnd_pct:.1%} of revenue", 0.9))
    sy, dil, bb = mv("shareholder_yield"), mv("share_count_change_1y"), mv("buyback_yield")
    if bb is not None and bb > 0.02:
        items.append(_fact("capital_return", "long", "Returning capital via buybacks", f"buybacks {bb:.1%} of market cap; diluted share count {dil:+.1%} YoY" if dil is not None else f"buybacks {bb:.1%} of market cap", 1.1))
    if dil is not None and dil > 0.03:
        items.append(_fact("financing", "medium", "Diluting shareholders", f"diluted share count {dil:+.1%} YoY", 1.2, sentiment=-0.5))
    acc, gq = mv("revenue_acceleration"), mv("revenue_growth_yoy_q")
    if gq is not None:
        items.append(_fact("earnings", "medium", f"Revenue {'accelerating' if (acc or 0) > 0 else 'decelerating'}", f"latest quarter {gq:+.1%} YoY" + (f", growth {'up' if acc > 0 else 'down'} {abs(acc):.1%} vs a year ago" if acc is not None else ""), 1.0, sentiment=0.4 if (acc or 0) > 0 else -0.3))
    if segments and segments.get("available"):
        for b in list(segments.get("breakdowns", {}).values())[:2]:
            mem = [x for x in b["members"] if x.get("yoy") is not None]
            if mem:
                best = max(mem, key=lambda x: x["yoy"]); worst = min(mem, key=lambda x: x["yoy"])
                items.append(_fact("strategy", "long", f"Fastest-growing {b['kind']} line: {best['member']}", f"{best['yoy']:+.0%} YoY, {best['share']:.0%} of revenue; weakest {worst['member']} {worst['yoy']:+.0%}", 1.1))
        if segments.get("top_product_share") and segments["top_product_share"] > 0.5:
            items.append(_fact("strategy", "long", f"Concentrated on {segments.get('top_product')}", f"{segments['top_product_share']:.0%} of revenue from one line", 0.9, sentiment=-0.2))

    # ---- catalysts (short) and analyst posture (medium)
    if events:
        d = events.get("days_to_earnings")
        if d is not None and d <= 45:
            items.append(_fact("earnings", "short", f"Earnings in {d} days", f"{events.get('next_earnings')}", 1.5))
        for e in (events.get("high_impact_next_14d") or [])[:3]:
            items.append(_fact("macro", "short", e["label"][:60], f"{e['date']} (importance {e['importance']})", 0.8))
    if analysts:
        ra = analysts.get("recent_actions") or {}
        if (ra.get("upgrades", 0) + ra.get("downgrades", 0)) >= 2:
            items.append(_fact("analyst", "medium", f"{ra.get('upgrades', 0)} upgrades / {ra.get('downgrades', 0)} downgrades (90d)", "sell-side is repositioning", 1.0, sentiment=0.5 if ra.get("upgrades", 0) > ra.get("downgrades", 0) else -0.5))

    # ---- rank, dedupe near-identical titles, split by horizon
    seen: set[str] = set()
    out: dict[str, list] = {"long": [], "medium": [], "short": []}
    for it in sorted(items, key=lambda x: -x["importance"]):
        key = re.sub(r"\W+", " ", it["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        out[it["horizon"]].append(it)
    themes: dict[str, int] = {}
    for it in items:
        themes[it["label"]] = themes.get(it["label"], 0) + 1
    return {"long": out["long"][:12], "medium": out["medium"][:14], "short": out["short"][:12], "themes": dict(sorted(themes.items(), key=lambda kv: -kv[1])),
            "n_items": len(items), "note": "Qualitative context from news clusters, 8-K filings, segment/capital-allocation facts and catalysts. Not scored — the quantitative factors are."}


def _fact(kind: str, horizon: str, title: str, detail: str, imp: float, sentiment: float | None = None) -> dict[str, Any]:
    label = next((l for k, _, _, l in KINDS if k == kind), kind)
    return {"kind": kind, "label": label, "horizon": horizon, "title": title, "detail": detail, "date": date.today().isoformat(), "source": "derived from filings",
            "url": None, "sentiment": sentiment, "importance": imp, "origin": "fundamentals"}

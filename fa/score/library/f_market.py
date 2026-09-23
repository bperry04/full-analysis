"""Macro, market-context, sentiment and event factors."""
from __future__ import annotations

from fa.score.factors import InputRef, bounded, factor, mk, scaled

L, M, S = "long", "medium", "short"


@factor("macro.risk_appetite", "Market risk appetite", "macro", {L: 0.5, M: 1.0, S: 1.0})
def risk_app(ctx):
    v = ctx.s("market", "risk_appetite", "score")
    return None if v is None else mk("", "", "", v, bounded(v, -1, 1), unit="score", narrative=f"{ctx.s('market','risk_appetite','label')} ({ctx.s('market','risk_appetite','votes')} signals)", inputs=[InputRef("risk_appetite", v, "", ctx.p("market"))])


@factor("macro.index_trend", "S&P 500 trend", "macro", {L: 0.6, M: 1.0, S: 0.8})
def idx(ctx):
    a50, a200 = ctx.s("market", "indices", "SPY", "above_50d"), ctx.s("market", "indices", "SPY", "above_200d")
    if a50 is None:
        return None
    v = (0.5 if a50 else -0.5) + (0.5 if a200 else -0.5)
    return mk("", "", "", v, v, unit="score", narrative=f"SPY {'above' if a50 else 'below'} 50d, {'above' if a200 else 'below'} 200d", inputs=[InputRef("spy_above_50d", a50, "", ctx.p("market")), InputRef("spy_above_200d", a200, "", ctx.p("market"))])


@factor("macro.sector_trend", "Sector ETF relative strength (3m)", "macro", {L: 0.6, M: 1.0, S: 0.6})
def sector(ctx):
    v = ctx.s("market", "subject_sector", "rs_3m_vs_spy")
    return None if v is None else mk("", "", "", v, scaled(v, 0.06), unit="pct", narrative=f"{ctx.s('market','subject_sector','name')} vs SPY {v:+.1%} (3m)", inputs=[InputRef("sector_rs_3m", v, "pct", ctx.p("market"))])


@factor("macro.vix", "VIX level", "macro", {L: 0.3, M: 0.8, S: 1.0})
def vix(ctx):
    v = ctx.s("market", "vix", "level")
    return None if v is None else mk("", "", "", v, bounded(v, 32, 12), unit="", narrative=f"VIX {v:.1f} ({ctx.s('market','vix','regime')}, {ctx.s('market','vix','percentile_1y'):.0%} pct of 1y)", inputs=[InputRef("vix", v, "", ctx.p("market"))])


@factor("macro.vix_term", "VIX term structure", "macro", {L: 0.2, M: 0.6, S: 1.0})
def vix_term(ctx):
    r = ctx.s("market", "vix_term", "ratio")
    return None if r is None else mk("", "", "", r, scaled(1 - r, 0.08), unit="x", narrative=f"VIX/VIX3M {r:.2f} ({ctx.s('market','vix_term','structure')})", inputs=[InputRef("vix_vix3m", r, "", ctx.p("market"))])


@factor("macro.credit", "Credit spreads trend (HYG/LQD)", "macro", {L: 0.6, M: 1.0, S: 0.6})
def credit(ctx):
    v = ctx.s("market", "credit", "ratio_chg_1m")
    return None if v is None else mk("", "", "", v, scaled(v, 0.015), unit="pct", narrative=f"high-yield vs IG ratio {v:+.1%} over 1m", inputs=[InputRef("hyg_lqd_chg_1m", v, "pct", ctx.p("market"))])


@factor("macro.yield_curve", "Yield curve (10y − 3m)", "macro", {L: 1.0, M: 0.6, S: 0.2})
def curve(ctx):
    v = ctx.s("market", "rates", "spread_10y_3m")
    return None if v is None else mk("", "", "", v, bounded(v, -1.0, 1.5), unit="", narrative=f"10y−3m {v:+.2f} pts ({'inverted' if v < 0 else 'normal'})", inputs=[InputRef("spread_10y_3m", v, "", ctx.p("market"))])


@factor("macro.rate_sensitivity", "Rate sensitivity × rate trend", "macro", {L: 0.8, M: 0.8, S: 0.3})
def rate_sens(ctx):
    b = ctx.s("sensitivity", "univariate", "TLT", "beta")
    chg = ctx.s("market", "rates", "chg_10y_1m")
    if b is None or chg is None:
        return None
    # beta to TLT (bond prices) > 0 means the name likes falling yields; rising 10y is a headwind then
    v = -b * chg
    return mk("", "", "", v, scaled(v, 0.3), unit="", narrative=f"beta to long bonds {b:+.2f}; 10y moved {chg:+.2f} pts in 1m", inputs=[InputRef("beta_TLT", b, "", ctx.p("sensitivity")), InputRef("chg_10y_1m", chg, "", ctx.p("market"))], confidence=0.5)


@factor("macro.dollar_sensitivity", "Dollar sensitivity × dollar trend", "macro", {L: 0.6, M: 0.7, S: 0.3})
def usd_sens(ctx):
    b = ctx.s("sensitivity", "univariate", "UUP", "beta")
    r = ctx.s("market", "factors", "UUP", "r_1m")
    if b is None or r is None:
        return None
    v = b * r
    return mk("", "", "", v, scaled(v, 0.01), unit="", narrative=f"beta to dollar {b:+.2f}; dollar {r:+.1%} in 1m", inputs=[InputRef("beta_UUP", b, "", ctx.p("sensitivity")), InputRef("uup_r_1m", r, "pct", ctx.p("market"))], confidence=0.5)


@factor("macro.breadth", "Sector breadth (ETFs above 50d)", "macro", {L: 0.4, M: 0.8, S: 0.6})
def breadth(ctx):
    v = ctx.s("market", "breadth_sectors_above_50d")
    return None if v is None else mk("", "", "", v, bounded(v, 0.2, 0.9), unit="pct", narrative=f"{v:.0%} of sector ETFs above their 50d", inputs=[InputRef("breadth", v, "", ctx.p("market"))])


# ------------------------------------------------------------------ sentiment
@factor("sentiment.news_short", "News sentiment (48h half-life)", "sentiment", {L: 0.0, M: 0.4, S: 1.0})
def news_s(ctx):
    v = ctx.s("news", "short_term", "score")
    n = ctx.s("news", "n_last_7d") or 0
    return None if v is None else mk("", "", "", v, scaled(v, 0.3), unit="score", narrative=f"weighted headline sentiment {v:+.2f} ({n} stories in 7d)", inputs=[InputRef("news_short_term", v, "", ctx.p("news"))], confidence=min(1.0, n / 15))


@factor("sentiment.news_medium", "News sentiment (2-week half-life)", "sentiment", {L: 0.5, M: 1.0, S: 0.3})
def news_m(ctx):
    v = ctx.s("news", "medium_term", "score")
    n = ctx.s("news", "n_stories") or 0
    return None if v is None else mk("", "", "", v, scaled(v, 0.3), unit="score", narrative=f"weighted sentiment {v:+.2f} over {n} stories", inputs=[InputRef("news_medium_term", v, "", ctx.p("news"))], confidence=min(1.0, n / 30))


@factor("sentiment.news_volume", "News volume anomaly", "sentiment", {L: 0.0, M: 0.3, S: 0.8})
def news_vol(ctx):
    z = ctx.s("news", "news_volume_z")
    if z is None:
        if ctx.s("news", "n_stories") is not None:
            return mk("", "", "", 0.0, 0.0, unit="", narrative="not enough stored history yet to judge volume (accrues from the news sweep)", inputs=[InputRef("news_volume_z", None, "", ctx.p("news"))], confidence=0.2)
        return None
    # attention spikes are risk (either direction); mild is fine
    return mk("", "", "", z, -min(abs(z), 4) / 4 * 0.6, unit="", narrative=f"news volume {z:+.1f}σ vs prior week", inputs=[InputRef("news_volume_z", z, "", ctx.p("news"))], confidence=0.5)


@factor("sentiment.social_bull_ratio", "StockTwits bull/bear ratio", "sentiment", {L: 0.0, M: 0.3, S: 1.0})
def st_bull(ctx):
    v = ctx.s("social", "stocktwits", "bull_ratio")
    n = (ctx.s("social", "stocktwits", "bullish") or 0) + (ctx.s("social", "stocktwits", "bearish") or 0)
    if v is None:
        return None
    # extreme unanimity is contrarian; use a hump: best around 0.6-0.75
    nrm = 0.5 if 0.55 <= v <= 0.78 else (-0.3 if v > 0.9 else (0.2 if v > 0.78 else (-0.5 if v < 0.35 else -0.1)))
    return mk("", "", "", v, nrm, unit="pct", narrative=f"{v:.0%} bullish of {n} tagged posts", inputs=[InputRef("bull_ratio", v, "", ctx.p("social"))], confidence=min(1.0, n / 30) * 0.7)


@factor("sentiment.reddit_mentions", "Reddit mention surge", "sentiment", {L: 0.0, M: 0.3, S: 0.8})
def reddit(ctx):
    z = ctx.s("social", "reddit", "mention_z")
    s = ctx.s("social", "reddit", "sentiment")
    if z is None:
        from fa.core.settings import get_settings
        if not get_settings().reddit_client_id:
            return mk("", "", "", None, None, narrative="Reddit API credentials not set (FA_REDDIT_CLIENT_ID / SECRET in .env)", status="MISSING")
        return None
    return mk("", "", "", z, scaled(s or 0, 0.3) * 0.5 - min(abs(z), 4) / 4 * 0.3, unit="", narrative=f"mentions {z:+.1f}σ vs prior 2 weeks, sentiment {s:+.2f}", inputs=[InputRef("mention_z", z, "", ctx.p("social"))], confidence=0.4)


# ------------------------------------------------------------------ events
@factor("events.days_to_earnings", "Earnings proximity", "events", {L: 0.0, M: 0.5, S: 0.4})
def dte(ctx):
    d = ctx.s("events", "days_to_earnings")
    if d is None:
        return None
    # binary event risk inside ~5 days; post-event drift window (1-10 days after) mildly positive if beat — unknown here
    n = -0.6 if d <= 5 else (-0.2 if d <= 15 else 0.1)
    return mk("", "", "", d, n, unit="days", narrative=f"earnings in {d} days" + (" — binary event risk" if d <= 5 else ""), inputs=[InputRef("days_to_earnings", d, "days", ctx.p("events"))])


@factor("events.macro_density", "High-impact macro events (next 14d)", "events", {L: 0.0, M: 0.4, S: 1.0})
def macro_events(ctx):
    ev = ctx.s("events", "high_impact_next_14d")
    if ev is None:                       # no events section at all ≠ a calm calendar
        return None
    n = len(ev)
    return mk("", "", "", n, bounded(n, 5, 0), unit="", narrative=f"{n} high-impact macro events in 14d: " + ", ".join(e["label"][:25] for e in ev[:4]), inputs=[InputRef("high_impact_events", [e["label"] for e in ev], "", ctx.p("events"))], confidence=0.6)


@factor("events.fomc_proximity", "FOMC proximity", "events", {L: 0.0, M: 0.4, S: 0.8})
def fomc(ctx):
    d = ctx.s("events", "days_to_fomc")
    if d is None:
        return None
    return mk("", "", "", d, -0.4 if d <= 3 else 0.0, unit="days", narrative=f"FOMC in {d} days", inputs=[InputRef("days_to_fomc", d, "days", ctx.p("events"))], confidence=0.6)

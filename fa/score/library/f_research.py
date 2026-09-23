"""Factors added from the literature review (see README → Research notes):

long   — gross profitability (Novy-Marx), asset growth (Cooper-Gulen-Schill, negative), low-volatility anomaly, dividend growth streak
medium — post-earnings-announcement drift, EPS estimate revisions / trend, consensus shift, target dispersion, 52-week-high proximity
short  — short-term reversal (Jegadeesh), turn-of-month, own-stock month seasonality, overnight vs intraday split, liquidity
"""
from __future__ import annotations

from fa.score.factors import InputRef, bounded, factor, mk, scaled

L, M, S = "long", "medium", "short"


# ------------------------------------------------------------------ long
@factor("quality.gross_profitability", "Gross profitability (GP / assets)", "quality", {L: 1.0, M: 0.4, S: 0.0})
def gross_prof(ctx):
    f = ctx.objects.get("fund")
    if f is None:
        return None
    gp, ta = f.latest("gross_profit"), f.latest("total_assets")
    if gp is None or not ta:
        return None
    v = gp / ta
    return mk("", "", "", v, bounded(v, 0.05, 0.60), unit="pct", narrative=f"gross profit / total assets {v:.1%} (Novy-Marx quality)", inputs=[InputRef("gross_profit", gp, "USD", ctx.p("fundamentals")), InputRef("total_assets", ta, "USD", ctx.p("fundamentals"))])


@factor("quality.asset_growth", "Asset growth (1y, lower is better)", "quality", {L: 1.0, M: 0.4, S: 0.0})
def asset_growth(ctx):
    f = ctx.objects.get("fund")
    if f is None:
        return None
    a0, a1 = f.annual_value("total_assets"), f.annual_value("total_assets", 1)
    if not a0 or not a1:
        return None
    g = a0 / a1 - 1
    return mk("", "", "", g, scaled(g, 0.25, direction=-1, center=0.08), unit="pct", narrative=f"total assets {g:+.1%} YoY — aggressive balance-sheet growth predicts weaker returns", inputs=[InputRef("total_assets", a0, "USD", ctx.p("fundamentals")), InputRef("total_assets_prior", a1, "USD", ctx.p("fundamentals"))])


@factor("volatility.low_vol_anomaly", "Low-volatility anomaly (long horizon)", "volatility", {L: 1.0, M: 0.3, S: 0.0})
def low_vol(ctx):
    v = ctx.s("risk", "ann_vol_1y")
    return None if v is None else mk("", "", "", v, bounded(v, 0.70, 0.15), unit="pct", narrative=f"1y realized vol {v:.0%} — lower-vol names have historically earned better risk-adjusted returns", inputs=[InputRef("ann_vol_1y", v, "pct", ctx.p("risk"))], confidence=0.6)


@factor("capital_allocation.dividend_streak", "Dividend growth consistency", "capital_allocation", {L: 0.8, M: 0.3, S: 0.0})
def div_streak(ctx):
    f = ctx.objects.get("fund")
    if f is None:
        return None
    s = f.series("dividends_paid", "annual")
    vals = [abs(float(x)) for x in s.values]
    if not vals or vals[-1] <= 0:
        return mk("", "", "", 0, 0.0, unit="", narrative="pays no dividend — factor neutral", inputs=[InputRef("dividends_paid", vals[-1] if vals else None, "USD", ctx.p("fundamentals"))], confidence=0.3)
    if len(vals) < 3:
        return None
    streak = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1] > 0:
            streak += 1
        else:
            break
    return mk("", "", "", streak, bounded(streak, 0, 8), unit="", narrative=f"{streak} consecutive years of rising dividends paid", inputs=[InputRef("dividend_history", vals[-6:], "USD", ctx.p("fundamentals"))])


# ------------------------------------------------------------------ medium
@factor("analysts.pead", "Post-earnings-announcement drift", "analysts", {L: 0.2, M: 1.0, S: 0.7})
def pead(ctx):
    ls = ctx.s("analysts", "last_surprise")
    if not ls or ls.get("surprise_pct") is None:
        return None
    sp, days = ls["surprise_pct"] / 100, ls.get("days_ago") or 999
    if days > 75:
        return mk("", "", "", sp, 0.0, unit="pct", narrative=f"last surprise {sp:+.1%} was {days}d ago — drift window has passed", inputs=[InputRef("surprise_pct", sp, "pct", ctx.p("analysts"))], confidence=0.4)
    decay = max(0.0, 1 - days / 75)
    return mk("", "", "", sp, scaled(sp, 0.10) * decay, unit="pct", narrative=f"EPS surprise {sp:+.1%} on {ls['date']} ({days}d ago) — prices drift in the surprise direction for ~60 days",
              inputs=[InputRef("eps_reported", ls.get("eps_reported"), "USD", ctx.p("analysts")), InputRef("eps_estimate", ls.get("eps_estimate"), "USD", ctx.p("analysts"))])


@factor("analysts.estimate_revisions", "EPS estimate revisions (30d, current quarter)", "analysts", {L: 0.3, M: 1.0, S: 0.5})
def revisions(ctx):
    r = ctx.s("analysts", "eps_revisions")
    if not r:
        return None
    up, dn = r.get("up_30d") or 0, r.get("down_30d") or 0
    if up + dn == 0:
        return mk("", "", "", 0.0, 0.0, unit="", narrative="no EPS revisions in the last 30 days", inputs=[InputRef("revisions", r, "", ctx.p("analysts"))], confidence=0.3)
    v = (up - dn) / (up + dn)
    return mk("", "", "", v, scaled(v, 0.6), unit="score", narrative=f"{int(up)} up / {int(dn)} down EPS revisions in 30 days", inputs=[InputRef("up_30d", up, "", ctx.p("analysts")), InputRef("down_30d", dn, "", ctx.p("analysts"))])


@factor("analysts.estimate_trend", "EPS estimate trend (90 days)", "analysts", {L: 0.5, M: 1.0, S: 0.3})
def est_trend(ctx):
    t = ctx.s("analysts", "eps_trend")
    if not t or t.get("chg_90d") is None:
        return None
    v = t["chg_90d"]
    return mk("", "", "", v, scaled(v, 0.08), unit="pct", narrative=f"current-year EPS consensus {v:+.1%} vs 90 days ago ({t.get('90d_ago')} → {t.get('current_fy')})", inputs=[InputRef("eps_current_fy", t.get("current_fy"), "USD", ctx.p("analysts")), InputRef("eps_90d_ago", t.get("90d_ago"), "USD", ctx.p("analysts"))])


@factor("analysts.consensus_shift", "Consensus rating shift (vs 2-3 months ago)", "analysts", {L: 0.3, M: 1.0, S: 0.4})
def shift(ctx):
    s = ctx.s("analysts", "consensus_shift")
    if not s:
        return None
    v = s["delta"]
    return mk("", "", "", v, scaled(v, 0.15), unit="score", narrative=f"rating score {s['prior']:+.2f} → {s['now']:+.2f}", inputs=[InputRef("now", s["now"], "", ctx.p("analysts")), InputRef("prior", s["prior"], "", ctx.p("analysts"))], confidence=0.6)


@factor("analysts.target_dispersion", "Analyst target dispersion", "analysts", {L: 0.4, M: 0.7, S: 0.2})
def dispersion(ctx):
    d = ctx.s("analysts", "target_dispersion")
    if d is None:
        return None
    return mk("", "", "", d, bounded(d, 1.2, 0.3), unit="pct", narrative=f"(high − low) / mean target = {d:.0%} — wide disagreement means less reliable consensus", inputs=[InputRef("target_dispersion", d, "pct", ctx.p("analysts"))], confidence=0.5)


# ------------------------------------------------------------------ short (2-20 days)
@factor("patterns.short_term_reversal", "5-day short-term reversal", "patterns", {L: 0.0, M: 0.2, S: 0.9})
def reversal(ctx):
    z = ctx.s("technicals", "swing_extra", "r5_z")
    if z is None:
        return None
    # a 5-day move beyond ±2σ tends to partially reverse over the next week; inside that band momentum dominates
    v = -0.6 * (abs(z) - 2) / 2 * (1 if z > 0 else -1) if abs(z) > 2 else 0.15 * (1 if z > 0 else -1)
    return mk("", "", "", z, bounded(v, -1, 1), unit="", narrative=f"5-day return is {z:+.1f}σ vs its 2-year distribution" + (" — stretched, reversal risk" if abs(z) > 2 else ""), inputs=[InputRef("r5_z", z, "", ctx.p("technicals"))], confidence=0.6)


@factor("patterns.turn_of_month", "Turn-of-month seasonality", "patterns", {L: 0.0, M: 0.1, S: 0.6})
def tom(ctx):
    edge = ctx.s("technicals", "swing_extra", "turn_of_month_edge")
    inside = ctx.s("technicals", "swing_extra", "in_turn_of_month")
    if edge is None:
        return None
    v = 0.4 if (inside and edge > 0) else (-0.2 if (inside and edge < 0) else 0.0)
    return mk("", "", "", edge, v, unit="pct", narrative=f"this stock's last-3/first-3-days-of-month daily edge is {edge*100:+.2f}%/day; {'currently inside' if inside else 'not in'} the window", inputs=[InputRef("turn_of_month_edge", edge, "pct", ctx.p("technicals"))], confidence=0.4)


@factor("patterns.month_seasonality", "Own-stock calendar-month tendency", "patterns", {L: 0.0, M: 0.5, S: 0.6})
def month_seas(ctx):
    m = ctx.s("technicals", "swing_extra", "month_avg_daily_ret")
    hit = ctx.s("technicals", "swing_extra", "month_hit_rate")
    if m is None:
        return None
    v = scaled(m, 0.002) * 0.6
    return mk("", "", "", m, v, unit="pct", narrative=f"this calendar month has averaged {m*100:+.2f}%/day for this stock with a {hit:.0%} positive-month hit rate", inputs=[InputRef("month_avg_daily_ret", m, "pct", ctx.p("technicals")), InputRef("month_hit_rate", hit, "", ctx.p("technicals"))], confidence=0.4)


@factor("patterns.overnight_split", "Overnight vs intraday return split (120d)", "patterns", {L: 0.0, M: 0.3, S: 0.6})
def overnight(ctx):
    o, i = ctx.s("technicals", "swing_extra", "overnight_ret_120d"), ctx.s("technicals", "swing_extra", "intraday_ret_120d")
    if o is None or i is None:
        return None
    v = scaled(o - i, 0.15) * 0.5
    return mk("", "", "", o - i, v, unit="pct", narrative=f"last 120 sessions: {o:+.1%} came overnight (gaps, news) vs {i:+.1%} intraday — {'gap-driven, holds through the close' if o > i else 'intraday-driven, fades gaps'}", inputs=[InputRef("overnight_ret_120d", o, "pct", ctx.p("technicals")), InputRef("intraday_ret_120d", i, "pct", ctx.p("technicals"))], confidence=0.5)


@factor("flow.liquidity", "Liquidity (20d dollar volume)", "flow", {L: 0.3, M: 0.4, S: 0.8})
def liquidity(ctx):
    dv = ctx.s("technicals", "swing_extra", "dollar_volume_20d")
    if dv is None:
        return None
    import math
    v = bounded(math.log10(max(dv, 1)), 6.5, 9.0)
    return mk("", "", "", dv, v, unit="USD", narrative=f"${dv/1e6:,.0f}M traded per day — {'deep' if dv > 5e8 else 'adequate' if dv > 5e7 else 'thin; spreads and slippage matter'}", inputs=[InputRef("dollar_volume_20d", dv, "USD", ctx.p("technicals"))], confidence=0.5)

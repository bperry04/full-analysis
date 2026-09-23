"""Swing-trading factors (2-20 trading days): candlesticks, chart patterns, setup quality, timeframe alignment, volume
confirmation, compression, gaps, 20-day relative strength, squeeze potential, event risk inside the window, IV-crush risk,
market regime, and reward-to-risk at the nearest levels."""
from __future__ import annotations

from fa.score.factors import InputRef, bounded, factor, mk, scaled

L, M, S = "long", "medium", "short"


def _pat(ctx, *path):
    return ctx.s("technicals", "patterns", *path)


@factor("patterns.candlesticks", "Candlestick signal (last 2 bars, trend-aware)", "patterns", {L: 0.0, M: 0.3, S: 1.0})
def candles(ctx):
    net = _pat(ctx, "candle_net_2bars")
    if net is None:
        return None
    names = [p["name"] for p in (_pat(ctx, "patterns") or []) if p["kind"] == "candle" and p["bars_ago"] <= 2]
    return mk("", "", "", net, scaled(net, 0.8), unit="score", narrative=(", ".join(names[:4]) if names else "no notable candles") + f" → net {net:+.2f}",
              inputs=[InputRef("candle_net_2bars", net, "", ctx.p("technicals")), InputRef("patterns", names, "", ctx.p("technicals"))], confidence=0.7 if names else 0.4)


@factor("patterns.chart", "Chart pattern / breakout signal (5 bars)", "patterns", {L: 0.0, M: 0.5, S: 1.0})
def chart(ctx):
    net = _pat(ctx, "chart_net")
    if net is None:
        return None
    ps = [p for p in (_pat(ctx, "patterns") or []) if p["kind"] in ("chart", "breakout") and p["bars_ago"] <= 5]
    return mk("", "", "", net, scaled(net, 0.8), unit="score", narrative=("; ".join(f"{p['name']} ({p['detail'][:50]})" for p in ps[:3]) if ps else "no chart pattern in the last 5 bars"),
              inputs=[InputRef(p["name"], p["detail"], "", ctx.p("technicals")) for p in ps[:6]], confidence=0.75 if ps else 0.35)


@factor("patterns.setup", "Swing setup quality × direction", "patterns", {L: 0.0, M: 0.4, S: 1.3})
def setup(ctx):
    st = _pat(ctx, "setup")
    if not st or st.get("direction") is None:
        return None
    d, q = st["direction"], st.get("quality") or 0.0
    v = d * q
    return mk("", "", "", v, bounded(v, -0.8, 0.8), unit="score", narrative=f"{st['setup']}: " + "; ".join(st.get("why") or [])[:140],
              inputs=[InputRef("setup", st["setup"], "", ctx.p("technicals")), InputRef("quality", q, "", ctx.p("technicals")), InputRef("direction", d, "", ctx.p("technicals"))],
              confidence=0.8 if d else 0.5)


@factor("patterns.alignment", "Multi-timeframe alignment (weekly / daily / 1h)", "patterns", {L: 0.2, M: 0.8, S: 1.0})
def alignment(ctx):
    wk = ctx.s("technicals", "intervals", "1wk", "signals", "supertrend")
    dy = ctx.s("technicals", "intervals", "1d", "signals", "ma_stack_bullish")
    dyb = ctx.s("technicals", "intervals", "1d", "signals", "ma_stack_bearish")
    hr = ctx.s("technicals", "intervals", "1h", "signals", "supertrend")
    votes = []
    if wk is not None:
        votes.append(1 if wk == "bullish" else -1)
    if dy is not None:
        votes.append(1 if dy else (-1 if dyb else 0))
    if hr is not None:
        votes.append(1 if hr == "bullish" else -1)
    if not votes:
        return None
    v = sum(votes) / len(votes)
    return mk("", "", "", v, bounded(v, -1, 1), unit="score", narrative=f"weekly {wk}, daily stack {'bull' if dy else 'bear' if dyb else 'mixed'}, 1h {hr} → {sum(1 for x in votes if x > 0)}/{len(votes)} bullish",
              inputs=[InputRef("weekly_supertrend", wk, "", ctx.p("technicals")), InputRef("daily_ma_stack", dy, "", ctx.p("technicals")), InputRef("hourly_supertrend", hr, "", ctx.p("technicals"))])


@factor("patterns.volume_confirmation", "Volume confirms the move", "patterns", {L: 0.0, M: 0.3, S: 1.0})
def volume_conf(ctx):
    rv = _pat(ctx, "setup", "rel_volume")
    r5 = ctx.s("technicals", "returns", "r_5d")
    if rv is None or r5 is None:
        return None
    v = (1 if r5 > 0 else -1) * max(0.0, min(rv - 1, 2)) / 2
    return mk("", "", "", rv, bounded(v, -1, 1), unit="x", narrative=f"today's volume {rv:.1f}x 20d average with a 5-day move of {r5:+.1%}",
              inputs=[InputRef("rel_volume", rv, "x", ctx.p("technicals")), InputRef("r_5d", r5, "pct", ctx.p("technicals"))], confidence=0.6)


@factor("patterns.compression", "Volatility compression (NR7 / inside bar / tight base / squeeze)", "patterns", {L: 0.0, M: 0.2, S: 0.7})
def compression(ctx):
    names = [p["name"] for p in (_pat(ctx, "patterns") or []) if p["bars_ago"] <= 1 and p["direction"] == 0]
    sq = ctx.s("technicals", "intervals", "1d", "signals", "squeeze")
    n = len(names) + (1 if sq else 0)
    if n == 0 and sq is None:
        return None
    # compression is opportunity (expansion ahead) but directionless: score mildly positive when trend is up, mildly negative when down
    tr = _pat(ctx, "setup", "trend")
    sign = 1 if tr == "up" else (-1 if tr == "down" else 0)
    return mk("", "", "", n, sign * min(n, 3) / 3 * 0.6, unit="", narrative=(", ".join(names + (["BB-in-Keltner squeeze"] if sq else [])) or "no compression") + f" in a {tr} trend",
              inputs=[InputRef("compression_patterns", names, "", ctx.p("technicals"))], confidence=0.5)


@factor("patterns.gap", "Unfilled gap", "patterns", {L: 0.0, M: 0.2, S: 0.8})
def gap(ctx):
    pats = _pat(ctx, "patterns")
    if pats is None:
        return None
    g = next((p for p in pats if p["kind"] == "gap" and p["bars_ago"] == 0), None)
    if g is None:
        return mk("", "", "", 0.0, 0.0, unit="", narrative="no ≥1% gap today", inputs=[InputRef("gap", None, "", ctx.p("technicals"))], confidence=0.3)
    unfilled = "unfilled" in g["name"]
    v = g["direction"] * (0.6 if unfilled else 0.2)
    return mk("", "", "", g["direction"], v, unit="", narrative=f"{g['name']} — {g['detail']}", inputs=[InputRef("gap", g["name"], "", ctx.p("technicals"))], confidence=0.6)


@factor("patterns.rs_20d", "20-day relative strength vs S&P 500", "patterns", {L: 0.0, M: 0.5, S: 1.0})
def rs20(ctx):
    v = ctx.s("technicals", "returns", "rs_20d_vs_spy")
    return None if v is None else mk("", "", "", v, scaled(v, 0.06), unit="pct", narrative=f"20-day return vs SPY {v:+.1%}", inputs=[InputRef("rs_20d_vs_spy", v, "pct", ctx.p("technicals"))])


@factor("patterns.channel_position", "Position in 60-day regression channel", "patterns", {L: 0.0, M: 0.4, S: 0.8})
def channel_pos(ctx):
    ch = _pat(ctx, "channel")
    if not ch or ch.get("position_z") is None:
        return None
    z, up = ch["position_z"], ch.get("direction") == "up"
    # in an up-channel, the lower band is the buy zone; in a down-channel the upper band is the sell zone
    v = (-z / 2) if up else (-z / 2) * 0.5 - 0.3
    return mk("", "", "", z, bounded(v, -1, 1), unit="", narrative=f"{z:+.1f}σ inside a {ch['direction']} channel (r² {ch['r2']:.2f}, {ch['slope_pct_per_day'] * 100:+.2f}%/day)",
              inputs=[InputRef("position_z", z, "", ctx.p("technicals")), InputRef("channel_r2", ch["r2"], "", ctx.p("technicals"))], confidence=min(1.0, 0.4 + ch["r2"]))


@factor("patterns.reward_to_risk", "Reward-to-risk at nearest levels", "patterns", {L: 0.0, M: 0.3, S: 1.0})
def rr(ctx):
    st = _pat(ctx, "setup")
    if not st:
        return None
    plan = st.get("plan") or {}
    rr_ = plan.get("rr")
    if rr_ is None:
        return mk("", "", "", None, 0.0, unit="x", narrative="no directional setup, so no entry/stop/target geometry yet", inputs=[InputRef("setup", st.get("setup"), "", ctx.p("technicals"))], confidence=0.3)
    return mk("", "", "", rr_, bounded(rr_, 0.5, 3.0), unit="x", narrative=f"entry {plan['entry']:.2f}, ATR stop {plan['stop']:.2f} ({plan['stop_pct']:+.1%}), target {plan['target']:.2f} ({plan['target_pct']:+.1%}) → {rr_:.1f}R",
              inputs=[InputRef(k, plan.get(k), "USD", ctx.p("technicals")) for k in ("entry", "stop", "target")], confidence=0.6)


@factor("patterns.squeeze_potential", "Short-squeeze potential", "shorts", {L: 0.0, M: 0.6, S: 1.0})
def squeeze(ctx):
    pf, dtc = ctx.s("shorts", "pct_of_float"), ctx.s("shorts", "days_to_cover")
    r5, rv = ctx.s("technicals", "returns", "r_5d"), _pat(ctx, "setup", "rel_volume")
    if pf is None or dtc is None:
        return None
    fuel = min(pf / 0.20, 1.0) * min(dtc / 5.0, 1.0)
    spark = 1.0 if (r5 or 0) > 0.03 and (rv or 1) > 1.3 else 0.3
    v = fuel * spark
    return mk("", "", "", v, bounded(v, 0, 0.8), unit="score", narrative=f"{pf:.1%} of float short, {dtc:.1f} days to cover" + (" — price and volume are already moving" if spark == 1.0 else " — no ignition yet"),
              inputs=[InputRef("pct_of_float", pf, "pct", ctx.p("shorts")), InputRef("days_to_cover", dtc, "days", ctx.p("shorts")), InputRef("rel_volume", rv, "x", ctx.p("technicals"))], confidence=0.6)


@factor("events.earnings_inside_window", "Earnings inside the 2-20 day window", "events", {L: 0.0, M: 0.3, S: 1.2})
def earnings_window(ctx):
    d = ctx.s("events", "days_to_earnings")
    if d is None:
        return None
    if d <= 20:
        n = -0.7 if d <= 7 else -0.4
        txt = f"earnings in {d} trading-ish days — a swing trade will hold through a binary event"
    else:
        n, txt = 0.15, f"no earnings for {d} days — clean window"
    return mk("", "", "", d, n, unit="days", narrative=txt, inputs=[InputRef("days_to_earnings", d, "days", ctx.p("events"))])


@factor("options.iv_crush_risk", "IV-crush risk for long-premium swings", "options", {L: 0.0, M: 0.2, S: 0.8})
def iv_crush(ctx):
    d = ctx.s("events", "days_to_earnings")
    rk = ctx.s("options", "ranks", "iv_rank")
    ivrv = ctx.s("options", "iv_vs_rv", "iv_rv_20")
    if d is None or (rk is None and ivrv is None):
        return None
    rich = (rk or 0.5) > 0.6 or (ivrv or 1.0) > 1.4
    if d <= 20 and rich:
        return mk("", "", "", ivrv, -0.6, unit="x", narrative=f"earnings in {d}d with rich IV (IV/RV {ivrv:.2f}) — buying options here fights the crush; spreads or stock instead",
                  inputs=[InputRef("days_to_earnings", d, "days", ctx.p("events")), InputRef("iv_rv_20", ivrv, "x", ctx.p("options"))], confidence=0.6)
    return mk("", "", "", ivrv, 0.2 if (ivrv or 1) < 1.0 else 0.0, unit="x", narrative=f"IV/RV {ivrv:.2f}" + (" — options relatively cheap for a directional swing" if (ivrv or 1) < 1.0 else ""),
              inputs=[InputRef("iv_rv_20", ivrv, "x", ctx.p("options"))], confidence=0.5)


@factor("macro.swing_regime", "Market regime for swings (SPY > 20d & 50d, VIX)", "macro", {L: 0.0, M: 0.5, S: 1.0})
def regime(ctx):
    ok = ctx.s("technicals", "market_regime_swing_ok")
    vix = ctx.s("market", "vix", "level")
    if ok is None:
        return None
    v = (0.6 if ok else -0.6) + (0.2 if vix and vix < 16 else (-0.3 if vix and vix > 24 else 0.0))
    return mk("", "", "", v, bounded(v, -1, 1), unit="score", narrative=f"SPY {'above' if ok else 'below'} its 20d/50d; VIX {vix:.1f}" if vix else f"SPY {'above' if ok else 'below'} its 20d/50d",
              inputs=[InputRef("spy_regime_ok", ok, "", ctx.p("technicals")), InputRef("vix", vix, "", ctx.p("market"))])

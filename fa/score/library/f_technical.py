"""Trend, volatility, flow and short-interest factors from prices, bars and FINRA data."""
from __future__ import annotations

from fa.score.factors import InputRef, bounded, factor, mk, scaled

L, M, S = "long", "medium", "short"


def _ti(ctx, key: str, interval: str = "1d"):
    return ctx.s("technicals", "intervals", interval, "latest", key)


def _sig(ctx, key: str, interval: str = "1d"):
    return ctx.s("technicals", "intervals", interval, "signals", key)


@factor("trend.ma_stack", "Moving-average stack (20/50/200)", "trend", {L: 1.0, M: 1.0, S: 0.6})
def ma_stack(ctx):
    c, s20, s50, s200 = _ti(ctx, "close"), _ti(ctx, "sma_20"), _ti(ctx, "sma_50"), _ti(ctx, "sma_200")
    if None in (c, s50, s200):
        return None
    pts = (1 if c > s200 else -1) + (1 if c > s50 else -1) + (0.5 if s50 > s200 else -0.5) + (0.5 if s20 and c > s20 else -0.5)
    return mk("", "", "", pts / 3, bounded(pts, -3, 3), unit="score", narrative=f"price {'above' if c > s200 else 'below'} 200d, {'above' if c > s50 else 'below'} 50d; 50d {'>' if s50 > s200 else '<'} 200d",
              inputs=[InputRef("close", c, "USD", ctx.p("technicals")), InputRef("sma_50", s50, "USD", ctx.p("technicals")), InputRef("sma_200", s200, "USD", ctx.p("technicals"))])


@factor("trend.momentum_6m", "6-month momentum (ex last month)", "trend", {L: 0.8, M: 1.0, S: 0.3})
def mom_6m(ctx):
    m = ctx.s("technicals", "returns", "r_6m_ex_1m")
    return None if m is None else mk("", "", "", m, scaled(m, 0.20), unit="pct", narrative=f"6m return ex-last-month {m:+.1%}", inputs=[InputRef("r_6m_ex_1m", m, "pct", ctx.p("technicals"))])


@factor("trend.relative_strength", "Relative strength vs S&P 500 (3m)", "trend", {L: 0.6, M: 1.0, S: 0.6})
def rs(ctx):
    r = ctx.s("technicals", "returns", "rs_3m_vs_spy")
    return None if r is None else mk("", "", "", r, scaled(r, 0.10), unit="pct", narrative=f"3m return vs SPY {r:+.1%}", inputs=[InputRef("rs_3m_vs_spy", r, "pct", ctx.p("technicals"))])


@factor("trend.sector_relative", "Relative strength vs sector ETF (3m)", "trend", {L: 0.4, M: 0.8, S: 0.5})
def sector_rs(ctx):
    r = ctx.s("technicals", "returns", "rs_3m_vs_sector")
    return None if r is None else mk("", "", "", r, scaled(r, 0.10), unit="pct", narrative=f"3m return vs sector ETF {r:+.1%}", inputs=[InputRef("rs_3m_vs_sector", r, "pct", ctx.p("technicals"))])


@factor("trend.adx_direction", "Trend strength (ADX × direction)", "trend", {L: 0.3, M: 0.8, S: 1.0})
def adx_dir(ctx):
    adx, pdi, mdi = _ti(ctx, "adx"), _ti(ctx, "plus_di"), _ti(ctx, "minus_di")
    if None in (adx, pdi, mdi):
        return None
    v = (adx / 50) * (1 if pdi > mdi else -1)
    return mk("", "", "", v, bounded(v, -1, 1), unit="score", narrative=f"ADX {adx:.0f} ({'bullish' if pdi > mdi else 'bearish'} DI)", inputs=[InputRef("adx", adx, "", ctx.p("technicals")), InputRef("plus_di", pdi, "", ctx.p("technicals")), InputRef("minus_di", mdi, "", ctx.p("technicals"))])


@factor("trend.rsi", "RSI(14) mean-reversion / momentum", "trend", {L: 0.1, M: 0.5, S: 0.7})
def rsi(ctx):
    r = _ti(ctx, "rsi_14")
    if r is None:
        return None
    # short horizon: extremes revert; neutral-bullish zone 50-65 is favourable
    v = -1.0 if r > 78 else (-0.4 if r > 70 else (0.6 if 50 <= r <= 68 else (0.2 if r < 30 else (-0.2 if r < 45 else 0.2))))
    return mk("", "", "", r, v, unit="", narrative=f"RSI {r:.0f}", inputs=[InputRef("rsi_14", r, "", ctx.p("technicals"))])


@factor("trend.macd", "MACD histogram", "trend", {L: 0.2, M: 0.7, S: 1.0})
def macd(ctx):
    h, c = _ti(ctx, "macd_hist"), _ti(ctx, "close")
    if h is None or not c:
        return None
    v = h / c
    return mk("", "", "", v, scaled(v, 0.01), unit="pct", narrative=f"MACD histogram {'positive' if h > 0 else 'negative'} ({v:+.2%} of price)", inputs=[InputRef("macd_hist", h, "", ctx.p("technicals"))])


@factor("trend.52w_position", "Position in 52-week range", "trend", {L: 0.5, M: 0.8, S: 0.6})
def pos52(ctx):
    p = _ti(ctx, "pos_52w")
    return None if p is None else mk("", "", "", p, bounded(p, 0.1, 0.9), unit="pct", narrative=f"{p:.0%} of 52-week range", inputs=[InputRef("pos_52w", p, "", ctx.p("technicals"))])


@factor("trend.weekly_structure", "Weekly trend (swing structure + supertrend)", "trend", {L: 1.0, M: 0.8, S: 0.2})
def weekly(ctx):
    st = _sig(ctx, "supertrend", "1wk")
    ich = _sig(ctx, "ichimoku", "1wk")
    if st is None:
        return None
    v = (1 if st == "bullish" else -1) * 0.6 + (0.4 if ich == "above_cloud" else (-0.4 if ich == "below_cloud" else 0))
    return mk("", "", "", v, bounded(v, -1, 1), unit="score", narrative=f"weekly supertrend {st}, {ich.replace('_', ' ') if ich else ''}", inputs=[InputRef("supertrend_1wk", st, "", ctx.p("technicals"))])


@factor("trend.intraday", "Intraday trend (1h)", "trend", {L: 0.0, M: 0.2, S: 1.0})
def intraday(ctx):
    st = _sig(ctx, "supertrend", "1h")
    ma = _sig(ctx, "trend_sma", "1h")
    if st is None:
        return None
    v = (0.6 if st == "bullish" else -0.6) + (0.4 if ma == "up" else (-0.4 if ma == "down" else 0))
    return mk("", "", "", v, bounded(v, -1, 1), unit="score", narrative=f"1h supertrend {st}, MAs {ma}", inputs=[InputRef("supertrend_1h", st, "", ctx.p("technicals"))])


@factor("trend.distance_to_200d", "Stretch vs 200-day (z)", "trend", {L: 0.4, M: 0.6, S: 0.5})
def stretch(ctx):
    z = _ti(ctx, "z_sma_200")
    if z is None:
        return None
    # mild positive stretch is momentum; extreme stretch is risk
    v = 0.4 if 0 < z <= 2 else (-0.6 if z > 3 else (-0.2 if z > 2 else (-0.4 if z < -2 else (0.0 if z < 0 else 0.2))))
    return mk("", "", "", z, v, unit="", narrative=f"{z:+.1f} σ from 200d", inputs=[InputRef("z_sma_200", z, "", ctx.p("technicals"))])


# ------------------------------------------------------------------ volatility
@factor("volatility.regime", "Realized vol regime", "volatility", {L: 0.6, M: 0.8, S: 1.0})
def vol_regime(ctx):
    p = ctx.s("technicals", "regime", "hv20_percentile_2y")
    if p is None:
        return None
    return mk("", "", "", p, bounded(p, 0.9, 0.1), unit="pct", narrative=f"20d realized vol at {p:.0%} percentile of 2y", inputs=[InputRef("hv20_percentile_2y", p, "", ctx.p("technicals"))])


@factor("volatility.drawdown", "Drawdown from 52w high", "volatility", {L: 0.5, M: 0.8, S: 0.6})
def dd(ctx):
    d = ctx.s("technicals", "regime", "drawdown", "current_dd")
    return None if d is None else mk("", "", "", d, bounded(d, -0.40, 0.0), unit="pct", narrative=f"{d:.1%} below peak", inputs=[InputRef("current_dd", d, "pct", ctx.p("technicals"))])


@factor("volatility.beta", "Beta vs S&P 500", "volatility", {L: 0.8, M: 0.5, S: 0.3})
def beta(ctx):
    b = ctx.s("risk", "beta_weekly_2y", "beta_adjusted")
    if b is None:
        return None
    return mk("", "", "", b, bounded(b, 2.0, 0.6), unit="x", narrative=f"beta {b:.2f} (2y weekly, Blume-adjusted)", inputs=[InputRef("beta_adjusted", b, "", ctx.p("risk"))], confidence=0.6)


@factor("volatility.tail_risk", "Tail risk (CVaR 95, kurtosis)", "volatility", {L: 0.5, M: 0.6, S: 1.0})
def tail(ctx):
    cv = ctx.s("risk", "var_95_1d", "cvar")
    k = ctx.s("risk", "kurtosis_1y")
    if cv is None:
        return None
    return mk("", "", "", cv, bounded(cv, 0.06, 0.015), unit="pct", narrative=f"1-day CVaR95 {cv:.1%}, excess kurtosis {k:.1f}" if k is not None else f"CVaR95 {cv:.1%}",
              inputs=[InputRef("cvar_95", cv, "pct", ctx.p("risk")), InputRef("kurtosis_1y", k, "", ctx.p("risk"))])


@factor("volatility.squeeze", "Volatility squeeze (BB inside Keltner)", "volatility", {L: 0.0, M: 0.3, S: 0.8})
def squeeze(ctx):
    s = _sig(ctx, "squeeze")
    if s is None:
        return None
    return mk("", "", "", 1.0 if s else 0.0, 0.3 if s else 0.0, unit="", narrative="squeeze on — expansion likely" if s else "no squeeze", inputs=[InputRef("squeeze_on", s, "", ctx.p("technicals"))], confidence=0.5)


# ------------------------------------------------------------------ flow
@factor("flow.cvd_5d", "Order-flow imbalance (5d, bar proxy)", "flow", {L: 0.0, M: 0.5, S: 1.0})
def cvd(ctx):
    v = ctx.s("flow", "bars", "imbalance_5d")
    if v is None:
        return None
    tape = ctx.s("flow", "tape", "imbalance")
    if tape is not None:
        return mk("", "", "", tape, scaled(tape, 0.15), unit="pct", narrative=f"tape imbalance {tape:+.1%} (Lee-Ready on IBKR ticks)", inputs=[InputRef("tape_imbalance", tape, "pct", ctx.p("flow"))])
    return mk("", "", "", v, scaled(v, 0.10), unit="pct", narrative=f"5-day buy/sell imbalance {v:+.1%} (tick-rule PROXY)", inputs=[InputRef("imbalance_5d", v, "pct", ctx.p("flow"))], confidence=0.5)


@factor("flow.relative_volume", "Relative volume", "flow", {L: 0.0, M: 0.4, S: 1.0})
def rvol(ctx):
    v = _ti(ctx, "rel_volume")
    r1 = ctx.s("technicals", "returns", "r_5d")
    if v is None:
        return None
    # high volume confirms the recent direction
    d = 1 if (r1 or 0) >= 0 else -1
    n = scaled(v - 1, 0.6) * d
    return mk("", "", "", v, n, unit="x", narrative=f"volume {v:.2f}x 20d average with 5d return {r1:+.1%}" if r1 is not None else f"volume {v:.2f}x average", inputs=[InputRef("rel_volume", v, "x", ctx.p("technicals"))], confidence=0.6)


@factor("flow.accumulation", "Accumulation / distribution (CMF 20)", "flow", {L: 0.2, M: 0.8, S: 0.8})
def cmf(ctx):
    v = _ti(ctx, "cmf_20")
    return None if v is None else mk("", "", "", v, scaled(v, 0.15), unit="", narrative=f"Chaikin money flow {v:+.2f}", inputs=[InputRef("cmf_20", v, "", ctx.p("technicals"))])


@factor("flow.short_volume", "Off-exchange short-volume ratio (FINRA)", "flow", {L: 0.0, M: 0.6, S: 1.0})
def short_vol(ctx):
    z = ctx.s("flow", "short_volume", "short_ratio_z_60d")
    r = ctx.s("flow", "short_volume", "short_ratio")
    if z is None:
        return None
    return mk("", "", "", r, scaled(z, 1.5, direction=-1), unit="pct", narrative=f"short-sale share of off-exchange volume {r:.0%} ({z:+.1f}σ vs 60d)", inputs=[InputRef("short_ratio", r, "pct", ctx.p("flow")), InputRef("short_ratio_z_60d", z, "", ctx.p("flow"))], confidence=0.6)


# ------------------------------------------------------------------ shorts
@factor("shorts.short_interest_pct_float", "Short interest % float", "shorts", {L: 0.5, M: 1.0, S: 0.8})
def si_pct(ctx):
    v = ctx.s("shorts", "pct_of_float")
    if v is None:
        return None
    return mk("", "", "", v, bounded(v, 0.20, 0.01), unit="pct", narrative=f"{v:.1%} of float short", inputs=[InputRef("pct_of_float", v, "pct", ctx.p("shorts"))])


@factor("shorts.days_to_cover", "Days to cover", "shorts", {L: 0.3, M: 0.8, S: 1.0})
def dtc(ctx):
    v = ctx.s("shorts", "days_to_cover")
    return None if v is None else mk("", "", "", v, bounded(v, 8, 1), unit="days", narrative=f"{v:.1f} days to cover", inputs=[InputRef("days_to_cover", v, "days", ctx.p("shorts"))])


@factor("shorts.trend", "Short interest change (vs prior report)", "shorts", {L: 0.3, M: 1.0, S: 0.8})
def si_trend(ctx):
    v = ctx.s("shorts", "change_pct")
    return None if v is None else mk("", "", "", v / 100, scaled(v / 100, 0.15, direction=-1), unit="pct", narrative=f"short interest {v:+.1f}% vs prior settlement", inputs=[InputRef("change_pct", v, "pct", ctx.p("shorts"))])

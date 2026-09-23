"""Options-derived factors: IV rank, term structure, skew, put/call, positioning, expected move vs realized."""
from __future__ import annotations

from fa.score.factors import InputRef, bounded, factor, mk, scaled

L, M, S = "long", "medium", "short"


@factor("options.iv_rank", "IV rank (1y)", "options", {L: 0.0, M: 0.6, S: 1.0})
def iv_rank(ctx):
    r = ctx.s("options", "ranks", "iv_rank")
    n = ctx.s("options", "ranks", "history_days") or 0
    if r is None:
        fl = ctx.s("options", "ranks", "flag")
        return mk("", "", "", None, None, narrative=f"suppressed: {fl}" if fl else "no history", status="SUPPRESSED")
    # low IV rank = options cheap / calm; high = stress priced in (slight contrarian for short horizon)
    return mk("", "", "", r, bounded(r, 0.9, 0.1), unit="pct", narrative=f"IV rank {r:.0%} over {n} days", inputs=[InputRef("iv_rank", r, "", ctx.p("options"))], confidence=min(1.0, n / 252))


@factor("options.iv_vs_rv", "Implied vs realized vol (30d)", "options", {L: 0.0, M: 0.5, S: 1.0})
def iv_rv(ctx):
    v = ctx.s("options", "iv_vs_rv", "iv_rv_20")
    if v is None:
        return None
    # IV >> RV: fear premium; IV << RV: complacency. Mild premium (1.0-1.3) is normal.
    n = 0.3 if 1.0 <= v <= 1.3 else (-0.5 if v > 1.8 else (-0.4 if v < 0.75 else 0.0))
    return mk("", "", "", v, n, unit="x", narrative=f"IV30 / HV20 = {v:.2f}", inputs=[InputRef("iv_rv_20", v, "x", ctx.p("options"))], confidence=0.7)


@factor("options.term_structure", "IV term structure", "options", {L: 0.0, M: 0.7, S: 1.0})
def term(ctx):
    s = ctx.s("options", "surface", "term_slope_30_90")
    if s is None:
        return None
    # backwardation (front > back) signals event/stress; contango is calm
    return mk("", "", "", s, scaled(s, 0.03), unit="pct", narrative=f"90d-30d ATM IV {s:+.1%} ({ctx.s('options','surface','term_shape')})", inputs=[InputRef("term_slope_30_90", s, "", ctx.p("options"))])


@factor("options.skew", "25-delta risk reversal (30d)", "options", {L: 0.0, M: 0.6, S: 1.0})
def skew(ctx):
    rr = ctx.s("options", "surface", "skew", "rr25")
    if rr is None:
        return None
    # typical equity RR is negative (put skew); unusually flat/positive = call demand; very negative = hedging demand
    return mk("", "", "", rr, scaled(rr + 0.03, 0.03), unit="pct", narrative=f"25Δ call IV − put IV = {rr:+.1%}", inputs=[InputRef("rr25", rr, "", ctx.p("options"))], confidence=0.7)


@factor("options.put_call_oi", "Put/call open interest", "options", {L: 0.0, M: 0.7, S: 0.8})
def pc_oi(ctx):
    v = ctx.s("options", "surface", "put_call_oi")
    if v is None:
        return None
    # contrarian at extremes: very high P/C OI (>1.3) = hedged/bearish crowd; very low (<0.5) = complacent
    n = 0.4 if v > 1.3 else (-0.3 if v < 0.5 else 0.0)
    return mk("", "", "", v, n, unit="x", narrative=f"P/C OI {v:.2f}", inputs=[InputRef("put_call_oi", v, "x", ctx.p("options"))], confidence=0.6)


@factor("options.put_call_volume", "Put/call volume (today vs history)", "options", {L: 0.0, M: 0.4, S: 1.0})
def pc_vol(ctx):
    v = ctx.s("options", "flow", "put_call_vol")
    z = ctx.s("options", "flow", "put_call_vol_z")
    if v is None:
        return None
    n = scaled(z, 1.5, direction=-1) if z is not None else (-0.3 if v > 1.2 else (0.2 if v < 0.6 else 0.0))
    return mk("", "", "", v, n, unit="x", narrative=f"P/C volume {v:.2f}" + (f" ({z:+.1f}σ vs 60d)" if z is not None else " (no history yet)"), inputs=[InputRef("put_call_vol", v, "x", ctx.p("options"))], confidence=0.8 if z is not None else 0.4)


@factor("options.net_premium", "Net options premium (calls − puts traded)", "options", {L: 0.0, M: 0.4, S: 1.0})
def net_prem(ctx):
    v = ctx.s("options", "flow", "net_premium_call_minus_put")
    tot = (ctx.s("options", "flow", "call_premium_traded") or 0) + (ctx.s("options", "flow", "put_premium_traded") or 0)
    if v is None or not tot:
        return None
    r = v / tot
    return mk("", "", "", r, scaled(r, 0.4), unit="pct", narrative=f"call premium share {(r + 1) / 2:.0%} of ${tot/1e6:.0f}M traded", inputs=[InputRef("net_premium", v, "USD", ctx.p("options"))], confidence=0.6)


@factor("options.gamma_regime", "Dealer gamma regime (proxy)", "options", {L: 0.0, M: 0.4, S: 1.0})
def gamma(ctx):
    g = ctx.s("options", "exposure", "gex_total")
    flip = ctx.s("options", "exposure", "gex_flip")
    spot = ctx.s("quote", "price")
    if g is None:
        return None
    n = 0.3 if g > 0 else -0.4
    txt = f"{'positive' if g > 0 else 'negative'} net gamma (dampened vs amplified moves)"
    if flip and spot:
        txt += f"; flip ≈ ${flip:.0f} ({(flip/spot-1):+.1%})"
    return mk("", "", "", g, n, unit="USD", narrative=txt + " — sign convention assumed", inputs=[InputRef("gex_total", g, "USD", ctx.p("options")), InputRef("gex_flip", flip, "USD", ctx.p("options"))], confidence=0.5)


@factor("options.oi_change", "Open interest change (calls − puts)", "options", {L: 0.0, M: 0.6, S: 1.0})
def oi_chg(ctx):
    c, p = ctx.s("options", "flow", "oi_change_calls"), ctx.s("options", "flow", "oi_change_puts")
    if c is None or p is None:
        return mk("", "", "", None, None, narrative="needs two snapshots (accrues from tomorrow)", status="MISSING")
    tot = abs(c) + abs(p)
    if not tot:
        return None
    r = (c - p) / tot
    return mk("", "", "", r, scaled(r, 0.5), unit="pct", narrative=f"OI Δ calls {c:+,.0f} / puts {p:+,.0f} vs prior snapshot", inputs=[InputRef("oi_change_calls", c, "", ctx.p("options")), InputRef("oi_change_puts", p, "", ctx.p("options"))], confidence=0.6)


@factor("options.expected_vs_realized_move", "Implied earnings move vs history", "options", {L: 0.0, M: 0.5, S: 0.8})
def em(ctx):
    imp = ctx.s("options", "expected_move", "earnings", "implied_move_pct")
    hist = ctx.s("options", "expected_move", "realized_earnings", "mean_abs_move_pct")
    if imp is None or hist is None:
        return None
    r = imp / hist - 1
    return mk("", "", "", r, scaled(r, 0.4, direction=-1), unit="pct", narrative=f"options price a {imp:.1%} earnings move vs {hist:.1%} historical average ({'rich' if r > 0 else 'cheap'})",
              inputs=[InputRef("implied_move_pct", imp, "pct", ctx.p("options")), InputRef("mean_abs_move_pct", hist, "pct", ctx.p("options"))], confidence=0.6)

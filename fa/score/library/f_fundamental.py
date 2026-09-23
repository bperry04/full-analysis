"""Valuation, quality, growth, balance-sheet, capital-allocation and analyst factors."""
from __future__ import annotations

from fa.score.factors import InputRef, bounded, factor, mk, scaled, zhist

L, M, S = "long", "medium", "short"


def _mi(ctx, key: str, prov: str | None = None) -> list[InputRef]:
    m = ctx.metric(key)
    if m is None:
        return []
    refs = [InputRef(key, m.value, m.unit, prov or ctx.p("fundamentals"), m.formula)]
    refs += [InputRef(k, v, "", prov or ctx.p("fundamentals")) for k, v in (m.inputs or {}).items()]
    return refs


# ------------------------------------------------------------------ valuation
@factor("valuation.dcf_upside", "DCF fair value vs price", "valuation", {L: 1.0, M: 0.5, S: 0.1})
def dcf_upside(ctx):
    up = ctx.s("valuation", "dcf", "upside_pct")
    if up is None:
        return None
    conf = ctx.s("valuation", "blend", "confidence", default=0.7) or 0.7
    return mk("", "", "", up, scaled(up, 0.35), unit="pct", narrative=f"FCFF DCF implies {up:+.0%} vs price (WACC {ctx.s('valuation','inputs','wacc','value'):.1%})",
              inputs=[InputRef("dcf_value_per_share", ctx.s("valuation", "dcf", "value_per_share_gordon"), "USD", ctx.p("valuation")),
                      InputRef("price", ctx.s("valuation", "inputs", "price", "value"), "USD", ctx.p("quote"))], confidence=float(conf))


@factor("valuation.blended_upside", "Blended fair value vs price", "valuation", {L: 1.0, M: 0.6, S: 0.1})
def blended_upside(ctx):
    up = ctx.s("valuation", "blend", "upside_pct")
    if up is None:
        return None
    kept = ctx.s("valuation", "blend", "kept", default={}) or {}
    return mk("", "", "", up, scaled(up, 0.35), unit="pct", narrative=f"{len(kept)} applicable models ({ctx.s('valuation','blend','profile')}): {up:+.0%}",
              inputs=[InputRef(k, v, "USD", ctx.p("valuation")) for k, v in kept.items()],
              confidence=float(ctx.s("valuation", "blend", "confidence", default=0.7)))


@factor("valuation.reverse_dcf_gap", "Implied growth vs delivered growth", "valuation", {L: 1.0, M: 0.5, S: 0.0})
def reverse_dcf_gap(ctx):
    g_imp = ctx.s("valuation", "reverse_dcf", "implied_growth")
    g_hist = ctx.s("valuation", "inputs", "growth_stage1", "value")
    if g_imp is None or g_hist is None:
        return None
    gap = g_hist - g_imp
    return mk("", "", "", gap, scaled(gap, 0.10), unit="pct", narrative=f"price implies {g_imp:.0%} growth vs {g_hist:.0%} delivered",
              inputs=[InputRef("implied_growth", g_imp, "pct", ctx.p("valuation")), InputRef("growth_stage1", g_hist, "pct", ctx.p("valuation"))])


@factor("valuation.pe_vs_history", "P/E vs own history", "valuation", {L: 0.8, M: 0.6, S: 0.2})
def pe_vs_history(ctx):
    pe = ctx.mval("pe")
    hist = [1 / e for e in ctx.mhist("earnings_yield") if e and e > 0]
    if pe is None:
        return None
    n, pct = zhist(pe, hist, direction=-1)
    if n is None:
        ey = ctx.mval("earnings_yield")
        n = scaled(ey, 0.04, center=0.045) if ey is not None else None
        basis = "earnings yield vs 4.5% anchor (no history)"
    else:
        basis = f"{len(hist)} fiscal years"
    return mk("", "", "", pe, n, unit="x", inputs=_mi(ctx, "pe"), narrative=f"P/E {pe:.1f}x", basis=basis, percentile=pct)


@factor("valuation.ev_ebitda_vs_peers", "EV/EBITDA vs peers", "valuation", {L: 1.0, M: 0.6, S: 0.1})
def ev_ebitda_peers(ctx):
    st = ctx.s("valuation", "comps", "stats", "ev_ebitda")
    if not st or st.get("subject") is None or st.get("median") is None:
        return None
    prem = st["subject"] / st["median"] - 1
    return mk("", "", "", st["subject"], scaled(prem, 0.5, direction=-1), unit="x", percentile=st.get("subject_percentile"),
              narrative=f"EV/EBITDA {st['subject']:.1f}x vs peer median {st['median']:.1f}x ({prem:+.0%})", basis=f"{st['n']} peers",
              inputs=[InputRef("ev_ebitda", st["subject"], "x", ctx.p("fundamentals")), InputRef("peer_median_ev_ebitda", st["median"], "x", ctx.p("valuation"))])


@factor("valuation.fcf_yield", "FCF yield", "valuation", {L: 1.0, M: 0.5, S: 0.1})
def fcf_yield(ctx):
    v = ctx.mval("fcf_yield")
    if v is None:
        return None
    rf = ctx.s("valuation", "inputs", "rf", "value") or 0.042
    return mk("", "", "", v, scaled(v - rf, 0.03), unit="pct", inputs=_mi(ctx, "fcf_yield"), narrative=f"FCF yield {v:.1%} vs 10y {rf:.1%}")


@factor("valuation.ev_sales_growth_adj", "EV/Sales vs growth-adjusted peers", "valuation", {L: 0.6, M: 0.4, S: 0.0})
def ev_sales_adj(ctx):
    reg = ctx.s("valuation", "comps", "regression")
    if not reg:
        return None
    prem = reg["premium_vs_fitted"]
    return mk("", "", "", prem, scaled(prem, 0.6, direction=-1), unit="pct", narrative=f"EV/S {reg['actual_ev_sales']:.1f}x vs growth/margin-fitted {reg['fitted_ev_sales']:.1f}x",
              basis=f"regression on {reg['n']} peers", inputs=[InputRef("fitted_ev_sales", reg["fitted_ev_sales"], "x", ctx.p("valuation"))], confidence=0.6)


# ------------------------------------------------------------------ quality
@factor("quality.roic", "Return on invested capital", "quality", {L: 1.0, M: 0.5, S: 0.0})
def roic(ctx):
    v = ctx.mval("roic")
    if v is None:
        return None
    wacc = ctx.s("valuation", "inputs", "wacc", "value") or 0.09
    return mk("", "", "", v, scaled(v - wacc, 0.10), unit="pct", inputs=_mi(ctx, "roic"), narrative=f"ROIC {v:.1%} vs WACC {wacc:.1%}", history=[[k, x] for k, x in (ctx.metric("roic").history or {}).items()])


@factor("quality.gross_margin_trend", "Gross margin trend", "quality", {L: 0.8, M: 0.6, S: 0.0})
def gm_trend(ctx):
    h = ctx.mhist("gross_margin")
    v = ctx.mval("gross_margin")
    if v is None or len(h) < 3:
        return None
    d = h[-1] - (sum(h[-4:-1]) / len(h[-4:-1]))
    return mk("", "", "", d, scaled(d, 0.04), unit="pct", inputs=_mi(ctx, "gross_margin"), narrative=f"GM {v:.1%}, {d:+.1%} vs 3y avg", history=[[k, x] for k, x in (ctx.metric("gross_margin").history or {}).items()])


@factor("quality.operating_margin", "Operating margin level", "quality", {L: 0.8, M: 0.4, S: 0.0})
def op_margin(ctx):
    v = ctx.mval("operating_margin")
    return None if v is None else mk("", "", "", v, bounded(v, -0.10, 0.35), unit="pct", inputs=_mi(ctx, "operating_margin"), narrative=f"operating margin {v:.1%}")


@factor("quality.cash_conversion", "Cash conversion (CFO/NI)", "quality", {L: 0.8, M: 0.4, S: 0.0})
def cash_conv(ctx):
    v = ctx.mval("cash_conversion")
    return None if v is None else mk("", "", "", v, bounded(v, 0.5, 1.5), unit="x", inputs=_mi(ctx, "cash_conversion"), narrative=f"CFO / net income {v:.2f}x")


@factor("quality.piotroski", "Piotroski F-score", "quality", {L: 1.0, M: 0.6, S: 0.0})
def piotroski(ctx):
    q = ctx.s("fundamentals", "quality", "piotroski")
    if not q or not q.get("of"):
        return None
    v = q["score"] / q["of"] * 9
    return mk("", "", "", v, bounded(v, 2, 8), unit="score", narrative=f"F-score {q['score']}/{q['of']}",
              inputs=[InputRef(k, t["pass"], "", ctx.p("fundamentals"), t["detail"]) for k, t in q["tests"].items()])


@factor("quality.beneish", "Beneish M-score (earnings manipulation risk)", "quality", {L: 0.8, M: 0.5, S: 0.0})
def beneish(ctx):
    b = ctx.s("fundamentals", "quality", "beneish")
    if not b or b.get("m") is None:
        return None
    return mk("", "", "", b["m"], scaled(b["m"], 0.8, direction=-1, center=-2.2), unit="score", narrative=f"M-score {b['m']:.2f} ({'flag' if b['flag'] else 'clean'} vs -1.78)",
              inputs=[InputRef(k, v, "", ctx.p("fundamentals")) for k, v in b["inputs"].items()])


@factor("quality.accruals", "Sloan accrual ratio", "quality", {L: 0.7, M: 0.5, S: 0.0})
def accruals(ctx):
    a = ctx.s("fundamentals", "quality", "accruals", "sloan_ratio")
    return None if a is None else mk("", "", "", a, scaled(a, 0.08, direction=-1), unit="pct", narrative=f"accruals {a:+.1%} of assets (lower is better)", inputs=[InputRef("sloan_ratio", a, "pct", ctx.p("fundamentals"))])


# ------------------------------------------------------------------ growth
@factor("growth.revenue_1y", "Revenue growth (last FY)", "growth", {L: 1.0, M: 0.7, S: 0.1})
def rev_1y(ctx):
    v = ctx.mval("revenue_growth_1y")
    return None if v is None else mk("", "", "", v, scaled(v, 0.15), unit="pct", inputs=_mi(ctx, "revenue_growth_1y"), narrative=f"revenue {v:+.1%} YoY", history=[[k, x] for k, x in (ctx.metric("revenue_growth_1y").history or {}).items()])


@factor("growth.revenue_cagr_3y", "Revenue CAGR (3y)", "growth", {L: 1.0, M: 0.4, S: 0.0})
def rev_3y(ctx):
    v = ctx.mval("revenue_cagr_3y")
    return None if v is None else mk("", "", "", v, scaled(v, 0.15), unit="pct", inputs=_mi(ctx, "revenue_cagr_3y"), narrative=f"3y revenue CAGR {v:+.1%}")


@factor("growth.revenue_yoy_q", "Revenue growth (latest quarter YoY)", "growth", {L: 0.6, M: 1.0, S: 0.5})
def rev_q(ctx):
    v = ctx.mval("revenue_growth_yoy_q")
    return None if v is None else mk("", "", "", v, scaled(v, 0.15), unit="pct", inputs=_mi(ctx, "revenue_growth_yoy_q"), narrative=f"latest quarter revenue {v:+.1%} YoY")


@factor("growth.acceleration", "Revenue growth acceleration", "growth", {L: 0.5, M: 1.0, S: 0.5})
def accel(ctx):
    v = ctx.mval("revenue_acceleration")
    return None if v is None else mk("", "", "", v, scaled(v, 0.08), unit="pct", inputs=_mi(ctx, "revenue_acceleration"), narrative=f"YoY growth {'accelerating' if v > 0 else 'decelerating'} by {abs(v):.1%}")


@factor("growth.eps_1y", "EPS growth (last FY)", "growth", {L: 0.8, M: 0.7, S: 0.1})
def eps_1y(ctx):
    v = ctx.mval("eps_diluted_growth_1y")
    return None if v is None else mk("", "", "", v, scaled(v, 0.20), unit="pct", inputs=_mi(ctx, "eps_diluted_growth_1y"), narrative=f"diluted EPS {v:+.1%} YoY")


@factor("growth.fcf_3y", "FCF CAGR (3y)", "growth", {L: 0.8, M: 0.4, S: 0.0})
def fcf_3y(ctx):
    v = ctx.mval("fcf_cagr_3y")
    return None if v is None else mk("", "", "", v, scaled(v, 0.15), unit="pct", inputs=_mi(ctx, "fcf_cagr_3y"), narrative=f"3y FCF CAGR {v:+.1%}")


@factor("growth.segment_momentum", "Segment growth breadth", "growth", {L: 0.6, M: 0.6, S: 0.1})
def seg_mom(ctx):
    seg = ctx.s("fundamentals", "segments")
    if not seg or not seg.get("available"):
        return None
    yoys = [m["yoy"] for b in seg["breakdowns"].values() if b["kind"] == "product" for m in b["members"] if m.get("yoy") is not None]
    if not yoys:
        return None
    share = sum(1 for y in yoys if y > 0) / len(yoys)
    return mk("", "", "", share, bounded(share, 0.2, 0.9), unit="pct", narrative=f"{share:.0%} of product segments growing YoY ({len(yoys)} segments)",
              inputs=[InputRef("segment_yoy", yoys, "", ctx.p("segments"))])


# ------------------------------------------------------------------ balance sheet
@factor("balance_sheet.net_debt_ebitda", "Net debt / EBITDA", "balance_sheet", {L: 1.0, M: 0.7, S: 0.2})
def nd_ebitda(ctx):
    v = ctx.mval("net_debt_to_ebitda")
    if v is None:
        return None
    return mk("", "", "", v, bounded(v, 4.0, -1.0), unit="x", inputs=_mi(ctx, "net_debt_to_ebitda"), narrative=f"net debt/EBITDA {v:.1f}x")


@factor("balance_sheet.interest_coverage", "Interest coverage", "balance_sheet", {L: 1.0, M: 0.6, S: 0.1})
def icov(ctx):
    v = ctx.mval("interest_coverage")
    if v is None:
        return None
    return mk("", "", "", v, bounded(min(v, 30), 1.0, 12.0), unit="x", inputs=_mi(ctx, "interest_coverage"), narrative=f"EBIT / interest {v:.1f}x")


@factor("balance_sheet.current_ratio", "Current ratio", "balance_sheet", {L: 0.6, M: 0.5, S: 0.2})
def cr(ctx):
    v = ctx.mval("current_ratio")
    return None if v is None else mk("", "", "", v, bounded(v, 0.8, 2.0), unit="x", inputs=_mi(ctx, "current_ratio"), narrative=f"current ratio {v:.2f}")


@factor("balance_sheet.altman", "Altman Z", "balance_sheet", {L: 1.0, M: 0.7, S: 0.2})
def altman(ctx):
    a = ctx.s("fundamentals", "quality", "altman")
    if not a or a.get("z") is None:
        return None
    if ctx.s("valuation", "profile", "primary") in ("bank", "insurer"):
        return mk("", "", "", a["z"], None, unit="score", narrative="Altman Z is not defined for banks/insurers", status="SUPPRESSED")
    return mk("", "", "", a["z"], bounded(a["z"], 1.5, 4.0), unit="score", narrative=f"Altman {a['model']} Z={a['z']:.2f} ({a['zone']})",
              inputs=[InputRef(k, v, "", ctx.p("fundamentals")) for k, v in a["inputs"].items()])


@factor("balance_sheet.net_cash_pct_mcap", "Net cash % of market cap", "balance_sheet", {L: 0.6, M: 0.4, S: 0.1})
def net_cash(ctx):
    nc, mc = ctx.mval("net_cash"), ctx.mval("market_cap")
    if nc is None or not mc:
        return None
    v = nc / mc
    return mk("", "", "", v, scaled(v, 0.15), unit="pct", inputs=_mi(ctx, "net_cash"), narrative=f"net cash {v:+.1%} of market cap")


# ------------------------------------------------------------------ capital allocation
@factor("capital_allocation.shareholder_yield", "Shareholder yield", "capital_allocation", {L: 1.0, M: 0.6, S: 0.1})
def sh_yield(ctx):
    v = ctx.mval("shareholder_yield")
    return None if v is None else mk("", "", "", v, scaled(v, 0.04), unit="pct", inputs=_mi(ctx, "shareholder_yield"), narrative=f"dividends + buybacks {v:.1%} of market cap")


@factor("capital_allocation.dilution", "Share count change", "capital_allocation", {L: 1.0, M: 0.7, S: 0.2})
def dilution(ctx):
    v = ctx.mval("share_count_change_1y")
    return None if v is None else mk("", "", "", v, scaled(v, 0.04, direction=-1), unit="pct", inputs=_mi(ctx, "share_count_change_1y"), narrative=f"diluted shares {v:+.1%} YoY")


@factor("capital_allocation.sbc", "Stock-based comp % revenue", "capital_allocation", {L: 0.7, M: 0.4, S: 0.0})
def sbc(ctx):
    v = ctx.mval("sbc_pct_rev")
    return None if v is None else mk("", "", "", v, bounded(v, 0.12, 0.0), unit="pct", inputs=_mi(ctx, "sbc_pct_rev"), narrative=f"SBC {v:.1%} of revenue")


@factor("capital_allocation.reinvestment", "Capex / D&A", "capital_allocation", {L: 0.5, M: 0.3, S: 0.0})
def reinvest(ctx):
    v = ctx.mval("capex_to_da")
    return None if v is None else mk("", "", "", v, bounded(v, 0.6, 1.6), unit="x", inputs=_mi(ctx, "capex_to_da"), narrative=f"capex {v:.2f}x D&A")


# ------------------------------------------------------------------ analysts / ownership
@factor("analysts.consensus", "Analyst consensus rating", "analysts", {L: 0.6, M: 1.0, S: 0.4})
def consensus(ctx):
    c = ctx.s("analysts", "consensus")
    if not c or not c.get("n"):
        return None
    n = c["n"]
    score_ = (2 * c["strong_buy"] + c["buy"] - c["sell"] - 2 * c["strong_sell"]) / (2 * n)
    return mk("", "", "", score_, scaled(score_, 0.5), unit="score", narrative=f"{n} analysts: {c['strong_buy']}SB/{c['buy']}B/{c['hold']}H/{c['sell']}S/{c['strong_sell']}SS",
              inputs=[InputRef(k, c[k], "", ctx.p("analysts")) for k in ("strong_buy", "buy", "hold", "sell", "strong_sell")], confidence=min(1.0, n / 10))


@factor("analysts.target_upside", "Consensus price target vs price", "analysts", {L: 0.7, M: 1.0, S: 0.4})
def target_upside(ctx):
    t = ctx.s("analysts", "targets")
    price = ctx.s("quote", "price")
    if not t or not t.get("mean") or not price:
        return None
    up = t["mean"] / price - 1
    return mk("", "", "", up, scaled(up, 0.20), unit="pct", narrative=f"mean target ${t['mean']:.0f} ({up:+.0%}), range ${t.get('low', 0):.0f}-{t.get('high', 0):.0f}",
              inputs=[InputRef("target_mean", t["mean"], "USD", ctx.p("analysts")), InputRef("price", price, "USD", ctx.p("quote"))], confidence=0.7)


@factor("analysts.recent_actions", "Recent upgrades vs downgrades", "analysts", {L: 0.3, M: 1.0, S: 0.8})
def actions(ctx):
    a = ctx.s("analysts", "recent_actions")
    if not a or (a.get("upgrades", 0) + a.get("downgrades", 0)) == 0:
        if ctx.s("analysts", "consensus") is not None:
            return mk("", "", "", 0.0, 0.0, unit="score", narrative="no upgrades or downgrades in the last 90 days (see consensus shift / revisions)", inputs=[InputRef("recent_actions", a, "", ctx.p("analysts"))], confidence=0.3)
        return None
    up, dn = a["upgrades"], a["downgrades"]
    v = (up - dn) / (up + dn)
    return mk("", "", "", v, scaled(v, 0.6), unit="score", narrative=f"last 90d: {up} upgrades, {dn} downgrades", inputs=[InputRef("upgrades", up, "", ctx.p("analysts")), InputRef("downgrades", dn, "", ctx.p("analysts"))])


@factor("analysts.insider_net", "Insider net buying (6m)", "analysts", {L: 0.8, M: 1.0, S: 0.4})
def insider(ctx):
    i = ctx.s("ownership", "insiders")
    if not i or i.get("net_shares_6m") is None or not i.get("n_txns_6m"):
        return None
    v = i["net_value_6m"]
    mc = ctx.mval("market_cap") or 1
    rel = v / mc
    return mk("", "", "", v, scaled(rel, 0.0005), unit="USD", narrative=f"net insider {'buying' if v > 0 else 'selling'} ${abs(v)/1e6:.1f}M over 6m ({i['n_txns_6m']} txns; sells are routine, buys are informative)",
              inputs=[InputRef("net_value_6m", v, "USD", ctx.p("ownership"))], confidence=0.6 if v < 0 else 0.9)

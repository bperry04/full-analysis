"""FCFF DCF with a fading growth stage, Gordon and exit-multiple terminals, and a WACC × g sensitivity grid.
Also the FCFE variant (discount at cost of equity) and reverse DCF (what growth does the price imply?)."""
from __future__ import annotations

from typing import Any

import numpy as np

from fa.compute.valuation.inputs import ValuationInputs


def project(rev0: float, g1: float, g_term: float, fade_years: int, margin: float, years: int = 10, margin_target: float | None = None) -> list[dict[str, float]]:
    """Revenue grows at g1 fading linearly to g_term; the FCF margin ramps linearly from `margin` to `margin_target`."""
    rows = []
    rev = rev0
    m_end = margin if margin_target is None else margin_target
    for y in range(1, years + 1):
        g = g1 + (g_term - g1) * min(y - 1, fade_years) / max(fade_years, 1)
        m = margin + (m_end - margin) * min(y, fade_years) / max(fade_years, 1)
        rev = rev * (1 + g)
        rows.append({"year": y, "growth": g, "margin": m, "revenue": rev, "fcf": rev * m})
    return rows


def dcf(inp: ValuationInputs, years: int = 10, exit_multiple: float | None = None, margin: float | None = None,
        g1: float | None = None, g_term: float | None = None, wacc: float | None = None, target_margin: float | None = None) -> dict[str, Any]:
    rev0 = inp.revenue_ttm.value
    m = margin if margin is not None else inp.fcf_margin.value
    if not rev0:
        return {"available": False, "reason": "no TTM revenue in the XBRL data"}
    if m is None:
        m = 0.0
    flags: list[str] = []
    notes: list[str] = []
    fade = int(inp.fade_years.value or 10)
    m_target = target_margin
    if m_target is None and m <= 0:
        # cash-burning today: value the business on a normalized margin it converges to, and say so loudly
        ebit_m, tr = inp.ebit_margin.value, inp.tax_rate.value or 0.21
        m_target = ebit_m * (1 - tr) if ebit_m and ebit_m > 0 else 0.05
        flags.append("ESTIMATED")
        notes.append(f"FCF margin today is {m:.1%} (cash-burning). Cash flows are modelled ramping to a normalized {m_target:.1%} "
                     f"({'after-tax operating margin' if ebit_m and ebit_m > 0 else 'default 5%'}) over {fade} years — treat the value as an estimate and edit the target margin.")
    g1 = g1 if g1 is not None else inp.growth_stage1.value
    gt = g_term if g_term is not None else inp.growth_terminal.value
    r = wacc if wacc is not None else inp.wacc.value
    if r is None or r <= gt + 0.005:
        return {"available": False, "reason": f"WACC {r:.1%} must exceed terminal growth {gt:.1%} by at least 0.5% — raise WACC or lower terminal growth" if r is not None else "no WACC"}
    rows = project(rev0, g1, gt, fade, m, years, m_target)
    disc = [(1 + r) ** -y["year"] for y in rows]
    pv_fcf = sum(y["fcf"] * d for y, d in zip(rows, disc))
    fcf_n = rows[-1]["fcf"]
    tv_gordon = fcf_n * (1 + gt) / (r - gt)
    pv_tv_gordon = tv_gordon * disc[-1]
    ev_gordon = pv_fcf + pv_tv_gordon
    out: dict[str, Any] = {"available": True, "projection": rows, "pv_fcf": pv_fcf, "pv_terminal_gordon": pv_tv_gordon, "ev_gordon": ev_gordon,
                           "terminal_share_gordon": pv_tv_gordon / ev_gordon if ev_gordon else None, "wacc": r, "g1": g1, "g_terminal": gt, "margin": m,
                           "margin_target": m_target if m_target is not None else m, "flags": flags, "notes": notes}
    if ev_gordon <= 0:
        out["notes"].append("enterprise value is not positive under these assumptions")
    if exit_multiple:
        # terminal value as an EV/EBITDA multiple on year-N EBITDA (EBITDA margin from TTM, normalized if negative)
        em = inp.extra.get("ebitda_margin")
        em = em if em is not None and em > 0 else max((out["margin_target"] or 0.0) + 0.05, 0.08)
        tv_exit = rows[-1]["revenue"] * em * exit_multiple
        out["ev_exit"] = pv_fcf + tv_exit * disc[-1]
        out["exit_multiple"] = exit_multiple
        out["exit_ebitda_margin"] = em
    nd = inp.net_debt.value or 0.0
    sh = inp.shares.value
    for k in ("ev_gordon", "ev_exit"):
        if k in out and sh:
            out[k.replace("ev_", "value_per_share_")] = (out[k] - nd) / sh
    fv = out.get("value_per_share_gordon")
    if fv and inp.price.value:
        out["upside_pct"] = fv / inp.price.value - 1
    return out


def scenarios(inp: ValuationInputs, target_margin: float | None = None) -> dict[str, Any]:
    """Bear / base / bull DCF with explicit probabilities (25/50/25): growth ±8 pts, margin ×0.8/×1.2, WACC ±1 pt."""
    base = dcf(inp, target_margin=target_margin)
    if not base.get("available"):
        return {"available": False, "reason": base.get("reason")}
    mt = base["margin_target"]
    g1, w = base["g1"], base["wacc"]
    cases = {
        "bear": dict(g1=g1 - 0.08, target_margin=mt * 0.8 if mt > 0 else mt - 0.02, wacc=w + 0.01, p=0.25),
        "base": dict(g1=g1, target_margin=mt, wacc=w, p=0.50),
        "bull": dict(g1=g1 + 0.08, target_margin=mt * 1.2 if mt > 0 else mt + 0.04, wacc=max(w - 0.01, base["g_terminal"] + 0.01), p=0.25),
    }
    out: dict[str, Any] = {"available": True, "cases": {}}
    ev = 0.0
    for name, c in cases.items():
        r = dcf(inp, g1=c["g1"], wacc=c["wacc"], target_margin=c["target_margin"])
        v = r.get("value_per_share_gordon")
        out["cases"][name] = {"growth": c["g1"], "target_margin": c["target_margin"], "wacc": c["wacc"], "probability": c["p"], "value_per_share": v}
        ev += (v or 0.0) * c["p"]
    out["value_per_share"] = ev
    out["formula"] = "probability-weighted (25/50/25) DCF across bear / base / bull growth, margin and WACC"
    return out


def sensitivity(inp: ValuationInputs, wacc_steps=(-0.02, -0.01, 0, 0.01, 0.02), g_steps=(-0.01, -0.005, 0, 0.005, 0.01), **kw: Any) -> dict[str, Any]:
    base_w, base_g = inp.wacc.value, inp.growth_terminal.value
    grid = []
    for dw in wacc_steps:
        row = []
        for dg in g_steps:
            res = dcf(inp, wacc=base_w + dw, g_term=base_g + dg, **kw)
            row.append(res.get("value_per_share_gordon"))
        grid.append(row)
    return {"wacc": [base_w + d for d in wacc_steps], "g": [base_g + d for d in g_steps], "values": grid}


def fcfe(inp: ValuationInputs, years: int = 10) -> dict[str, Any]:
    """Equity DCF: FCFE ≈ FCF − after-tax interest + net borrowing (assumed to keep leverage constant), at cost of equity."""
    rev0, m = inp.revenue_ttm.value, inp.fcf_margin.value
    ke, gt = inp.cost_of_equity.value, inp.growth_terminal.value
    if not rev0 or m is None or ke is None or ke <= gt + 0.005:
        return {"available": False}
    rows = project(rev0, inp.growth_stage1.value, gt, int(inp.fade_years.value or 10), m, years)
    wd = inp.weight_debt.value or 0.0
    # net borrowing to maintain capital structure ≈ wd × reinvestment; approximate FCFE = FCF × (1 - wd × 0.3)
    adj = 1 - 0.3 * wd
    disc = [(1 + ke) ** -y["year"] for y in rows]
    pv = sum(y["fcf"] * adj * d for y, d in zip(rows, disc))
    tv = rows[-1]["fcf"] * adj * (1 + gt) / (ke - gt) * disc[-1]
    eq = pv + tv
    sh = inp.shares.value
    return {"available": True, "equity_value": eq, "value_per_share": (eq / sh) if sh else None, "ke": ke, "fcfe_adjustment": adj}


def reverse_dcf(inp: ValuationInputs, years: int = 10) -> dict[str, Any]:
    """Solve the stage-1 growth rate that makes the Gordon DCF equal the current market cap."""
    mc = inp.market_cap.value
    if not mc or not inp.revenue_ttm.value:
        return {"available": False, "reason": "needs market cap and revenue"}
    nd = inp.net_debt.value or 0.0
    target_ev = mc + nd
    lo, hi = -0.30, 0.80
    def f(g):
        r = dcf(inp, years=years, g1=g)          # uses the same normalized-margin ramp when FCF is negative
        return (r.get("ev_gordon") or 0) - target_ev
    if f(lo) > 0:
        return {"available": True, "implied_growth": lo, "note": "price implies growth below -30%"}
    if f(hi) < 0:
        return {"available": True, "implied_growth": hi, "note": "price implies growth above 80%"}
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    g = (lo + hi) / 2
    return {"available": True, "implied_growth": g, "historical_growth": inp.extra.get("revenue_cagr_3y"), "fcf_margin": inp.fcf_margin.value,
            "wacc": inp.wacc.value, "note": f"stage-1 revenue growth (fading to {inp.growth_terminal.value:.1%} over {int(inp.fade_years.value)}y) that justifies today's EV"}


def implied_margin(inp: ValuationInputs) -> dict[str, Any]:
    """Alternative reverse-DCF: FCF margin required at historical growth to justify the price."""
    mc = inp.market_cap.value
    if not mc or not inp.revenue_ttm.value:
        return {"available": False}
    target_ev = mc + (inp.net_debt.value or 0.0)
    lo, hi = -0.2, 0.8
    def f(m):
        return (dcf(inp, margin=m).get("ev_gordon") or 0) - target_ev
    if f(hi) < 0:
        return {"available": True, "implied_fcf_margin": hi, "note": "requires >80% margin"}
    for _ in range(60):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return {"available": True, "implied_fcf_margin": (lo + hi) / 2, "current_fcf_margin": inp.fcf_margin.value}

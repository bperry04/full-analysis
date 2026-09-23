"""Absolute and relative valuation models beyond the core DCF.

Each returns {"available": bool, "reason": str?, "value_per_share": float?, ...inputs}. `applies` decisions live in
profile.py; models here only say whether they *could* compute.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from fa.compute.fundamentals.statements import Fundamentals
from fa.compute.valuation.inputs import ValuationInputs


def _v(x):
    try:
        f = float(x)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ dividend / earnings power
def ddm(inp: ValuationInputs) -> dict[str, Any]:
    dps, ke, roe, payout = inp.dps.value, inp.cost_of_equity.value, inp.roe.value, inp.payout.value
    if not dps or dps <= 0 or ke is None:
        return {"available": False, "reason": "no dividend"}
    g_sust = (roe * (1 - payout)) if roe is not None and payout is not None else None
    g = min(g_sust if g_sust is not None else inp.growth_terminal.value, ke - 0.01, 0.08)
    g = max(g, 0.0)
    v = dps * (1 + g) / (ke - g)
    g1 = min(max(g_sust if g_sust is not None else 0.0, inp.growth_stage1.value or 0.0, 0.0), 0.15)
    gt = min(inp.growth_terminal.value, ke - 0.01)
    pv, d = 0.0, dps
    for y in range(1, 6):
        d *= 1 + g1
        pv += d / (1 + ke) ** y
    tv = d * (1 + gt) / (ke - gt) / (1 + ke) ** 5
    return {"available": True, "gordon_value": v, "two_stage_value": pv + tv, "value_per_share": pv + tv, "g_sustainable": g_sust, "g_used": g, "ke": ke, "dps": dps,
            "formula": "2-stage: 5y DPS growth at max(sustainable, stage-1) capped 15%, then Gordon at terminal g"}


def residual_income(inp: ValuationInputs, years: int = 5) -> dict[str, Any]:
    bv, roe, ke, payout = inp.bvps.value, inp.roe.value, inp.cost_of_equity.value, inp.payout.value or 0.0
    if not bv or bv <= 0 or roe is None or ke is None:
        return {"available": False, "reason": "needs positive book value and ROE"}
    roe_t, pv, b = roe, 0.0, bv
    fade = (roe - ke) / years
    for y in range(1, years + 1):
        pv += (roe_t - ke) * b / (1 + ke) ** y
        b = b * (1 + roe_t * (1 - payout))
        roe_t -= fade
    ri_last = (roe - ke) * b * 0.5
    tv = sum(ri_last / (1 + ke) ** y for y in range(years + 1, years + 6))
    return {"available": True, "value_per_share": bv + pv + tv, "bvps": bv, "roe": roe, "ke": ke, "pv_residual_income": pv, "terminal": tv,
            "formula": "BVPS + Σ(ROE−ke)·BV, abnormal return fading to zero over 5y, half-strength for 5 more"}


def epv(inp: ValuationInputs) -> dict[str, Any]:
    rev, m, tr, wacc = inp.revenue_ttm.value, inp.ebit_margin.value, inp.tax_rate.value, inp.wacc.value
    if not rev or m is None or not wacc:
        return {"available": False, "reason": "needs revenue, operating margin and WACC"}
    if m <= 0:
        return {"available": False, "reason": "negative operating margin — no earnings power to capitalize"}
    ebit_norm = rev * m
    ev = ebit_norm * (1 - (tr or 0.21)) / wacc
    eq = ev - (inp.net_debt.value or 0.0)
    sh = inp.shares.value
    return {"available": True, "ev": ev, "equity_value": eq, "value_per_share": (eq / sh) if sh else None, "normalized_ebit": ebit_norm, "wacc": wacc,
            "formula": "EBIT × (1−t) / WACC − net debt (zero-growth value of current earnings power)"}


def graham_number(inp: ValuationInputs) -> dict[str, Any]:
    eps, bv = inp.eps_ttm.value, inp.bvps.value
    if not eps or eps <= 0 or not bv or bv <= 0:
        return {"available": False, "reason": "needs positive EPS and book value"}
    return {"available": True, "value_per_share": (22.5 * eps * bv) ** 0.5, "formula": "√(22.5 × EPS × BVPS)"}


def justified_pe(inp: ValuationInputs) -> dict[str, Any]:
    """Gordon-growth justified P/E = payout × (1+g) / (ke − g), applied to TTM EPS."""
    eps, ke, payout = inp.eps_ttm.value, inp.cost_of_equity.value, inp.payout.value
    if not eps or eps <= 0 or ke is None:
        return {"available": False, "reason": "needs positive EPS"}
    if not payout or payout <= 0:
        return {"available": False, "reason": "no dividend payout — justified P/E is undefined; use DCF / EPV"}
    g = min(max(inp.growth_terminal.value, 0.0), ke - 0.01)
    pe = payout * (1 + g) / (ke - g)
    return {"available": True, "justified_pe": pe, "value_per_share": pe * eps, "formula": "P/E* = payout × (1+g) / (ke − g); value = P/E* × EPS"}


def justified_pb(inp: ValuationInputs) -> dict[str, Any]:
    """P/B* = (ROE − g) / (ke − g): the standard bank / insurer cross-check."""
    bv, roe, ke = inp.bvps.value, inp.roe.value, inp.cost_of_equity.value
    if not bv or bv <= 0 or roe is None or ke is None:
        return {"available": False, "reason": "needs positive book value and ROE"}
    g = min(max(inp.growth_terminal.value, 0.0), ke - 0.01)
    if roe <= g:
        return {"available": True, "justified_pb": (roe - g) / (ke - g), "value_per_share": bv * max((roe - g) / (ke - g), 0.2), "formula": "P/B* = (ROE − g)/(ke − g) (ROE below g → floored at 0.2× book)", "note": "ROE below growth"}
    pb = (roe - g) / (ke - g)
    return {"available": True, "justified_pb": pb, "value_per_share": pb * bv, "formula": "P/B* = (ROE − g) / (ke − g); value = P/B* × BVPS"}


def peg_value(inp: ValuationInputs) -> dict[str, Any]:
    """Fair P/E = growth (in %) × PEG of 1, applied to TTM EPS — a growth investor's rule of thumb."""
    eps, g = inp.eps_ttm.value, inp.growth_stage1.value
    if not eps or eps <= 0:
        return {"available": False, "reason": "needs positive EPS"}
    if g is None or g <= 0.03:
        return {"available": False, "reason": "growth too low for a PEG-based value"}
    pe = min(g * 100, 50)
    return {"available": True, "fair_pe": pe, "value_per_share": pe * eps, "formula": "P/E = growth% × 1.0 (PEG 1), capped at 50× ; value = P/E × EPS"}


# ------------------------------------------------------------------ asset-based
def ncav(fund: Fundamentals, shares: float | None) -> dict[str, Any]:
    ca, tl = _v(fund.latest("current_assets")), _v(fund.latest("total_liabilities"))
    if ca is None or tl is None or not shares:
        return {"available": False, "reason": "needs current assets, total liabilities and shares"}
    v = (ca - tl) / shares
    return {"available": v > 0, "value_per_share": v if v > 0 else None, "ncav": ca - tl, "reason": None if v > 0 else "liabilities exceed current assets — no net-net value",
            "formula": "(current assets − total liabilities) / shares (Graham net-net liquidation floor)"}


def tangible_book(fund: Fundamentals, shares: float | None) -> dict[str, Any]:
    eq, gw, intang = _v(fund.latest("equity")), _v(fund.latest("goodwill")) or 0.0, _v(fund.latest("intangibles")) or 0.0
    if eq is None or not shares:
        return {"available": False, "reason": "needs equity and shares"}
    tb = eq - gw - intang
    return {"available": tb > 0, "value_per_share": tb / shares if tb > 0 else None, "tangible_book": tb, "reason": None if tb > 0 else "tangible book is negative",
            "formula": "(equity − goodwill − intangibles) / shares"}


def ffo_cap(fund: Fundamentals, shares: float | None, rf: float, spread: float = 0.035, dps: float | None = None) -> dict[str, Any]:
    """REIT: FFO ≈ net income + D&A, capitalized at a cap-rate-like yield (rf + spread), cross-checked with the dividend."""
    ni, da = _v(fund.latest("net_income")), _v(fund.latest("da"))
    if ni is None or da is None or not shares:
        return {"available": False, "reason": "needs net income and D&A"}
    ffo = ni + da
    if ffo <= 0:
        return {"available": False, "reason": "FFO not positive"}
    y = rf + spread
    return {"available": True, "ffo": ffo, "ffo_per_share": ffo / shares, "cap_yield": y, "value_per_share": ffo / shares / y, "implied_p_ffo": 1 / y,
            "formula": f"FFO/share / (rf + {spread:.1%}) — FFO = net income + D&A"}


def cash_runway(fund: Fundamentals) -> dict[str, Any]:
    cash, sti, fcf = _v(fund.latest("cash")) or 0.0, _v(fund.latest("st_investments")) or 0.0, _v(fund.latest("fcf"))
    if fcf is None or fcf >= 0:
        return {"available": False, "reason": "not burning cash"}
    burn = -fcf
    return {"available": True, "cash": cash + sti, "annual_burn": burn, "runway_years": (cash + sti) / burn if burn else None,
            "formula": "(cash + short-term investments) / annual FCF burn"}


# ------------------------------------------------------------------ own-history multiple reversion
def historical_multiples(fund: Fundamentals, daily: pd.DataFrame | None, price: float | None, shares: float | None, ttm: dict[str, float | None], years: int = 7) -> dict[str, Any]:
    """Value at the company's own median P/E, P/S, EV/EBITDA and P/B over the last N fiscal years (price at each FY end)."""
    if daily is None or daily.empty or not price or not shares or fund.annual.empty:
        return {"available": False, "reason": "needs price history, shares and annual statements"}
    px = daily.set_index(pd.to_datetime(daily["ts"]).dt.tz_convert(None).dt.normalize())["close"].astype(float).sort_index()
    cols = list(fund.annual.columns)[-years:]
    rows = []
    for end in cols:
        d = pd.Timestamp(end)
        p = px[px.index <= d]
        if p.empty:
            continue
        p0 = float(p.iloc[-1])
        g = lambda k: (float(fund.annual.loc[k, end]) if k in fund.annual.index and pd.notna(fund.annual.loc[k, end]) else None)  # noqa: E731
        sh = g("shares_diluted") or g("shares_outstanding")
        if not sh:
            continue
        mc = p0 * sh
        eps, rev, ebitda, eq, debt, cash = g("eps_diluted"), g("revenue"), g("ebitda"), g("equity"), g("total_debt"), g("cash")
        ev = mc + (debt or 0) - (cash or 0)
        rows.append({"fy_end": str(end), "price": p0, "pe": (p0 / eps) if eps and eps > 0 else None, "ps": (mc / rev) if rev else None,
                     "ev_ebitda": (ev / ebitda) if ebitda and ebitda > 0 else None, "pb": (mc / eq) if eq and eq > 0 else None})
    if len(rows) < 3:
        return {"available": False, "reason": "fewer than 3 fiscal years with prices"}
    h = pd.DataFrame(rows)
    med = {k: float(h[k].dropna().median()) for k in ("pe", "ps", "ev_ebitda", "pb") if h[k].notna().sum() >= 3}
    implied = {}
    eps, rev, ebitda, eq, nd = ttm.get("eps_diluted"), ttm.get("revenue"), ttm.get("ebitda"), ttm.get("equity"), ttm.get("net_debt") or 0.0
    if "pe" in med and eps and eps > 0:
        implied["pe"] = med["pe"] * eps
    if "ps" in med and rev:
        implied["ps"] = med["ps"] * rev / shares
    if "ev_ebitda" in med and ebitda and ebitda > 0:
        implied["ev_ebitda"] = (med["ev_ebitda"] * ebitda - nd) / shares
    if "pb" in med and eq and eq > 0:
        implied["pb"] = med["pb"] * eq / shares
    if not implied:
        return {"available": False, "reason": "no multiple is computable on TTM figures (losses / negative book)", "history": h}
    vals = list(implied.values())
    current = {"pe": (price / eps) if eps and eps > 0 else None, "ps": price * shares / rev if rev else None, "ev_ebitda": ((price * shares + nd) / ebitda) if ebitda and ebitda > 0 else None,
               "pb": price * shares / eq if eq and eq > 0 else None}
    return {"available": True, "value_per_share": float(np.median(vals)), "implied": implied, "median_multiples": med, "current_multiples": current, "history": h, "n_years": len(h),
            "formula": f"median of the company's own {len(h)}-year median multiples applied to TTM (P/E, P/S, EV/EBITDA, P/B)"}

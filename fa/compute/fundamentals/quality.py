"""Earnings-quality and distress models: Piotroski F, Altman Z / Z'', Beneish M, Sloan accruals, cash conversion.

Every output carries the inputs it used so the UI can trace each score to line items.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from fa.compute.fundamentals.statements import Fundamentals


def _v(x: Any) -> float | None:
    try:
        f = float(x)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _a(fund: Fundamentals, k: str, n: int = 0) -> float | None:
    return _v(fund.annual_value(k, n))


def piotroski(fund: Fundamentals) -> dict[str, Any]:
    """Nine binary tests on the latest two fiscal years."""
    tests: dict[str, dict[str, Any]] = {}

    def add(name: str, cond: bool | None, detail: str):
        tests[name] = {"pass": None if cond is None else bool(cond), "detail": detail}

    ni, ni1 = _a(fund, "net_income"), _a(fund, "net_income", 1)
    ta, ta1, ta2 = _a(fund, "total_assets"), _a(fund, "total_assets", 1), _a(fund, "total_assets", 2)
    cfo = _a(fund, "cfo")
    roa = ni / ta1 if ni is not None and ta1 else None
    roa1 = ni1 / ta2 if ni1 is not None and ta2 else None
    add("roa_positive", roa > 0 if roa is not None else None, f"ROA {roa:.3f}" if roa is not None else "n/a")
    add("cfo_positive", cfo > 0 if cfo is not None else None, f"CFO {cfo:,.0f}" if cfo is not None else "n/a")
    add("roa_improving", roa > roa1 if roa is not None and roa1 is not None else None, f"{roa1:.3f} -> {roa:.3f}" if roa is not None and roa1 is not None else "n/a")
    add("accruals", cfo / ta1 > roa if cfo is not None and ta1 and roa is not None else None, "CFO/assets > ROA")
    ltd, ltd1 = _a(fund, "lt_debt"), _a(fund, "lt_debt", 1)
    lev, lev1 = (ltd / ta if ltd is not None and ta else 0.0), (ltd1 / ta1 if ltd1 is not None and ta1 else 0.0)
    add("leverage_down", lev <= lev1 if ta and ta1 else None, f"LTD/assets {lev1:.3f} -> {lev:.3f}")
    ca, cl, ca1, cl1 = _a(fund, "current_assets"), _a(fund, "current_liabilities"), _a(fund, "current_assets", 1), _a(fund, "current_liabilities", 1)
    cr, cr1 = (ca / cl if ca and cl else None), (ca1 / cl1 if ca1 and cl1 else None)
    add("liquidity_up", cr > cr1 if cr is not None and cr1 is not None else None, f"current ratio {cr1:.2f} -> {cr:.2f}" if cr and cr1 else "n/a")
    sh, sh1 = _a(fund, "shares_diluted"), _a(fund, "shares_diluted", 1)
    add("no_dilution", sh <= sh1 * 1.005 if sh and sh1 else None, f"diluted shares {sh1:,.0f} -> {sh:,.0f}" if sh and sh1 else "n/a")
    gp, gp1, rev, rev1 = _a(fund, "gross_profit"), _a(fund, "gross_profit", 1), _a(fund, "revenue"), _a(fund, "revenue", 1)
    gm, gm1 = (gp / rev if gp is not None and rev else None), (gp1 / rev1 if gp1 is not None and rev1 else None)
    add("gross_margin_up", gm > gm1 if gm is not None and gm1 is not None else None, f"GM {gm1:.3f} -> {gm:.3f}" if gm and gm1 else "n/a")
    at, at1 = (rev / ta1 if rev and ta1 else None), (rev1 / ta2 if rev1 and ta2 else None)
    add("asset_turnover_up", at > at1 if at is not None and at1 is not None else None, f"turnover {at1:.3f} -> {at:.3f}" if at and at1 else "n/a")
    passed = sum(1 for t in tests.values() if t["pass"])
    evaluated = sum(1 for t in tests.values() if t["pass"] is not None)
    return {"score": passed, "of": evaluated, "tests": tests}


def altman_z(fund: Fundamentals, market_cap: float | None) -> dict[str, Any]:
    ta = _v(fund.latest("total_assets"))
    tl = _v(fund.latest("total_liabilities"))
    ca, cl = _v(fund.latest("current_assets")), _v(fund.latest("current_liabilities"))
    re_ = _v(fund.latest("retained_earnings"))
    ebit = _v(fund.latest("ebit")) or _v(fund.latest("operating_income"))
    rev = _v(fund.latest("revenue"))
    if not ta or tl is None:
        return {"z": None, "zone": None, "inputs": {}}
    wc = (ca - cl) if ca is not None and cl is not None else None
    x1 = wc / ta if wc is not None else 0.0
    x2 = (re_ or 0.0) / ta
    x3 = (ebit or 0.0) / ta
    x4 = (market_cap / tl) if market_cap and tl else None
    x5 = (rev or 0.0) / ta
    if x4 is not None:
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        zone = "safe" if z > 2.99 else ("grey" if z > 1.81 else "distress")
        model = "Z (public manufacturing, 1968)"
    else:
        bv_eq = _v(fund.latest("equity")) or 0.0
        z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * (bv_eq / tl if tl else 0.0)
        zone = "safe" if z > 2.6 else ("grey" if z > 1.1 else "distress")
        model = "Z'' (non-manufacturing / book equity)"
    return {"z": round(z, 2), "zone": zone, "model": model, "inputs": {"x1_wc_ta": x1, "x2_re_ta": x2, "x3_ebit_ta": x3, "x4_mve_tl": x4, "x5_sales_ta": x5}}


def beneish_m(fund: Fundamentals) -> dict[str, Any]:
    """Eight-variable M-score on the last two fiscal years. > -1.78 suggests possible manipulation."""
    def a(k, n=0):
        return _a(fund, k, n)
    rev, rev1 = a("revenue"), a("revenue", 1)
    rec, rec1 = a("receivables"), a("receivables", 1)
    cogs, cogs1 = a("cogs"), a("cogs", 1)
    ca, ca1 = a("current_assets"), a("current_assets", 1)
    ppe, ppe1 = a("ppe_net"), a("ppe_net", 1)
    ta, ta1 = a("total_assets"), a("total_assets", 1)
    da, da1 = a("da"), a("da", 1)
    sga, sga1 = a("sga"), a("sga", 1)
    ltd, ltd1 = a("lt_debt"), a("lt_debt", 1)
    cl, cl1 = a("current_liabilities"), a("current_liabilities", 1)
    ni, cfo = a("net_income"), a("cfo")
    need = [rev, rev1, ta, ta1, ni, cfo]
    if any(x is None for x in need) or not rev1 or not ta or not ta1:
        return {"m": None, "flag": None, "inputs": {}}
    dsri = ((rec or 0) / rev) / ((rec1 or 0) / rev1) if rec1 else 1.0
    # gross-margin index needs COGS; filers without it (airlines, banks) get a neutral 1.0
    gmi = ((rev1 - cogs1) / rev1) / ((rev - cogs) / rev) if (cogs is not None and cogs1 is not None and (rev - cogs)) else 1.0
    aqi_now = 1 - ((ca or 0) + (ppe or 0)) / ta
    aqi_prev = 1 - ((ca1 or 0) + (ppe1 or 0)) / ta1
    aqi = aqi_now / aqi_prev if aqi_prev else 1.0
    sgi = rev / rev1
    depi = ((da1 or 0) / ((da1 or 0) + (ppe1 or 1))) / ((da or 0) / ((da or 0) + (ppe or 1))) if (da and da1) else 1.0
    sgai = ((sga or 0) / rev) / ((sga1 or 0) / rev1) if sga1 else 1.0
    lvgi = (((ltd or 0) + (cl or 0)) / ta) / (((ltd1 or 0) + (cl1 or 0)) / ta1) if ta1 else 1.0
    tata = (ni - cfo) / ta
    m = -4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
    return {"m": round(m, 2), "flag": m > -1.78, "inputs": {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi, "DEPI": depi, "SGAI": sgai, "TATA": tata, "LVGI": lvgi}}


def accruals(fund: Fundamentals) -> dict[str, Any]:
    ni, cfo = _v(fund.latest("net_income")), _v(fund.latest("cfo"))
    ta, ta1 = _a(fund, "total_assets"), _a(fund, "total_assets", 1)
    if ni is None or cfo is None or not ta:
        return {"sloan_ratio": None, "cash_conversion": None}
    avg_ta = (ta + ta1) / 2 if ta1 else ta
    return {"sloan_ratio": (ni - cfo) / avg_ta, "cash_conversion": (cfo / ni) if ni else None,
            "fcf_conversion": ((_v(fund.latest("fcf")) or 0) / ni) if ni else None}


def all_quality(fund: Fundamentals, market_cap: float | None) -> dict[str, Any]:
    return {"piotroski": piotroski(fund), "altman": altman_z(fund, market_cap), "beneish": beneish_m(fund), "accruals": accruals(fund)}

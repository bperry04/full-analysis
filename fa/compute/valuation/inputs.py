"""Valuation inputs with explicit assumptions: risk-free, ERP, beta, cost of debt, tax, WACC, growth and margin bases.

Every field carries where it came from so the Valuation tab can show (and let you override) each assumption.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np

from fa.compute.fundamentals.statements import Fundamentals


@dataclass
class Assumption:
    value: float | None
    source: str
    note: str = ""


@dataclass
class ValuationInputs:
    rf: Assumption
    erp: Assumption
    beta: Assumption
    cost_of_equity: Assumption
    cost_of_debt_pre_tax: Assumption
    tax_rate: Assumption
    wacc: Assumption
    weight_equity: Assumption
    weight_debt: Assumption
    revenue_ttm: Assumption
    fcf_margin: Assumption
    ebit_margin: Assumption
    growth_stage1: Assumption
    growth_terminal: Assumption
    fade_years: Assumption
    shares: Assumption
    net_debt: Assumption
    market_cap: Assumption
    price: Assumption
    eps_ttm: Assumption
    dps: Assumption
    bvps: Assumption
    roe: Assumption
    payout: Assumption
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {k: (asdict(v) if isinstance(v, Assumption) else v) for k, v in asdict(self).items()}

    def override(self, **kw: float) -> "ValuationInputs":
        touched = {k for k, v in kw.items() if v is not None and hasattr(self, k)}
        for k in touched:
            setattr(self, k, Assumption(float(kw[k]), "user_override"))
        # re-derive dependent rates unless the user pinned them directly
        if "cost_of_equity" not in touched and "wacc" not in touched:
            ke = self.rf.value + self.beta.value * self.erp.value
            self.cost_of_equity = Assumption(ke, "derived", "rf + beta * ERP")
        if "wacc" not in touched:
            we, wd = self.weight_equity.value, self.weight_debt.value
            self.wacc = Assumption(we * self.cost_of_equity.value + wd * self.cost_of_debt_pre_tax.value * (1 - self.tax_rate.value), "derived", "we*ke + wd*kd*(1-t)")
        return self

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "ValuationInputs":
        """Rebuild from the serialized `inputs` block of a stored run (used by the recompute endpoint)."""
        fields = {k: Assumption(**{kk: vv for kk, vv in v.items() if kk in ("value", "source", "note")}) for k, v in d.items() if isinstance(v, dict) and "value" in v}
        return cls(**fields, extra=d.get("extra") or {})


def _clip(x: float | None, lo: float, hi: float) -> float | None:
    return None if x is None else float(min(max(x, lo), hi))


def build_inputs(fund: Fundamentals, price: float | None, market_cap: float | None, shares: float | None, beta: float | None,
                 rf: float | None, erp: float = 0.045) -> ValuationInputs:
    t = fund.latest
    rf_v = rf if rf is not None else 0.042
    rf_src = "FRED/Treasury DGS10" if rf is not None else "default (no macro data)"
    beta_v = _clip(beta, 0.3, 2.5) if beta is not None else 1.0
    ke = rf_v + beta_v * erp
    debt = t("total_debt") or 0.0
    cash = (t("cash") or 0.0) + (t("st_investments") or 0.0)
    int_exp = t("interest_expense")
    avg_debt = np.mean([x for x in (fund.annual_value("total_debt"), fund.annual_value("total_debt", 1)) if x]) if debt else None
    kd = (abs(int_exp) / avg_debt) if int_exp and avg_debt else None
    kd = _clip(kd, rf_v + 0.005, rf_v + 0.10) if kd else rf_v + 0.015
    tax = t("income_tax")
    pretax = t("pretax_income")
    tr = _clip(tax / pretax, 0.0, 0.45) if tax is not None and pretax and pretax > 0 else 0.21
    mc = market_cap or ((price * shares) if price and shares else None)
    total_cap = (mc or 0) + debt
    we = (mc / total_cap) if mc and total_cap else 1.0
    wd = 1 - we
    wacc = we * ke + wd * kd * (1 - tr)
    rev = t("revenue")
    fcf = t("fcf")
    oi = t("operating_income")
    # margins: blend TTM with 3-year average to avoid anchoring on one year
    fcf_margins = [fund.annual_value("fcf", i) / fund.annual_value("revenue", i) for i in range(3) if fund.annual_value("fcf", i) is not None and fund.annual_value("revenue", i)]
    fcf_m = float(np.mean(fcf_margins)) if fcf_margins else ((fcf / rev) if fcf is not None and rev else None)
    ebit_m = (oi / rev) if oi is not None and rev else None
    # growth: blend of 3y revenue CAGR (50%), latest FY growth (30%) and latest-quarter YoY (20%), capped
    r0, r1, r3 = fund.annual_value("revenue"), fund.annual_value("revenue", 1), fund.annual_value("revenue", 3)
    cagr = ((r0 / r3) ** (1 / 3) - 1) if r0 and r3 and r0 > 0 and r3 > 0 else None
    g_fy = (r0 / r1 - 1) if r0 and r1 and r1 > 0 else None
    qrev = fund.series("revenue", "quarterly")
    g_q = (float(qrev.iloc[-1]) / float(qrev.iloc[-5]) - 1) if len(qrev) >= 5 and qrev.iloc[-5] > 0 else None
    parts = [(cagr, 0.5), (g_fy, 0.3), (g_q, 0.2)]
    have = [(g, w) for g, w in parts if g is not None]
    g1 = _clip(sum(g * w for g, w in have) / sum(w for _, w in have), -0.10, 0.30) if have else 0.05
    growth_src = "blend: 50% 3y CAGR, 30% last FY, 20% latest quarter YoY (capped -10%..30%)" if have else "default 5%"
    g_term = min(rf_v - 0.005, 0.03)
    ni = t("net_income")
    eq = t("equity")
    div = t("dividends_paid")
    sh = shares or fund.ttm.get("shares_outstanding_latest") or t("shares_diluted")
    eps = t("eps_diluted")
    dps = (div / sh) if div and sh else 0.0
    bvps = (eq / sh) if eq and sh else None
    roe = (ni / eq) if ni is not None and eq and eq > 0 else None
    payout = (div / ni) if div and ni and ni > 0 else 0.0
    return ValuationInputs(
        rf=Assumption(rf_v, rf_src), erp=Assumption(erp, "assumption", "equity risk premium"),
        beta=Assumption(beta_v, "2y weekly OLS vs SPY, Blume-adjusted" if beta is not None else "default 1.0"),
        cost_of_equity=Assumption(ke, "derived", "rf + beta * ERP"),
        cost_of_debt_pre_tax=Assumption(kd, "interest_expense / avg total_debt (floored at rf+0.5%)" if int_exp and avg_debt else "rf + 1.5% default"),
        tax_rate=Assumption(tr, "income_tax / pretax_income (TTM)" if tax is not None and pretax else "21% statutory default"),
        wacc=Assumption(wacc, "derived", "we*ke + wd*kd*(1-t)"), weight_equity=Assumption(we, "market cap / (market cap + debt)"),
        weight_debt=Assumption(wd, "derived"), revenue_ttm=Assumption(rev, "XBRL TTM"),
        fcf_margin=Assumption(fcf_m, "avg of last 3 FY FCF margins" if fcf_margins else "TTM"), ebit_margin=Assumption(ebit_m, "TTM"),
        growth_stage1=Assumption(g1, growth_src),
        growth_terminal=Assumption(g_term, "min(rf - 0.5%, 3%)"), fade_years=Assumption(10, "assumption", "stage-1 growth fades linearly to terminal over N years"),
        shares=Assumption(sh, "latest cover-page shares outstanding" if fund.ttm.get("shares_outstanding_latest") else "diluted weighted average"),
        net_debt=Assumption(debt - cash, "total_debt - cash - st_investments"), market_cap=Assumption(mc, "price * shares"),
        price=Assumption(price, "quote"), eps_ttm=Assumption(eps, "XBRL TTM"), dps=Assumption(dps, "dividends_paid / shares"),
        bvps=Assumption(bvps, "equity / shares"), roe=Assumption(roe, "net_income / equity"), payout=Assumption(payout, "dividends_paid / net_income"),
        extra={"cash_and_investments": cash, "total_debt": debt, "net_income_ttm": ni, "fcf_ttm": fcf, "operating_income_ttm": oi,
               "revenue_cagr_3y": cagr, "revenue_growth_fy": g_fy, "revenue_growth_q_yoy": g_q, "fcf_margin_history": fcf_margins,
               "ebitda_margin": (t("ebitda") / rev) if t("ebitda") is not None and rev else None, "ebitda_ttm": t("ebitda"), "equity_ttm": eq},
    )

"""Metric library: ~100 ratios derived from normalized fundamentals + market data. Every metric records its formula and
the concept inputs it used, so the UI can trace it to line items and their XBRL tags.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from fa.compute.fundamentals.statements import Fundamentals


@dataclass(slots=True)
class Metric:
    key: str
    label: str
    group: str
    value: float | None
    formula: str
    inputs: dict[str, float | None] = field(default_factory=dict)
    unit: str = "ratio"        # ratio | pct | x | USD | USD/share | days | shares
    history: dict[str, float] | None = None   # period_end -> value (annual)


def _f(x: Any) -> float | None:
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


class MetricLibrary:
    def __init__(self, fund: Fundamentals, price: float | None, market_cap: float | None, shares: float | None):
        self.f = fund
        self.price = _f(price)
        self.shares = _f(shares) or _f(fund.ttm.get("shares_outstanding_latest")) or _f(fund.latest("shares_outstanding")) or _f(fund.latest("shares_diluted"))
        self.market_cap = _f(market_cap) or (self.price * self.shares if self.price and self.shares else None)
        self.metrics: dict[str, Metric] = {}

    # -- helpers
    def t(self, k: str) -> float | None:
        return _f(self.f.latest(k))

    def a(self, k: str, n: int = 0) -> float | None:
        return _f(self.f.annual_value(k, n))

    def avg2(self, k: str) -> float | None:
        x, y = self.a(k), self.a(k, 1)
        if x is None:
            return None
        return (x + y) / 2 if y is not None else x

    def add(self, key: str, label: str, group: str, value: float | None, formula: str, inputs: dict[str, Any], unit: str = "ratio",
            hist: Callable[[int], float | None] | None = None) -> None:
        history = None
        if hist is not None and not self.f.annual.empty:
            history = {}
            for i in range(min(8, self.f.annual.shape[1])):
                col = self.f.annual.columns[-1 - i]
                try:
                    v = hist(i)
                except Exception:
                    v = None
                if v is not None and not (isinstance(v, float) and math.isnan(v)):
                    history[str(col)] = float(v)
            history = dict(sorted(history.items()))
        self.metrics[key] = Metric(key, label, group, _f(value), formula, {k: _f(v) for k, v in inputs.items()}, unit, history)

    def build(self) -> dict[str, Metric]:
        t, a, add = self.t, self.a, self.add
        rev, gp, oi, ni, ebitda, ebit = t("revenue"), t("gross_profit"), t("operating_income"), t("net_income"), t("ebitda"), t("ebit")
        cfo, capex, fcf, da, sbc = t("cfo"), t("capex"), t("fcf"), t("da"), t("sbc")
        ta, tl, eq, cash, sti, debt = t("total_assets"), t("total_liabilities"), t("equity"), t("cash"), t("st_investments"), t("total_debt")
        ca, cl, inv, rec, pay = t("current_assets"), t("current_liabilities"), t("inventory"), t("receivables"), t("payables")
        int_exp, tax, pretax = t("interest_expense"), t("income_tax"), t("pretax_income")
        div, bb = t("dividends_paid"), t("buybacks")
        eps = t("eps_diluted")
        sh_dil = t("shares_diluted")
        cash_all = (cash or 0) + (sti or 0) if (cash is not None or sti is not None) else None
        net_debt = (debt or 0) - (cash_all or 0) if debt is not None or cash_all is not None else None
        ev = (self.market_cap + (net_debt or 0)) if self.market_cap else None
        tax_rate = _div(tax, pretax) if pretax and pretax > 0 and tax is not None else None
        eff_tax = min(max(tax_rate, 0.0), 0.5) if tax_rate is not None else 0.21
        nopat = oi * (1 - eff_tax) if oi is not None else None
        ic = ((eq or 0) + (debt or 0) - (cash_all or 0)) if eq is not None else None

        # ---- margins
        add("gross_margin", "Gross margin", "margins", _div(gp, rev), "gross_profit / revenue", {"gross_profit": gp, "revenue": rev}, "pct",
            lambda i: _div(a("gross_profit", i), a("revenue", i)))
        add("operating_margin", "Operating margin", "margins", _div(oi, rev), "operating_income / revenue", {"operating_income": oi, "revenue": rev}, "pct",
            lambda i: _div(a("operating_income", i), a("revenue", i)))
        add("ebitda_margin", "EBITDA margin", "margins", _div(ebitda, rev), "ebitda / revenue", {"ebitda": ebitda, "revenue": rev}, "pct",
            lambda i: _div(a("ebitda", i), a("revenue", i)))
        add("net_margin", "Net margin", "margins", _div(ni, rev), "net_income / revenue", {"net_income": ni, "revenue": rev}, "pct",
            lambda i: _div(a("net_income", i), a("revenue", i)))
        add("fcf_margin", "FCF margin", "margins", _div(fcf, rev), "fcf / revenue", {"fcf": fcf, "revenue": rev}, "pct",
            lambda i: _div(a("fcf", i), a("revenue", i)))
        add("rnd_pct_rev", "R&D % revenue", "margins", _div(t("rnd"), rev), "rnd / revenue", {"rnd": t("rnd"), "revenue": rev}, "pct")
        add("sga_pct_rev", "SG&A % revenue", "margins", _div(t("sga"), rev), "sga / revenue", {"sga": t("sga"), "revenue": rev}, "pct")
        add("sbc_pct_rev", "SBC % revenue", "capital_allocation", _div(sbc, rev), "sbc / revenue", {"sbc": sbc, "revenue": rev}, "pct")

        # ---- returns
        add("roe", "Return on equity", "returns", _div(ni, self.avg2("equity")), "net_income / avg equity", {"net_income": ni, "avg_equity": self.avg2("equity")}, "pct",
            lambda i: _div(a("net_income", i), a("equity", i)))
        add("roa", "Return on assets", "returns", _div(ni, self.avg2("total_assets")), "net_income / avg total_assets", {"net_income": ni, "avg_assets": self.avg2("total_assets")}, "pct",
            lambda i: _div(a("net_income", i), a("total_assets", i)))
        add("roic", "Return on invested capital", "returns", _div(nopat, ic), "operating_income*(1-tax) / (equity + debt - cash)",
            {"nopat": nopat, "invested_capital": ic, "tax_rate": eff_tax}, "pct",
            lambda i: _div((a("operating_income", i) or 0) * (1 - eff_tax), ((a("equity", i) or 0) + (a("total_debt", i) or 0) - (a("cash", i) or 0))) if a("equity", i) else None)
        add("roce", "Return on capital employed", "returns", _div(ebit, (ta - cl) if ta is not None and cl is not None else None), "ebit / (total_assets - current_liabilities)",
            {"ebit": ebit, "capital_employed": (ta - cl) if ta is not None and cl is not None else None}, "pct")
        add("cash_roic", "Cash ROIC (FCF / invested capital)", "returns", _div(fcf, ic), "fcf / invested_capital", {"fcf": fcf, "invested_capital": ic}, "pct")

        # ---- efficiency
        add("asset_turnover", "Asset turnover", "efficiency", _div(rev, self.avg2("total_assets")), "revenue / avg total_assets", {"revenue": rev, "avg_assets": self.avg2("total_assets")}, "x")
        add("inventory_turnover", "Inventory turnover", "efficiency", _div(t("cogs"), self.avg2("inventory")), "cogs / avg inventory", {"cogs": t("cogs"), "avg_inventory": self.avg2("inventory")}, "x")
        dso = _div(rec, rev)
        dio = _div(inv, t("cogs"))
        dpo = _div(pay, t("cogs"))
        add("dso", "Days sales outstanding", "efficiency", dso * 365 if dso is not None else None, "receivables / revenue * 365", {"receivables": rec, "revenue": rev}, "days")
        add("dio", "Days inventory outstanding", "efficiency", dio * 365 if dio is not None else None, "inventory / cogs * 365", {"inventory": inv, "cogs": t("cogs")}, "days")
        add("dpo", "Days payables outstanding", "efficiency", dpo * 365 if dpo is not None else None, "payables / cogs * 365", {"payables": pay, "cogs": t("cogs")}, "days")
        ccc = (dso or 0) * 365 + (dio or 0) * 365 - (dpo or 0) * 365 if dso is not None else None
        add("cash_conversion_cycle", "Cash conversion cycle", "efficiency", ccc, "dso + dio - dpo", {"dso": dso, "dio": dio, "dpo": dpo}, "days")

        # ---- leverage & liquidity
        add("debt_to_equity", "Debt / equity", "leverage", _div(debt, eq), "total_debt / equity", {"total_debt": debt, "equity": eq}, "x")
        add("net_debt", "Net debt", "leverage", net_debt, "total_debt - cash - st_investments", {"total_debt": debt, "cash": cash, "st_investments": sti}, "USD")
        add("net_debt_to_ebitda", "Net debt / EBITDA", "leverage", _div(net_debt, ebitda), "net_debt / ebitda", {"net_debt": net_debt, "ebitda": ebitda}, "x")
        add("debt_to_assets", "Debt / assets", "leverage", _div(debt, ta), "total_debt / total_assets", {"total_debt": debt, "total_assets": ta}, "pct")
        add("interest_coverage", "Interest coverage", "leverage", _div(ebit or oi, int_exp), "ebit / interest_expense", {"ebit": ebit or oi, "interest_expense": int_exp}, "x")
        add("equity_ratio", "Equity / assets", "leverage", _div(eq, ta), "equity / total_assets", {"equity": eq, "total_assets": ta}, "pct")
        add("current_ratio", "Current ratio", "liquidity", _div(ca, cl), "current_assets / current_liabilities", {"current_assets": ca, "current_liabilities": cl}, "x")
        add("quick_ratio", "Quick ratio", "liquidity", _div((ca - (inv or 0)) if ca is not None else None, cl), "(current_assets - inventory) / current_liabilities", {"current_assets": ca, "inventory": inv, "current_liabilities": cl}, "x")
        add("cash_ratio", "Cash ratio", "liquidity", _div(cash_all, cl), "(cash + st_investments) / current_liabilities", {"cash_all": cash_all, "current_liabilities": cl}, "x")

        # ---- per share
        bvps = _div(eq, self.shares)
        fcfps = _div(fcf, self.shares)
        rps = _div(rev, self.shares)
        add("eps_ttm", "EPS (diluted, TTM)", "per_share", eps, "sum of last 4 quarters diluted EPS", {"eps_diluted": eps}, "USD/share", lambda i: a("eps_diluted", i))
        add("bvps", "Book value / share", "per_share", bvps, "equity / shares", {"equity": eq, "shares": self.shares}, "USD/share")
        add("fcf_per_share", "FCF / share", "per_share", fcfps, "fcf / shares", {"fcf": fcf, "shares": self.shares}, "USD/share")
        add("revenue_per_share", "Revenue / share", "per_share", rps, "revenue / shares", {"revenue": rev, "shares": self.shares}, "USD/share")
        add("cash_per_share", "Cash / share", "per_share", _div(cash_all, self.shares), "(cash + st_investments) / shares", {"cash_all": cash_all, "shares": self.shares}, "USD/share")

        # ---- valuation
        add("market_cap", "Market cap", "valuation", self.market_cap, "price * shares", {"price": self.price, "shares": self.shares}, "USD")
        add("enterprise_value", "Enterprise value", "valuation", ev, "market_cap + net_debt", {"market_cap": self.market_cap, "net_debt": net_debt}, "USD")
        add("pe", "P/E (TTM)", "valuation", _div(self.price, eps) if eps and eps > 0 else None, "price / eps_ttm", {"price": self.price, "eps": eps}, "x")
        add("earnings_yield", "Earnings yield", "valuation", _div(eps, self.price), "eps_ttm / price", {"eps": eps, "price": self.price}, "pct")
        add("ps", "P/S (TTM)", "valuation", _div(self.market_cap, rev), "market_cap / revenue", {"market_cap": self.market_cap, "revenue": rev}, "x")
        add("pb", "P/B", "valuation", _div(self.market_cap, eq) if eq and eq > 0 else None, "market_cap / equity", {"market_cap": self.market_cap, "equity": eq}, "x")
        add("p_fcf", "P/FCF", "valuation", _div(self.market_cap, fcf) if fcf and fcf > 0 else None, "market_cap / fcf", {"market_cap": self.market_cap, "fcf": fcf}, "x")
        add("fcf_yield", "FCF yield", "valuation", _div(fcf, self.market_cap), "fcf / market_cap", {"fcf": fcf, "market_cap": self.market_cap}, "pct")
        add("ev_sales", "EV / Sales", "valuation", _div(ev, rev), "enterprise_value / revenue", {"ev": ev, "revenue": rev}, "x")
        add("ev_ebitda", "EV / EBITDA", "valuation", _div(ev, ebitda) if ebitda and ebitda > 0 else None, "enterprise_value / ebitda", {"ev": ev, "ebitda": ebitda}, "x")
        add("ev_ebit", "EV / EBIT", "valuation", _div(ev, ebit) if ebit and ebit > 0 else None, "enterprise_value / ebit", {"ev": ev, "ebit": ebit}, "x")
        add("ev_fcf", "EV / FCF", "valuation", _div(ev, fcf) if fcf and fcf > 0 else None, "enterprise_value / fcf", {"ev": ev, "fcf": fcf}, "x")
        add("p_cfo", "P / CFO", "valuation", _div(self.market_cap, cfo) if cfo and cfo > 0 else None, "market_cap / cfo", {"market_cap": self.market_cap, "cfo": cfo}, "x")

        # ---- growth (annual CAGR + latest yoy on TTM vs prior TTM approximated by FY)
        for k, label in (("revenue", "Revenue"), ("net_income", "Net income"), ("eps_diluted", "EPS"), ("fcf", "FCF"), ("operating_income", "Operating income"), ("cfo", "CFO")):
            add(f"{k}_growth_1y", f"{label} growth (1y)", "growth", _growth(a(k), a(k, 1)), f"{k}[FY] / {k}[FY-1] - 1", {"now": a(k), "prior": a(k, 1)}, "pct",
                lambda i, k=k: _growth(a(k, i), a(k, i + 1)))
            add(f"{k}_cagr_3y", f"{label} CAGR (3y)", "growth", _cagr(a(k), a(k, 3), 3), f"({k}[FY]/{k}[FY-3])^(1/3) - 1", {"now": a(k), "base": a(k, 3)}, "pct")
            add(f"{k}_cagr_5y", f"{label} CAGR (5y)", "growth", _cagr(a(k), a(k, 5), 5), f"({k}[FY]/{k}[FY-5])^(1/5) - 1", {"now": a(k), "base": a(k, 5)}, "pct")
        qrev = self.f.series("revenue", "quarterly")
        if len(qrev) >= 5:
            add("revenue_growth_yoy_q", "Revenue growth (latest quarter YoY)", "growth", _growth(float(qrev.iloc[-1]), float(qrev.iloc[-5])), "revenue[Q] / revenue[Q-4] - 1",
                {"now": float(qrev.iloc[-1]), "prior": float(qrev.iloc[-5])}, "pct")
            if len(qrev) >= 9:
                g1 = _growth(float(qrev.iloc[-1]), float(qrev.iloc[-5]))
                g2 = _growth(float(qrev.iloc[-5]), float(qrev.iloc[-9]))
                add("revenue_acceleration", "Revenue growth acceleration", "growth", (g1 - g2) if g1 is not None and g2 is not None else None,
                    "yoy growth[Q] - yoy growth[Q-4]", {"g_now": g1, "g_prior": g2}, "pct")
        qni = self.f.series("net_income", "quarterly")
        if len(qni) >= 5:
            add("net_income_growth_yoy_q", "Net income growth (latest quarter YoY)", "growth", _growth(float(qni.iloc[-1]), float(qni.iloc[-5])), "net_income[Q] / net_income[Q-4] - 1",
                {"now": float(qni.iloc[-1]), "prior": float(qni.iloc[-5])}, "pct")

        # ---- capital allocation
        add("dividend_yield", "Dividend yield (cash paid basis)", "capital_allocation", _div(div, self.market_cap), "dividends_paid / market_cap", {"dividends_paid": div, "market_cap": self.market_cap}, "pct")
        add("buyback_yield", "Buyback yield", "capital_allocation", _div(bb, self.market_cap), "buybacks / market_cap", {"buybacks": bb, "market_cap": self.market_cap}, "pct")
        add("shareholder_yield", "Shareholder yield", "capital_allocation", _div((div or 0) + (bb or 0), self.market_cap) if (div is not None or bb is not None) else None,
            "(dividends + buybacks) / market_cap", {"dividends_paid": div, "buybacks": bb, "market_cap": self.market_cap}, "pct")
        add("payout_ratio", "Payout ratio", "capital_allocation", _div(div, ni) if ni and ni > 0 else None, "dividends_paid / net_income", {"dividends_paid": div, "net_income": ni}, "pct")
        add("capex_pct_rev", "Capex % revenue", "capital_allocation", _div(capex, rev), "capex / revenue", {"capex": capex, "revenue": rev}, "pct")
        add("capex_to_da", "Capex / D&A", "capital_allocation", _div(capex, da), "capex / da", {"capex": capex, "da": da}, "x")
        add("reinvestment_rate", "Reinvestment rate", "capital_allocation", _div((capex or 0) - (da or 0) + (t("acquisitions") or 0), nopat), "(capex - da + acquisitions) / nopat",
            {"capex": capex, "da": da, "acquisitions": t("acquisitions"), "nopat": nopat}, "pct")
        sh0, sh1 = a("shares_diluted"), a("shares_diluted", 1)
        add("share_count_change_1y", "Diluted share count change (1y)", "capital_allocation", _growth(sh0, sh1), "shares_diluted[FY]/shares_diluted[FY-1] - 1", {"now": sh0, "prior": sh1}, "pct",
            lambda i: _growth(a("shares_diluted", i), a("shares_diluted", i + 1)))
        add("cash_conversion", "Cash conversion (CFO / NI)", "quality", _div(cfo, ni) if ni and ni > 0 else None, "cfo / net_income", {"cfo": cfo, "net_income": ni}, "x")
        add("fcf_conversion", "FCF conversion (FCF / NI)", "quality", _div(fcf, ni) if ni and ni > 0 else None, "fcf / net_income", {"fcf": fcf, "net_income": ni}, "x")
        add("effective_tax_rate", "Effective tax rate", "quality", tax_rate, "income_tax / pretax_income", {"income_tax": tax, "pretax_income": pretax}, "pct")
        add("net_cash", "Net cash (cash + investments - debt)", "leverage", (-net_debt) if net_debt is not None else None, "cash + st_investments - total_debt", {"cash_all": cash_all, "total_debt": debt}, "USD")
        return self.metrics


def _growth(now: float | None, prior: float | None) -> float | None:
    if now is None or prior is None or prior == 0:
        return None
    if prior < 0 and now < 0:
        return -(now / prior - 1)
    if prior < 0:
        return None
    return now / prior - 1


def _cagr(now: float | None, base: float | None, years: int) -> float | None:
    if now is None or base is None or base <= 0 or now <= 0:
        return None
    return (now / base) ** (1 / years) - 1


def build_metrics(fund: Fundamentals, price: float | None, market_cap: float | None, shares: float | None) -> dict[str, Metric]:
    return MetricLibrary(fund, price, market_cap, shares).build()

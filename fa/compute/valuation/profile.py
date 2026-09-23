"""Company profile classification → which valuation models apply and how the blend is weighted.

The profile is a set of tags (a company can be several things: growth + cash-burning + concentrated) plus a primary kind.
Every judgment is written down in `notes` so the Valuation tab can show why a model was or wasn't run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fa.compute.fundamentals.statements import Fundamentals


@dataclass
class Profile:
    primary: str
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def has(self, *t: str) -> bool:
        return any(x in self.tags for x in t)


def _v(x):
    try:
        f = float(x)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def classify(fund: Fundamentals, sic: str | None, industry: str | None, sector: str | None, payout: float | None, altman_zone: str | None,
             rev_growth: float | None, market_cap: float | None) -> Profile:
    t = fund.latest
    rev, ni, fcf, cfo = _v(t("revenue")), _v(t("net_income")), _v(t("fcf")), _v(t("cfo"))
    eq, cash, debt = _v(t("equity")), _v(t("cash")), _v(t("total_debt"))
    nii, loans, deposits, cogs = _v(t("net_interest_income")), _v(t("loans_net")), _v(t("deposits")), _v(t("cogs"))
    ind = (industry or "").lower()
    sec = (sector or "").lower()
    sic_s = str(sic or "")
    tags: list[str] = []
    notes: list[str] = []
    facts: dict[str, Any] = {"revenue": rev, "net_income": ni, "fcf": fcf, "equity": eq, "sic": sic, "industry": industry}

    is_bank = bool((nii and (loans or deposits)) or sic_s[:2] in ("60", "61") or "bank" in ind)
    is_insurer = bool(sic_s[:2] == "63" or "insurance" in ind)
    is_reit = bool(sic_s == "6798" or "reit" in ind or "real estate" in ind and "reit" in sec)
    is_utility = bool(sic_s[:2] == "49" or "utilit" in sec)
    if is_bank:
        tags.append("bank"); notes.append("Bank: cash-flow DCF is meaningless (deposits are the raw material); use residual income, justified P/B, comps, DDM.")
    if is_insurer:
        tags.append("insurer"); notes.append("Insurer: book value and ROE drive value; justified P/B and residual income apply.")
    if is_reit:
        tags.append("reit"); notes.append("REIT: net income is depressed by depreciation; value on FFO/AFFO and dividends, not EPS.")
    if is_utility:
        tags.append("utility"); notes.append("Regulated utility: stable payout — DDM and justified P/E carry weight.")
    if rev is None or (market_cap and rev < 0.01 * market_cap and rev < 5e7):
        tags.append("pre_revenue"); notes.append("Pre-revenue / negligible revenue: cash-flow and multiple models are not meaningful; show cash runway and comps only.")
    if fcf is not None and fcf < 0 and not is_bank:
        tags.append("cash_burning"); notes.append(f"Negative free cash flow ({fcf/1e6:,.0f}M): FCFF DCF uses a normalized-margin ramp and is an estimate; EV/Sales comps, scenario and exit-multiple DCF matter more.")
    if ni is not None and ni < 0:
        tags.append("loss_making"); notes.append("Net loss: P/E, PEG, Graham and justified P/E do not apply.")
    if rev_growth is not None and rev_growth > 0.20:
        tags.append("high_growth"); notes.append(f"Revenue growth {rev_growth:.0%}: terminal value dominates any DCF; growth-adjusted EV/Sales regression and scenario analysis are the sanity checks.")
    if payout is not None and payout > 0.30 and ni and ni > 0:
        tags.append("dividend_payer"); notes.append(f"Payout {payout:.0%}: dividend models (DDM, justified P/E) apply.")
    if eq is not None and eq <= 0:
        tags.append("negative_equity"); notes.append("Negative book equity: P/B, justified P/B, residual income and Graham do not apply.")
    if altman_zone == "distress" and not (is_bank or is_insurer):      # Altman Z is not defined for financials
        tags.append("distressed"); notes.append("Altman distress zone: asset-based values (NCAV, tangible book) and EPV are shown alongside going-concern models.")
    if (is_bank or is_insurer) and altman_zone == "distress":
        notes.append("Altman Z is not applicable to banks/insurers (leverage is the business model) — ignored.")
    if rev and ni is not None and ni > 0 and fcf is not None and fcf > 0 and not tags:
        tags.append("mature_profitable")
    if not tags:
        tags.append("general")

    primary = ("bank" if is_bank else "insurer" if is_insurer else "reit" if is_reit else "utility" if is_utility else "pre_revenue" if "pre_revenue" in tags
               else "cash_burning_growth" if "cash_burning" in tags and "high_growth" in tags else "cash_burning" if "cash_burning" in tags
               else "distressed" if "distressed" in tags else "high_growth" if "high_growth" in tags else "dividend_mature" if "dividend_payer" in tags else "mature_profitable")
    return Profile(primary, tags, notes, facts)


# blend weights per primary profile — only models that produced a value are used; weights renormalize
WEIGHTS: dict[str, dict[str, float]] = {
    "mature_profitable": {"dcf": 0.25, "fcfe": 0.08, "dcf_exit": 0.10, "dcf_scenarios": 0.10, "comps": 0.15, "hist_multiples": 0.10, "mc_dcf": 0.10, "epv": 0.05, "justified_pe": 0.04, "ddm": 0.03},
    "dividend_mature": {"dcf": 0.20, "fcfe": 0.08, "dcf_exit": 0.08, "dcf_scenarios": 0.08, "comps": 0.14, "hist_multiples": 0.10, "mc_dcf": 0.08, "epv": 0.05, "justified_pe": 0.08, "ddm": 0.11},
    "high_growth": {"dcf": 0.18, "dcf_exit": 0.14, "dcf_scenarios": 0.14, "comps": 0.24, "hist_multiples": 0.08, "mc_dcf": 0.12, "fcfe": 0.05, "epv": 0.02, "peg": 0.03},
    "cash_burning_growth": {"dcf": 0.12, "dcf_exit": 0.16, "dcf_scenarios": 0.16, "comps": 0.32, "hist_multiples": 0.10, "mc_dcf": 0.10, "peg": 0.04},
    "cash_burning": {"dcf": 0.12, "dcf_exit": 0.14, "dcf_scenarios": 0.16, "comps": 0.30, "hist_multiples": 0.10, "mc_dcf": 0.08, "epv": 0.05, "ncav": 0.05},
    "bank": {"rim": 0.32, "justified_pb": 0.28, "comps": 0.22, "ddm": 0.12, "hist_multiples": 0.06},
    "insurer": {"rim": 0.30, "justified_pb": 0.30, "comps": 0.22, "ddm": 0.10, "hist_multiples": 0.08},
    "reit": {"ffo_cap": 0.32, "comps": 0.25, "ddm": 0.18, "hist_multiples": 0.15, "rim": 0.10},
    "utility": {"ddm": 0.25, "justified_pe": 0.15, "dcf": 0.15, "comps": 0.20, "hist_multiples": 0.15, "rim": 0.10},
    "distressed": {"epv": 0.22, "comps": 0.24, "ncav": 0.14, "tangible_book": 0.10, "dcf_scenarios": 0.15, "dcf": 0.10, "hist_multiples": 0.05},
    "pre_revenue": {"comps": 0.6, "ncav": 0.2, "tangible_book": 0.2},
}

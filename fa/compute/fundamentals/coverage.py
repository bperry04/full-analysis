"""Coverage summary for the Financials tab: what resolved, from which tag, what is missing, what was derived."""
from __future__ import annotations

from typing import Any

from fa.compute.fundamentals.statements import Fundamentals


def summarize(fund: Fundamentals) -> dict[str, Any]:
    cov = fund.coverage
    resolved = [c for c in cov if c["status"] == "resolved"]
    formula = [c for c in cov if c["status"] == "formula"]
    missing = [c for c in cov if c["status"] == "missing"]
    core = ["revenue", "net_income", "cfo", "total_assets", "equity", "eps_diluted", "operating_income", "capex", "cash", "total_debt"]
    core_ok = sum(1 for c in cov if c["concept"] in core and c["status"] != "missing")
    return {
        "resolved": len(resolved), "formula": len(formula), "missing": len(missing), "total": len(cov),
        "core_coverage": core_ok / len(core), "fye_month": fund.fye_month, "annual_periods": int(fund.annual.shape[1]) if not fund.annual.empty else 0,
        "quarterly_periods": int(fund.quarterly.shape[1]) if not fund.quarterly.empty else 0, "ttm_end": fund.ttm_end,
        "restatements": len(fund.restatements), "spliced": [c["concept"] for c in cov if c["spliced_from"]],
        "missing_concepts": [c["concept"] for c in missing], "rows": cov,
    }

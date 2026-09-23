"""Assemble normalized statements (FY / quarterly / TTM grids) from resolved concepts, with formulas and a coverage report."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from fa.compute.fundamentals.concepts import ConceptMap, load_concepts
from fa.compute.fundamentals.periods import derive_quarters, ttm
from fa.compute.fundamentals.resolve import Resolution, eval_formula, resolve_all

log = logging.getLogger(__name__)


@dataclass
class Fundamentals:
    symbol: str
    cik: str
    fye_month: int
    annual: pd.DataFrame            # rows = concept, cols = fiscal year end date (latest values)
    quarterly: pd.DataFrame         # rows = concept, cols = quarter end date
    ttm: dict[str, float | None]    # concept -> TTM value (flows) / latest (stocks)
    ttm_end: date | None
    long: pd.DataFrame              # the full normalized long table (for the DB)
    resolutions: dict[str, Resolution]
    coverage: list[dict[str, Any]]
    restatements: list[dict[str, Any]]
    flags: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)

    def series(self, concept: str, freq: str = "annual") -> pd.Series:
        g = self.annual if freq == "annual" else self.quarterly
        if concept not in g.index:
            return pd.Series(dtype=float)
        return g.loc[concept].dropna()

    def latest(self, concept: str) -> float | None:
        v = self.ttm.get(concept)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)

    def annual_value(self, concept: str, n_back: int = 0) -> float | None:
        s = self.series(concept, "annual")
        if len(s) <= n_back:
            return None
        return float(s.iloc[-1 - n_back])


def build_fundamentals(facts: pd.DataFrame, symbol: str, cmap: ConceptMap | None = None) -> Fundamentals:
    cmap = cmap or load_concepts()
    cik = str(facts["cik"].iloc[0]) if "cik" in facts.columns and len(facts) else ""
    long, resolutions, fye = resolve_all(facts, cmap)
    if long.empty:
        return Fundamentals(symbol, cik, fye, pd.DataFrame(), pd.DataFrame(), {}, None, long, resolutions, [], [])

    current = long[~long["as_filed"]]           # latest-filed values drive the grids
    # drop impossible dates (typos in filings) — nothing can be reported for a period ending > 30 days from now
    current = current[pd.to_datetime(current["period_end"]) <= pd.Timestamp.today() + pd.Timedelta(days=30)]
    restatements = _restatements(long)
    # instants (balance sheet, cover-page share counts) only belong on the grid at real period ends
    flow_ends = sorted(current[current["kind"].isin(["Q", "H", "NM", "FY"])]["period_end"].unique().tolist())
    fy_ends = _fy_end_dates(current, fye)
    by_concept: dict[str, pd.DataFrame] = {k: g for k, g in current.groupby("concept", sort=False)}
    latest_instants: dict[str, tuple[date, float]] = {}

    annual: dict[str, pd.Series] = {}
    quarterly: dict[str, pd.Series] = {}
    q_frames: dict[str, pd.DataFrame] = {}
    ttm_vals: dict[str, float | None] = {}
    ttm_end: date | None = None
    derived_counts: dict[str, int] = {}

    for key, c in cmap.concepts.items():
        sub = by_concept.get(key)
        if sub is None or sub.empty:
            continue
        if c.period == "instant":
            s = sub.sort_values(["period_end", "filed"]).drop_duplicates("period_end", keep="last").set_index("period_end")["value"]
            if len(s):
                latest_instants[key] = (s.index[-1], float(s.iloc[-1]))
            # annual = values at fiscal-year ends; quarterly = instants that sit on a reported period end
            annual[key] = s[[e for e in s.index if _near_any(e, fy_ends)]]
            on_grid = s[[e for e in s.index if _near_any(e, flow_ends)]]
            quarterly[key] = on_grid
            ttm_vals[key] = float(on_grid.iloc[-1]) if len(on_grid) else (float(s.iloc[-1]) if len(s) else None)
        else:
            flows = sub[sub["kind"].isin(["Q", "H", "NM", "FY"])].sort_values(["period_end", "filed"]).drop_duplicates(["period_start", "period_end"], keep="last")
            fy = flows[flows["kind"] == "FY"].set_index("period_end")["value"]
            annual[key] = fy
            qd = derive_quarters(flows[["period_start", "period_end", "value", "kind", "fy", "fq", "source_tag", "filed", "accn", "flags"]])
            derived_counts[key] = int(qd["derived"].sum()) if "derived" in qd.columns and len(qd) else 0
            q_frames[key] = qd
            quarterly[key] = qd.set_index("period_end")["value"] if len(qd) else pd.Series(dtype=float)
            v, end, _ = ttm(qd)
            if v is None and len(fy):
                # fall back to latest FY if we cannot assemble 4 quarters
                v, end = float(fy.iloc[-1]), fy.index[-1]
                ttm_vals[key] = v
            else:
                ttm_vals[key] = v
            if end and (ttm_end is None or end > ttm_end) and key in ("revenue", "net_income", "cfo"):
                ttm_end = end

    # formulas for unresolved (or partially resolved) concepts, on each grid
    for grid_name, grid in (("annual", annual), ("quarterly", quarterly)):
        for key, c in cmap.concepts.items():
            if not c.formula:
                continue
            existing = grid.get(key)
            if existing is not None and len(existing) and grid_name == "annual" and len(existing) >= 3:
                continue
            res, used = eval_formula(c.formula, lambda k: grid.get(k) if (grid.get(k) is not None and len(grid.get(k))) else None)
            if res is None or res.empty:
                continue
            if existing is not None and len(existing):
                merged = existing.combine_first(res)
            else:
                merged = res
            grid[key] = merged.sort_index()
            r = resolutions.get(key)
            if r is not None and r.tag is None:
                r.via_formula = c.formula
                r.coverage = int(len(merged))
    for key, c in cmap.concepts.items():
        if c.formula and (ttm_vals.get(key) is None):
            res, used = eval_formula(c.formula, lambda k: pd.Series([ttm_vals[k]], index=[0]) if ttm_vals.get(k) is not None else None)
            if res is not None and len(res):
                ttm_vals[key] = float(res.iloc[0])

    # the cover-page share count is the freshest shares-outstanding figure; expose it even though it is off-grid
    if "shares_outstanding" in latest_instants:
        d, v = latest_instants["shares_outstanding"]
        ttm_vals["shares_outstanding_latest"] = v
        ttm_vals["shares_outstanding_latest_date"] = d  # type: ignore[assignment]
    annual_df = _grid(annual)
    quarterly_df = _grid(quarterly)
    coverage = _coverage(cmap, resolutions, annual_df, quarterly_df, derived_counts)
    labels = {k: c.label for k, c in cmap.concepts.items()}
    flags = []
    if any(r.spliced_from for r in resolutions.values()):
        flags.append("TAG_SPLICE")
    if restatements:
        flags.append("RESTATED")
    return Fundamentals(symbol, cik, fye, annual_df, quarterly_df, ttm_vals, ttm_end, long, resolutions, coverage, restatements, flags, labels)


def _grid(series: dict[str, pd.Series]) -> pd.DataFrame:
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame({k: v for k, v in series.items() if v is not None and len(v)}).T
    df = df.reindex(sorted(df.columns), axis=1)
    return df


def _fy_end_dates(current: pd.DataFrame, fye: int) -> list[date]:
    ends = current[current["kind"] == "FY"]["period_end"].unique().tolist()
    return sorted(ends)


def _near_any(e: date, ends: list[date], tol: int = 6) -> bool:
    return any(abs((e - x).days) <= tol for x in ends)


def _restatements(long: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    asf = long[long["as_filed"]]
    if asf.empty:
        return out
    cur = long[(~long["as_filed"]) & (long["is_restated"])]
    m = asf.merge(cur, on=["concept", "period_start", "period_end"], suffixes=("_orig", "_new"))
    share_like = {"shares_basic", "shares_diluted", "shares_outstanding", "eps_basic", "eps_diluted"}
    from types import SimpleNamespace
    from fa.compute.fundamentals.periods import records as _records
    for r in (SimpleNamespace(**d) for d in _records(m)):
        reason = "restatement"
        if r.concept in share_like and r.value_orig:
            ratio = r.value_new / r.value_orig
            for k in (2, 3, 4, 5, 7, 10, 20, 50):
                if abs(ratio - k) < 0.02 * k or abs(ratio - 1 / k) < 0.02 / k:
                    reason = f"split_adjustment_{k}:1" if ratio > 1 else f"reverse_split_1:{k}"
                    break
        out.append({"concept": r.concept, "period_end": r.period_end, "original": r.value_orig, "restated": r.value_new,
                    "original_filed": r.filed_orig, "restated_filed": r.filed_new, "reason": reason,
                    "change_pct": (r.value_new - r.value_orig) / abs(r.value_orig) * 100 if r.value_orig else None})
    # genuine restatements first, split adjustments after
    out.sort(key=lambda x: (x["reason"] != "restatement", -x["period_end"].toordinal(), x["concept"]))
    return out[:300]


def _coverage(cmap: ConceptMap, res: dict[str, Resolution], annual: pd.DataFrame, quarterly: pd.DataFrame, derived: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    for key, c in cmap.concepts.items():
        r = res.get(key)
        n_fy = int(annual.loc[key].notna().sum()) if key in annual.index else 0
        n_q = int(quarterly.loc[key].notna().sum()) if key in quarterly.index else 0
        status = "resolved" if (r and r.tag) else ("formula" if (r and r.via_formula) or (n_fy or n_q) else "missing")
        out.append(
            {"concept": key, "label": c.label, "statement": c.statement, "status": status, "tag": r.tag if r else None,
             "formula": (r.via_formula if r and r.via_formula else (c.formula if status == "formula" else None)),
             "annual_periods": n_fy, "quarterly_periods": n_q, "derived_quarters": derived.get(key, 0),
             "spliced_from": r.spliced_from if r else [], "candidates": r.candidates if r else {}}
        )
    return out


def long_for_db(fund: Fundamentals, prov_id: str) -> pd.DataFrame:
    """Rows for fundamentals_normalized from the grids (annual + quarterly + TTM)."""
    rows = []
    for grid, ptype in ((fund.annual, "FY"), (fund.quarterly, "Q")):
        if grid is None or grid.empty:
            continue
        for concept in grid.index:
            r = fund.resolutions.get(concept)
            for end, v in grid.loc[concept].dropna().items():
                rows.append({"symbol": fund.symbol, "cik": fund.cik, "metric": concept, "period_type": ptype, "period_end": end,
                             "value": float(v), "unit": None, "source_tag": r.tag if r else None, "derived": bool(r and r.tag is None),
                             "derivation": r.via_formula if r else None, "is_restated": False, "confidence": 1.0 if (r and r.tag) else 0.8,
                             "prov_id": prov_id})
    for concept, v in fund.ttm.items():
        if v is None or not isinstance(v, (int, float)) or (isinstance(v, float) and np.isnan(v)):
            continue
        r = fund.resolutions.get(concept)
        rows.append({"symbol": fund.symbol, "cik": fund.cik, "metric": concept, "period_type": "TTM", "period_end": fund.ttm_end,
                     "value": float(v), "unit": None, "source_tag": r.tag if r else None, "derived": True, "derivation": "ttm_sum",
                     "is_restated": False, "confidence": 0.95, "prov_id": prov_id})
    return pd.DataFrame(rows)

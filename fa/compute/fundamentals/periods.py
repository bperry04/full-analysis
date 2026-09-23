"""Period arithmetic for XBRL facts.

- classify a duration by length: Q (≈3 months), H (≈6), NM (≈9), FY (≈12)
- assign fiscal year / quarter from the period END and the filer's fiscal-year-end month
- derive quarters from YTD figures when the direct quarter is not reported: Q2 = 6M − Q1, Q3 = 9M − 6M, Q4 = FY − 9M
- trailing twelve months = sum of the four most recent quarters (flows) / latest instant (stocks)
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Iterable

import pandas as pd

def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> list of dicts, ~20x faster than DataFrame.to_dict('records') on pandas 3 (no per-cell boxing)."""
    cols = list(df.columns)
    return [dict(zip(cols, row)) for row in zip(*(df[c].tolist() for c in cols))]


Q_DAYS = (80, 100)
H_DAYS = (170, 200)
NM_DAYS = (260, 290)
FY_DAYS = (350, 380)


def classify(start: date | None, end: date) -> str:
    if start is None or pd.isna(start):
        return "INSTANT"
    d = (end - start).days
    if Q_DAYS[0] <= d <= Q_DAYS[1]:
        return "Q"
    if H_DAYS[0] <= d <= H_DAYS[1]:
        return "H"
    if NM_DAYS[0] <= d <= NM_DAYS[1]:
        return "NM"
    if FY_DAYS[0] <= d <= FY_DAYS[1]:
        return "FY"
    return "OTHER"


def fiscal_year_end_month(fy_ends: Iterable[date]) -> int:
    """Most common month among annual-period end dates (a 52/53-week year ending Oct 1 still counts as September)."""
    months = []
    for e in fy_ends:
        if e is None or pd.isna(e):
            continue
        m = e.month
        if e.day <= 4:                    # e.g. 2023-10-01 belongs to a September year end
            m = 12 if m == 1 else m - 1
        months.append(m)
    if not months:
        return 12
    return Counter(months).most_common(1)[0][0]


def _norm_month(end: date) -> int:
    m = end.month
    if end.day <= 4:
        m = 12 if m == 1 else m - 1
    return m


def fiscal_year_of(end: date, fye_month: int) -> int:
    m = _norm_month(end)
    y = end.year if end.day > 4 or end.month != 1 else end.year - 1
    return y + 1 if m > fye_month else y


def fiscal_quarter_of(end: date, fye_month: int) -> int:
    """1..4 for a period ending at `end` — months after FYE: 3→Q1, 6→Q2, 9→Q3, 0→Q4 (nearest multiple of three)."""
    m = _norm_month(end)
    after = (m - fye_month) % 12
    q = int(round(after / 3.0))
    return 4 if q in (0, 4) else q


def derive_quarters(flows: pd.DataFrame) -> pd.DataFrame:
    """Input: rows with period_start, period_end, value, kind in {Q,H,NM,FY} for ONE concept (latest values only).
    Output: quarterly rows (kind='Q') including derived ones, with `derived` and `derivation` set.

    Works on plain records (dict lookups) — per-row DataFrame filtering is pathologically slow on Arrow-backed frames.
    """
    if flows.empty:
        return flows
    recs = sorted(records(flows), key=lambda r: r["period_end"])
    direct = [dict(r, derived=False, derivation=None) for r in recs if r["kind"] == "Q"]
    q_ends = [r["period_end"] for r in direct]
    by_start_kind: dict[tuple, dict] = {}
    for r in recs:
        by_start_kind[(r["period_start"], r["kind"])] = r          # later (longer-history) rows win; periods are already deduped
    out = list(direct)
    need_n = {"H": 1, "NM": 2, "FY": 3}
    for r in recs:
        if r["kind"] not in ("H", "NM", "FY"):
            continue
        end = r["period_end"]
        if any(abs((end - e).days) <= 6 for e in q_ends):
            continue                                   # direct quarter already reported for this end
        prev_kind = {"H": "Q", "NM": "H", "FY": "NM"}[r["kind"]]
        prev = by_start_kind.get((r["period_start"], prev_kind))
        if prev is None:
            # fall back to the sum of directly-reported quarters in the same fiscal-year window
            lo, hi = r["period_start"] - timedelta(days=6), end - timedelta(days=60)
            qs = [d for d in direct if d["period_start"] >= lo and d["period_end"] < hi]
            if len(qs) == need_n[r["kind"]]:
                prev = {"period_end": qs[-1]["period_end"], "value": sum(q["value"] for q in qs)}
        if prev is None:
            continue
        start_q = prev["period_end"] + timedelta(days=1)
        span = (end - start_q).days
        if span < Q_DAYS[0] - 10 or span > Q_DAYS[1] + 10:
            continue
        out.append(dict(r, period_start=start_q, period_end=end, value=r["value"] - prev["value"], kind="Q", derived=True,
                        derivation=f"{r['kind']}-{prev_kind}"))
    if not out:
        return pd.DataFrame(columns=list(flows.columns) + ["derived", "derivation"])
    res = pd.DataFrame(out).sort_values("period_end").drop_duplicates("period_end", keep="first").reset_index(drop=True)
    return res


def ttm(quarters: pd.DataFrame) -> tuple[float | None, date | None, list[date]]:
    """Sum of the four most recent consecutive quarters. Returns (value, end, [quarter ends])."""
    if quarters is None or len(quarters) < 4:
        return None, None, []
    q = quarters.sort_values("period_end").tail(4)
    ends = list(q["period_end"])
    span = (ends[-1] - ends[0]).days
    if span < 250 or span > 300:
        return None, None, []
    return float(q["value"].sum()), ends[-1], ends

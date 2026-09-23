"""Unified catalyst timeline: earnings, ex-dividend, FOMC, high-importance macro releases, monthly/quad-witching OPEX,
estimated 10-K/10-Q due dates. Each event: days_until, importance (1-5), confirmed flag."""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

HIGH_IMPACT = {
    r"cpi|consumer price": 5, r"nonfarm|non-farm|payroll": 5, r"fomc|fed interest rate|federal funds": 5, r"pce": 4, r"gdp": 4,
    r"ism manufacturing|ism services|ism non": 3, r"retail sales": 3, r"ppi|producer price": 3, r"jobless|unemployment claims": 2,
    r"jolts": 2, r"consumer confidence|michigan": 2, r"housing starts|existing home|new home": 1, r"durable": 2, r"trade balance": 1,
    r"fed chair|powell": 4, r"treasury.*auction|auction": 1,
}


def third_friday(y: int, m: int) -> date:
    c = calendar.monthcalendar(y, m)
    fridays = [w[calendar.FRIDAY] for w in c if w[calendar.FRIDAY]]
    return date(y, m, fridays[2])


def opex_dates(today: date, months: int = 4) -> list[dict[str, Any]]:
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        d = third_friday(y, m)
        if d >= today:
            quad = m in (3, 6, 9, 12)
            out.append({"type": "opex", "date": d, "label": "Quad witching" if quad else "Monthly OPEX", "importance": 3 if quad else 2, "confirmed": True, "source": "calendar"})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def filing_due_dates(fye_month: int, last_10k: date | None, last_10q: date | None, today: date, large_accelerated: bool = True) -> list[dict[str, Any]]:
    """Estimate next 10-K (60 days after FYE for large accelerated filers) and 10-Q (40 days after quarter end)."""
    out = []
    k_days, q_days = (60, 40) if large_accelerated else (75, 40)
    y = today.year
    fye = date(y, fye_month, calendar.monthrange(y, fye_month)[1])
    if fye + timedelta(days=k_days) < today:
        fye = date(y + 1, fye_month, calendar.monthrange(y + 1, fye_month)[1])
    out.append({"type": "10-K due", "date": fye + timedelta(days=k_days), "label": "Annual report (10-K) due (est.)", "importance": 2, "confirmed": False, "source": "estimate"})
    for i in (1, 2, 3):
        qm = (fye_month + 3 * i - 1) % 12 + 1
        qy = today.year if qm > today.month or (qm == today.month) else today.year
        qend = date(qy, qm, calendar.monthrange(qy, qm)[1])
        due = qend + timedelta(days=q_days)
        if due < today:
            qend = date(qy + 1, qm, calendar.monthrange(qy + 1, qm)[1])
            due = qend + timedelta(days=q_days)
        if (due - today).days <= 200:
            out.append({"type": "10-Q due", "date": due, "label": "Quarterly report (10-Q) due (est.)", "importance": 1, "confirmed": False, "source": "estimate"})
    return out


def merge(symbol: str, earnings: pd.DataFrame | None, earnings_meta: dict | None, dividends_meta: dict | None, fomc: pd.DataFrame | None,
          econ: pd.DataFrame | None, fye_month: int | None, today: date | None = None, realized_moves: dict | None = None) -> dict[str, Any]:
    today = today or date.today()
    ev: list[dict[str, Any]] = []
    # earnings
    next_earn = None
    if earnings is not None and not earnings.empty:
        fut = [pd.Timestamp(t).date() for t in earnings["ts"] if pd.Timestamp(t).date() >= today]
        if fut:
            next_earn = min(fut)
            confirmed = False
            if earnings_meta and earnings_meta.get("Earnings Date"):
                ed = earnings_meta["Earnings Date"]
                eds = [pd.Timestamp(x).date() for x in (ed if isinstance(ed, list) else [ed])]
                confirmed = len(eds) == 1 and eds[0] == next_earn
            ev.append({"type": "earnings", "date": next_earn, "label": f"{symbol} earnings", "importance": 5, "confirmed": confirmed, "source": "yahoo",
                       "detail": {"historical_mean_abs_move": (realized_moves or {}).get("mean_abs_move_pct"), "eps_estimate": _first(earnings, "eps_estimate", next_earn)}})
    # ex-dividend
    if dividends_meta:
        exd = dividends_meta.get("exDividendDate") or dividends_meta.get("ex_date")
        try:
            d = pd.Timestamp(exd).date() if exd else None
            if d and d >= today:
                ev.append({"type": "ex_dividend", "date": d, "label": f"{symbol} ex-dividend", "importance": 1, "confirmed": True, "source": "nasdaq/yahoo"})
        except Exception:
            pass
    # FOMC
    if fomc is not None and not fomc.empty:
        for r in fomc.itertuples():
            d = pd.Timestamp(r.end).date()
            if today <= d <= today + timedelta(days=120):
                ev.append({"type": "fomc", "date": d, "label": r.label + (" (press conf.)" if getattr(r, "press_conference", False) else ""), "importance": 5, "confirmed": True, "source": "federalreserve.gov"})
    # macro releases (US only, high impact)
    if econ is not None and not econ.empty:
        for r in econ.itertuples():
            if str(getattr(r, "country", "")).lower() not in ("united states", "us", "usa"):
                continue
            name = str(getattr(r, "event", ""))
            imp = 0
            for pat, w in HIGH_IMPACT.items():
                if re.search(pat, name, flags=re.I):
                    imp = max(imp, w)
            if re.search(r"speaks|speech|testif|remarks|member", name, flags=re.I):
                imp = min(imp, 1)          # a Fed official talking is not an FOMC decision
            if imp >= 2:
                d = pd.Timestamp(getattr(r, "date")).date()
                ev.append({"type": "macro", "date": d, "label": name, "importance": imp, "confirmed": True, "source": "nasdaq",
                           "detail": {"time_gmt": getattr(r, "time_gmt", None), "consensus": getattr(r, "consensus", None), "previous": getattr(r, "previous", None)}})
    ev.extend(opex_dates(today))
    if fye_month:
        ev.extend(filing_due_dates(fye_month, None, None, today))
    for e in ev:
        e["days_until"] = (e["date"] - today).days
        e["symbol"] = symbol if e["type"] in ("earnings", "ex_dividend", "10-K due", "10-Q due") else "_MACRO"
    ev = sorted([e for e in ev if e["days_until"] >= -1], key=lambda e: (e["date"], -e["importance"]))
    return {"events": ev, "next_earnings": next_earn, "days_to_earnings": (next_earn - today).days if next_earn else None,
            "next_fomc": next((e["date"] for e in ev if e["type"] == "fomc"), None),
            "high_impact_next_14d": [e for e in ev if e["importance"] >= 4 and e["days_until"] <= 14]}


def _first(df: pd.DataFrame, col: str, d: date):
    try:
        row = df[pd.to_datetime(df["ts"]).dt.date == d]
        v = row[col].iloc[0] if len(row) and col in row.columns else None
        return None if v is None or pd.isna(v) else float(v)
    except Exception:
        return None

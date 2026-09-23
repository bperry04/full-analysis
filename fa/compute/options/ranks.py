"""IV rank / percentile from accumulated history, and IV vs realized.

History sources, best first: IBKR underlying IV bars (years), our own iv_surface_daily snapshots (grows daily).
Below 60 observations the rank is suppressed and flagged SHORT_HISTORY — a rank on 12 days of data is a lie.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MIN_DAYS = 60


def iv_rank(history: pd.Series, current: float | None, lookback: int = 252) -> dict[str, Any]:
    h = history.dropna().astype(float) if history is not None else pd.Series(dtype=float)
    if current is None:
        return {"iv_rank": None, "iv_percentile": None, "history_days": int(len(h)), "flag": "NO_CURRENT"}
    h = h.tail(lookback)
    n = int(len(h))
    if n < MIN_DAYS:
        return {"iv_rank": None, "iv_percentile": None, "history_days": n, "flag": f"SHORT_HISTORY:{n}d", "min": None, "max": None}
    lo, hi = float(h.min()), float(h.max())
    return {"iv_rank": (current - lo) / (hi - lo) if hi > lo else None, "iv_percentile": float((h < current).mean()),
            "history_days": n, "flag": None, "min": lo, "max": hi, "mean": float(h.mean()), "lookback": lookback}


def realized_vol(close: pd.Series, window: int) -> float | None:
    r = np.log(close.astype(float)).diff().dropna()
    if len(r) < window:
        return None
    return float(r.tail(window).std(ddof=1) * np.sqrt(252))


def iv_vs_rv(close: pd.Series, iv30: float | None) -> dict[str, Any]:
    hv20, hv60, hv252 = realized_vol(close, 20), realized_vol(close, 60), realized_vol(close, 252)
    return {"hv20": hv20, "hv60": hv60, "hv252": hv252, "iv30": iv30,
            "iv_rv_20": (iv30 / hv20) if iv30 and hv20 else None, "iv_rv_60": (iv30 / hv60) if iv30 and hv60 else None,
            "vol_risk_premium": (iv30 - hv20) if iv30 and hv20 else None}


def combine_history(surface_hist: pd.DataFrame | None, ib_hist: pd.DataFrame | None) -> pd.Series:
    """Daily IV series indexed by date: prefer our ATM-30 surface where present, otherwise IBKR underlying IV."""
    parts = []
    if ib_hist is not None and not ib_hist.empty and "iv" in ib_hist.columns:
        s = ib_hist.dropna(subset=["iv"])
        dcol = "dt" if "dt" in s.columns else "date"          # provider payload says `date`, the DB table says `dt`
        parts.append(pd.Series(s["iv"].astype(float).values, index=pd.to_datetime(s[dcol])))
    if surface_hist is not None and not surface_hist.empty and "atm_iv_30" in surface_hist.columns:
        s = surface_hist.dropna(subset=["atm_iv_30"])
        dcol = "dt" if "dt" in s.columns else "date"
        parts.append(pd.Series(s["atm_iv_30"].astype(float).values, index=pd.to_datetime(s[dcol])))
    if not parts:
        return pd.Series(dtype=float)
    out = pd.concat(parts)
    return out[~out.index.duplicated(keep="last")].sort_index()

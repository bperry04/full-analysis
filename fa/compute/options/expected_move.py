"""Straddle-implied expected moves per expiry, earnings-implied move (front vs back vol), realized post-earnings moves."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


def straddle_moves(chain: pd.DataFrame, spot: float | None, max_expiries: int = 16) -> pd.DataFrame:
    if not spot:
        return pd.DataFrame()
    c = chain[(chain["dte"] > 0) & chain["mid"].notna()]
    rows = []
    for exp, g in c.groupby("expiry"):
        k = g.iloc[(g["strike"] - spot).abs().argsort()[:1]]["strike"].iloc[0] if len(g) else None
        if k is None:
            continue
        call = g[(g["strike"] == k) & (g["right"] == "C")]["mid"]
        put = g[(g["strike"] == k) & (g["right"] == "P")]["mid"]
        if call.empty or put.empty:
            continue
        straddle = float(call.iloc[0] + put.iloc[0])
        atm_iv = float(g.iloc[(g["strike"] - spot).abs().argsort()[:2]]["iv"].mean())
        dte = int(g["dte"].iloc[0])
        rows.append({"expiry": exp, "dte": dte, "atm_strike": float(k), "straddle": straddle, "implied_move_pct": straddle / spot,
                     "one_sigma_pct": atm_iv * np.sqrt(dte / 365.0) if np.isfinite(atm_iv) else None, "atm_iv": atm_iv,
                     "upper": spot + straddle, "lower": spot - straddle})
        if len(rows) >= max_expiries:
            break
    return pd.DataFrame(rows)


def earnings_implied_move(moves: pd.DataFrame, next_earnings: date | None, today: date) -> dict[str, Any]:
    """If an earnings date falls inside the front expiry, isolate the event variance: σ_evt² = σ_front²·T_front − σ_back²·T_front."""
    if moves is None or moves.empty or next_earnings is None:
        return {"available": False}
    m = moves.sort_values("dte")
    front = m[pd.to_datetime(m["expiry"]).dt.date >= next_earnings]
    if front.empty:
        return {"available": False}
    front = front.iloc[0]
    back = m[m["dte"] > front["dte"] + 20]
    if back.empty:
        return {"available": True, "front_expiry": str(front["expiry"]), "implied_move_pct": float(front["implied_move_pct"]), "method": "front straddle only"}
    back = back.iloc[0]
    tf = front["dte"] / 365.0
    var_evt = front["atm_iv"] ** 2 * tf - back["atm_iv"] ** 2 * tf
    evt = float(np.sqrt(max(var_evt, 0.0))) if np.isfinite(var_evt) else None
    return {"available": True, "front_expiry": str(front["expiry"]), "back_expiry": str(back["expiry"]),
            "implied_move_pct": float(front["implied_move_pct"]), "event_sigma_pct": evt, "front_iv": float(front["atm_iv"]), "back_iv": float(back["atm_iv"]),
            "method": "front straddle; event sigma from front-minus-back variance"}


def realized_earnings_moves(daily: pd.DataFrame, earnings_dates: list[date], n: int = 8) -> dict[str, Any]:
    """Absolute close-to-next-close move around each past earnings date (event after close → next session)."""
    if daily is None or daily.empty or not earnings_dates:
        return {"n": 0}
    d = daily.copy()
    d["d"] = pd.to_datetime(d["ts"]).dt.tz_convert("UTC").dt.date if getattr(d["ts"].dt, "tz", None) is not None else pd.to_datetime(d["ts"]).dt.date
    d = d.set_index("d")["close"].astype(float)
    idx = list(d.index)
    out = []
    for ed in sorted([e for e in earnings_dates if e <= date.today()], reverse=True)[:n]:
        pos = [i for i, x in enumerate(idx) if x >= ed]
        if not pos or pos[0] == 0 or pos[0] + 1 >= len(idx):
            continue
        i = pos[0]
        before = d.iloc[i - 1] if idx[i] == ed else d.iloc[i - 1]
        after = d.iloc[i + 1] if idx[i] == ed else d.iloc[i]
        out.append({"date": ed, "move_pct": float(after / before - 1)})
    if not out:
        return {"n": 0}
    mv = np.array([abs(x["move_pct"]) for x in out])
    return {"n": len(out), "mean_abs_move_pct": float(mv.mean()), "median_abs_move_pct": float(np.median(mv)), "max_abs_move_pct": float(mv.max()),
            "moves": out}

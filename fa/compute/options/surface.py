"""Implied-volatility surface summary: ATM IV per expiry, constant-maturity ATM IV (interpolated in total variance),
term-structure slopes, 25-delta risk reversal / butterfly, skew slope, put/call ratios."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

CM_DAYS = (7, 30, 60, 90, 180, 365)


def _clean(chain: pd.DataFrame) -> pd.DataFrame:
    c = chain.copy()
    c = c[(c["dte"] > 0) & c["iv"].notna() & (c["iv"] > 0.01) & (c["iv"] < 4.0)]
    c = c[~((c["bid"].fillna(0) == 0) & (c["open_interest"].fillna(0) == 0) & (c["volume"].fillna(0) == 0))]
    c = c[c["spread_bps"].fillna(0) < 6000]
    return c


def atm_iv_by_expiry(chain: pd.DataFrame) -> pd.DataFrame:
    """Per expiry: ATM IV (distance-weighted average of the 4 nearest-the-money contracts), dte, OI/volume by right."""
    c = _clean(chain)
    rows = []
    for exp, g in c.groupby("expiry"):
        g = g.dropna(subset=["moneyness"])
        if g.empty:
            continue
        near = g.reindex(g["moneyness"].abs().sort_values().index).head(4)
        w = 1.0 / (near["moneyness"].abs() + 0.005)
        rows.append({"expiry": exp, "dte": int(g["dte"].iloc[0]), "atm_iv": float(np.average(near["iv"], weights=w)), "n": int(len(g)),
                     "call_oi": float(g.loc[g["right"] == "C", "open_interest"].sum()), "put_oi": float(g.loc[g["right"] == "P", "open_interest"].sum()),
                     "call_vol": float(g.loc[g["right"] == "C", "volume"].sum()), "put_vol": float(g.loc[g["right"] == "P", "volume"].sum())})
    if not rows:
        return pd.DataFrame(columns=["expiry", "dte", "atm_iv", "n", "call_oi", "put_oi", "call_vol", "put_vol"])
    return pd.DataFrame(rows).sort_values("dte").reset_index(drop=True)


def constant_maturity(term: pd.DataFrame) -> dict[int, float | None]:
    """Interpolate ATM IV at fixed maturities in total-variance space (linear in σ²T)."""
    out: dict[int, float | None] = {d: None for d in CM_DAYS}
    if term.empty:
        return out
    t = term["dte"].values / 365.0
    v = (term["atm_iv"].values ** 2) * t
    for d in CM_DAYS:
        T = d / 365.0
        if T < t.min() * 0.5 or T > t.max() * 1.5:
            continue
        if T <= t.min():
            out[d] = float(term["atm_iv"].iloc[0])
        elif T >= t.max():
            out[d] = float(term["atm_iv"].iloc[-1])
        else:
            tv = float(np.interp(T, t, v))
            out[d] = float(np.sqrt(max(tv, 1e-8) / T))
    return out


def _delta_iv(g: pd.DataFrame, right: str, target_delta: float) -> float | None:
    s = g[(g["right"] == right) & g["delta"].notna()]
    if s.empty:
        return None
    d = s["delta"].abs()
    idx = (d - target_delta).abs().sort_values().index[:2]
    near = s.loc[idx]
    if near.empty or (near["delta"].abs() - target_delta).abs().min() > 0.15:
        return None
    w = 1.0 / ((near["delta"].abs() - target_delta).abs() + 0.01)
    return float(np.average(near["iv"], weights=w))


def skew_metrics(chain: pd.DataFrame, target_dte: int = 30) -> dict[str, Any]:
    c = _clean(chain)
    if c.empty:
        return {}
    exps = c.groupby("expiry")["dte"].first().sort_values()
    exps = exps[exps >= 7]
    if exps.empty:
        return {}
    below, above = exps[exps <= target_dte], exps[exps > target_dte]
    picks = ([below.index[-1]] if len(below) else []) + ([above.index[0]] if len(above) else [])
    res = []
    for e in picks:
        g = c[c["expiry"] == e]
        atm = _delta_iv(g, "C", 0.5) or _delta_iv(g, "P", 0.5)
        c25, p25 = _delta_iv(g, "C", 0.25), _delta_iv(g, "P", 0.25)
        c10, p10 = _delta_iv(g, "C", 0.10), _delta_iv(g, "P", 0.10)
        otm = g[((g["right"] == "P") & (g["moneyness"] < 0)) | ((g["right"] == "C") & (g["moneyness"] > 0))]
        otm = otm[otm["moneyness"].abs() <= 0.12]
        slope = float(np.polyfit(otm["moneyness"].values, otm["iv"].values, 1)[0]) if len(otm) >= 5 else None
        res.append({"expiry": str(e), "dte": int(exps[e]), "atm": atm, "rr25": (c25 - p25) if c25 and p25 else None,
                    "fly25": ((c25 + p25) / 2 - atm) if c25 and p25 and atm else None,
                    "rr10": (c10 - p10) if c10 and p10 else None, "skew_slope": slope, "put25_iv": p25, "call25_iv": c25})
    if not res:
        return {}
    if len(res) == 1:
        out = dict(res[0])
    else:
        d0, d1 = res[0]["dte"], res[1]["dte"]
        w = (target_dte - d0) / (d1 - d0) if d1 != d0 else 0.5
        out = {}
        for k in ("atm", "rr25", "fly25", "rr10", "skew_slope", "put25_iv", "call25_iv"):
            a, b = res[0][k], res[1][k]
            out[k] = (a * (1 - w) + b * w) if a is not None and b is not None else (a if a is not None else b)
        out["expiry"] = f"{res[0]['expiry']}..{res[1]['expiry']}"
        out["dte"] = target_dte
    out["by_expiry"] = res
    return out


def _term_shape(cm: dict[int, float | None]) -> str | None:
    a, b = cm.get(30), cm.get(90)
    if a is None or b is None:
        return None
    return "contango" if b > a * 1.03 else ("backwardation" if b < a * 0.97 else "flat")


def surface_summary(chain: pd.DataFrame, spot: float | None, iv30_vendor: float | None = None) -> dict[str, Any]:
    term = atm_iv_by_expiry(chain)
    cm = constant_maturity(term)
    sk = skew_metrics(chain, 30)
    c = _clean(chain)
    call_oi = float(c.loc[c["right"] == "C", "open_interest"].sum()) if len(c) else 0.0
    put_oi = float(c.loc[c["right"] == "P", "open_interest"].sum()) if len(c) else 0.0
    call_vol = float(c.loc[c["right"] == "C", "volume"].sum()) if len(c) else 0.0
    put_vol = float(c.loc[c["right"] == "P", "volume"].sum()) if len(c) else 0.0
    return {
        "spot": spot, "term": term, "atm_iv": {f"d{d}": v for d, v in cm.items()}, "iv30_vendor": iv30_vendor,
        "term_slope_30_90": (cm[90] - cm[30]) if cm.get(90) is not None and cm.get(30) is not None else None,
        "term_slope_7_30": (cm[30] - cm[7]) if cm.get(30) is not None and cm.get(7) is not None else None,
        "term_shape": _term_shape(cm), "skew": sk,
        "put_call_oi": (put_oi / call_oi) if call_oi else None, "put_call_vol": (put_vol / call_vol) if call_vol else None,
        "call_oi": call_oi, "put_oi": put_oi, "call_vol": call_vol, "put_vol": put_vol,
        "total_oi": call_oi + put_oi, "total_volume": call_vol + put_vol, "contracts_n": int(len(chain)),
        "next_expiry": str(term["expiry"].iloc[0]) if len(term) else None,
    }

"""Regime classification: trend strength, volatility regime, Hurst exponent, drawdown state, gap statistics."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def hurst(close: pd.Series, max_lag: int = 100) -> float | None:
    x = np.log(close.astype(float).dropna().values)
    if len(x) < max_lag * 2:
        return None
    lags = range(2, max_lag)
    tau = [np.std(x[lag:] - x[:-lag]) for lag in lags]
    if any(t <= 0 for t in tau):
        return None
    slope = np.polyfit(np.log(list(lags)), np.log(tau), 1)[0]
    return float(slope)


def drawdown(close: pd.Series) -> dict[str, Any]:
    c = close.astype(float)
    peak = c.cummax()
    dd = c / peak - 1
    i_trough = int(dd.idxmin()) if len(dd) else None
    return {"current_dd": float(dd.iloc[-1]), "max_dd": float(dd.min()), "days_since_high": int((len(c) - 1) - int(c.idxmax())) if len(c) else None,
            "peak": float(peak.iloc[-1])}


def vol_regime(ind: pd.DataFrame) -> dict[str, Any]:
    hv = ind["hv_cc_20"].dropna()
    if len(hv) < 60:
        return {}
    cur = float(hv.iloc[-1])
    hist = hv.tail(504)
    pct = float((hist < cur).mean())
    return {"hv20": cur, "hv20_percentile_2y": pct, "regime": "high_vol" if pct > 0.8 else ("low_vol" if pct < 0.2 else "normal"),
            "vol_of_vol": float(hv.tail(60).std() / hv.tail(60).mean()) if hv.tail(60).mean() else None}


def vol_cone(df: pd.DataFrame) -> list[dict[str, Any]]:
    lr = np.log(df["close"].astype(float)).diff().dropna()
    out = []
    for n in (10, 20, 30, 60, 90, 120, 252):
        rv = lr.rolling(n).std(ddof=1) * np.sqrt(252)
        rv = rv.dropna()
        if len(rv) < 30:
            continue
        out.append({"window": n, "current": float(rv.iloc[-1]), "min": float(rv.min()), "p10": float(rv.quantile(0.1)), "p25": float(rv.quantile(0.25)),
                    "median": float(rv.median()), "p75": float(rv.quantile(0.75)), "p90": float(rv.quantile(0.9)), "max": float(rv.max())})
    return out


def gaps(df: pd.DataFrame, lookback: int = 252) -> dict[str, Any]:
    d = df.tail(lookback)
    g = (d["open"] / d["close"].shift() - 1).dropna()
    if g.empty:
        return {}
    big = g[g.abs() > 0.03]
    return {"n_gaps_gt_3pct": int(len(big)), "mean_abs_gap": float(g.abs().mean()), "last_gap": float(g.iloc[-1]),
            "gap_std": float(g.std())}


def classify(ind: pd.DataFrame, df: pd.DataFrame) -> dict[str, Any]:
    if ind is None or ind.empty:
        return {}
    last = ind.iloc[-1]
    adx = float(last.get("adx", np.nan))
    slope = float(last.get("lr_slope_20", np.nan))
    trend = "trending_up" if adx > 25 and slope > 0 else ("trending_down" if adx > 25 and slope < 0 else "ranging")
    return {"trend_regime": trend, "adx": adx, "lr_slope_20_annualized": slope, "hurst": hurst(df["close"]), **vol_regime(ind),
            "drawdown": drawdown(df["close"].reset_index(drop=True)), "gaps": gaps(df), "vol_cone": vol_cone(df)}

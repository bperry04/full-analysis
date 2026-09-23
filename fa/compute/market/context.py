"""Overall market context: index trends, sector relative strength, VIX level/term, credit, rates, dollar, commodities → risk-on/off composite.
Plus per-name macro sensitivity: rolling multivariate betas to the factors that move it."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

INDEX = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "DIA": "Dow"}
SECTORS = {"XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care", "XLY": "Cons. Discretionary", "XLP": "Cons. Staples",
           "XLI": "Industrials", "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication"}
FACTORS = {"SPY": "market", "TLT": "long rates (bond price)", "UUP": "dollar", "USO": "oil", "HYG": "high yield credit", "GLD": "gold"}
SECTOR_BY_YAHOO = {"Technology": "XLK", "Financial Services": "XLF", "Energy": "XLE", "Healthcare": "XLV", "Consumer Cyclical": "XLY",
                   "Consumer Defensive": "XLP", "Industrials": "XLI", "Utilities": "XLU", "Basic Materials": "XLB", "Real Estate": "XLRE",
                   "Communication Services": "XLC"}


def _ret(df: pd.DataFrame, n: int) -> float | None:
    c = df["close"].astype(float)
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None


def _trend(df: pd.DataFrame) -> dict[str, Any]:
    c = df["close"].astype(float)
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    return {"price": float(c.iloc[-1]), "above_50d": bool(c.iloc[-1] > s50.iloc[-1]) if pd.notna(s50.iloc[-1]) else None,
            "above_200d": bool(c.iloc[-1] > s200.iloc[-1]) if pd.notna(s200.iloc[-1]) else None,
            "r_1m": _ret(df, 21), "r_3m": _ret(df, 63), "r_6m": _ret(df, 126), "r_ytd": _ytd(df),
            "dd_from_52w_high": float(c.iloc[-1] / c.tail(252).max() - 1)}


def _ytd(df: pd.DataFrame) -> float | None:
    d = df.copy()
    d["y"] = pd.to_datetime(d["ts"]).dt.year
    this = d[d["y"] == d["y"].max()]
    prev = d[d["y"] < d["y"].max()]
    if prev.empty or this.empty:
        return None
    return float(this["close"].iloc[-1] / prev["close"].iloc[-1] - 1)


def market_context(bars: dict[str, pd.DataFrame], vix_hist: pd.DataFrame | None, yc: pd.DataFrame | None, subject_sector: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {"indices": {}, "sectors": {}, "factors": {}}
    for s, name in INDEX.items():
        if s in bars and not bars[s].empty:
            out["indices"][s] = {"name": name, **_trend(bars[s])}
    spy = bars.get("SPY")
    for s, name in SECTORS.items():
        if s in bars and not bars[s].empty:
            t = _trend(bars[s])
            if spy is not None and not spy.empty:
                t["rs_1m_vs_spy"] = (t["r_1m"] - (_ret(spy, 21) or 0)) if t["r_1m"] is not None else None
                t["rs_3m_vs_spy"] = (t["r_3m"] - (_ret(spy, 63) or 0)) if t["r_3m"] is not None else None
            out["sectors"][s] = {"name": name, **t}
    for s, name in FACTORS.items():
        if s in bars and not bars[s].empty:
            out["factors"][s] = {"name": name, "r_1m": _ret(bars[s], 21), "r_3m": _ret(bars[s], 63)}
    # VIX
    if vix_hist is not None and not vix_hist.empty and "close" in vix_hist.columns:
        v = vix_hist["close"].astype(float)
        cur = float(v.iloc[-1])
        out["vix"] = {"level": cur, "percentile_1y": float((v.tail(252) < cur).mean()), "percentile_5y": float((v.tail(1260) < cur).mean()),
                      "change_5d": float(cur - v.iloc[-6]) if len(v) > 6 else None, "mean_1y": float(v.tail(252).mean()),
                      "regime": "high" if cur > 25 else ("elevated" if cur > 18 else ("low" if cur < 13 else "normal"))}
    if "^VIX3M" in bars and "^VIX" in bars and not bars["^VIX"].empty and not bars["^VIX3M"].empty:
        a, b = float(bars["^VIX"]["close"].iloc[-1]), float(bars["^VIX3M"]["close"].iloc[-1])
        out["vix_term"] = {"vix": a, "vix3m": b, "ratio": a / b if b else None, "structure": "backwardation (stress)" if a > b else "contango (calm)"}
    # rates / curve
    if yc is not None and not yc.empty:
        last = yc.iloc[-1]
        m1 = yc.iloc[-22] if len(yc) > 22 else yc.iloc[0]
        def g(col, row=last):
            return float(row[col]) if col in row and pd.notna(row[col]) else None
        out["rates"] = {"dgs3mo": g("DGS3MO"), "dgs2": g("DGS2"), "dgs10": g("DGS10"), "dgs30": g("DGS30"),
                        "spread_10y_2y": (g("DGS10") - g("DGS2")) if g("DGS10") is not None and g("DGS2") is not None else None,
                        "spread_10y_3m": (g("DGS10") - g("DGS3MO")) if g("DGS10") is not None and g("DGS3MO") is not None else None,
                        "chg_10y_1m": (g("DGS10") - g("DGS10", m1)) if g("DGS10") is not None and g("DGS10", m1) is not None else None,
                        "as_of": str(last["date"])}
    # credit: HYG/LQD ratio trend
    if "HYG" in bars and "LQD" in bars and not bars["HYG"].empty and not bars["LQD"].empty:
        h = bars["HYG"].set_index("ts")["close"]
        l = bars["LQD"].set_index("ts")["close"]
        ratio = (h / l).dropna()
        if len(ratio) > 63:
            out["credit"] = {"hyg_lqd_ratio": float(ratio.iloc[-1]), "ratio_chg_1m": float(ratio.iloc[-1] / ratio.iloc[-22] - 1), "ratio_chg_3m": float(ratio.iloc[-1] / ratio.iloc[-64] - 1)}
    # composite risk appetite (-1..1)
    votes = []
    for s in ("SPY", "QQQ", "IWM"):
        i = out["indices"].get(s)
        if i and i.get("above_50d") is not None:
            votes.append(1 if i["above_50d"] else -1)
    if out.get("vix"):
        votes.append(-1 if out["vix"]["level"] > 22 else (1 if out["vix"]["level"] < 16 else 0))
    if out.get("vix_term"):
        votes.append(-1 if out["vix_term"]["ratio"] and out["vix_term"]["ratio"] > 1 else 1)
    if out.get("credit"):
        votes.append(1 if out["credit"]["ratio_chg_1m"] > 0 else -1)
    xly, xlp = out["sectors"].get("XLY"), out["sectors"].get("XLP")
    if xly and xlp and xly.get("r_1m") is not None and xlp.get("r_1m") is not None:
        votes.append(1 if xly["r_1m"] > xlp["r_1m"] else -1)
    out["risk_appetite"] = {"score": float(np.mean(votes)) if votes else None, "votes": len(votes),
                            "label": ("risk-on" if votes and np.mean(votes) > 0.3 else ("risk-off" if votes and np.mean(votes) < -0.3 else "mixed"))}
    out["subject_sector_etf"] = SECTOR_BY_YAHOO.get(subject_sector or "", None)
    if out["subject_sector_etf"] and out["subject_sector_etf"] in out["sectors"]:
        out["subject_sector"] = out["sectors"][out["subject_sector_etf"]]
    # breadth proxy: share of sector ETFs above their 50d
    above = [s["above_50d"] for s in out["sectors"].values() if s.get("above_50d") is not None]
    out["breadth_sectors_above_50d"] = float(np.mean(above)) if above else None
    return out


def sensitivity(stock: pd.DataFrame, factor_bars: dict[str, pd.DataFrame], window: int = 126, sector_etf: str | None = None) -> dict[str, Any]:
    """Multivariate OLS of the name's daily returns on factor returns (last `window` days) + univariate correlations."""
    def rets(df):
        s = df.set_index(pd.to_datetime(df["ts"]).dt.normalize())["close"].astype(float)
        return np.log(s).diff()
    y = rets(stock).rename("y")
    cols = {}
    names = dict(FACTORS)
    if sector_etf and sector_etf in factor_bars:
        names[sector_etf] = f"sector ({SECTORS.get(sector_etf, sector_etf)})"
    for s in names:
        if s in factor_bars and not factor_bars[s].empty:
            cols[s] = rets(factor_bars[s])
    if not cols:
        return {}
    X = pd.concat([y, pd.DataFrame(cols)], axis=1).dropna().tail(window)
    if len(X) < 40:
        return {}
    uni = {s: {"name": names[s], "beta": float(np.cov(X["y"], X[s])[0, 1] / X[s].var()) if X[s].var() else None, "corr": float(X["y"].corr(X[s]))} for s in cols}
    # multivariate (market + sector + rates + dollar + oil + credit), ridge-lite to keep it stable
    fs = [s for s in cols]
    A = np.column_stack([np.ones(len(X))] + [X[s].values for s in fs])
    lam = 1e-4 * len(X)
    beta = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ X["y"].values)
    resid = X["y"].values - A @ beta
    r2 = 1 - resid.var() / X["y"].var() if X["y"].var() else None
    multi = {s: float(b) for s, b in zip(fs, beta[1:])}
    ranked = sorted(uni.items(), key=lambda kv: -abs(kv[1]["corr"] or 0))
    return {"window_days": int(len(X)), "univariate": uni, "multivariate_betas": multi, "r2_multivariate": float(r2) if r2 is not None else None,
            "idiosyncratic_share": float(1 - r2) if r2 is not None else None, "most_influential": [k for k, _ in ranked[:3]],
            "note": "log-return OLS; betas are per 1% factor move"}

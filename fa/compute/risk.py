"""Risk statistics: beta (Blume-adjusted, weekly 2y + daily 1y), correlation, VaR/CVaR, Sharpe/Sortino, skew/kurtosis, capture ratios."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _returns(df: pd.DataFrame, freq: str = "D") -> pd.Series:
    s = df.set_index(pd.to_datetime(df["ts"]))["close"].astype(float)
    if freq == "W":
        s = s.resample("W-FRI").last()
    return np.log(s).diff().dropna()


def beta(stock: pd.DataFrame, bench: pd.DataFrame, freq: str = "W", years: int = 2) -> dict[str, Any]:
    a, b = _returns(stock, freq), _returns(bench, freq)
    j = pd.concat([a, b], axis=1, join="inner").dropna()
    j.columns = ["s", "m"]
    j = j[j.index >= j.index.max() - pd.Timedelta(days=365 * years)]
    if len(j) < 30:
        return {"beta": None}
    cov = np.cov(j["s"], j["m"])
    raw = cov[0, 1] / cov[1, 1] if cov[1, 1] else None
    r2 = float(np.corrcoef(j["s"], j["m"])[0, 1] ** 2)
    return {"beta_raw": raw, "beta_adjusted": (0.67 * raw + 0.33) if raw is not None else None, "r2": r2, "n": int(len(j)),
            "freq": freq, "years": years, "correlation": float(np.sqrt(r2)) * (1 if raw and raw > 0 else -1)}


def var_cvar(returns: pd.Series, level: float = 0.95) -> dict[str, float | None]:
    r = returns.dropna()
    if len(r) < 60:
        return {"var": None, "cvar": None}
    q = float(np.quantile(r, 1 - level))
    tail = r[r <= q]
    return {"var": -q, "cvar": -float(tail.mean()) if len(tail) else None, "var_parametric": float(-(r.mean() + r.std() * _z(level)))}


def _z(level: float) -> float:
    from scipy.stats import norm
    return float(norm.ppf(1 - level))


def capture(stock: pd.DataFrame, bench: pd.DataFrame) -> dict[str, float | None]:
    a, b = _returns(stock, "D"), _returns(bench, "D")
    j = pd.concat([a, b], axis=1, join="inner").dropna().tail(504)
    j.columns = ["s", "m"]
    up, dn = j[j["m"] > 0], j[j["m"] < 0]
    return {"up_capture": float(up["s"].mean() / up["m"].mean()) if len(up) and up["m"].mean() else None,
            "down_capture": float(dn["s"].mean() / dn["m"].mean()) if len(dn) and dn["m"].mean() else None}


def summary(stock: pd.DataFrame, bench: pd.DataFrame | None, rf_annual: float = 0.04) -> dict[str, Any]:
    r = _returns(stock, "D")
    r1y = r.tail(252)
    out: dict[str, Any] = {}
    if len(r1y) >= 60:
        ann_ret = float(r1y.mean() * 252)
        ann_vol = float(r1y.std() * np.sqrt(252))
        downside = float(r1y[r1y < 0].std() * np.sqrt(252)) if (r1y < 0).any() else None
        out.update({"ann_return_1y": ann_ret, "ann_vol_1y": ann_vol, "sharpe_1y": (ann_ret - rf_annual) / ann_vol if ann_vol else None,
                    "sortino_1y": (ann_ret - rf_annual) / downside if downside else None, "skew_1y": float(r1y.skew()), "kurtosis_1y": float(r1y.kurt()),
                    "var_95_1d": var_cvar(r1y, 0.95), "var_99_1d": var_cvar(r1y, 0.99),
                    "worst_day_1y": float(r1y.min()), "best_day_1y": float(r1y.max()), "pct_up_days": float((r1y > 0).mean())})
    if bench is not None and not bench.empty:
        out["beta_weekly_2y"] = beta(stock, bench, "W", 2)
        out["beta_daily_1y"] = beta(stock, bench, "D", 1)
        out["capture"] = capture(stock, bench)
    return out

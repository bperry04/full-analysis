"""Native technical indicators (pure pandas/numpy). Input: OHLCV frame with columns ts, open, high, low, close, volume."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wma(s: pd.Series, n: int) -> pd.Series:
    w = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def hma(s: pd.Series, n: int) -> pd.Series:
    half, sq = max(int(n / 2), 1), max(int(np.sqrt(n)), 1)
    return wma(2 * wma(s, half) - wma(s, n), sq)


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    ru = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rd = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = ru / rd.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> pd.DataFrame:
    line = ema(s, fast) - ema(s, slow)
    signal = line.ewm(span=sig, adjust=False).mean()
    return pd.DataFrame({"macd": line, "macd_signal": signal, "macd_hist": line - signal})


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift()
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up, dn = df["high"].diff(), -df["low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean(), "plus_di": pdi, "minus_di": mdi})


def stochastic(df: pd.DataFrame, n: int = 14, d: int = 3) -> pd.DataFrame:
    lo, hi = df["low"].rolling(n).min(), df["high"].rolling(n).max()
    k = 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)
    return pd.DataFrame({"stoch_k": k, "stoch_d": k.rolling(d).mean()})


def stoch_rsi(s: pd.Series, n: int = 14) -> pd.Series:
    r = rsi(s, n)
    lo, hi = r.rolling(n).min(), r.rolling(n).max()
    return (r - lo) / (hi - lo).replace(0, np.nan)


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    lo, hi = df["low"].rolling(n).min(), df["high"].rolling(n).max()
    return -100 * (hi - df["close"]) / (hi - lo).replace(0, np.nan)


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(n).mean()
    md = (tp - ma).abs().rolling(n).mean()
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    m, sd = sma(s, n), s.rolling(n).std(ddof=0)
    up, lo = m + k * sd, m - k * sd
    return pd.DataFrame({"bb_mid": m, "bb_upper": up, "bb_lower": lo, "bb_pct_b": (s - lo) / (up - lo).replace(0, np.nan), "bb_width": (up - lo) / m})


def keltner(df: pd.DataFrame, n: int = 20, mult: float = 1.5) -> pd.DataFrame:
    m, a = ema(df["close"], n), atr(df, n)
    return pd.DataFrame({"kc_mid": m, "kc_upper": m + mult * a, "kc_lower": m - mult * a})


def donchian(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    return pd.DataFrame({"dc_upper": df["high"].rolling(n).max(), "dc_lower": df["low"].rolling(n).min()})


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff()).fillna(0) * df["volume"]).cumsum()


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"]).replace(0, np.nan)
    mfv = mfm.fillna(0) * df["volume"]
    return mfv.rolling(n).sum() / df["volume"].rolling(n).sum().replace(0, np.nan)


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    flow = tp * df["volume"]
    pos = flow.where(tp > tp.shift(), 0.0).rolling(n).sum()
    neg = flow.where(tp < tp.shift(), 0.0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg.replace(0, np.nan))


def ad_line(df: pd.DataFrame) -> pd.Series:
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"]).replace(0, np.nan)
    return (mfm.fillna(0) * df["volume"]).cumsum()


def vwap(df: pd.DataFrame, anchor_idx: int | None = None) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv, v = tp * df["volume"], df["volume"]
    if anchor_idx is not None:
        pv, v = pv.iloc[anchor_idx:], v.iloc[anchor_idx:]
        return (pv.cumsum() / v.cumsum().replace(0, np.nan)).reindex(df.index)
    return pv.cumsum() / v.cumsum().replace(0, np.nan)


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.DataFrame:
    hl2 = (df["high"] + df["low"]) / 2
    a = atr(df, n)
    upper, lower = hl2 + mult * a, hl2 - mult * a
    st = pd.Series(np.nan, index=df.index)
    direction = pd.Series(1, index=df.index)
    close = df["close"].values
    up, lo = upper.values.copy(), lower.values.copy()
    for i in range(1, len(df)):
        if np.isnan(up[i - 1]):
            continue
        lo[i] = lo[i] if lo[i] > lo[i - 1] or close[i - 1] < lo[i - 1] else lo[i - 1]
        up[i] = up[i] if up[i] < up[i - 1] or close[i - 1] > up[i - 1] else up[i - 1]
        if close[i] > up[i - 1]:
            direction.iloc[i] = 1
        elif close[i] < lo[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
        st.iloc[i] = lo[i] if direction.iloc[i] == 1 else up[i]
    return pd.DataFrame({"supertrend": st, "supertrend_dir": direction})


def ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    def mid(n):
        return (df["high"].rolling(n).max() + df["low"].rolling(n).min()) / 2
    tenkan, kijun = mid(9), mid(26)
    return pd.DataFrame({"tenkan": tenkan, "kijun": kijun, "senkou_a": ((tenkan + kijun) / 2).shift(26), "senkou_b": mid(52).shift(26)})


def linreg_slope(s: pd.Series, n: int = 20) -> pd.DataFrame:
    x = np.arange(n)
    xm = x - x.mean()
    def f(y):
        ym = y - y.mean()
        b = np.dot(xm, ym) / np.dot(xm, xm)
        r2 = (b * b * np.dot(xm, xm)) / np.dot(ym, ym) if np.dot(ym, ym) else 0.0
        return b / y.mean() if y.mean() else 0.0, r2
    out = s.rolling(n).apply(lambda y: f(y)[0], raw=True)
    r2 = s.rolling(n).apply(lambda y: f(y)[1], raw=True)
    return pd.DataFrame({f"lr_slope_{n}": out * 252, f"lr_r2_{n}": r2})


def realized_vols(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    lr = np.log(df["close"]).diff()
    cc = lr.rolling(n).std(ddof=1) * np.sqrt(252)
    park = np.sqrt((np.log(df["high"] / df["low"]) ** 2).rolling(n).mean() / (4 * np.log(2))) * np.sqrt(252)
    gk = np.sqrt((0.5 * np.log(df["high"] / df["low"]) ** 2 - (2 * np.log(2) - 1) * np.log(df["close"] / df["open"]) ** 2).rolling(n).mean()) * np.sqrt(252)
    o = np.log(df["open"] / df["close"].shift())
    c = np.log(df["close"] / df["open"])
    rs = (np.log(df["high"] / df["open"]) * np.log(df["high"] / df["close"]) + np.log(df["low"] / df["open"]) * np.log(df["low"] / df["close"]))
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    yz = np.sqrt(o.rolling(n).var(ddof=1) + k * c.rolling(n).var(ddof=1) + (1 - k) * rs.rolling(n).mean()) * np.sqrt(252)
    return pd.DataFrame({f"hv_cc_{n}": cc, f"hv_park_{n}": park, f"hv_gk_{n}": gk, f"hv_yz_{n}": yz})


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Full indicator frame for one interval."""
    d = df.copy().reset_index(drop=True)
    c = d["close"].astype(float)
    out = pd.DataFrame(index=d.index)
    for n in (10, 20, 50, 100, 200):
        out[f"sma_{n}"] = sma(c, n)
    for n in (9, 21, 50, 200):
        out[f"ema_{n}"] = ema(c, n)
    out["hma_20"] = hma(c, 20)
    out = pd.concat([out, macd(c), adx(d), stochastic(d), bollinger(c), keltner(d), donchian(d), supertrend(d), ichimoku(d), linreg_slope(c, 20), realized_vols(d, 20)], axis=1)
    out["rsi_14"], out["rsi_2"] = rsi(c, 14), rsi(c, 2)
    out["stoch_rsi"] = stoch_rsi(c)
    out["williams_r"] = williams_r(d)
    out["cci_20"] = cci(d)
    out["roc_10"], out["roc_21"], out["roc_63"] = c.pct_change(10), c.pct_change(21), c.pct_change(63)
    out["atr_14"] = atr(d)
    out["natr_14"] = out["atr_14"] / c
    out["obv"], out["cmf_20"], out["mfi_14"], out["ad"] = obv(d), cmf(d), mfi(d), ad_line(d)
    out["vwap_cum"] = vwap(d)
    out["vol_sma_20"] = d["volume"].rolling(20).mean()
    out["rel_volume"] = d["volume"] / out["vol_sma_20"].replace(0, np.nan)
    out["hi_252"], out["lo_252"] = d["high"].rolling(252, min_periods=60).max(), d["low"].rolling(252, min_periods=60).min()
    out["pos_52w"] = (c - out["lo_252"]) / (out["hi_252"] - out["lo_252"]).replace(0, np.nan)
    for n in (20, 50, 200):
        sd = c.rolling(n).std(ddof=0)
        out[f"z_sma_{n}"] = (c - out[f"sma_{n}"]) / sd.replace(0, np.nan)
    out["squeeze_on"] = (out["bb_upper"] < out["kc_upper"]) & (out["bb_lower"] > out["kc_lower"])
    out["ts"], out["close"], out["volume"] = d["ts"], c, d["volume"]
    return out


def snapshot(ind: pd.DataFrame) -> dict[str, Any]:
    """Latest values + signal states for one interval."""
    if ind is None or ind.empty:
        return {}
    last = ind.iloc[-1]
    prev = ind.iloc[-2] if len(ind) > 1 else last
    c = float(last["close"])
    def g(k):
        v = last.get(k)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else (bool(v) if isinstance(v, (bool, np.bool_)) else float(v))
    sig = {
        "trend_sma": "up" if all(g(f"sma_{n}") and c > g(f"sma_{n}") for n in (20, 50, 200) if g(f"sma_{n}")) else ("down" if all(g(f"sma_{n}") and c < g(f"sma_{n}") for n in (20, 50, 200) if g(f"sma_{n}")) else "mixed"),
        "ma_stack_bullish": bool(g("sma_20") and g("sma_50") and g("sma_200") and g("sma_20") > g("sma_50") > g("sma_200")),
        "ma_stack_bearish": bool(g("sma_20") and g("sma_50") and g("sma_200") and g("sma_20") < g("sma_50") < g("sma_200")),
        "golden_cross_recent": bool(g("sma_50") and g("sma_200") and g("sma_50") > g("sma_200") and float(prev.get("sma_50", np.nan)) <= float(prev.get("sma_200", np.nan))),
        "rsi_state": "overbought" if (g("rsi_14") or 50) > 70 else ("oversold" if (g("rsi_14") or 50) < 30 else "neutral"),
        "macd_state": "bullish" if (g("macd_hist") or 0) > 0 else "bearish",
        "macd_cross_up": bool((g("macd_hist") or 0) > 0 and float(prev.get("macd_hist", 0) or 0) <= 0),
        "adx_trend": "strong" if (g("adx") or 0) > 25 else ("weak" if (g("adx") or 0) < 20 else "moderate"),
        "di_bias": "bullish" if (g("plus_di") or 0) > (g("minus_di") or 0) else "bearish",
        "bb_state": "above_upper" if g("bb_pct_b") is not None and g("bb_pct_b") > 1 else ("below_lower" if g("bb_pct_b") is not None and g("bb_pct_b") < 0 else "inside"),
        "supertrend": "bullish" if (g("supertrend_dir") or 0) > 0 else "bearish",
        "ichimoku": ("above_cloud" if g("senkou_a") and g("senkou_b") and c > max(g("senkou_a"), g("senkou_b")) else ("below_cloud" if g("senkou_a") and g("senkou_b") and c < min(g("senkou_a"), g("senkou_b")) else "in_cloud")),
        "squeeze": bool(g("squeeze_on")),
        "rel_volume": g("rel_volume"),
    }
    keys = [k for k in ind.columns if k not in ("ts",)]
    return {"latest": {k: g(k) for k in keys}, "signals": sig, "ts": str(last["ts"])}

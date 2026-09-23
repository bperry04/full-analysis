"""Price structure: swing highs/lows, support/resistance clusters, volume profile (POC/VAH/VAL), pivots, anchored VWAPs."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from fa.compute.technical.indicators import vwap


def swings(df: pd.DataFrame, k: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    h, l = df["high"].values, df["low"].values
    hi_idx = [i for i in range(k, len(df) - k) if h[i] == h[i - k:i + k + 1].max()]
    lo_idx = [i for i in range(k, len(df) - k) if l[i] == l[i - k:i + k + 1].min()]
    return df.iloc[hi_idx][["ts", "high"]].rename(columns={"high": "price"}), df.iloc[lo_idx][["ts", "low"]].rename(columns={"low": "price"})


def cluster_levels(prices: list[float], spot: float, tol: float = 0.01) -> list[dict[str, Any]]:
    if not prices:
        return []
    p = sorted(prices)
    clusters: list[list[float]] = [[p[0]]]
    for x in p[1:]:
        if abs(x - clusters[-1][-1]) / spot <= tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return sorted([{"level": float(np.mean(c)), "touches": len(c)} for c in clusters], key=lambda d: -d["touches"])


def volume_profile(df: pd.DataFrame, bins: int = 40, lookback: int = 120) -> dict[str, Any]:
    d = df.tail(lookback)
    if d.empty:
        return {}
    lo, hi = float(d["low"].min()), float(d["high"].max())
    edges = np.linspace(lo, hi, bins + 1)
    vol = np.zeros(bins)
    for r in d.itertuples():
        a, b = np.searchsorted(edges, r.low, side="right") - 1, np.searchsorted(edges, r.high, side="right") - 1
        a, b = max(a, 0), min(b, bins - 1)
        vol[a:b + 1] += r.volume / (b - a + 1)
    poc_i = int(vol.argmax())
    total = vol.sum()
    # value area: expand around POC until 70% of volume
    lo_i = hi_i = poc_i
    acc = vol[poc_i]
    while acc < 0.7 * total and (lo_i > 0 or hi_i < bins - 1):
        left = vol[lo_i - 1] if lo_i > 0 else -1
        right = vol[hi_i + 1] if hi_i < bins - 1 else -1
        if right >= left:
            hi_i += 1
            acc += vol[hi_i]
        else:
            lo_i -= 1
            acc += vol[lo_i]
    mids = (edges[:-1] + edges[1:]) / 2
    return {"poc": float(mids[poc_i]), "vah": float(edges[hi_i + 1]), "val": float(edges[lo_i]), "lookback": len(d),
            "profile": pd.DataFrame({"price": mids, "volume": vol})}


def pivots(df: pd.DataFrame) -> dict[str, float]:
    last = df.iloc[-1]
    h, l, c = float(last["high"]), float(last["low"]), float(last["close"])
    p = (h + l + c) / 3
    return {"pivot": p, "r1": 2 * p - l, "s1": 2 * p - h, "r2": p + (h - l), "s2": p - (h - l), "r3": h + 2 * (p - l), "s3": l - 2 * (h - p)}


def anchored_vwaps(df: pd.DataFrame, anchors: dict[str, int]) -> dict[str, float | None]:
    out = {}
    for name, idx in anchors.items():
        if idx is None or idx < 0 or idx >= len(df):
            out[name] = None
            continue
        v = vwap(df.reset_index(drop=True), idx)
        out[name] = float(v.iloc[-1]) if len(v) and np.isfinite(v.iloc[-1]) else None
    return out


def structure(df: pd.DataFrame, spot: float) -> dict[str, Any]:
    d = df.reset_index(drop=True)
    sh, sl = swings(d.tail(400).reset_index(drop=True))
    hi_levels = cluster_levels([p for p in sh["price"].tolist() if p > spot], spot)
    lo_levels = cluster_levels([p for p in sl["price"].tolist() if p < spot], spot)
    resist = sorted(hi_levels, key=lambda x: x["level"])[:4]
    support = sorted(lo_levels, key=lambda x: -x["level"])[:4]
    trend = None
    if len(sh) >= 2 and len(sl) >= 2:
        hh = sh["price"].iloc[-1] > sh["price"].iloc[-2]
        hl = sl["price"].iloc[-1] > sl["price"].iloc[-2]
        trend = "uptrend (HH/HL)" if hh and hl else ("downtrend (LH/LL)" if not hh and not hl else "range / transition")
    anchors = {}
    tail = d.tail(252)
    if len(tail):
        anchors["from_52w_high"] = int(tail["high"].idxmax())
        anchors["from_52w_low"] = int(tail["low"].idxmin())
    anchors["ytd"] = int(d[pd.to_datetime(d["ts"]).dt.year == pd.Timestamp.utcnow().year].index.min()) if (pd.to_datetime(d["ts"]).dt.year == pd.Timestamp.utcnow().year).any() else None
    return {"resistance": resist, "support": support, "swing_trend": trend, "volume_profile": volume_profile(d),
            "pivots": pivots(d), "anchored_vwap": anchored_vwaps(d, anchors),
            "recent_swing_high": float(sh["price"].iloc[-1]) if len(sh) else None, "recent_swing_low": float(sl["price"].iloc[-1]) if len(sl) else None}

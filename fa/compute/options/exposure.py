"""Dealer positioning proxies: max pain, gamma exposure (GEX) profile and flip level, delta exposure (DEX).

Sign convention (stated as an ASSUMPTION in the UI): dealers are long calls and short puts against customer flow, so
call gamma contributes positive GEX and put gamma negative. This is the common retail convention; it is a proxy, not a tape.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def max_pain(chain: pd.DataFrame, expiry=None) -> dict[str, Any]:
    c = chain[chain["dte"] > 0]              # a series expiring today is settled at the close; use the next live one
    if expiry is not None:
        c = c[c["expiry"] == expiry]
    else:
        nearest = c["expiry"].min() if len(c) else None
        c = c[c["expiry"] == nearest]
    if c.empty:
        return {"max_pain": None}
    strikes = np.sort(c["strike"].unique())
    calls = c[c["right"] == "C"].groupby("strike")["open_interest"].sum().reindex(strikes).fillna(0).values
    puts = c[c["right"] == "P"].groupby("strike")["open_interest"].sum().reindex(strikes).fillna(0).values
    pain = []
    for s in strikes:
        call_val = np.sum(np.maximum(s - strikes, 0) * calls)
        put_val = np.sum(np.maximum(strikes - s, 0) * puts)
        pain.append(call_val + put_val)
    i = int(np.argmin(pain))
    return {"max_pain": float(strikes[i]), "expiry": str(c["expiry"].iloc[0]), "total_oi": float(calls.sum() + puts.sum()),
            "profile": pd.DataFrame({"strike": strikes, "pain": pain})}


def _gamma_flip(c: pd.DataFrame, spot: float, r: float = 0.04) -> float | None:
    """Spot level where total dealer gamma changes sign: re-price every contract's gamma over a grid of hypothetical spots
    and find the zero crossing nearest to the current price (the definition used by GEX practitioners)."""
    from fa.compute.options.pricing import greeks
    live = c[c["iv"].notna() & (c["iv"] > 0.01)]
    if live.empty:
        return None
    K = live["strike"].values.astype(float)
    T = np.maximum(live["dte"].values.astype(float), 0.5) / 365.0
    iv = live["iv"].values.astype(float)
    oi = live["open_interest"].values.astype(float)
    sign = np.where(live["right"].values == "C", 1.0, -1.0)
    grid = np.linspace(spot * 0.75, spot * 1.25, 101)
    totals = []
    for s in grid:
        g = greeks(np.full(len(K), s), K, T, r, 0.0, iv, np.ones(len(K), dtype=bool))["gamma"]   # gamma is the same for calls and puts
        totals.append(float(np.nansum(g * oi * 100 * s * s * 0.01 * sign)))
    totals = np.array(totals)
    crossings = [i for i in range(1, len(grid)) if totals[i - 1] * totals[i] < 0]
    if not crossings:
        return None
    i = min(crossings, key=lambda j: abs(grid[j] - spot))
    g0, g1 = totals[i - 1], totals[i]
    return float(grid[i - 1] + (grid[i] - grid[i - 1]) * (0 - g0) / (g1 - g0))


def gex_profile(chain: pd.DataFrame, spot: float | None, max_dte: int = 60) -> dict[str, Any]:
    if not spot:
        return {"gex_total": None}
    c = chain[(chain["dte"] > 0) & (chain["dte"] <= max_dte) & chain["gamma"].notna() & chain["open_interest"].notna()].copy()
    if c.empty:
        return {"gex_total": None}
    sign = np.where(c["right"] == "C", 1.0, -1.0)
    c["gex"] = c["gamma"] * c["open_interest"] * 100 * spot * spot * 0.01 * sign
    c["dex"] = c["delta"].fillna(0) * c["open_interest"] * 100 * spot
    by_strike = c.groupby("strike").agg(gex=("gex", "sum"), dex=("dex", "sum"), call_oi=("open_interest", lambda s: float(s[c.loc[s.index, "right"] == "C"].sum())),
                                        put_oi=("open_interest", lambda s: float(s[c.loc[s.index, "right"] == "P"].sum()))).reset_index().sort_values("strike")
    flip = _gamma_flip(c, spot)
    near = by_strike[(by_strike["strike"] > spot * 0.8) & (by_strike["strike"] < spot * 1.2)]
    return {
        "gex_total": float(c["gex"].sum()), "dex_total": float(c["dex"].sum()), "gex_flip": flip,
        "largest_positive_gex_strike": float(by_strike.loc[by_strike["gex"].idxmax(), "strike"]) if len(by_strike) else None,
        "largest_negative_gex_strike": float(by_strike.loc[by_strike["gex"].idxmin(), "strike"]) if len(by_strike) else None,
        "regime": ("positive_gamma" if float(c["gex"].sum()) > 0 else "negative_gamma"),
        "profile": near, "max_dte": max_dte, "assumption": "dealers long calls / short puts; call gamma +, put gamma −",
    }

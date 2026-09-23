"""Order-flow proxies from bars, FINRA short volume, and (when IBKR is connected) the real tick tape.

Everything here that is not from the tape is labelled PROXY — a tick-rule CVD from 1-minute bars is directionally useful
and is not the same thing as classified trades.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def bar_cvd(intraday: pd.DataFrame) -> dict[str, Any]:
    """Tick-rule aggressor classification on intraday bars → buy/sell volume, cumulative volume delta, relative volume by time-of-day."""
    if intraday is None or intraday.empty:
        return {}
    d = intraday.copy().sort_values("ts")
    d["ts"] = pd.to_datetime(d["ts"], utc=True)
    sign = np.sign(d["close"].diff()).replace(0, np.nan).ffill().fillna(0)
    # within-bar refinement: close position in range
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    pos = ((d["close"] - d["low"]) / rng).fillna(0.5)
    buy_frac = np.where(sign > 0, 0.5 + 0.5 * pos, np.where(sign < 0, 0.5 * pos, 0.5))
    d["buy_vol"] = d["volume"] * buy_frac
    d["sell_vol"] = d["volume"] - d["buy_vol"]
    d["delta"] = d["buy_vol"] - d["sell_vol"]
    d["date"] = d["ts"].dt.tz_convert("America/New_York").dt.date
    d["tod"] = d["ts"].dt.tz_convert("America/New_York").dt.strftime("%H:%M")
    daily = d.groupby("date").agg(volume=("volume", "sum"), delta=("delta", "sum"), buy=("buy_vol", "sum"), sell=("sell_vol", "sum")).reset_index()
    daily["cvd"] = daily["delta"].cumsum()
    daily["imbalance"] = daily["delta"] / daily["volume"].replace(0, np.nan)
    today = daily.iloc[-1] if len(daily) else None
    # relative volume at this time of day vs prior 20 sessions
    last_day = d[d["date"] == d["date"].max()]
    prior = d[d["date"] < d["date"].max()]
    rvol_tod = None
    if len(last_day) and len(prior):
        cutoff = last_day["tod"].max()
        prior_by_day = prior[prior["tod"] <= cutoff].groupby("date")["volume"].sum().tail(20)
        if len(prior_by_day) and prior_by_day.mean():
            rvol_tod = float(last_day["volume"].sum() / prior_by_day.mean())
    last5 = daily.tail(5)
    return {"method": "tick-rule on bars (PROXY)", "today_imbalance": float(today["imbalance"]) if today is not None and pd.notna(today["imbalance"]) else None,
            "today_delta": float(today["delta"]) if today is not None else None, "imbalance_5d": float(last5["delta"].sum() / last5["volume"].sum()) if len(last5) and last5["volume"].sum() else None,
            "rel_volume_time_of_day": rvol_tod, "daily": daily.tail(30), "cvd_trend_20d": float(daily["delta"].tail(20).sum() / daily["volume"].tail(20).sum()) if len(daily) >= 5 and daily["volume"].tail(20).sum() else None}


def short_volume_stats(sv: pd.DataFrame) -> dict[str, Any]:
    if sv is None or sv.empty:
        return {}
    d = sv.sort_values("date").copy()
    d["ratio"] = d["short_volume"] / d["total_volume"].replace(0, np.nan)
    last = d.iloc[-1]
    hist = d["ratio"].tail(60)
    z = float((last["ratio"] - hist.mean()) / hist.std()) if len(hist) >= 10 and hist.std() else None
    return {"date": str(last["date"]), "short_ratio": float(last["ratio"]), "short_ratio_mean_20d": float(d["ratio"].tail(20).mean()),
            "short_ratio_z_60d": z, "short_volume": float(last["short_volume"]), "off_exchange_volume": float(last["total_volume"]),
            "series": d[["date", "short_volume", "total_volume", "ratio"]].tail(60), "note": "FINRA off-exchange (TRF) short-sale volume — flow, not short interest"}


def tape_stats(trades: pd.DataFrame, quotes: pd.DataFrame) -> dict[str, Any]:
    """Real order flow from IBKR ticks: quote-rule/Lee-Ready aggressor classification, CVD, large prints, off-exchange share."""
    if trades is None or trades.empty:
        return {}
    t = trades.sort_values("ts").copy()
    t["ts"] = pd.to_datetime(t["ts"], utc=True)
    if quotes is not None and not quotes.empty:
        q = quotes.sort_values("ts").copy()
        q["ts"] = pd.to_datetime(q["ts"], utc=True)
        t = pd.merge_asof(t, q[["ts", "bid", "ask"]], on="ts", direction="backward")
        mid = (t["bid"] + t["ask"]) / 2
        side = np.where(t["price"] > mid, 1, np.where(t["price"] < mid, -1, 0))
        tick = np.sign(t["price"].diff()).replace(0, np.nan).ffill().fillna(0)
        t["side"] = np.where(side == 0, tick, side)                 # Lee-Ready: quote rule, tick rule at the mid
        t["spread_bps"] = (t["ask"] - t["bid"]) / mid * 1e4
    else:
        t["side"] = np.sign(t["price"].diff()).replace(0, np.nan).ffill().fillna(0)
        t["spread_bps"] = np.nan
    t["signed"] = t["side"] * t["size"]
    vol = float(t["size"].sum())
    big_cut = float(t["size"].quantile(0.99)) if len(t) > 50 else float(t["size"].max())
    big = t[t["size"] >= big_cut]
    offex = t[t["exchange"].astype(str).str.upper().isin(["D", "ADF", "TRF", "FINRA"])] if "exchange" in t.columns else pd.DataFrame()
    return {"method": "Lee-Ready on tick tape (IBKR)", "n_trades": int(len(t)), "buy_volume": float(t.loc[t["side"] > 0, "size"].sum()),
            "sell_volume": float(t.loc[t["side"] < 0, "size"].sum()), "imbalance": float(t["signed"].sum() / vol) if vol else None,
            "cvd_series": t[["ts", "signed"]].assign(cvd=t["signed"].cumsum()).tail(500),
            "large_prints": big[["ts", "price", "size", "exchange", "side"]].tail(20), "large_print_share": float(big["size"].sum() / vol) if vol else None,
            "off_exchange_share": float(offex["size"].sum() / vol) if vol and len(offex) else None,
            "avg_trade_size": float(t["size"].mean()), "median_spread_bps": float(t["spread_bps"].median()) if t["spread_bps"].notna().any() else None,
            "window": [str(t["ts"].min()), str(t["ts"].max())]}


def depth_stats(depth: dict[str, pd.DataFrame] | None) -> dict[str, Any]:
    if not depth:
        return {}
    b, a = depth.get("bids"), depth.get("asks")
    if b is None or a is None or b.empty or a.empty:
        return {}
    bs, as_ = float(b["size"].sum()), float(a["size"].sum())
    return {"bid_depth": bs, "ask_depth": as_, "depth_imbalance": (bs - as_) / (bs + as_) if (bs + as_) else None,
            "best_bid": float(b["price"].max()), "best_ask": float(a["price"].min()), "levels": int(min(len(b), len(a)))}

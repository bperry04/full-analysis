"""Options positioning flow: OI change vs the previous snapshot, volume/OI, unusual activity, strike walls, net premium."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def oi_change(today: pd.DataFrame, prev: pd.DataFrame | None) -> pd.DataFrame:
    out = today[["contract_symbol", "expiry", "strike", "right", "open_interest", "volume"]].copy()
    if prev is None or prev.empty or "contract_symbol" not in prev.columns:
        out["oi_prev"], out["oi_change"] = np.nan, np.nan
        return out
    p = prev[["contract_symbol", "open_interest"]].drop_duplicates("contract_symbol").rename(columns={"open_interest": "oi_prev"})
    out = out.merge(p, on="contract_symbol", how="left")
    out["oi_change"] = out["open_interest"] - out["oi_prev"]
    return out


def flow_summary(chain: pd.DataFrame, prev: pd.DataFrame | None, spot: float | None, hist_pc: pd.Series | None = None) -> dict[str, Any]:
    c = chain[chain["dte"] > 0].copy()
    if c.empty:
        return {}
    px = c["mid"].fillna(c["last"]).fillna(0)
    c["premium_vol"] = px * c["volume"].fillna(0) * 100
    with np.errstate(divide="ignore", invalid="ignore"):
        c["vol_oi"] = np.where(c["open_interest"].fillna(0) > 0, c["volume"].fillna(0) / c["open_interest"], np.nan)
    oic = oi_change(c, prev)
    c = c.merge(oic[["contract_symbol", "oi_prev", "oi_change"]], on="contract_symbol", how="left")
    is_c, is_p = c["right"] == "C", c["right"] == "P"

    liquid = c[(c["spread_bps"].fillna(1e9) < 2500) & (c["volume"].fillna(0) >= 100)]
    unusual = liquid[liquid["vol_oi"] > 1.0].sort_values("premium_vol", ascending=False).head(15)
    calls_prem, puts_prem = float(c.loc[is_c, "premium_vol"].sum()), float(c.loc[is_p, "premium_vol"].sum())

    rows = []
    for exp, g in c.groupby("expiry"):
        gc, gp = g[g["right"] == "C"], g[g["right"] == "P"]
        rows.append({"expiry": exp, "dte": int(g["dte"].iloc[0]), "call_vol": float(gc["volume"].sum()), "put_vol": float(gp["volume"].sum()),
                     "call_oi": float(gc["open_interest"].sum()), "put_oi": float(gp["open_interest"].sum()),
                     "oi_change": float(g["oi_change"].sum()) if g["oi_change"].notna().any() else None})
    by_exp = pd.DataFrame(rows)
    cols = ["contract_symbol", "expiry", "strike", "right", "open_interest", "volume", "iv", "delta", "oi_change", "premium_vol"]
    top_oi = c.sort_values("open_interest", ascending=False).head(12)[cols]
    top_vol = c.sort_values("volume", ascending=False).head(12)[cols]
    call_wall = put_wall = None
    if spot:
        above = c[is_c & (c["strike"] >= spot)].groupby("strike")["open_interest"].sum()
        below = c[is_p & (c["strike"] <= spot)].groupby("strike")["open_interest"].sum()
        call_wall = float(above.idxmax()) if len(above) else None
        put_wall = float(below.idxmax()) if len(below) else None
    cv = float(c.loc[is_c, "volume"].sum())
    pc_vol = float(c.loc[is_p, "volume"].sum()) / cv if cv else None
    pc_z = None
    if hist_pc is not None and pc_vol is not None:
        h = hist_pc.dropna().tail(60)
        if len(h) >= 20 and h.std():
            pc_z = float((pc_vol - h.mean()) / h.std())
    has_prev = bool(oic["oi_change"].notna().any())
    return {
        "put_call_vol": pc_vol, "put_call_vol_z": pc_z, "call_premium_traded": calls_prem, "put_premium_traded": puts_prem,
        "net_premium_call_minus_put": calls_prem - puts_prem,
        "unusual": unusual[["contract_symbol", "expiry", "strike", "right", "volume", "open_interest", "vol_oi", "premium_vol", "iv", "delta", "spread_bps"]],
        "by_expiry": by_exp, "top_oi": top_oi, "top_volume": top_vol, "call_wall": call_wall, "put_wall": put_wall,
        "oi_change_total": float(oic["oi_change"].sum()) if has_prev else None,
        "oi_change_calls": float(oic.loc[oic["right"] == "C", "oi_change"].sum()) if has_prev else None,
        "oi_change_puts": float(oic.loc[oic["right"] == "P", "oi_change"].sum()) if has_prev else None,
        "has_prev_snapshot": has_prev,
    }

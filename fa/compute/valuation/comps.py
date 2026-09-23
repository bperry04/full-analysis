"""Relative valuation: peer multiples distribution, subject percentile, implied prices at peer median, growth-adjusted regression."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

MULTIPLES = {
    "pe": ("trailingPE", "P/E (TTM)", "eps"), "fwd_pe": ("forwardPE", "Forward P/E", "fwd_eps"), "ev_ebitda": ("enterpriseToEbitda", "EV/EBITDA", "ebitda"),
    "ev_sales": ("enterpriseToRevenue", "EV/Sales", "revenue"), "pb": ("priceToBook", "P/B", "bvps"), "peg": ("pegRatio", "PEG", None),
}


def _num(x: Any) -> float | None:
    try:
        v = float(x)
        return None if not np.isfinite(v) or v <= 0 or v > 500 else v
    except (TypeError, ValueError):
        return None


def comps_table(subject: str, subject_info: dict, peers: dict[str, dict], subject_metrics: dict[str, float | None]) -> dict[str, Any]:
    rows = []
    for sym, info in peers.items():
        rows.append({"symbol": sym, "name": info.get("shortName") or info.get("longName"), "market_cap": info.get("marketCap"),
                     "rev_growth": info.get("revenueGrowth"), "gross_margin": info.get("grossMargins"), "op_margin": info.get("operatingMargins"),
                     **{k: _num(info.get(f[0])) for k, f in MULTIPLES.items()}})
    peers_df = pd.DataFrame(rows)
    subj = {k: _num(subject_info.get(f[0])) for k, f in MULTIPLES.items()}
    # prefer our own XBRL-based multiples for the subject where available
    for k in ("pe", "ev_ebitda", "ev_sales", "pb"):
        if subject_metrics.get(k):
            subj[k] = subject_metrics[k]
    stats, implied = {}, {}
    price = subject_info.get("currentPrice") or subject_info.get("regularMarketPrice") or subject_metrics.get("price")
    for k, (_, label, base) in MULTIPLES.items():
        col = peers_df[k].dropna() if k in peers_df.columns else pd.Series(dtype=float)
        if len(col) < 2:
            continue
        s = {"label": label, "n": int(len(col)), "min": float(col.min()), "p25": float(col.quantile(0.25)), "median": float(col.median()),
             "p75": float(col.quantile(0.75)), "max": float(col.max()), "subject": subj.get(k),
             "subject_percentile": float((col < subj[k]).mean()) if subj.get(k) else None,
             "premium_to_median": (subj[k] / col.median() - 1) if subj.get(k) and col.median() else None}
        stats[k] = s
        if subj.get(k) and price and k != "peg":
            implied[k] = {"at_median": price * col.median() / subj[k], "at_p25": price * col.quantile(0.25) / subj[k], "at_p75": price * col.quantile(0.75) / subj[k]}
    # growth-adjusted EV/Sales: regress ln(EV/S) on revenue growth and gross margin across peers
    reg = None
    d = peers_df.dropna(subset=["ev_sales", "rev_growth"])
    if len(d) >= 8:          # three coefficients need a real sample; fewer peers overfit badly
        X = np.column_stack([np.ones(len(d)), d["rev_growth"].values, d["gross_margin"].fillna(d["gross_margin"].median()).values])
        y = np.log(d["ev_sales"].values)
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            sg, sm = subject_info.get("revenueGrowth"), subject_info.get("grossMargins")
            if sg is not None and sm is not None and subj.get("ev_sales"):
                fitted = float(np.exp(beta[0] + beta[1] * sg + beta[2] * sm))
                reg = {"fitted_ev_sales": fitted, "actual_ev_sales": subj["ev_sales"], "premium_vs_fitted": subj["ev_sales"] / fitted - 1,
                       "implied_price": price * fitted / subj["ev_sales"] if price else None, "coef": {"growth": float(beta[1]), "gross_margin": float(beta[2])}, "n": int(len(d))}
        except Exception:
            reg = None
    implied_median = [v["at_median"] for v in implied.values()]
    return {"peers": peers_df, "stats": stats, "implied": implied, "regression": reg,
            "blended_implied_price": float(np.median(implied_median)) if implied_median else None, "n_peers": int(len(peers_df))}

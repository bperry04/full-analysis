"""Monte Carlo — two clearly separated engines.

1. Price paths: GBM with Student-t innovations calibrated to realized kurtosis, stationary block bootstrap of historical
   returns, and an implied-vol variant that uses the option surface as the volatility input.
2. Driver-space DCF: sample growth, margin, WACC and terminal growth from stated distributions → fair-value distribution.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from fa.compute.valuation.dcf import dcf
from fa.compute.valuation.inputs import ValuationInputs


def _pct(x: np.ndarray) -> dict[str, float]:
    return {f"p{p}": float(np.percentile(x, p)) for p in (1, 5, 10, 25, 50, 75, 90, 95, 99)}


def price_paths(close: pd.Series, spot: float, horizons: tuple[int, ...] = (5, 21, 63, 126, 252), n: int = 20000,
                iv_annual: float | None = None, targets: tuple[float, ...] = (0.9, 1.0, 1.1, 1.2), seed: int = 7) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    r = np.log(close.astype(float)).diff().dropna().values
    if len(r) < 120:
        return {"available": False}
    r = r[-756:]
    sigma_d = r.std(ddof=1)
    kurt = pd.Series(r).kurt()
    nu = 4 + 6 / kurt if kurt and kurt > 0 else 30.0     # t degrees of freedom from excess kurtosis
    nu = float(min(max(nu, 3.0), 30.0))
    out: dict[str, Any] = {"available": True, "n_paths": n, "daily_sigma": float(sigma_d), "t_dof": nu, "engines": {}}
    H = max(horizons)
    # (a) Student-t GBM, zero drift
    t_draws = rng.standard_t(nu, size=(n, H)) * np.sqrt((nu - 2) / nu) * sigma_d
    # (b) stationary block bootstrap (mean block 10 days)
    blocks = np.empty((n, H))
    p = 1 / 10
    idx = rng.integers(0, len(r), size=n)
    for h in range(H):
        blocks[:, h] = r[idx]
        restart = rng.random(n) < p
        idx = np.where(restart, rng.integers(0, len(r), size=n), (idx + 1) % len(r))
    engines = {"student_t": t_draws, "block_bootstrap": blocks}
    # (c) implied-vol normal (drift 0), using surface IV
    if iv_annual:
        engines["implied_vol"] = rng.standard_normal((n, H)) * iv_annual / np.sqrt(252)
    for name, draws in engines.items():
        cum = np.cumsum(draws, axis=1)
        res = {}
        for h in horizons:
            px = spot * np.exp(cum[:, h - 1])
            res[f"h{h}"] = {"percentiles": _pct(px), "prob_above": {str(t): float((px > spot * t).mean()) for t in targets},
                            "expected_abs_move_pct": float(np.mean(np.abs(px / spot - 1))), "var95_pct": float(1 - np.percentile(px, 5) / spot),
                            "cvar95_pct": float(1 - px[px <= np.percentile(px, 5)].mean() / spot)}
        # max drawdown distribution over the longest horizon
        paths = spot * np.exp(cum)
        peaks = np.maximum.accumulate(paths, axis=1)
        mdd = (paths / peaks - 1).min(axis=1)
        res["max_drawdown_252"] = _pct(mdd)
        out["engines"][name] = res
    # fan chart (median engine = student_t) at a few percentiles across days
    cum = np.cumsum(engines["student_t"], axis=1)
    days = list(range(1, H + 1, max(1, H // 60)))
    out["fan"] = {"days": days, **{f"p{p}": [float(spot * np.exp(np.percentile(cum[:, d - 1], p))) for d in days] for p in (5, 25, 50, 75, 95)}}
    return out


def dcf_distribution(inp: ValuationInputs, n: int = 8000, seed: int = 11, growth_sd: float | None = None, margin_sd: float | None = None,
                     margin_history: list[float] | None = None, growth_history: list[float] | None = None) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    g1, m, w, gt = inp.growth_stage1.value, inp.fcf_margin.value, inp.wacc.value, inp.growth_terminal.value
    if g1 is None or m is None or w is None:
        return {"available": False}
    gsd = growth_sd if growth_sd is not None else (float(np.std(growth_history)) if growth_history and len(growth_history) >= 3 else 0.06)
    msd = margin_sd if margin_sd is not None else (float(np.std(margin_history)) if margin_history and len(margin_history) >= 3 else max(abs(m) * 0.25, 0.02))
    gsd, msd = min(max(gsd, 0.02), 0.20), min(max(msd, 0.01), 0.15)
    vals = []
    draws = {"g1": rng.normal(g1, gsd, n), "margin": rng.normal(m, msd, n), "wacc": rng.normal(w, 0.01, n), "gt": rng.uniform(max(gt - 0.01, 0.0), gt + 0.01, n)}
    for i in range(n):
        r = dcf(inp, margin=float(draws["margin"][i]), g1=float(np.clip(draws["g1"][i], -0.3, 0.6)), g_term=float(draws["gt"][i]),
                wacc=float(max(draws["wacc"][i], draws["gt"][i] + 0.01)))
        v = r.get("value_per_share_gordon")
        if v is not None and np.isfinite(v):
            vals.append(v)
    if len(vals) < 100:
        return {"available": False}
    x = np.array(vals)
    price = inp.price.value
    return {"available": True, "n": len(x), "percentiles": _pct(x), "mean": float(x.mean()),
            "prob_above_price": float((x > price).mean()) if price else None, "inputs_sd": {"growth_sd": gsd, "margin_sd": msd, "wacc_sd": 0.01},
            "histogram": _hist(x)}


def _hist(x: np.ndarray, bins: int = 40) -> dict[str, list[float]]:
    lo, hi = np.percentile(x, 1), np.percentile(x, 99)
    cnt, edges = np.histogram(x[(x >= lo) & (x <= hi)], bins=bins)
    return {"edges": [float(e) for e in edges], "counts": [int(c) for c in cnt]}

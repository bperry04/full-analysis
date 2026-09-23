"""Option evaluator: rank every liquid contract of one expiry / right for a given holding period and thesis.

For each contract we price the option at the END OF THE HOLD (not at expiry) with Black-Scholes across a distribution of
underlying prices, so theta decay, IV change and the probability of the move are all in the number.

Distributions:
  neutral  — lognormal, zero drift, sigma = blend of ATM implied vol and 20-day realized vol
  thesis   — same sigma, drift toward `target` (user) or `direction × setup quality × 1σ` (from the swing setup)
IV at exit = contract IV, reduced toward realized vol if earnings fall inside the hold (crush), otherwise sticky.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from fa.compute.options.pricing import price as bs_price

HORIZON_DEFAULTS = {
    "short": {"hold_days": 10, "dte_min": 21, "dte_max": 60, "delta_lo": 0.35, "delta_hi": 0.65, "label": "2-20 day swing"},
    "medium": {"hold_days": 45, "dte_min": 60, "dte_max": 150, "delta_lo": 0.45, "delta_hi": 0.75, "label": "1-6 month position"},
    "long": {"hold_days": 180, "dte_min": 270, "dte_max": 1000, "delta_lo": 0.65, "delta_hi": 0.90, "label": "6-24 month (LEAPS / stock replacement)"},
}


def suggest_expiry(expiries: list, horizon: str, today) -> Any:
    cfg = HORIZON_DEFAULTS.get(horizon, HORIZON_DEFAULTS["short"])
    cands = [(e, (pd.Timestamp(e).date() - today).days) for e in expiries]
    inside = [e for e, d in cands if cfg["dte_min"] <= d <= cfg["dte_max"]]
    if inside:
        # for swings prefer the nearer end (cheaper), for long the farther (more time)
        return inside[0] if horizon != "long" else inside[-1]
    after = [e for e, d in cands if d >= cfg["dte_min"]]
    return after[0] if after else (cands[-1][0] if cands else None)


def top_contracts(chain: pd.DataFrame, spot: float, dte_min: int, dte_max: int, n: int = 3, rights: tuple[str, ...] = ("C", "P"), **kw: Any) -> dict[str, Any]:
    """Best N contracts across every expiry in [dte_min, dte_max] and both rights, ranked by the same score.
    Under a directional thesis the opposite right scores poorly on expected value, so the list self-selects the aligned side."""
    exps = sorted({(pd.Timestamp(e).date(), int(d)) for e, d in zip(chain["expiry"], chain["dte"]) if dte_min <= int(d) <= dte_max})
    if not exps:
        return {"available": False, "reason": f"no expirations between {dte_min} and {dte_max} days out"}
    frames, per_expiry = [], []
    for exp, dte in exps:
        for right in rights:
            r = evaluate(chain, spot, exp, right, **kw)
            if not r.get("available"):
                continue
            df = r["ranked"].copy()
            df["expiry"], df["right"], df["dte"] = str(exp), right, dte
            frames.append(df)
            per_expiry.append({"expiry": str(exp), "right": right, "dte": dte, "n": int(len(df)), "best_score": float(df["score"].max()), "thesis": r["thesis"], "iv_crush": r["iv_crush_modelled"]})
    if not frames:
        return {"available": False, "reason": "no liquid contracts in that window"}
    allc = pd.concat(frames, ignore_index=True).sort_values("score", ascending=False)
    # diversify: first one contract per (expiry, right), then fill with the next-best contracts whose strike is ≥4% away from every pick
    recs = allc.to_dict("records")
    picks, combos = [], set()
    for r in recs:
        if (r["expiry"], r["right"]) in combos:
            continue
        combos.add((r["expiry"], r["right"]))
        picks.append(r)
        if len(picks) >= n:
            break
    for r in recs:
        if len(picks) >= n:
            break
        if any(p is r for p in picks) or any(p["expiry"] == r["expiry"] and p["right"] == r["right"] and abs(p["strike"] - r["strike"]) / spot < 0.04 for p in picks):
            continue
        picks.append(r)
    picks.sort(key=lambda r: -r["score"])
    return {"available": True, "window": [dte_min, dte_max], "top": picks, "n_scored": int(len(allc)), "expiries": per_expiry, "spot": spot,
            "note": "ranked across all expirations in the window and both calls and puts; diversified across expiry and call/put before filling by score"}


def _grid(spot: float, sigma_h: float, drift: float, n: int = 601) -> tuple[np.ndarray, np.ndarray]:
    """Lognormal grid of terminal prices and probability weights over ±5σ."""
    z = np.linspace(-5, 5, n)
    w = norm.pdf(z)
    w /= w.sum()
    s_t = spot * np.exp(drift - 0.5 * sigma_h**2 + sigma_h * z)
    return s_t, w


def evaluate(chain: pd.DataFrame, spot: float, expiry, right: str, horizon: str = "short", hold_days: int | None = None, target: float | None = None,
             direction: int = 0, quality: float = 0.0, iv_atm: float | None = None, hv20: float | None = None, days_to_earnings: int | None = None,
             rf: float = 0.04, q: float = 0.0, iv_rank: float | None = None) -> dict[str, Any]:
    cfg = HORIZON_DEFAULTS.get(horizon, HORIZON_DEFAULTS["short"])
    hold = int(hold_days or cfg["hold_days"])
    exp_d = pd.Timestamp(expiry).date()
    c = chain[(pd.to_datetime(chain["expiry"]).dt.date == exp_d) & (chain["right"] == right.upper())].copy()
    if c.empty or not spot:
        return {"available": False, "reason": "no contracts for that expiry / right"}
    dte = int(c["dte"].iloc[0])
    hold = min(hold, max(dte, 1))
    t_hold = hold / 252.0
    t_exit = max(dte - hold, 0) / 365.0
    sigma = float(np.nanmean([x for x in (iv_atm, hv20) if x])) if (iv_atm or hv20) else float(c["iv"].median())
    sigma_h = sigma * np.sqrt(t_hold)
    one_sigma_move = spot * sigma_h
    # thesis drift: user target wins; else direction × quality × 1σ (capped at 1σ)
    if target:
        drift = float(np.log(target / spot))
        thesis_src = f"target {target:.2f}"
    else:
        drift = float(direction * min(max(quality, 0.0), 1.0) * sigma_h)
        thesis_src = f"setup direction {direction:+d} × quality {quality:.2f} → {drift:+.1%} drift" if direction else "no directional thesis (neutral)"
    s_n, w = _grid(spot, sigma_h, 0.0)
    s_t, _ = _grid(spot, sigma_h, drift)
    crush = days_to_earnings is not None and 0 <= days_to_earnings <= hold
    is_call = right.upper() == "C"

    liquid = c[(c["bid"].fillna(0) > 0) & (c["ask"].fillna(0) > 0)].copy()
    liquid = liquid[(liquid["open_interest"].fillna(0) >= 20) | (liquid["volume"].fillna(0) >= 20)]
    if liquid.empty:
        return {"available": False, "reason": "no liquid contracts (need bid > 0 and OI or volume ≥ 20)"}

    rows = []
    for r in liquid.itertuples():
        mid = float(r.mid) if np.isfinite(r.mid) else float((r.bid + r.ask) / 2)
        if mid <= 0.02:
            continue
        iv = float(r.iv) if np.isfinite(r.iv) and r.iv > 0 else sigma
        iv_exit = max(iv * 0.7, hv20 or iv * 0.7) if crush else iv
        K = float(r.strike)
        val_n = bs_price(s_n, K, t_exit, rf, q, iv_exit, is_call) if t_exit > 0 else (np.maximum(s_n - K, 0) if is_call else np.maximum(K - s_n, 0))
        val_t = bs_price(s_t, K, t_exit, rf, q, iv_exit, is_call) if t_exit > 0 else (np.maximum(s_t - K, 0) if is_call else np.maximum(K - s_t, 0))
        pnl_n, pnl_t = val_n - mid, val_t - mid
        ev_n, ev_t = float((pnl_n * w).sum()), float((pnl_t * w).sum())
        pop_n, pop_t = float(w[pnl_n > 0].sum()), float(w[pnl_t > 0].sum())
        # payoff if the thesis lands exactly on the drift point
        s_star = spot * np.exp(drift)
        v_star = float(bs_price(np.array([s_star]), K, t_exit, rf, q, iv_exit, is_call)[0]) if t_exit > 0 else max((s_star - K) if is_call else (K - s_star), 0.0)
        spread_pct = float((r.ask - r.bid) / mid) if mid else 1.0
        delta = abs(float(r.delta)) if np.isfinite(r.delta) else float("nan")
        theta = float(r.theta) if np.isfinite(r.theta) else 0.0
        theta_burn = abs(theta) * hold / mid if mid else 1.0          # share of premium lost to time over the hold (all else equal)
        be = K + mid if is_call else K - mid
        be_move = be / spot - 1
        iv_rich_rv = (iv / hv20) if hv20 else None
        skew_prem = (iv - iv_atm) if iv_atm else None
        # --- component scores (0..1)
        s_ev = 0.5 + 0.5 * np.tanh(ev_t / mid / 0.6) if mid else 0.0                       # +60% EV → ~0.88
        s_pop = float(np.clip(pop_t, 0, 1))
        lo, hi = cfg["delta_lo"], cfg["delta_hi"]
        if not np.isfinite(delta):
            s_delta = 0.3
        elif lo <= delta <= hi:
            s_delta = 1.0
        elif delta >= 0.95:
            s_delta = 0.0                      # that is stock with a worse spread, not an option
        else:
            s_delta = max(0.0, 1 - min(abs(delta - lo), abs(delta - hi)) / 0.12)
        s_theta = float(np.clip(1 - theta_burn / 0.5, 0, 1))                                   # 50% burn → 0
        s_liq = float(np.clip(1 - spread_pct / 0.15, 0, 1)) * (0.6 + 0.4 * min((r.open_interest or 0) / 500, 1))
        s_iv = 1.0 if iv_rich_rv is None else float(np.clip(1 - (iv_rich_rv - 1.0) / 0.8, 0, 1))
        if skew_prem is not None and skew_prem > 0:
            s_iv *= float(np.clip(1 - skew_prem / 0.15, 0.3, 1))
        score = 100 * (0.32 * s_ev + 0.15 * s_pop + 0.15 * s_delta + 0.12 * s_theta + 0.14 * s_liq + 0.12 * s_iv)
        warn = []
        if spread_pct > 0.15:
            warn.append(f"wide spread {spread_pct:.0%}")
        if (r.open_interest or 0) < 100:
            warn.append(f"thin OI {int(r.open_interest or 0)}")
        if theta_burn > 0.35:
            warn.append(f"theta eats {theta_burn:.0%} of premium over {hold}d")
        if crush:
            warn.append("earnings inside hold — IV crush modelled")
        if dte - hold < 7 and dte > hold:
            warn.append("little time left after the hold (gamma/theta trap)")
        rows.append({
            "contract_symbol": r.contract_symbol, "strike": K, "mid": mid, "bid": float(r.bid), "ask": float(r.ask), "spread_pct": spread_pct, "volume": int(r.volume or 0),
            "open_interest": int(r.open_interest or 0), "iv": iv, "iv_exit": iv_exit, "delta": float(r.delta) if np.isfinite(r.delta) else None, "gamma": float(r.gamma) if np.isfinite(r.gamma) else None,
            "theta": theta, "vega": float(r.vega) if np.isfinite(r.vega) else None, "moneyness": float(r.moneyness) if np.isfinite(r.moneyness) else None,
            "breakeven": be, "breakeven_move_pct": be_move, "prob_itm_expiry": float(norm.cdf((np.log(spot / K) + (rf - q + 0.5 * iv**2) * dte / 365) / (iv * np.sqrt(dte / 365)) - iv * np.sqrt(dte / 365)) if is_call else 1 - norm.cdf((np.log(spot / K) + (rf - q + 0.5 * iv**2) * dte / 365) / (iv * np.sqrt(dte / 365)) - iv * np.sqrt(dte / 365))),
            "ev_neutral": ev_n, "ev_neutral_pct": ev_n / mid, "pop_neutral": pop_n, "ev_thesis": ev_t, "ev_thesis_pct": ev_t / mid, "pop_thesis": pop_t,
            "payoff_at_thesis": v_star - mid, "payoff_at_thesis_pct": (v_star - mid) / mid, "max_loss": mid, "theta_burn_pct": theta_burn,
            "leverage": (delta * spot / mid) if np.isfinite(delta) and mid else None, "iv_vs_rv": iv_rich_rv, "skew_premium": skew_prem,
            "score": score, "components": {"expected_value": s_ev, "prob_profit": s_pop, "delta_fit": s_delta, "theta": s_theta, "liquidity": s_liq, "iv_richness": s_iv},
            "warnings": warn, "pnl_curve": {"s": [float(x) for x in s_t[::30]], "pnl": [float(x) for x in pnl_t[::30]]},
        })
    if not rows:
        return {"available": False, "reason": "no priceable contracts"}
    df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    best = df.iloc[0].to_dict()
    # debit-spread alternative when IV is rich: buy best strike, sell the strike nearest the thesis price
    alt = None
    rich = (iv_rank or 0) > 0.6 or ((best.get("iv_vs_rv") or 1) > 1.3)
    s_star = spot * np.exp(drift)
    if rich and direction != 0 or target:
        sell_cands = df[(df["strike"] > best["strike"]) if is_call else (df["strike"] < best["strike"])]
        if not sell_cands.empty:
            sell = sell_cands.iloc[(sell_cands["strike"] - s_star).abs().argsort()[:1]].iloc[0]
            debit = best["mid"] - sell["mid"]
            width = abs(sell["strike"] - best["strike"])
            if debit > 0 and width > debit:
                alt = {"type": "vertical debit spread", "long": best["contract_symbol"], "short": sell["contract_symbol"], "long_strike": best["strike"], "short_strike": float(sell["strike"]),
                       "debit": debit, "max_profit": width - debit, "max_profit_pct": (width - debit) / debit, "breakeven": (best["strike"] + debit) if is_call else (best["strike"] - debit),
                       "why": f"IV is rich ({'rank ' + f'{iv_rank:.0%}' if iv_rank is not None else ''}{' IV/RV ' + f'{best.get("iv_vs_rv"):.2f}' if best.get('iv_vs_rv') else ''}); selling the {sell['strike']:.0f} strike near the thesis price cuts cost by {sell['mid'] / best['mid']:.0%} and neutralizes vega"}
    return {
        "available": True, "expiry": str(exp_d), "right": right.upper(), "dte": dte, "hold_days": hold, "horizon": horizon, "horizon_label": cfg["label"],
        "spot": spot, "sigma_used": sigma, "one_sigma_move_hold": one_sigma_move, "one_sigma_move_hold_pct": one_sigma_move / spot, "thesis": thesis_src, "thesis_price": spot * np.exp(drift),
        "iv_crush_modelled": crush, "delta_sweet_spot": [cfg["delta_lo"], cfg["delta_hi"]], "n_evaluated": int(len(df)),
        "best": best, "ranked": df.drop(columns=["pnl_curve"]).head(25), "alternative_spread": alt,
        "method": "P&L priced at the end of the hold with Black-Scholes across a lognormal grid; score = 32% expected value, 15% P(profit), 15% delta fit, 12% theta, 14% liquidity, 12% IV richness",
        "disclaimer": "model output on delayed quotes — check the live market before trading",
    }

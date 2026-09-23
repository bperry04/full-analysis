"""Black-Scholes-Merton (continuous dividend yield): vectorized prices, greeks, and implied-vol solver.

Used to (a) fill greeks when a source only gives IV (Yahoo), (b) cross-check vendor greeks, (c) solve IV from mids.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


def _d1d2(S, K, T, r, q, sigma):
    with np.errstate(divide="ignore", invalid="ignore"):
        vs = sigma * np.sqrt(T)
        d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / vs
        d2 = d1 - vs
    return d1, d2


def price(S, K, T, r, q, sigma, is_call) -> np.ndarray:
    S, K, T, sigma = map(lambda x: np.asarray(x, dtype=float), (S, K, T, sigma))
    is_call = np.asarray(is_call, dtype=bool)
    d1, d2 = _d1d2(S, K, T, r, q, sigma)
    call = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    put = K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)
    out = np.where(is_call, call, put)
    intrinsic = np.where(is_call, np.maximum(S - K, 0), np.maximum(K - S, 0))
    return np.where(T <= 0, intrinsic, out)


def greeks(S, K, T, r, q, sigma, is_call) -> dict[str, np.ndarray]:
    S, K, T, sigma = map(lambda x: np.asarray(x, dtype=float), (S, K, T, sigma))
    is_call = np.asarray(is_call, dtype=bool)
    d1, d2 = _d1d2(S, K, T, r, q, sigma)
    pdf = norm.pdf(d1)
    eqt, ert = np.exp(-q * T), np.exp(-r * T)
    with np.errstate(divide="ignore", invalid="ignore"):
        delta = np.where(is_call, eqt * norm.cdf(d1), -eqt * norm.cdf(-d1))
        gamma = eqt * pdf / (S * sigma * np.sqrt(T))
        vega = S * eqt * pdf * np.sqrt(T) / 100.0                                  # per 1 vol point
        theta_c = (-S * eqt * pdf * sigma / (2 * np.sqrt(T)) - r * K * ert * norm.cdf(d2) + q * S * eqt * norm.cdf(d1)) / 365.0
        theta_p = (-S * eqt * pdf * sigma / (2 * np.sqrt(T)) + r * K * ert * norm.cdf(-d2) - q * S * eqt * norm.cdf(-d1)) / 365.0
        theta = np.where(is_call, theta_c, theta_p)                                 # per calendar day
        rho = np.where(is_call, K * T * ert * norm.cdf(d2), -K * T * ert * norm.cdf(-d2)) / 100.0
        vanna = -eqt * pdf * d2 / sigma
        charm_c = q * eqt * norm.cdf(d1) - eqt * pdf * (2 * (r - q) * T - d2 * sigma * np.sqrt(T)) / (2 * T * sigma * np.sqrt(T))
        charm = np.where(is_call, charm_c, charm_c - q * eqt) / 365.0
    bad = ~np.isfinite(d1)
    out = {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho, "vanna": vanna, "charm": charm}
    for k, arr in out.items():
        arr = np.array(arr, dtype=float)
        arr[bad] = np.nan
        out[k] = arr
    return out


def implied_vol(target, S, K, T, r, q, is_call, tol: float = 1e-6, max_iter: int = 60) -> np.ndarray:
    """Vectorized Newton with bisection fallback. NaN where no solution (price below intrinsic / bad inputs)."""
    target, S, K, T = map(lambda x: np.asarray(x, dtype=float), (target, S, K, T))
    is_call = np.asarray(is_call, dtype=bool)
    n = target.shape[0]
    sigma = np.full(n, 0.3)
    intrinsic = np.where(is_call, np.maximum(S - K * np.exp(-r * T), 0), np.maximum(K * np.exp(-r * T) - S, 0))
    valid = np.isfinite(target) & (target > intrinsic + 1e-10) & (T > 0) & (S > 0) & (K > 0)
    lo, hi = np.full(n, 1e-4), np.full(n, 5.0)
    for _ in range(max_iter):
        p = price(S, K, T, r, q, sigma, is_call)
        diff = p - target
        d1, _ = _d1d2(S, K, T, r, q, sigma)
        vega = S * np.exp(-q * T) * norm.pdf(d1) * np.sqrt(T)
        hi = np.where(diff > 0, np.minimum(hi, sigma), hi)
        lo = np.where(diff < 0, np.maximum(lo, sigma), lo)
        with np.errstate(divide="ignore", invalid="ignore"):
            newton = sigma - diff / vega
        use_newton = np.isfinite(newton) & (newton > lo) & (newton < hi) & (vega > 1e-10)
        sigma = np.where(use_newton, newton, (lo + hi) / 2)
        if valid.any() and np.all(np.abs(diff[valid]) < tol):
            break
    sigma = np.where(valid, sigma, np.nan)
    return np.where((sigma <= 1.5e-4) | (sigma >= 4.99), np.nan, sigma)


def fill_greeks(chain: pd.DataFrame, r: float = 0.04, q: float = 0.0, force: bool = False) -> pd.DataFrame:
    """Compute BSM greeks (and IV from mid where missing) for a canonical chain; keeps vendor values unless force."""
    df = chain.copy()
    if df.empty:
        return df
    S = df["underlying_price"].astype(float).values
    K = df["strike"].astype(float).values
    T = np.maximum(df["dte"].astype(float).values, 0.5) / 365.0
    is_call = (df["right"] == "C").values
    iv = df["iv"].astype(float).values.copy()
    need_iv = ~np.isfinite(iv) | force
    if need_iv.any():
        mid = df["mid"].astype(float).values
        solved = implied_vol(mid, S, K, T, r, q, is_call)
        ok = need_iv & np.isfinite(solved)
        iv = np.where(ok, solved, iv)
        df.loc[ok, "iv_source"] = "computed"
    df["iv"] = iv
    g = greeks(S, K, T, r, q, iv, is_call)
    vendor_delta = df["delta"].astype(float).values.copy()
    for k in ("delta", "gamma", "theta", "vega", "rho"):
        have = df[k].astype(float).values
        df[k] = np.where(np.isfinite(have) & ~force, have, g[k])
    df["vanna"], df["charm"] = g["vanna"], g["charm"]
    df["greeks_source"] = df["greeks_source"].where(df["greeks_source"].notna() & ~force, "computed")
    df["delta_model"] = g["delta"]
    df["delta_mismatch"] = np.where(np.isfinite(vendor_delta) & np.isfinite(g["delta"]), np.abs(vendor_delta - g["delta"]) > 0.05, False)
    return df

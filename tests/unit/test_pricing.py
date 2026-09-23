import numpy as np

from fa.compute.options.pricing import greeks, implied_vol, price


def test_put_call_parity():
    S, K, T, r, q, sig = 100.0, 105.0, 0.5, 0.04, 0.01, 0.3
    c = price(S, K, T, r, q, sig, True)
    p = price(S, K, T, r, q, sig, False)
    assert abs((c - p) - (S * np.exp(-q * T) - K * np.exp(-r * T))) < 1e-8


def test_implied_vol_roundtrip():
    n = 500
    rng = np.random.default_rng(0)
    S = np.full(n, 250.0)
    K = rng.uniform(180, 320, n)
    T = rng.uniform(0.02, 1.5, n)
    sig = rng.uniform(0.12, 0.9, n)
    is_call = rng.random(n) > 0.5
    px = price(S, K, T, 0.04, 0.005, sig, is_call)
    iv = implied_vol(px, S, K, T, 0.04, 0.005, is_call)
    ok = np.isfinite(iv)
    assert ok.mean() > 0.97
    assert np.nanmax(np.abs(iv[ok] - sig[ok])) < 1e-4


def test_greeks_sanity():
    g = greeks(np.array([100.0]), np.array([100.0]), np.array([0.25]), 0.04, 0.0, np.array([0.25]), np.array([True]))
    assert 0.5 < g["delta"][0] < 0.6
    assert g["gamma"][0] > 0 and g["vega"][0] > 0 and g["theta"][0] < 0
    gp = greeks(np.array([100.0]), np.array([100.0]), np.array([0.25]), 0.04, 0.0, np.array([0.25]), np.array([False]))
    assert abs(g["delta"][0] - gp["delta"][0] - 1.0) < 1e-9       # call delta − put delta = e^{-qT} = 1 when q = 0
    assert abs(g["gamma"][0] - gp["gamma"][0]) < 1e-12


def test_intrinsic_below_price_returns_nan():
    iv = implied_vol(np.array([1.0]), np.array([100.0]), np.array([80.0]), np.array([0.5]), 0.04, 0.0, np.array([True]))
    assert np.isnan(iv[0])

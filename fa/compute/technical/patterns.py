"""Candlestick and chart pattern recognition + swing-setup classification for a 2-20 day horizon.

Everything here is deterministic geometry on OHLCV bars. Each detected pattern carries: name, direction (+1 bullish,
-1 bearish, 0 neutral/compression), reliability weight, bar date, and the trend context it appeared in.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from fa.compute.technical.indicators import atr, ema, rsi, sma


@dataclass
class Pattern:
    name: str
    kind: str                # candle | chart | gap | breakout
    direction: int           # +1 / -1 / 0
    weight: float            # reliability 0..1
    date: str
    bars_ago: int
    context: str
    detail: str = ""

    def json(self) -> dict[str, Any]:
        return asdict(self)


# ----------------------------------------------------------------------------- candlesticks
def candlesticks(df: pd.DataFrame, lookback: int = 12) -> list[Pattern]:
    d = df.reset_index(drop=True)
    if len(d) < 30:
        return []
    o, h, l, c = (d[k].astype(float).values for k in ("open", "high", "low", "close"))
    ts = pd.to_datetime(d["ts"]).dt.strftime("%Y-%m-%d").values
    body = np.abs(c - o)
    rng = np.maximum(h - l, 1e-9)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    avg_body = pd.Series(body).rolling(14).mean().values
    e21 = ema(pd.Series(c), 21).values
    n = len(d)
    out: list[Pattern] = []

    def trend_ctx(i: int) -> str:
        if i < 5:
            return "n/a"
        up5 = c[i - 1] > c[i - 5]
        above = c[i - 1] > e21[i - 1] if np.isfinite(e21[i - 1]) else up5
        return "after advance" if (up5 and above) else ("after decline" if (not up5 and not above) else "mixed")

    def add(i, name, direction, w, detail=""):
        out.append(Pattern(name, "candle", direction, w, ts[i], n - 1 - i, trend_ctx(i), detail))

    for i in range(max(2, n - lookback), n):
        b, r, ab = body[i], rng[i], avg_body[i] if np.isfinite(avg_body[i]) else body[i]
        green, red = c[i] > o[i], c[i] < o[i]
        pg, pr = c[i - 1] > o[i - 1], c[i - 1] < o[i - 1]
        ctx = trend_ctx(i)
        # single-bar
        if b <= 0.1 * r and r > 0.5 * ab:
            add(i, "Doji", 0, 0.3, "indecision")
        if lower[i] >= 2 * b and upper[i] <= max(b, 0.1 * r) and b > 0.05 * r:
            if ctx == "after decline":
                add(i, "Hammer", +1, 0.6, "long lower shadow after decline")
            elif ctx == "after advance":
                add(i, "Hanging man", -1, 0.4, "long lower shadow after advance")
        if upper[i] >= 2 * b and lower[i] <= max(b, 0.1 * r) and b > 0.05 * r:
            if ctx == "after decline":
                add(i, "Inverted hammer", +1, 0.4)
            elif ctx == "after advance":
                add(i, "Shooting star", -1, 0.6)
        if b >= 0.9 * r and b > 1.2 * ab:
            add(i, "Marubozu", +1 if green else -1, 0.5, "full-range conviction bar")
        if h[i] < h[i - 1] and l[i] > l[i - 1]:
            add(i, "Inside bar", 0, 0.3, "range compression")
        if h[i] > h[i - 1] and l[i] < l[i - 1] and b > ab:
            add(i, "Outside bar", +1 if green else -1, 0.4, "range expansion")
        if i >= 6 and r <= np.min(rng[i - 6:i]):
            add(i, "NR7 (narrowest range in 7)", 0, 0.4, "compression — expansion often follows")
        # two-bar
        if green and pr and c[i] >= o[i - 1] and o[i] <= c[i - 1] and b > body[i - 1]:
            add(i, "Bullish engulfing", +1, 0.7 if ctx == "after decline" else 0.45)
        if red and pg and o[i] >= c[i - 1] and c[i] <= o[i - 1] and b > body[i - 1]:
            add(i, "Bearish engulfing", -1, 0.7 if ctx == "after advance" else 0.45)
        if green and pr and o[i] < c[i - 1] and c[i] > (o[i - 1] + c[i - 1]) / 2 and c[i] < o[i - 1]:
            add(i, "Piercing line", +1, 0.5)
        if red and pg and o[i] > c[i - 1] and c[i] < (o[i - 1] + c[i - 1]) / 2 and c[i] > o[i - 1]:
            add(i, "Dark cloud cover", -1, 0.5)
        if body[i - 1] > 1.2 * ab and b < 0.5 * body[i - 1] and max(o[i], c[i]) <= max(o[i - 1], c[i - 1]) and min(o[i], c[i]) >= min(o[i - 1], c[i - 1]):
            add(i, "Harami", +1 if pr else -1, 0.4, "small body inside a large one — pause")
        if abs(l[i] - l[i - 1]) <= 0.0015 * c[i] and pr and green and ctx == "after decline":
            add(i, "Tweezer bottom", +1, 0.45)
        if abs(h[i] - h[i - 1]) <= 0.0015 * c[i] and pg and red and ctx == "after advance":
            add(i, "Tweezer top", -1, 0.45)
        # three-bar
        if i >= 2:
            b2, b1 = body[i - 2], body[i - 1]
            red2, green2 = c[i - 2] < o[i - 2], c[i - 2] > o[i - 2]
            mid2 = (o[i - 2] + c[i - 2]) / 2
            if red2 and b2 > ab and b1 < 0.4 * b2 and green and c[i] > mid2:
                add(i, "Morning star", +1, 0.75)
            if green2 and b2 > ab and b1 < 0.4 * b2 and red and c[i] < mid2:
                add(i, "Evening star", -1, 0.75)
            if all(c[j] > o[j] for j in (i - 2, i - 1, i)) and c[i] > c[i - 1] > c[i - 2] and all(upper[j] < 0.3 * body[j] for j in (i - 2, i - 1, i) if body[j] > 0):
                add(i, "Three white soldiers", +1, 0.65)
            if all(c[j] < o[j] for j in (i - 2, i - 1, i)) and c[i] < c[i - 1] < c[i - 2] and all(lower[j] < 0.3 * body[j] for j in (i - 2, i - 1, i) if body[j] > 0):
                add(i, "Three black crows", -1, 0.65)
    return out


def rel_volume(d: pd.DataFrame) -> float:
    """Today's volume vs the 20-day average, scaled up when the last bar is today's still-open session."""
    v = d["volume"].astype(float).values
    if len(v) < 22:
        return 1.0
    today = float(v[-1])
    try:
        from fa.core.clock import ET, session_state, utcnow
        last_ts = pd.Timestamp(d["ts"].iloc[-1])
        now = utcnow().astimezone(ET)
        if last_ts.tz_convert(ET).date() == now.date() and session_state() == "rth":
            elapsed = ((now.hour * 60 + now.minute) - (9 * 60 + 30)) / 390.0
            today = today / max(elapsed, 0.1)      # project the partial session to a full day
    except Exception:
        pass
    return today / max(float(np.mean(v[-21:-1])), 1.0)


# ----------------------------------------------------------------------------- swing points
def _swings(h: np.ndarray, l: np.ndarray, k: int = 3) -> tuple[list[int], list[int]]:
    hi = [i for i in range(k, len(h) - k) if h[i] == h[i - k:i + k + 1].max()]
    lo = [i for i in range(k, len(l) - k) if l[i] == l[i - k:i + k + 1].min()]
    return hi, lo


def _fit(idx: list[int], vals: np.ndarray) -> tuple[float, float]:
    """slope per bar as % of level, and intercept."""
    if len(idx) < 2:
        return 0.0, float(vals[idx[0]]) if idx else 0.0
    x = np.array(idx, dtype=float)
    y = vals[idx]
    slope, icpt = np.polyfit(x, y, 1)
    return float(slope / max(np.mean(y), 1e-9)), float(icpt)


# ----------------------------------------------------------------------------- chart patterns
def chart_patterns(df: pd.DataFrame, window: int = 120) -> list[Pattern]:
    d = df.reset_index(drop=True).tail(window).reset_index(drop=True)
    if len(d) < 40:
        return []
    o, h, l, c, v = (d[k].astype(float).values for k in ("open", "high", "low", "close", "volume"))
    ts = pd.to_datetime(d["ts"]).dt.strftime("%Y-%m-%d").values
    n = len(d)
    a = atr(d, 14).values
    A = float(a[-1]) if np.isfinite(a[-1]) else float(np.mean(h[-14:] - l[-14:]))
    last = c[-1]
    rvol = rel_volume(d)
    out: list[Pattern] = []
    P = lambda name, kind, dirn, w, detail, i=n - 1: out.append(Pattern(name, kind, dirn, w, ts[i], n - 1 - i, "", detail))  # noqa: E731

    # --- breakouts / breakdowns (close beyond the prior N-bar extreme)
    for N in (20, 55):
        hh, ll = np.max(h[-N - 1:-1]), np.min(l[-N - 1:-1])
        if last > hh:
            P(f"{N}-day breakout", "breakout", +1, 0.7 if rvol > 1.5 else 0.45, f"close {last:.2f} > prior {N}d high {hh:.2f}; rel. volume {rvol:.1f}x" + (" (confirmed)" if rvol > 1.5 else " (weak volume)"))
        if last < ll:
            P(f"{N}-day breakdown", "breakout", -1, 0.7 if rvol > 1.5 else 0.45, f"close {last:.2f} < prior {N}d low {ll:.2f}; rel. volume {rvol:.1f}x" + (" (confirmed)" if rvol > 1.5 else " (weak volume)"))
    # failed breakdown / failed breakout (yesterday beyond, today back inside)
    if n > 22:
        hh20, ll20 = np.max(h[-22:-2]), np.min(l[-22:-2])
        if c[-2] < ll20 and last > ll20:
            P("Failed breakdown (spring)", "breakout", +1, 0.6, f"closed below {ll20:.2f} then reclaimed it")
        if c[-2] > hh20 and last < hh20:
            P("Failed breakout (upthrust)", "breakout", -1, 0.6, f"closed above {hh20:.2f} then lost it")

    # --- swing-based geometry over the last 60 bars
    W = min(60, n)
    hs, ls = _swings(h[-W:], l[-W:], 3)
    off = n - W
    sh = [i + off for i in hs]
    sl = [i + off for i in ls]
    # double top / bottom
    if len(sh) >= 2:
        i1, i2 = sh[-2], sh[-1]
        if i2 - i1 >= 8 and abs(h[i1] - h[i2]) / h[i1] <= 0.02:
            trough = np.min(l[i1:i2 + 1])
            if (h[i1] - trough) / h[i1] >= 0.03:
                confirmed = last < trough
                P("Double top", "chart", -1, 0.75 if confirmed else 0.45, f"peaks {h[i1]:.2f}/{h[i2]:.2f}, neckline {trough:.2f}" + (" — confirmed" if confirmed else " — forming"), i2)
    if len(sl) >= 2:
        i1, i2 = sl[-2], sl[-1]
        if i2 - i1 >= 8 and abs(l[i1] - l[i2]) / l[i1] <= 0.02:
            peak = np.max(h[i1:i2 + 1])
            if (peak - l[i1]) / l[i1] >= 0.03:
                confirmed = last > peak
                P("Double bottom", "chart", +1, 0.75 if confirmed else 0.45, f"lows {l[i1]:.2f}/{l[i2]:.2f}, neckline {peak:.2f}" + (" — confirmed" if confirmed else " — forming"), i2)
    # head & shoulders / inverse
    if len(sh) >= 3:
        a1, hd, a2 = sh[-3], sh[-2], sh[-1]
        if h[hd] > h[a1] * 1.02 and h[hd] > h[a2] * 1.02 and abs(h[a1] - h[a2]) / h[a1] <= 0.04:
            neck = min(np.min(l[a1:hd + 1]), np.min(l[hd:a2 + 1]))
            confirmed = last < neck
            P("Head & shoulders", "chart", -1, 0.8 if confirmed else 0.45, f"head {h[hd]:.2f}, shoulders {h[a1]:.2f}/{h[a2]:.2f}, neckline {neck:.2f}" + (" — confirmed" if confirmed else " — forming"), a2)
    if len(sl) >= 3:
        a1, hd, a2 = sl[-3], sl[-2], sl[-1]
        if l[hd] < l[a1] * 0.98 and l[hd] < l[a2] * 0.98 and abs(l[a1] - l[a2]) / l[a1] <= 0.04:
            neck = max(np.max(h[a1:hd + 1]), np.max(h[hd:a2 + 1]))
            confirmed = last > neck
            P("Inverse head & shoulders", "chart", +1, 0.8 if confirmed else 0.45, f"head {l[hd]:.2f}, neckline {neck:.2f}" + (" — confirmed" if confirmed else " — forming"), a2)
    # triangles / wedges from the slopes of recent swing highs and lows
    if len(sh) >= 3 and len(sl) >= 3:
        s_h, _ = _fit(sh[-3:], h)
        s_l, _ = _fit(sl[-3:], l)
        start_rng = h[min(sh[-3], sl[-3])] - l[min(sh[-3], sl[-3])]
        end_rng = np.max(h[-5:]) - np.min(l[-5:])
        converging = end_rng < 0.75 * (np.max(h[-40:-30]) - np.min(l[-40:-30])) if n >= 40 else False
        flat = 0.0006
        if converging:
            if abs(s_h) < flat and s_l > flat:
                P("Ascending triangle", "chart", +1, 0.55, "flat highs, rising lows — usually resolves up")
            elif abs(s_l) < flat and s_h < -flat:
                P("Descending triangle", "chart", -1, 0.55, "flat lows, falling highs — usually resolves down")
            elif s_h < -flat and s_l > flat:
                P("Symmetrical triangle", "chart", 0, 0.4, "converging highs and lows — direction of break decides")
            elif s_h > flat and s_l > flat and s_l > s_h:
                P("Rising wedge", "chart", -1, 0.5, "both rising, converging — bearish tendency")
            elif s_h < -flat and s_l < -flat and s_h < s_l:
                P("Falling wedge", "chart", +1, 0.5, "both falling, converging — bullish tendency")
    # flag / pennant: impulse then tight drift
    if n >= 30:
        rets10 = c[10:] - c[:-10]
        imp_end = int(np.argmax(np.abs(rets10[-25:]))) + (len(rets10) - 25)
        impulse = rets10[imp_end]
        bars_since = (n - 1) - (imp_end + 10)
        if abs(impulse) >= 2.5 * A and 3 <= bars_since <= 12:
            cons = c[imp_end + 10:]
            if len(cons) >= 3 and np.std(cons) < 0.7 * A and abs(cons[-1] - cons[0]) < 1.2 * A:
                P("Bull flag" if impulse > 0 else "Bear flag", "chart", 1 if impulse > 0 else -1, 0.6, f"{impulse / A:+.1f} ATR impulse, then {bars_since} bars of tight consolidation")
    # tight base
    if (np.max(c[-20:]) - np.min(c[-20:])) < 3 * A:
        P("Tight 20-day base", "chart", 0, 0.4, f"20-day close range {np.max(c[-20:]) - np.min(c[-20:]):.2f} < 3 ATR — compression")
    # gaps
    gap = o[-1] / c[-2] - 1
    if abs(gap) >= 0.01:
        unfilled = (l[-1] > c[-2]) if gap > 0 else (h[-1] < c[-2])
        fills = 0
        cnt = 0
        for i in range(max(1, n - 250), n - 6):
            g = o[i] / c[i - 1] - 1
            if abs(g) >= 0.01:
                cnt += 1
                if (g > 0 and np.min(l[i:i + 6]) <= c[i - 1]) or (g < 0 and np.max(h[i:i + 6]) >= c[i - 1]):
                    fills += 1
        P(f"{'Gap up' if gap > 0 else 'Gap down'} {gap:+.1%}" + (" (unfilled)" if unfilled else " (filled intraday)"), "gap", 1 if gap > 0 else -1, 0.5 if unfilled else 0.25,
          f"this name filled {fills}/{cnt} ({fills / cnt:.0%}) of ≥1% gaps within 5 days over the past year" if cnt else "no gap history")
    return out


# ----------------------------------------------------------------------------- regression channel
def channel(df: pd.DataFrame, n: int = 60) -> dict[str, Any]:
    d = df.tail(n)
    c = d["close"].astype(float).values
    if len(c) < 20:
        return {}
    x = np.arange(len(c))
    slope, icpt = np.polyfit(x, c, 1)
    fit = slope * x + icpt
    resid = c - fit
    sd = float(resid.std()) or 1e-9
    r2 = 1 - resid.var() / c.var() if c.var() else 0.0
    return {"bars": len(c), "slope_pct_per_day": float(slope / c.mean()), "r2": float(r2), "position_z": float(resid[-1] / sd),
            "upper": float(fit[-1] + 2 * sd), "mid": float(fit[-1]), "lower": float(fit[-1] - 2 * sd), "direction": "up" if slope > 0 else "down"}


# ----------------------------------------------------------------------------- swing setup + trade plan
def swing_setup(df: pd.DataFrame, patterns: list[Pattern], structure: dict[str, Any] | None, iv30: float | None, weekly_bull: bool | None,
                intraday_bull: bool | None, spy_regime_ok: bool | None) -> dict[str, Any]:
    d = df.reset_index(drop=True)
    c = d["close"].astype(float)
    h, l = d["high"].astype(float), d["low"].astype(float)
    if len(c) < 60:
        return {"setup": "insufficient history"}
    last = float(c.iloc[-1])
    A = float(atr(d, 14).iloc[-1])
    e21, e50, s200 = float(ema(c, 21).iloc[-1]), float(ema(c, 50).iloc[-1]), float(sma(c, 200).iloc[-1]) if len(c) >= 200 else float("nan")
    r14, r2 = float(rsi(c, 14).iloc[-1]), float(rsi(c, 2).iloc[-1])
    green = float(d["close"].iloc[-1]) > float(d["open"].iloc[-1])
    uptrend = last > e50 and (not np.isfinite(s200) or e50 > s200)
    downtrend = last < e50 and (not np.isfinite(s200) or e50 < s200)
    rvol = rel_volume(d)
    names = {p.name for p in patterns if p.bars_ago <= 1}
    recent_candle = sum(p.direction * p.weight for p in patterns if p.kind == "candle" and p.bars_ago <= 2)

    setup, direction, quality, why = "No defined setup", 0, 0.0, []
    if any(n.startswith("20-day breakout") or n.startswith("55-day breakout") for n in names) and rvol > 1.2:
        setup, direction, quality = "Breakout (continuation)", +1, 0.6 + 0.2 * min(rvol - 1, 1)
        why.append(f"new {'55' if '55-day breakout' in names else '20'}-day high on {rvol:.1f}x volume")
    elif any(n.startswith("20-day breakdown") or n.startswith("55-day breakdown") for n in names) and rvol > 1.2:
        setup, direction, quality = "Breakdown (continuation short)", -1, 0.6 + 0.2 * min(rvol - 1, 1)
        why.append(f"new low on {rvol:.1f}x volume")
    elif "Failed breakdown (spring)" in names:
        setup, direction, quality = "Failed breakdown (spring)", +1, 0.6
        why.append("lost the 20-day low and reclaimed it — trapped shorts")
    elif "Failed breakout (upthrust)" in names:
        setup, direction, quality = "Failed breakout (upthrust)", -1, 0.6
        why.append("lost the breakout level — trapped longs")
    elif uptrend and abs(last - e21) <= 1.0 * A and 38 <= r14 <= 58 and green:
        setup, direction, quality = "Pullback to 21-EMA in uptrend", +1, 0.65
        why.append(f"price {((last / e21) - 1):+.1%} from EMA21, RSI {r14:.0f}, green bar")
    elif downtrend and abs(last - e21) <= 1.0 * A and 42 <= r14 <= 62 and not green:
        setup, direction, quality = "Rally into 21-EMA in downtrend", -1, 0.6
        why.append(f"price near EMA21 from below, RSI {r14:.0f}, red bar")
    elif uptrend and r2 < 10:
        setup, direction, quality = "Oversold bounce in uptrend (RSI-2)", +1, 0.55
        why.append(f"RSI(2) {r2:.0f} with price above the 50-EMA")
    elif downtrend and r2 > 90:
        setup, direction, quality = "Overbought fade in downtrend (RSI-2)", -1, 0.5
        why.append(f"RSI(2) {r2:.0f} with price below the 50-EMA")
    elif "NR7 (narrowest range in 7)" in names or "Tight 20-day base" in names or "Inside bar" in names:
        setup, direction, quality = "Volatility compression — await the break", 0, 0.4
        why.append("range contraction; trade the direction of the expansion bar")
    if recent_candle:
        why.append(f"candles net {recent_candle:+.2f} ({', '.join(p.name for p in patterns if p.kind == 'candle' and p.bars_ago <= 2)})")
        if direction and np.sign(recent_candle) == direction:
            quality = min(1.0, quality + 0.1)
        elif direction and np.sign(recent_candle) == -direction:
            quality = max(0.0, quality - 0.15)
    align = [x for x in (weekly_bull, intraday_bull) if x is not None]
    if direction and align:
        agree = sum(1 for x in align if x == (direction > 0)) / len(align)
        quality = quality * (0.8 + 0.4 * agree)
        why.append(f"timeframe alignment {agree:.0%}")
    if spy_regime_ok is not None and direction:
        if (direction > 0) != spy_regime_ok:
            quality *= 0.8
            why.append("market regime opposes the setup")

    # trade plan (illustrative geometry, not advice): ATR stop, level-based target, R:R, option-implied 10-day move
    st = structure or {}
    plan: dict[str, Any] = {}
    if direction:
        swing_lo, swing_hi = st.get("recent_swing_low"), st.get("recent_swing_high")
        if direction > 0:
            stop = last - 1.5 * A
            if swing_lo and last - swing_lo < 3 * A and swing_lo < last:
                stop = min(stop, swing_lo - 0.2 * A)
            res = [r["level"] for r in (st.get("resistance") or []) if r["level"] > last * 1.005]
            target = min(res) if res else last + 2 * (last - stop)
        else:
            stop = last + 1.5 * A
            if swing_hi and swing_hi - last < 3 * A and swing_hi > last:
                stop = max(stop, swing_hi + 0.2 * A)
            sup = [r["level"] for r in (st.get("support") or []) if r["level"] < last * 0.995]
            target = max(sup) if sup else last - 2 * (stop - last)
        risk = abs(last - stop)
        reward = abs(target - last)
        plan = {"entry": last, "stop": stop, "target": target, "risk_per_share": risk, "reward_per_share": reward, "rr": (reward / risk) if risk else None,
                "stop_pct": -risk / last * direction, "target_pct": reward / last * direction, "atr": A, "position_size_hint": "risk 1% of equity → shares = 0.01 × equity / risk_per_share"}
    em10 = (iv30 * np.sqrt(10 / 252) * last) if iv30 else None
    return {"setup": setup, "direction": direction, "quality": round(float(quality), 2), "why": why, "trend": "up" if uptrend else ("down" if downtrend else "sideways"),
            "rsi14": r14, "rsi2": r2, "rel_volume": rvol, "atr": A, "atr_pct": A / last, "ema21": e21, "ema50": e50, "sma200": s200 if np.isfinite(s200) else None,
            "plan": plan, "implied_10d_move": em10, "implied_10d_move_pct": (em10 / last) if em10 else None,
            "horizon": "2-20 trading days", "disclaimer": "pattern geometry and ATR arithmetic — not a recommendation"}


def analyze(daily: pd.DataFrame, structure: dict[str, Any] | None = None, iv30: float | None = None, weekly_bull: bool | None = None,
            intraday_bull: bool | None = None, spy_regime_ok: bool | None = None) -> dict[str, Any]:
    cs = candlesticks(daily)
    cp = chart_patterns(daily)
    pats = sorted(cs + cp, key=lambda p: (p.bars_ago, -p.weight))
    recent = [p for p in pats if p.bars_ago <= 3]
    net = sum(p.direction * p.weight for p in recent)
    return {
        "patterns": [p.json() for p in pats[:40]], "recent_net_signal": float(net), "n_recent": len(recent),
        "candle_net_2bars": float(sum(p.direction * p.weight for p in cs if p.bars_ago <= 2)),
        "chart_net": float(sum(p.direction * p.weight for p in cp if p.kind in ("chart", "breakout") and p.bars_ago <= 5)),
        "channel": channel(daily), "setup": swing_setup(daily, pats, structure, iv30, weekly_bull, intraday_bull, spy_regime_ok),
    }

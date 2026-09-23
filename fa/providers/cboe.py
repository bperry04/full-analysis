"""CBOE delayed quotes: full option chain with exchange-computed greeks, IV, OI, sizes; underlying quote; VIX history.

Free, no key, ~15 min delayed. Index symbols use an underscore prefix (_SPX, _VIX).
"""
from __future__ import annotations

import io
import time
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from fa.core import http
from fa.core.clock import ET
from fa.core.errors import NoData
from fa.core.types import Latency, Tier
from fa.providers._util import finish_chain, parse_occ
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

BASE = "https://cdn.cboe.com/api/global/delayed_quotes/options"
VIX_HIST = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def _cboe_symbol(symbol: str) -> str:
    s = symbol.upper()
    if s.startswith("^"):
        return "_" + s[1:]
    return s


class Cboe(Provider):
    name = "cboe"
    tier = Tier.A
    latency = Latency.DELAYED_15
    license_note = "CBOE delayed quotes (personal use)"

    def __init__(self) -> None:
        self._memo: dict[str, tuple[float, dict, bytes]] = {}

    def capabilities(self):
        return {
            N.QUOTE: self.quote,
            N.OPTION_EXPIRATIONS: self.expirations,
            N.OPTION_CHAIN: self.chain,
            N.VIX_HISTORY: self.vix_history,
        }

    async def _payload(self, symbol: str) -> tuple[dict, bytes, str]:
        """One JSON fetch serves quote + expirations + chain; memoized for 60s inside the provider."""
        sym = _cboe_symbol(symbol)
        hit = self._memo.get(sym)
        if hit and time.time() - hit[0] < 60:
            return hit[1], hit[2], f"{BASE}/{sym}.json"
        url = f"{BASE}/{sym}.json"
        raw = await http.get_bytes(self.name, url, timeout=40)
        import json
        data = json.loads(raw)
        if not data.get("data") or not data["data"].get("options"):
            raise NoData(self.name, f"no options payload for {symbol}")
        self._memo[sym] = (time.time(), data, raw)
        return data, raw, url

    @staticmethod
    def _as_of(data: dict) -> datetime | None:
        ts = data.get("timestamp")
        if not ts:
            return None
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)
        except Exception:
            return None

    async def quote(self, symbol: str, **_: Any) -> Payload:
        data, raw, url = await self._payload(symbol)
        d = data["data"]
        q = {
            "symbol": symbol.upper(), "price": d.get("current_price"), "bid": d.get("bid"), "ask": d.get("ask"),
            "bid_size": d.get("bid_size"), "ask_size": d.get("ask_size"), "open": d.get("open"), "high": d.get("high"),
            "low": d.get("low"), "prev_close": d.get("prev_day_close"), "close": d.get("close"),
            "volume": d.get("volume"), "change": d.get("price_change"), "change_pct": d.get("price_change_percent"),
            "iv30": d.get("iv30"), "iv30_change": d.get("iv30_change"), "iv30_change_pct": d.get("iv30_change_percent"),
            "security_type": d.get("security_type"),
        }
        return Payload(q, url, as_of=self._as_of(data), raw=raw)

    async def expirations(self, symbol: str, **_: Any) -> Payload:
        data, raw, url = await self._payload(symbol)
        exps = set()
        for o in data["data"]["options"]:
            p = parse_occ(o["option"])
            if p:
                exps.add(p[1])
        if not exps:
            raise NoData(self.name, "no parsable contracts")
        return Payload(sorted(exps), url, as_of=self._as_of(data), row_count=len(exps))

    async def chain(self, symbol: str, **_: Any) -> Payload:
        data, raw, url = await self._payload(symbol)
        d = data["data"]
        rows = []
        for o in d["options"]:
            p = parse_occ(o["option"])
            if not p:
                continue
            _, expiry, right, strike = p
            rows.append(
                {
                    "contract_symbol": o["option"], "expiry": expiry, "strike": strike, "right": right,
                    "bid": o.get("bid"), "ask": o.get("ask"), "bid_size": o.get("bid_size"), "ask_size": o.get("ask_size"),
                    "last": o.get("last_trade_price"), "last_ts": o.get("last_trade_time"),
                    "volume": o.get("volume"), "open_interest": o.get("open_interest"),
                    "iv": o.get("iv"), "delta": o.get("delta"), "gamma": o.get("gamma"), "theta": o.get("theta"),
                    "vega": o.get("vega"), "rho": o.get("rho"), "theo": o.get("theo"),
                }
            )
        if not rows:
            raise NoData(self.name, "no parsable contracts")
        df = pd.DataFrame(rows)
        df["iv"] = pd.to_numeric(df["iv"], errors="coerce").replace(0.0, np.nan)   # CBOE emits 0 for unsolvable IV
        df["iv_source"] = "cboe"
        df["greeks_source"] = "cboe"
        as_of = self._as_of(data)
        df = finish_chain(df, d.get("current_price"), as_of)
        return Payload(df, url, as_of=as_of, raw=raw, row_count=len(df),
                       meta={"iv30": d.get("iv30"), "underlying_price": d.get("current_price")})

    async def vix_history(self, **_: Any) -> Payload:
        text = await http.get_text(self.name, VIX_HIST, timeout=30)
        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.rename(columns={"date": "ts"})
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce", utc=True)
        df = df.dropna(subset=["ts"])
        return Payload(df, VIX_HIST, raw=text, row_count=len(df), latency=Latency.EOD)


PROVIDER = Cboe()

"""Stooq public CSV: daily OHLCV backup and a few macro proxies. No key."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.errors import NoData
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

BASE = "https://stooq.com/q/d/l/"
MACRO = {"SP500": "^spx", "VIXCLS": "^vix", "DGS10": "10usy.b", "DGS2": "2usy.b", "DGS30": "30usy.b", "DCOILWTICO": "cl.f",
         "GOLDAMGBD228NLBM": "gc.f", "DEXUSEU": "eurusd", "DEXJPUS": "usdjpy", "NASDAQCOM": "^ndq"}


def _sym(symbol: str) -> str:
    s = symbol.lower()
    if s.startswith("^"):
        return s
    return s if "." in s else f"{s}.us"


class Stooq(Provider):
    name = "stooq"
    tier = Tier.C
    latency = Latency.EOD
    license_note = "Stooq public CSV"

    def capabilities(self):
        return {N.OHLCV: self.ohlcv, N.MACRO_SERIES: self.series}

    async def _csv(self, stooq_symbol: str) -> tuple[pd.DataFrame, str]:
        url = f"{BASE}?s={stooq_symbol}&i=d"
        text = await http.get_text(self.name, url, timeout=30)
        if "No data" in text or len(text) < 30:
            raise NoData(self.name, f"no data for {stooq_symbol}")
        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"date": "ts"})
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        return df.dropna(subset=["ts"]), url

    async def ohlcv(self, symbol: str, interval: str = "1d", **_: Any) -> Payload:
        if interval not in ("1d", "1wk", "1mo"):
            raise NoData(self.name, "stooq serves daily bars only")
        df, url = await self._csv(_sym(symbol))
        df["adj_close"] = df["close"]
        df["symbol"], df["interval"] = symbol.upper(), "1d"
        if "volume" not in df.columns:
            df["volume"] = 0
        df = df[["ts", "open", "high", "low", "close", "adj_close", "volume", "symbol", "interval"]]
        return Payload(df, url, row_count=len(df), as_of=df["ts"].max().to_pydatetime(), flags=["DEGRADED"])

    async def series(self, series_id: str, **_: Any) -> Payload:
        s = MACRO.get(series_id)
        if not s:
            raise NoData(self.name, f"no stooq proxy for {series_id}")
        df, url = await self._csv(s)
        out = pd.DataFrame({"date": df["ts"].dt.date, "value": df["close"], "series_id": series_id})
        return Payload(out, url, row_count=len(out), flags=["PROXY", "DEGRADED"],
                       as_of=datetime.combine(out["date"].max(), datetime.min.time(), tzinfo=timezone.utc))


PROVIDER = Stooq()

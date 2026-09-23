"""Finnhub free tier (optional key, 60 req/min): recommendation trends, price targets, earnings calendar."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.errors import NoData
from fa.core.settings import get_settings
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

BASE = "https://finnhub.io/api/v1"


class Finnhub(Provider):
    name = "finnhub"
    tier = Tier.B
    latency = Latency.DELAYED_15
    license_note = "Finnhub free tier"

    def capabilities(self):
        return {N.ANALYST_RECS: self.recs, N.ANALYST_TARGETS: self.targets, N.EARNINGS_DATES: self.earnings}

    async def _get(self, path: str, **params: Any) -> Any:
        key = get_settings().finnhub_api_key
        if not key:
            raise NoData(self.name, "FA_FINNHUB_API_KEY not set")
        return await http.get_json(self.name, f"{BASE}{path}", params={**params, "token": key}, timeout=20)

    async def recs(self, symbol: str, **_: Any) -> Payload:
        j = await self._get("/stock/recommendation", symbol=symbol.upper())
        if not j:
            raise NoData(self.name, "no recommendations")
        df = pd.DataFrame(j).rename(columns={"strongBuy": "strongBuy", "period": "period"})
        return Payload({"trend": df, "actions": pd.DataFrame()}, f"{BASE}/stock/recommendation?symbol={symbol}", row_count=len(df), latency=Latency.EOD)

    async def targets(self, symbol: str, **_: Any) -> Payload:
        j = await self._get("/stock/price-target", symbol=symbol.upper())
        if not j or not j.get("targetMean"):
            raise NoData(self.name, "no price target")
        return Payload({"mean": j.get("targetMean"), "median": j.get("targetMedian"), "high": j.get("targetHigh"), "low": j.get("targetLow"),
                        "last_updated": j.get("lastUpdated")}, f"{BASE}/stock/price-target?symbol={symbol}", latency=Latency.EOD)

    async def earnings(self, symbol: str, **_: Any) -> Payload:
        frm, to = date.today() - timedelta(days=400), date.today() + timedelta(days=200)
        j = await self._get("/calendar/earnings", symbol=symbol.upper(), **{"from": str(frm), "to": str(to)})
        rows = (j or {}).get("earningsCalendar") or []
        if not rows:
            raise NoData(self.name, "no earnings calendar")
        df = pd.DataFrame(rows).rename(columns={"date": "ts", "epsEstimate": "eps_estimate", "epsActual": "eps_reported",
                                                "revenueEstimate": "rev_estimate", "revenueActual": "rev_reported", "hour": "time"})
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df["surprise_pct"] = (df["eps_reported"] - df["eps_estimate"]) / df["eps_estimate"].abs() * 100
        return Payload(df.sort_values("ts", ascending=False), f"{BASE}/calendar/earnings?symbol={symbol}", row_count=len(df), latency=Latency.EOD)


PROVIDER = Finnhub()

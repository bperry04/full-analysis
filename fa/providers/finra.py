"""FINRA public data: RegSHO daily short-sale volume (CNMS consolidated file) and bi-monthly consolidated short interest."""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.clock import is_trading_day, last_trading_day
from fa.core.errors import NoData
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

DAILY = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{ymd}.txt"
SI_API = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"


class Finra(Provider):
    name = "finra"
    tier = Tier.A
    latency = Latency.EOD
    license_note = "FINRA public data"

    def __init__(self) -> None:
        self._daily: dict[date, pd.DataFrame] = {}

    def capabilities(self):
        return {N.SHORT_VOLUME: self.short_volume, N.SHORT_INTEREST: self.short_interest}

    async def daily_file(self, d: date) -> pd.DataFrame:
        if d in self._daily:
            return self._daily[d]
        url = DAILY.format(ymd=d.strftime("%Y%m%d"))
        text = await http.get_text(self.name, url, timeout=60)
        df = pd.read_csv(io.StringIO(text), sep="|")
        df = df[df["Symbol"].notna()]
        df = df.rename(columns={"Date": "date", "Symbol": "symbol", "ShortVolume": "short_volume",
                                "ShortExemptVolume": "short_exempt_volume", "TotalVolume": "total_volume", "Market": "market"})
        df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce").dt.date
        for c in ("short_volume", "short_exempt_volume", "total_volume"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["short_ratio"] = df["short_volume"] / df["total_volume"]
        self._daily[d] = df
        if len(self._daily) > 60:
            self._daily.pop(next(iter(self._daily)))
        return df

    async def short_volume(self, symbol: str | None = None, days: int = 30, date: date | str | None = None, **_: Any) -> Payload:
        """One symbol over N trading days, or the whole market for one date (symbol=None)."""
        if date is not None:
            d = pd.Timestamp(date).date()
            df = await self.daily_file(d)
            if symbol:
                df = df[df["symbol"] == symbol.upper()]
            return Payload(df, DAILY.format(ymd=d.strftime("%Y%m%d")), row_count=len(df),
                           as_of=datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc))
        # candidate trading days, newest first; fetch concurrently (files are ~500KB each)
        import asyncio
        cands: list = []
        d = last_trading_day()
        while len(cands) < days + 2:
            if is_trading_day(d):
                cands.append(d)
            d -= timedelta(days=1)
        sem = asyncio.Semaphore(4)
        async def one(day):
            async with sem:
                try:
                    return day, await self.daily_file(day)
                except Exception:
                    return day, None          # today's file may not be published yet
        results = await asyncio.gather(*[one(x) for x in cands])
        frames, urls = [], []
        for day, f in results:
            if f is None:
                continue
            urls.append(DAILY.format(ymd=day.strftime("%Y%m%d")))
            frames.append(f[f["symbol"] == symbol.upper()] if symbol else f)
            if len(frames) >= days:
                break
        if not frames:
            raise NoData(self.name, "no daily short volume files")
        df = pd.concat(frames, ignore_index=True).sort_values("date")
        if df.empty:
            raise NoData(self.name, f"no short volume rows for {symbol}")
        return Payload(df, urls[0] if urls else DAILY, row_count=len(df),
                       as_of=datetime.combine(df["date"].max(), datetime.min.time(), tzinfo=timezone.utc))

    async def short_interest(self, symbol: str, limit: int = 5000, **_: Any) -> Payload:
        # The API ignores/rejects sortFields for this dataset, so pull the symbol's full history and sort locally.
        body = {
            "limit": limit,
            "compareFilters": [{"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": symbol.upper()}],
        }
        hdr = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": http.BROWSER_UA}
        r = await http.client().post(SI_API, json=body, headers=hdr, timeout=60)
        if r.status_code != 200:
            raise NoData(self.name, f"short interest HTTP {r.status_code}")
        rows = r.json()
        if not rows:
            raise NoData(self.name, f"no short interest rows for {symbol}")
        df = pd.DataFrame(rows).rename(columns={
            "settlementDate": "settlement_date", "currentShortPositionQuantity": "shares_short",
            "previousShortPositionQuantity": "shares_short_prior", "averageDailyVolumeQuantity": "avg_daily_volume",
            "daysToCoverQuantity": "days_to_cover", "changePercent": "change_pct", "marketClassCode": "market",
        })
        df["settlement_date"] = pd.to_datetime(df["settlement_date"], errors="coerce").dt.date
        df = df.sort_values("settlement_date", ascending=False).reset_index(drop=True)
        latest = df.iloc[0]
        out = {
            "symbol": symbol.upper(), "shares_short": float(latest["shares_short"]), "shares_short_prior": float(latest["shares_short_prior"]) if pd.notna(latest["shares_short_prior"]) else None,
            "settlement_date": latest["settlement_date"].isoformat(), "days_to_cover": float(latest["days_to_cover"]) if pd.notna(latest["days_to_cover"]) else None,
            "avg_daily_volume": float(latest["avg_daily_volume"]) if pd.notna(latest["avg_daily_volume"]) else None,
            "change_pct": float(latest["change_pct"]) if pd.notna(latest.get("change_pct")) else None,
            "history": df[["settlement_date", "shares_short", "shares_short_prior", "avg_daily_volume", "days_to_cover", "change_pct"]],
        }
        return Payload(out, SI_API, raw=rows, row_count=len(df),
                       as_of=datetime.combine(latest["settlement_date"], datetime.min.time(), tzinfo=timezone.utc))


PROVIDER = Finra()

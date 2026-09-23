"""Nasdaq.com public API (unofficial, browser UA required): quote, profile, institutional holdings, short interest,
economic-events calendar, earnings calendar, dividends."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.errors import NoData
from fa.core.types import Latency, Tier
from fa.providers._util import num
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

BASE = "https://api.nasdaq.com/api"
H = {"User-Agent": http.BROWSER_UA, "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9",
     "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


class Nasdaq(Provider):
    name = "nasdaq"
    tier = Tier.B
    latency = Latency.DELAYED_15
    license_note = "Nasdaq.com public API (unofficial)"

    def capabilities(self):
        return {
            N.QUOTE: self.quote,
            N.COMPANY_PROFILE: self.profile,
            N.INSTITUTIONAL_HOLDERS: self.institutional,
            N.SHORT_INTEREST: self.short_interest,
            N.ECON_CALENDAR: self.econ_calendar,
            N.EARNINGS_CALENDAR: self.earnings_calendar,
            N.DIVIDENDS: self.dividends,
        }

    async def _get(self, path: str, **params: Any) -> dict:
        url = f"{BASE}{path}"
        j = await http.get_json(self.name, url, params=params, headers=H, timeout=25)
        if not j or j.get("data") is None:
            raise NoData(self.name, f"empty payload {path}")
        return j

    async def quote(self, symbol: str, **_: Any) -> Payload:
        j = await self._get(f"/quote/{symbol.upper()}/info", assetclass="stocks")
        d = j["data"]
        p = d.get("primaryData") or {}
        k = d.get("keyStats") or {}
        q = {
            "symbol": symbol.upper(), "price": num(p.get("lastSalePrice")), "change": num(p.get("netChange")),
            "change_pct": num(p.get("percentageChange")), "bid": num(p.get("bidPrice")), "ask": num(p.get("askPrice")),
            "bid_size": num(p.get("bidSize")), "ask_size": num(p.get("askSize")), "volume": num(p.get("volume")),
            "prev_close": num((k.get("PreviousClose") or {}).get("value")), "open": num((k.get("OpenPrice") or {}).get("value")),
            "market_status": d.get("marketStatus"), "last_trade": p.get("lastTradeTimestamp"), "exchange": d.get("exchange"),
            "name": d.get("companyName"),
        }
        if not q["price"]:
            raise NoData(self.name, "no price")
        return Payload(q, f"{BASE}/quote/{symbol}/info", raw=j, as_of=datetime.now(timezone.utc))

    async def profile(self, symbol: str, **_: Any) -> Payload:
        j = await self._get(f"/quote/{symbol.upper()}/summary", assetclass="stocks")
        sd = j["data"].get("summaryData") or {}
        out = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in sd.items()}
        try:
            cp = await self._get(f"/company/{symbol.upper()}/company-profile")
            for k, v in (cp["data"] or {}).items():
                out[f"profile_{k}"] = v.get("value") if isinstance(v, dict) else v
        except Exception:
            pass
        return Payload(out, f"{BASE}/quote/{symbol}/summary", raw=j)

    async def institutional(self, symbol: str, limit: int = 50, **_: Any) -> Payload:
        j = await self._get(f"/company/{symbol.upper()}/institutional-holdings", limit=limit, type="TOTAL", sortColumn="marketValue")
        d = j["data"]
        rows = ((d.get("holdingsTransactions") or {}).get("table") or {}).get("rows") or []
        if not rows:
            raise NoData(self.name, "no holdings rows")
        df = pd.DataFrame(rows)
        df = df.rename(columns={"ownerName": "holder", "date": "reported", "sharesHeld": "shares", "sharesChange": "change_shares",
                                "sharesChangePCT": "pct_change", "marketValue": "value"})
        for c in ("shares", "change_shares", "pct_change", "value"):
            if c in df.columns:
                df[c] = df[c].map(num)
        if "reported" in df.columns:
            df["reported"] = pd.to_datetime(df["reported"], errors="coerce").dt.date
        own = d.get("ownershipSummary") or {}
        major = {k: num((v or {}).get("value")) for k, v in own.items()} if isinstance(own, dict) else {}
        return Payload({"institutional": df, "major": major}, f"{BASE}/company/{symbol}/institutional-holdings", raw=j,
                       row_count=len(df), latency=Latency.FILING)

    async def short_interest(self, symbol: str, **_: Any) -> Payload:
        j = await self._get(f"/quote/{symbol.upper()}/short-interest", assetClass="stocks")
        rows = ((j["data"].get("shortInterestTable") or {}).get("rows")) or []
        if not rows:
            raise NoData(self.name, "no short interest rows")
        df = pd.DataFrame(rows).rename(columns={"settlementDate": "settlement_date", "interest": "shares_short",
                                                "avgDailyShareVolume": "avg_daily_volume", "daysToCover": "days_to_cover"})
        df["settlement_date"] = pd.to_datetime(df["settlement_date"], errors="coerce").dt.date
        for c in ("shares_short", "avg_daily_volume", "days_to_cover"):
            df[c] = df[c].map(num)
        df = df.sort_values("settlement_date", ascending=False).reset_index(drop=True)
        latest = df.iloc[0]
        out = {
            "symbol": symbol.upper(), "shares_short": latest["shares_short"], "settlement_date": latest["settlement_date"].isoformat(),
            "days_to_cover": latest["days_to_cover"], "avg_daily_volume": latest["avg_daily_volume"],
            "shares_short_prior": df["shares_short"].iloc[1] if len(df) > 1 else None, "history": df,
        }
        return Payload(out, f"{BASE}/quote/{symbol}/short-interest", raw=j, row_count=len(df), latency=Latency.EOD)

    async def econ_calendar(self, date: str | date | None = None, **_: Any) -> Payload:
        d = str(date or datetime.now(timezone.utc).date())
        j = await self._get("/calendar/economicevents", date=d)
        rows = j["data"].get("rows") or []
        df = pd.DataFrame(rows)
        if df.empty:
            raise NoData(self.name, f"no events {d}")
        df["date"] = d
        for c in ("actual", "consensus", "previous"):
            if c in df.columns:
                df[c] = df[c].astype(str).str.replace("&nbsp;", "", regex=False).str.strip()
        df = df.rename(columns={"gmt": "time_gmt", "eventName": "event"})
        return Payload(df, f"{BASE}/calendar/economicevents?date={d}", raw=j, row_count=len(df), latency=Latency.RELEASE)

    async def earnings_calendar(self, date: str | date | None = None, **_: Any) -> Payload:
        d = str(date or datetime.now(timezone.utc).date())
        j = await self._get("/calendar/earnings", date=d)
        rows = j["data"].get("rows") or []
        df = pd.DataFrame(rows)
        if df.empty:
            raise NoData(self.name, f"no earnings {d}")
        df["date"] = d
        df = df.rename(columns={"epsForecast": "eps_forecast", "noOfEsts": "n_estimates", "lastYearRptDt": "last_year_report_date",
                                "lastYearEPS": "last_year_eps", "marketCap": "market_cap", "fiscalQuarterEnding": "fiscal_quarter_ending"})
        return Payload(df, f"{BASE}/calendar/earnings?date={d}", raw=j, row_count=len(df), latency=Latency.RELEASE)

    async def dividends(self, symbol: str, **_: Any) -> Payload:
        j = await self._get(f"/quote/{symbol.upper()}/dividends", assetclass="stocks")
        d = j["data"]
        rows = ((d.get("dividends") or {}).get("rows")) or []
        if not rows:
            raise NoData(self.name, "no dividends")
        df = pd.DataFrame(rows).rename(columns={"exOrEffDate": "ex_date", "paymentDate": "pay_date", "recordDate": "record_date",
                                                "declarationDate": "declared", "amount": "dividend"})
        df["dividend"] = df["dividend"].map(num)
        for c in ("ex_date", "pay_date", "record_date", "declared"):
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        meta = {k: d.get(k) for k in ("exDividendDate", "dividendPaymentDate", "yield", "annualizedDividend", "payoutRatio")}
        return Payload(df, f"{BASE}/quote/{symbol}/dividends", raw=j, row_count=len(df), meta=meta, latency=Latency.EOD)


PROVIDER = Nasdaq()

"""Yahoo Finance via yfinance (unofficial, ~15 min delayed): prices at every interval, chains (IV only),
5-period statements, profile, analysts, holders, insiders, earnings dates, short-interest fields, news.

yfinance is synchronous; every call is pushed to a worker thread.
"""
from __future__ import annotations

import asyncio
import logging
import warnings
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from fa.core.errors import NoData
from fa.core.types import Latency, Tier
from fa.providers._util import finish_chain, parse_occ
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

log = logging.getLogger(__name__)
warnings.filterwarnings("ignore", module="yfinance")

# yfinance max lookback per interval (Yahoo-side limits)
MAX_PERIOD = {"1m": "7d", "2m": "60d", "5m": "60d", "15m": "60d", "30m": "60d", "60m": "730d", "1h": "730d",
              "90m": "60d", "1d": "max", "5d": "max", "1wk": "max", "1mo": "max", "3mo": "max"}


def _tk(symbol: str):
    import yfinance as yf
    return yf.Ticker(symbol.upper())


class Yahoo(Provider):
    name = "yahoo"
    tier = Tier.B
    latency = Latency.DELAYED_15
    license_note = "Yahoo Finance via yfinance (unofficial)"

    def capabilities(self):
        return {
            N.QUOTE: self.quote,
            N.OHLCV: self.ohlcv,
            N.OPTION_EXPIRATIONS: self.expirations,
            N.OPTION_CHAIN: self.chain,
            N.STATEMENTS_FALLBACK: self.statements,
            N.COMPANY_PROFILE: self.profile,
            N.EARNINGS_DATES: self.earnings_dates,
            N.ANALYST_RECS: self.analyst_recs,
            N.ANALYST_TARGETS: self.analyst_targets,
            N.ANALYST_ESTIMATES: self.analyst_estimates,
            N.INSIDER_TXNS: self.insider_txns,
            N.INSTITUTIONAL_HOLDERS: self.institutional_holders,
            N.SHORT_INTEREST: self.short_interest,
            N.NEWS: self.news,
            N.DIVIDENDS: self.dividends,
            N.SPLITS: self.splits,
            N.VIX_HISTORY: self.vix_history,
        }

    # ------------------------------------------------------------------ prices
    async def quote(self, symbol: str, **_: Any) -> Payload:
        def _f():
            t = _tk(symbol)
            fi = t.fast_info
            g = lambda k: _safe(getattr(fi, k, None))  # noqa: E731
            return {
                "symbol": symbol.upper(), "price": g("last_price"), "prev_close": g("previous_close"), "open": g("open"),
                "high": g("day_high"), "low": g("day_low"), "volume": g("last_volume"), "avg_volume_3m": g("three_month_average_volume"),
                "avg_volume_10d": g("ten_day_average_volume"), "market_cap": g("market_cap"), "shares": g("shares"),
                "year_high": g("year_high"), "year_low": g("year_low"), "currency": getattr(fi, "currency", None),
                "exchange": getattr(fi, "exchange", None), "ma50": g("fifty_day_average"), "ma200": g("two_hundred_day_average"),
            }
        q = await asyncio.to_thread(_f)
        if not q.get("price"):
            raise NoData(self.name, f"no quote for {symbol}")
        q["change"] = (q["price"] - q["prev_close"]) if q.get("prev_close") else None
        q["change_pct"] = (q["change"] / q["prev_close"] * 100) if q.get("prev_close") else None
        return Payload(q, f"yfinance.Ticker({symbol}).fast_info", as_of=datetime.now(timezone.utc))

    async def ohlcv(self, symbol: str, interval: str = "1d", period: str | None = None,
                    start: str | None = None, end: str | None = None, **_: Any) -> Payload:
        def _f():
            t = _tk(symbol)
            kw: dict[str, Any] = {"interval": interval, "auto_adjust": False, "actions": False, "prepost": False}
            if start:
                kw["start"], kw["end"] = start, end
            else:
                kw["period"] = period or MAX_PERIOD.get(interval, "1y")
            return t.history(**kw)
        h = await asyncio.to_thread(_f)
        if h is None or h.empty:
            raise NoData(self.name, f"no {interval} bars for {symbol}")
        df = h.reset_index()
        tscol = "Datetime" if "Datetime" in df.columns else "Date"
        df = df.rename(columns={tscol: "ts", "Open": "open", "High": "high", "Low": "low", "Close": "close",
                                "Adj Close": "adj_close", "Volume": "volume"})
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        if "adj_close" not in df.columns:
            df["adj_close"] = df["close"]
        df = df[["ts", "open", "high", "low", "close", "adj_close", "volume"]].dropna(subset=["close"])
        df["symbol"], df["interval"] = symbol.upper(), interval
        lat = Latency.EOD if interval in ("1d", "5d", "1wk", "1mo", "3mo") else Latency.DELAYED_15
        return Payload(df, f"yfinance.Ticker({symbol}).history(interval={interval})", as_of=df["ts"].max().to_pydatetime(),
                       row_count=len(df), latency=lat)

    # ------------------------------------------------------------------ options
    async def expirations(self, symbol: str, **_: Any) -> Payload:
        exps = await asyncio.to_thread(lambda: list(_tk(symbol).options))
        if not exps:
            raise NoData(self.name, "no expirations")
        return Payload([pd.Timestamp(e).date() for e in exps], f"yfinance.Ticker({symbol}).options", row_count=len(exps))

    async def chain(self, symbol: str, max_expiries: int = 24, **_: Any) -> Payload:
        def _f():
            t = _tk(symbol)
            price = _safe(getattr(t.fast_info, "last_price", None))
            frames = []
            for e in list(t.options)[:max_expiries]:
                try:
                    ch = t.option_chain(e)
                except Exception:
                    continue
                for right, part in (("C", ch.calls), ("P", ch.puts)):
                    if part is None or part.empty:
                        continue
                    p = part.copy()
                    p["right"] = right
                    p["expiry"] = pd.Timestamp(e).date()
                    frames.append(p)
            return price, (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
        price, raw = await asyncio.to_thread(_f)
        if raw.empty:
            raise NoData(self.name, "empty chain")
        df = pd.DataFrame(
            {
                "contract_symbol": raw["contractSymbol"], "expiry": raw["expiry"], "strike": raw["strike"], "right": raw["right"],
                "bid": raw.get("bid"), "ask": raw.get("ask"), "last": raw.get("lastPrice"), "last_ts": raw.get("lastTradeDate"),
                "volume": raw.get("volume"), "open_interest": raw.get("openInterest"), "iv": raw.get("impliedVolatility"),
            }
        )
        df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
        df.loc[df["iv"] <= 1e-4, "iv"] = np.nan
        df["iv_source"] = "yahoo"
        df["greeks_source"] = None          # computed downstream
        df = finish_chain(df, price, None)
        return Payload(df, f"yfinance.Ticker({symbol}).option_chain(*)", as_of=datetime.now(timezone.utc), row_count=len(df),
                       flags=["DEGRADED"], meta={"underlying_price": price})

    # ------------------------------------------------------------------ fundamentals fallback / profile
    async def statements(self, symbol: str, **_: Any) -> Payload:
        def _f():
            t = _tk(symbol)
            out = {}
            for k, attr in (("income_annual", "income_stmt"), ("income_quarterly", "quarterly_income_stmt"),
                            ("balance_annual", "balance_sheet"), ("balance_quarterly", "quarterly_balance_sheet"),
                            ("cashflow_annual", "cashflow"), ("cashflow_quarterly", "quarterly_cashflow")):
                try:
                    v = getattr(t, attr)
                    out[k] = v if isinstance(v, pd.DataFrame) else pd.DataFrame()
                except Exception:
                    out[k] = pd.DataFrame()
            return out
        d = await asyncio.to_thread(_f)
        n = sum(len(v) for v in d.values())
        if n == 0:
            raise NoData(self.name, "no statements")
        return Payload(d, f"yfinance.Ticker({symbol}).income_stmt/balance_sheet/cashflow", row_count=n, flags=["DEGRADED"],
                       latency=Latency.FILING)

    async def profile(self, symbol: str, **_: Any) -> Payload:
        info = await asyncio.to_thread(lambda: dict(_tk(symbol).info or {}))
        if not info or not info.get("symbol"):
            raise NoData(self.name, "no info")
        keys = [
            "longName", "shortName", "sector", "industry", "industryKey", "sectorKey", "country", "website", "longBusinessSummary",
            "fullTimeEmployees", "exchange", "quoteType", "currency", "marketCap", "enterpriseValue", "sharesOutstanding",
            "floatShares", "impliedSharesOutstanding", "beta", "trailingPE", "forwardPE", "priceToBook", "enterpriseToRevenue",
            "enterpriseToEbitda", "trailingEps", "forwardEps", "pegRatio", "dividendYield", "dividendRate", "payoutRatio",
            "exDividendDate", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
            "averageVolume", "averageVolume10days", "regularMarketVolume", "heldPercentInsiders", "heldPercentInstitutions",
            "sharesShort", "sharesShortPriorMonth", "shortRatio", "shortPercentOfFloat", "dateShortInterest",
            "targetMeanPrice", "targetMedianPrice", "targetHighPrice", "targetLowPrice", "numberOfAnalystOpinions",
            "recommendationMean", "recommendationKey", "earningsGrowth", "revenueGrowth", "grossMargins", "operatingMargins",
            "profitMargins", "ebitdaMargins", "returnOnEquity", "returnOnAssets", "debtToEquity", "currentRatio", "quickRatio",
            "totalCash", "totalDebt", "freeCashflow", "operatingCashflow", "totalRevenue", "ebitda", "bookValue",
            "lastFiscalYearEnd", "nextFiscalYearEnd", "mostRecentQuarter", "auditRisk", "boardRisk", "compensationRisk",
            "shareHolderRightsRisk", "overallRisk", "companyOfficers",
        ]
        out = {k: info.get(k) for k in keys if k in info}
        if "companyOfficers" in out and isinstance(out["companyOfficers"], list):
            out["companyOfficers"] = [{k: o.get(k) for k in ("name", "title", "age", "totalPay")} for o in out["companyOfficers"][:8]]
        return Payload(out, f"yfinance.Ticker({symbol}).info", raw=info, as_of=datetime.now(timezone.utc))

    # ------------------------------------------------------------------ estimates / analysts / holders
    async def earnings_dates(self, symbol: str, **_: Any) -> Payload:
        def _f():
            t = _tk(symbol)
            ed = t.earnings_dates
            cal = t.calendar or {}
            return ed, cal
        ed, cal = await asyncio.to_thread(_f)
        if ed is None or ed.empty:
            raise NoData(self.name, "no earnings dates")
        df = ed.reset_index().rename(columns={"Earnings Date": "ts", "EPS Estimate": "eps_estimate", "Reported EPS": "eps_reported",
                                              "Surprise(%)": "surprise_pct"})
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts"]).sort_values("ts", ascending=False)
        meta = {k: (v.isoformat() if hasattr(v, "isoformat") else (
            [x.isoformat() if hasattr(x, "isoformat") else x for x in v] if isinstance(v, list) else v)) for k, v in cal.items()}
        return Payload(df, f"yfinance.Ticker({symbol}).earnings_dates", row_count=len(df), meta=meta, latency=Latency.EOD)

    async def analyst_recs(self, symbol: str, **_: Any) -> Payload:
        def _f():
            t = _tk(symbol)
            return t.recommendations, t.upgrades_downgrades
        trend, actions = await asyncio.to_thread(_f)
        if (trend is None or trend.empty) and (actions is None or actions.empty):
            raise NoData(self.name, "no recommendations")
        t = trend.copy() if trend is not None else pd.DataFrame()
        a = actions.reset_index() if actions is not None and not actions.empty else pd.DataFrame()
        if not a.empty:
            a = a.rename(columns={"GradeDate": "date", "Firm": "firm", "ToGrade": "to_grade", "FromGrade": "from_grade", "Action": "action"})
            a["date"] = pd.to_datetime(a["date"], errors="coerce").dt.date
        return Payload({"trend": t, "actions": a}, f"yfinance.Ticker({symbol}).recommendations", row_count=len(t) + len(a), latency=Latency.EOD)

    async def analyst_targets(self, symbol: str, **_: Any) -> Payload:
        d = await asyncio.to_thread(lambda: dict(_tk(symbol).analyst_price_targets or {}))
        if not d:
            raise NoData(self.name, "no targets")
        return Payload(d, f"yfinance.Ticker({symbol}).analyst_price_targets", latency=Latency.EOD)

    async def analyst_estimates(self, symbol: str, **_: Any) -> Payload:
        """EPS / revenue estimates for current+next quarter/year, EPS revisions (last 7/30 days) and EPS trend (now vs 7/30/60/90d ago)."""
        def _f():
            t = _tk(symbol)
            out = {}
            for k in ("earnings_estimate", "revenue_estimate", "eps_trend", "eps_revisions", "growth_estimates"):
                try:
                    v = getattr(t, k)
                    out[k] = v if isinstance(v, pd.DataFrame) else pd.DataFrame()
                except Exception:
                    out[k] = pd.DataFrame()
            return out
        d = await asyncio.to_thread(_f)
        if all(v.empty for v in d.values()):
            raise NoData(self.name, "no estimates")
        return Payload(d, f"yfinance.Ticker({symbol}).eps_trend/eps_revisions/earnings_estimate", row_count=sum(len(v) for v in d.values()), latency=Latency.EOD)

    async def insider_txns(self, symbol: str, **_: Any) -> Payload:
        df = await asyncio.to_thread(lambda: _tk(symbol).insider_transactions)
        if df is None or df.empty:
            raise NoData(self.name, "no insider transactions")
        df = df.rename(columns={"Shares": "shares", "Value": "value", "Text": "text", "Insider": "insider", "Position": "title",
                                "Transaction": "transaction", "Start Date": "date", "Ownership": "ownership", "URL": "url"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        if "text" in df.columns:
            df["acq_disp"] = np.where(df["text"].str.contains("Sale", case=False, na=False), "D",
                                      np.where(df["text"].str.contains("Purchase|Buy", case=False, na=False), "A", None))
        return Payload(df, f"yfinance.Ticker({symbol}).insider_transactions", row_count=len(df), latency=Latency.FILING)

    async def institutional_holders(self, symbol: str, **_: Any) -> Payload:
        def _f():
            t = _tk(symbol)
            return t.institutional_holders, t.major_holders
        inst, major = await asyncio.to_thread(_f)
        if inst is None or inst.empty:
            raise NoData(self.name, "no holders")
        inst = inst.rename(columns={"Date Reported": "reported", "Holder": "holder", "pctHeld": "pct_held", "Shares": "shares",
                                    "Value": "value", "pctChange": "pct_change"})
        inst["reported"] = pd.to_datetime(inst["reported"], errors="coerce").dt.date
        mj = {}
        if major is not None and not major.empty:
            try:
                mj = {str(k): float(v) for k, v in major.iloc[:, 0].items()}
            except Exception:
                mj = {}
        return Payload({"institutional": inst, "major": mj}, f"yfinance.Ticker({symbol}).institutional_holders", row_count=len(inst),
                       latency=Latency.FILING)

    async def short_interest(self, symbol: str, **_: Any) -> Payload:
        info = await asyncio.to_thread(lambda: dict(_tk(symbol).info or {}))
        if not info.get("sharesShort"):
            raise NoData(self.name, "no short fields")
        d = {
            "symbol": symbol.upper(), "shares_short": info.get("sharesShort"), "shares_short_prior": info.get("sharesShortPriorMonth"),
            "days_to_cover": info.get("shortRatio"), "pct_of_float": info.get("shortPercentOfFloat"),
            "settlement_date": datetime.fromtimestamp(info["dateShortInterest"], tz=timezone.utc).date().isoformat() if info.get("dateShortInterest") else None,
            "float_shares": info.get("floatShares"), "shares_outstanding": info.get("sharesOutstanding"),
        }
        return Payload(d, f"yfinance.Ticker({symbol}).info[sharesShort]", latency=Latency.EOD)

    async def news(self, symbol: str, **_: Any) -> Payload:
        items = await asyncio.to_thread(lambda: list(_tk(symbol).news or []))
        if not items:
            raise NoData(self.name, "no news")
        rows = []
        for it in items:
            c = it.get("content", it)
            rows.append(
                {
                    "id": it.get("id") or c.get("id"), "title": c.get("title"), "publisher": (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher"),
                    "url": (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link"),
                    "published": c.get("pubDate") or c.get("providerPublishTime"), "summary": c.get("summary"), "source": "yahoo",
                }
            )
        df = pd.DataFrame(rows)
        df["published"] = pd.to_datetime(df["published"], utc=True, errors="coerce")
        return Payload(df, f"yfinance.Ticker({symbol}).news", row_count=len(df), latency=Latency.NEAR_REALTIME)

    async def dividends(self, symbol: str, **_: Any) -> Payload:
        s = await asyncio.to_thread(lambda: _tk(symbol).dividends)
        if s is None or s.empty:
            raise NoData(self.name, "no dividends")
        df = s.reset_index()
        df.columns = ["ts", "dividend"]
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return Payload(df, f"yfinance.Ticker({symbol}).dividends", row_count=len(df), latency=Latency.EOD)

    async def splits(self, symbol: str, **_: Any) -> Payload:
        s = await asyncio.to_thread(lambda: _tk(symbol).splits)
        if s is None or s.empty:
            raise NoData(self.name, "no splits")
        df = s.reset_index()
        df.columns = ["ts", "ratio"]
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return Payload(df, f"yfinance.Ticker({symbol}).splits", row_count=len(df), latency=Latency.EOD)

    async def vix_history(self, **_: Any) -> Payload:
        p = await self.ohlcv("^VIX", interval="1d", period="max")
        p.data = p.data.rename(columns={"close": "close"})
        return p


def _safe(v: Any) -> Any:
    try:
        if v is None:
            return None
        f = float(v)
        return None if np.isnan(f) else f
    except Exception:
        return v


PROVIDER = Yahoo()

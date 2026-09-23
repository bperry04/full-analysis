"""Interactive Brokers via ib_async against IB Gateway / TWS.

Runs on a DEDICATED THREAD with its own asyncio loop — ib_async must never share the FastAPI loop.
Serves: real-time (or delayed) quotes, historical bars at any interval, option greeks overlay for NTM contracts,
underlying-level historical IV and HV daily bars (years of free IV history), tick-by-tick trades/quotes, L2 depth.

Live market data needs the account's market-data subscriptions; without them IB returns 15-min delayed data,
which we detect and stamp as DELAYED_15.
"""
from __future__ import annotations

import asyncio
import logging
import math
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from fa.core.errors import NoData, ProviderError
from fa.core.settings import get_settings
from fa.core.types import Latency, Tier
from fa.providers._util import finish_chain
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

log = logging.getLogger(__name__)

BAR_SIZE = {"1m": "1 min", "2m": "2 mins", "5m": "5 mins", "15m": "15 mins", "30m": "30 mins", "60m": "1 hour", "1h": "1 hour",
            "1d": "1 day", "1wk": "1 week", "1mo": "1 month"}
DEFAULT_DURATION = {"1m": "5 D", "2m": "10 D", "5m": "30 D", "15m": "60 D", "30m": "90 D", "60m": "1 Y", "1h": "1 Y",
                    "1d": "5 Y", "1wk": "10 Y", "1mo": "20 Y"}


class _Session:
    """Owns the ib_async IB object on a background thread."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.ib = None
        self._lock = threading.Lock()
        self.last_error = ""
        self.market_data_type = 1        # 1 realtime, 3 delayed
        self._last_probe = 0.0
        self._probe_ok = False

    # ---- thread / loop
    def _ensure_thread(self) -> None:
        with self._lock:
            if self.thread and self.thread.is_alive():
                return
            self.loop = asyncio.new_event_loop()

            def run():
                asyncio.set_event_loop(self.loop)
                self.loop.run_forever()

            self.thread = threading.Thread(target=run, name="ibkr-loop", daemon=True)
            self.thread.start()

    async def call(self, coro_factory, timeout: float = 60.0):
        """Run a coroutine on the IB thread's loop and await its result from any loop."""
        self._ensure_thread()
        assert self.loop is not None
        fut = asyncio.run_coroutine_threadsafe(coro_factory(), self.loop)
        return await asyncio.wait_for(asyncio.wrap_future(fut), timeout=timeout)

    # ---- connection
    def port_open(self) -> bool:
        s = get_settings()
        now = time.time()
        if now - self._last_probe < 15:
            return self._probe_ok
        self._last_probe = now
        try:
            with socket.create_connection((s.ib_host, s.ib_port), timeout=0.5):
                self._probe_ok = True
        except OSError:
            self._probe_ok = False
        return self._probe_ok

    async def _connect(self):
        from ib_async import IB
        s = get_settings()
        if self.ib is not None and self.ib.isConnected():
            return self.ib
        ib = IB()
        try:
            await ib.connectAsync(s.ib_host, s.ib_port, clientId=s.ib_client_id, timeout=s.ib_connect_timeout_s, readonly=True)
        except Exception as e:
            self.last_error = str(e)
            raise ProviderError("ibkr", f"connect failed: {e}") from e
        ib.reqMarketDataType(self.market_data_type)
        self.ib = ib
        return ib

    def connected(self) -> bool:
        return self.ib is not None and self.ib.isConnected()


SESSION = _Session()


def _stock(symbol: str):
    from ib_async import Stock, Index
    s = symbol.upper()
    if s.startswith("^"):
        return Index(s[1:], "CBOE", "USD")
    return Stock(s, "SMART", "USD")


class Ibkr(Provider):
    name = "ibkr"
    tier = Tier.A
    latency = Latency.REALTIME
    license_note = "IBKR API — subject to the account's market-data entitlements"

    def capabilities(self):
        return {
            N.QUOTE: self.quote,
            N.OHLCV: self.ohlcv,
            N.OPTION_CHAIN: self.chain_overlay,
            N.IV_HISTORY: self.iv_history,
            N.HV_HISTORY: self.hv_history,
            N.TICKS: self.ticks,
            N.DEPTH: self.depth,
        }

    def condition_context(self) -> dict[str, Any]:
        return {"ibkr_connected": SESSION.connected() or SESSION.port_open()}

    async def healthy(self) -> bool:
        return SESSION.port_open()

    # ------------------------------------------------------------------ quote
    async def quote(self, symbol: str, **_: Any) -> Payload:
        async def _run():
            ib = await SESSION._connect()
            c = _stock(symbol)
            await ib.qualifyContractsAsync(c)

            def got(t) -> bool:
                return (_f(t.last) is not None) or (_f(t.bid) is not None and _f(t.ask) is not None)

            async def request(mdt: int, wait_s: float):
                ib.reqMarketDataType(mdt)
                t = ib.reqMktData(c, "", snapshot=False, regulatorySnapshot=False)
                for _ in range(int(wait_s / 0.1)):
                    await asyncio.sleep(0.1)
                    if got(t):
                        break
                return t

            # delayed data (no subscription) takes a few seconds to start streaming; real-time is near-instant
            t = await request(SESSION.market_data_type, 3.0 if SESSION.market_data_type == 1 else 8.0)
            if not got(t) and SESSION.market_data_type == 1:
                ib.cancelMktData(c)
                SESSION.market_data_type = 3              # remember: this account has no real-time entitlement
                t = await request(3, 8.0)
            mdt = getattr(t, "marketDataType", SESSION.market_data_type) or SESSION.market_data_type
            out = {
                "symbol": symbol.upper(), "price": _f(t.last) or _f(t.close), "bid": _f(t.bid), "ask": _f(t.ask),
                "bid_size": _f(t.bidSize), "ask_size": _f(t.askSize), "last_size": _f(t.lastSize), "open": _f(t.open),
                "high": _f(t.high), "low": _f(t.low), "prev_close": _f(t.close),
                "volume": _f(t.volume) if mdt == 1 else None,      # IB's delayed volume field is not reliable
                "halted": _f(t.halted), "market_data_type": mdt,
            }
            ib.cancelMktData(c)
            return out
        q = await SESSION.call(_run, timeout=25)
        if not q.get("price"):
            raise NoData(self.name, f"no ticks for {symbol}")
        delayed = (q.get("market_data_type") or 1) >= 3
        if delayed and q.get("bid") is None:
            # without an entitlement IB's delayed stock quote is last/close only; CBOE's delayed quote carries bid/ask/sizes — let it answer
            raise NoData(self.name, "IBKR delayed quote has no bid/ask (no market-data subscription) — deferring to CBOE")
        if q.get("prev_close") and q.get("price"):
            q["change"] = q["price"] - q["prev_close"]
            q["change_pct"] = q["change"] / q["prev_close"] * 100
        return Payload(q, f"ibkr.reqMktData({symbol})", as_of=datetime.now(timezone.utc),
                       latency=Latency.DELAYED_15 if delayed else Latency.REALTIME)

    # ------------------------------------------------------------------ bars
    async def ohlcv(self, symbol: str, interval: str = "1d", period: str | None = None, duration: str | None = None, **_: Any) -> Payload:
        bar = BAR_SIZE.get(interval)
        if not bar:
            raise NoData(self.name, f"unsupported interval {interval}")
        dur = duration or DEFAULT_DURATION[interval]

        async def _run():
            ib = await SESSION._connect()
            c = _stock(symbol)
            await ib.qualifyContractsAsync(c)
            bars = await ib.reqHistoricalDataAsync(c, endDateTime="", durationStr=dur, barSizeSetting=bar, whatToShow="TRADES",
                                                   useRTH=True, formatDate=2)
            return [(b.date, b.open, b.high, b.low, b.close, b.volume) for b in bars]
        rows = await SESSION.call(_run, timeout=90)
        if not rows:
            raise NoData(self.name, "no bars")
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df["adj_close"] = df["close"]
        df["symbol"], df["interval"] = symbol.upper(), interval
        df = df[["ts", "open", "high", "low", "close", "adj_close", "volume", "symbol", "interval"]]
        return Payload(df, f"ibkr.reqHistoricalData({symbol},{bar},{dur})", row_count=len(df), as_of=df["ts"].max().to_pydatetime(),
                       latency=Latency.EOD if interval in ("1d", "1wk", "1mo") else Latency.REALTIME)

    # ------------------------------------------------------------------ option greeks overlay
    async def chain_overlay(self, symbol: str, base: pd.DataFrame | None = None, max_contracts: int = 250, **_: Any) -> Payload:
        """Refresh NTM contracts of a base chain with IBKR quotes + model greeks. Keyed on contract_symbol."""
        if base is None or base.empty:
            raise NoData(self.name, "overlay requires a base chain")
        sel = base[(base["moneyness"].abs() <= 0.15) & (base["dte"] <= 90) & (base["dte"] >= 0)].copy()
        sel = sel.sort_values("open_interest", ascending=False).head(max_contracts)
        if sel.empty:
            raise NoData(self.name, "no NTM contracts to overlay")

        async def _run():
            from ib_async import Option
            ib = await SESSION._connect()
            und = _stock(symbol)
            await ib.qualifyContractsAsync(und)
            opts = [Option(symbol.upper(), r.expiry.strftime("%Y%m%d"), float(r.strike), r.right, "SMART", tradingClass=symbol.upper())
                    for r in sel.itertuples()]
            qualified = []
            for i in range(0, len(opts), 50):
                q = await ib.qualifyContractsAsync(*opts[i:i + 50])
                qualified.extend([c for c in q if c.conId])

            def collect(tickers):
                rows, und_price = [], None
                for c, t in zip(qualified, tickers):
                    g = t.modelGreeks or t.lastGreeks or t.bidGreeks
                    if g and g.undPrice:
                        und_price = g.undPrice
                    rows.append(
                        {"contract_symbol": c.localSymbol.replace(" ", ""), "bid": _f(t.bid), "ask": _f(t.ask), "bid_size": _f(t.bidSize),
                         "ask_size": _f(t.askSize), "last": _f(t.last), "iv": _f(g.impliedVol) if g else None,
                         "delta": _f(g.delta) if g else None, "gamma": _f(g.gamma) if g else None, "theta": _f(g.theta) if g else None,
                         "vega": _f(g.vega) if g else None, "underlying_price": _f(g.undPrice) if g else None,
                         "market_data_type": getattr(t, "marketDataType", SESSION.market_data_type)}
                    )
                return rows, und_price

            ib.reqMarketDataType(SESSION.market_data_type)
            rows, und_price = collect(await ib.reqTickersAsync(*qualified))
            filled = sum(1 for r in rows if r["bid"] is not None or r["iv"] is not None)
            if filled < max(3, len(rows) // 5) and SESSION.market_data_type == 1:
                # no real-time options subscription (IB error 354) → use IBKR's free delayed data for this and later calls
                SESSION.market_data_type = 3
                ib.reqMarketDataType(3)
                rows, und_price = collect(await ib.reqTickersAsync(*qualified))
            return rows, und_price
        rows, und_price = await SESSION.call(_run, timeout=90)
        rows = [r for r in rows if r["bid"] is not None or r["iv"] is not None or r["delta"] is not None]
        if not rows:
            raise NoData(self.name, "no option data from IBKR (no options market-data entitlement, delayed included)")
        df = pd.DataFrame(rows)
        df["iv_source"] = "ibkr"
        df["greeks_source"] = "ibkr"
        delayed = (df["market_data_type"].max() or 1) >= 3
        return Payload(df.drop(columns=["market_data_type"]), f"ibkr.reqTickers({len(rows)} option contracts)", row_count=len(df),
                       as_of=datetime.now(timezone.utc), latency=Latency.DELAYED_15 if delayed else Latency.REALTIME,
                       meta={"underlying_price": und_price})

    # ------------------------------------------------------------------ IV / HV history
    async def _vol_history(self, symbol: str, what: str, days: int) -> pd.DataFrame:
        dur = f"{min(max(days, 30), 730)} D" if days <= 365 else f"{math.ceil(days / 365)} Y"

        async def _run():
            ib = await SESSION._connect()
            c = _stock(symbol)
            await ib.qualifyContractsAsync(c)
            bars = await ib.reqHistoricalDataAsync(c, endDateTime="", durationStr=dur, barSizeSetting="1 day", whatToShow=what,
                                                   useRTH=True, formatDate=2)
            return [(b.date, b.open, b.high, b.low, b.close) for b in bars]
        rows = await SESSION.call(_run, timeout=90)
        if not rows:
            raise NoData(self.name, f"no {what} bars")
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"])
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    async def iv_history(self, symbol: str, days: int = 730, **_: Any) -> Payload:
        df = await self._vol_history(symbol, "OPTION_IMPLIED_VOLATILITY", days)
        df = df.rename(columns={"close": "iv"})[["date", "iv"]]
        return Payload(df, f"ibkr.reqHistoricalData({symbol},OPTION_IMPLIED_VOLATILITY)", row_count=len(df), latency=Latency.EOD)

    async def hv_history(self, symbol: str, days: int = 730, **_: Any) -> Payload:
        df = await self._vol_history(symbol, "HISTORICAL_VOLATILITY", days)
        df = df.rename(columns={"close": "hv"})[["date", "hv"]]
        return Payload(df, f"ibkr.reqHistoricalData({symbol},HISTORICAL_VOLATILITY)", row_count=len(df), latency=Latency.EOD)

    # ------------------------------------------------------------------ ticks / depth
    async def ticks(self, symbol: str, n: int = 1000, **_: Any) -> Payload:
        async def _run():
            ib = await SESSION._connect()
            c = _stock(symbol)
            await ib.qualifyContractsAsync(c)
            trades = await ib.reqHistoricalTicksAsync(c, "", datetime.now(timezone.utc), n, "TRADES", useRth=True)
            quotes = await ib.reqHistoricalTicksAsync(c, "", datetime.now(timezone.utc), n, "BID_ASK", useRth=True)
            tr = [(t.time, t.price, t.size, t.exchange, getattr(t.tickAttribLast, "pastLimit", None),
                   getattr(t.tickAttribLast, "unreported", None), t.specialConditions) for t in trades]
            qu = [(q.time, q.priceBid, q.priceAsk, q.sizeBid, q.sizeAsk) for q in quotes]
            return tr, qu
        tr, qu = await SESSION.call(_run, timeout=60)
        if not tr:
            raise NoData(self.name, "no ticks")
        trades = pd.DataFrame(tr, columns=["ts", "price", "size", "exchange", "past_limit", "unreported", "conditions"])
        quotes = pd.DataFrame(qu, columns=["ts", "bid", "ask", "bid_size", "ask_size"])
        trades["ts"] = pd.to_datetime(trades["ts"], utc=True)
        quotes["ts"] = pd.to_datetime(quotes["ts"], utc=True)
        return Payload({"trades": trades, "quotes": quotes}, f"ibkr.reqHistoricalTicks({symbol},{n})", row_count=len(trades),
                       as_of=trades["ts"].max().to_pydatetime())

    async def depth(self, symbol: str, rows: int = 10, seconds: float = 3.0, **_: Any) -> Payload:
        async def _run():
            ib = await SESSION._connect()
            c = _stock(symbol)
            await ib.qualifyContractsAsync(c)
            t = ib.reqMktDepth(c, numRows=rows, isSmartDepth=True)
            await asyncio.sleep(seconds)
            bids = [(d.price, d.size, d.marketMaker) for d in t.domBids]
            asks = [(d.price, d.size, d.marketMaker) for d in t.domAsks]
            ib.cancelMktDepth(c, isSmartDepth=True)
            return bids, asks
        bids, asks = await SESSION.call(_run, timeout=20)
        if not bids and not asks:
            raise NoData(self.name, "no depth (entitlement?)")
        return Payload({"bids": pd.DataFrame(bids, columns=["price", "size", "mm"]), "asks": pd.DataFrame(asks, columns=["price", "size", "mm"])},
                       f"ibkr.reqMktDepth({symbol})", as_of=datetime.now(timezone.utc))


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        x = float(v)
        return None if (np.isnan(x) or x < 0 and False) else x
    except Exception:
        return None


PROVIDER = Ibkr()

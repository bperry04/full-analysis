"""Schwab Trader API (thinkorswim account): real-time quotes and option chains with greeks. Free developer API.

Requires a registered app (FA_SCHWAB_APP_KEY / SECRET) and a one-time browser login (`python -m fa schwab-login`),
after which the refresh token (valid 7 days) is stored at <data_root>/schwab_tokens.json.
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.errors import NoData, ProviderError
from fa.core.settings import get_settings
from fa.core.types import Latency, Tier
from fa.providers._util import finish_chain
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

AUTH = "https://api.schwabapi.com/v1/oauth/token"
MD = "https://api.schwabapi.com/marketdata/v1"


def _token_path():
    return get_settings().data_root / "schwab_tokens.json"


class Schwab(Provider):
    name = "schwab"
    tier = Tier.A
    latency = Latency.REALTIME
    license_note = "Schwab Trader API (personal use)"

    def __init__(self) -> None:
        self._tokens: dict | None = None

    def capabilities(self):
        return {N.QUOTE: self.quote, N.OPTION_CHAIN: self.chain}

    def _load(self) -> dict | None:
        p = _token_path()
        if self._tokens is None and p.exists():
            try:
                self._tokens = json.loads(p.read_text())
            except Exception:
                self._tokens = None
        return self._tokens

    def condition_context(self) -> dict[str, Any]:
        s = get_settings()
        return {"schwab_authed": bool(s.schwab_app_key and self._load())}

    async def _access_token(self) -> str:
        s = get_settings()
        t = self._load()
        if not t:
            raise ProviderError(self.name, "not authenticated — run `python -m fa schwab-login`")
        if time.time() < t.get("expires_at", 0) - 60:
            return t["access_token"]
        basic = base64.b64encode(f"{s.schwab_app_key}:{s.schwab_app_secret}".encode()).decode()
        r = await http.client().post(AUTH, data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"]},
                                     headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
        if r.status_code != 200:
            raise ProviderError(self.name, f"token refresh failed {r.status_code}: {r.text[:200]}")
        j = r.json()
        t.update({"access_token": j["access_token"], "expires_at": time.time() + int(j.get("expires_in", 1800))})
        if j.get("refresh_token"):
            t["refresh_token"] = j["refresh_token"]
        _token_path().write_text(json.dumps(t))
        self._tokens = t
        return t["access_token"]

    async def _get(self, path: str, **params: Any) -> Any:
        tok = await self._access_token()
        return await http.get_json(self.name, f"{MD}{path}", params=params, headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"}, timeout=30)

    async def quote(self, symbol: str, **_: Any) -> Payload:
        j = await self._get("/quotes", symbols=symbol.upper(), fields="quote,reference")
        d = (j or {}).get(symbol.upper()) or {}
        q = d.get("quote") or {}
        if not q.get("lastPrice"):
            raise NoData(self.name, "no quote")
        out = {"symbol": symbol.upper(), "price": q.get("lastPrice"), "bid": q.get("bidPrice"), "ask": q.get("askPrice"),
               "bid_size": q.get("bidSize"), "ask_size": q.get("askSize"), "open": q.get("openPrice"), "high": q.get("highPrice"),
               "low": q.get("lowPrice"), "prev_close": q.get("closePrice"), "volume": q.get("totalVolume"), "change": q.get("netChange"),
               "change_pct": q.get("netPercentChange"), "year_high": q.get("52WeekHigh"), "year_low": q.get("52WeekLow")}
        delayed = bool(d.get("delayed") or (d.get("reference") or {}).get("isDelayed", False))
        return Payload(out, f"{MD}/quotes?symbols={symbol}", raw=j, as_of=datetime.now(timezone.utc),
                       latency=Latency.DELAYED_15 if delayed else Latency.REALTIME)

    async def chain(self, symbol: str, **_: Any) -> Payload:
        j = await self._get("/chains", symbol=symbol.upper(), contractType="ALL", includeUnderlyingQuote="true", strategy="SINGLE")
        if not j or j.get("status") == "FAILED":
            raise NoData(self.name, "no chain")
        rows = []
        for side, key in (("C", "callExpDateMap"), ("P", "putExpDateMap")):
            for exp_key, strikes in (j.get(key) or {}).items():
                exp = exp_key.split(":")[0]
                for strike, contracts in strikes.items():
                    for c in contracts:
                        rows.append(
                            {"contract_symbol": (c.get("symbol") or "").replace(" ", ""), "expiry": exp, "strike": float(strike), "right": side,
                             "bid": c.get("bid"), "ask": c.get("ask"), "bid_size": c.get("bidSize"), "ask_size": c.get("askSize"),
                             "last": c.get("last"), "last_ts": c.get("tradeTimeInLong"), "volume": c.get("totalVolume"),
                             "open_interest": c.get("openInterest"), "iv": (c.get("volatility") or 0) / 100.0, "delta": c.get("delta"),
                             "gamma": c.get("gamma"), "theta": c.get("theta"), "vega": c.get("vega"), "rho": c.get("rho"),
                             "theo": c.get("theoreticalOptionValue")}
                        )
        if not rows:
            raise NoData(self.name, "empty chain")
        df = pd.DataFrame(rows)
        df.loc[df["iv"] <= 1e-4, "iv"] = None
        df["iv_source"], df["greeks_source"] = "schwab", "schwab"
        und = (j.get("underlying") or {}).get("last") or j.get("underlyingPrice")
        df = finish_chain(df, und, None)
        delayed = bool(j.get("isDelayed"))
        return Payload(df, f"{MD}/chains?symbol={symbol}", raw=j, row_count=len(df), as_of=datetime.now(timezone.utc),
                       latency=Latency.DELAYED_15 if delayed else Latency.REALTIME, meta={"underlying_price": und})


PROVIDER = Schwab()

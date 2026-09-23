"""StockTwits public symbol stream (no key): messages, user-tagged Bullish/Bearish sentiment."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.errors import NoData
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

BASE = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"


class StockTwits(Provider):
    name = "stocktwits"
    tier = Tier.C
    latency = Latency.NEAR_REALTIME
    license_note = "StockTwits public API"

    def capabilities(self):
        return {N.SOCIAL_STOCKTWITS: self.stream}

    async def stream(self, symbol: str, pages: int = 2, **_: Any) -> Payload:
        url = BASE.format(sym=symbol.upper())
        rows = []
        max_id = None
        for _ in range(pages):
            params = {"limit": 30}
            if max_id:
                params["max"] = max_id
            j = await http.get_json(self.name, url, params=params, timeout=20)
            msgs = j.get("messages") or []
            if not msgs:
                break
            for m in msgs:
                ent = (m.get("entities") or {}).get("sentiment") or {}
                u = m.get("user") or {}
                rows.append(
                    {"id": m.get("id"), "created": m.get("created_at"), "body": m.get("body"), "user": u.get("username"),
                     "followers": u.get("followers"), "sentiment": ent.get("basic"), "likes": (m.get("likes") or {}).get("total", 0),
                     "source": "stocktwits"}
                )
            max_id = min(m["id"] for m in msgs) - 1
        if not rows:
            raise NoData(self.name, f"no messages for {symbol}")
        df = pd.DataFrame(rows)
        df["created"] = pd.to_datetime(df["created"], utc=True, errors="coerce")
        sym_meta = (j.get("symbol") or {}) if isinstance(j, dict) else {}
        return Payload(df, url, row_count=len(df), as_of=datetime.now(timezone.utc),
                       meta={"watchlist_count": sym_meta.get("watchlist_count"), "title": sym_meta.get("title")})


PROVIDER = StockTwits()

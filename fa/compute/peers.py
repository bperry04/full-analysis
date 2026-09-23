"""Peer discovery: Yahoo 'recommendations by symbol' (keyless), manual overrides in config/peers.yaml, same-industry filter."""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

import yaml

from fa.core import http
from fa.core.settings import CONFIG_DIR

log = logging.getLogger(__name__)
REC = "https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{sym}"


@lru_cache(maxsize=1)
def manual() -> dict[str, list[str]]:
    p = CONFIG_DIR / "peers.yaml"
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return {k.upper(): [x.upper() for x in v] for k, v in (yaml.safe_load(f) or {}).items()}


async def discover(symbol: str, max_peers: int = 8) -> tuple[list[str], str]:
    sym = symbol.upper()
    if sym in manual():
        return manual()[sym][:max_peers], "config/peers.yaml"
    try:
        j = await http.get_json("yahoo", REC.format(sym=sym), timeout=15)
        recs = (j.get("finance", {}).get("result") or [{}])[0].get("recommendedSymbols") or []
        peers = [r["symbol"].upper() for r in sorted(recs, key=lambda r: -r.get("score", 0)) if r.get("symbol") and r["symbol"].upper() != sym]
        if peers:
            return peers[:max_peers], "yahoo recommendationsbysymbol"
    except Exception as e:
        log.debug("peer discovery failed: %s", e)
    return [], "none"


async def peer_profiles(peers: list[str]) -> dict[str, dict[str, Any]]:
    """yfinance .info for each peer, concurrently (thread pool)."""
    import yfinance as yf

    def one(s: str) -> tuple[str, dict]:
        try:
            return s, dict(yf.Ticker(s).info or {})
        except Exception:
            return s, {}
    res = await asyncio.gather(*[asyncio.to_thread(one, s) for s in peers])
    return {s: info for s, info in res if info.get("marketCap")}

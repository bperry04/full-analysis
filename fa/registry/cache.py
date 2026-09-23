"""TTL cache in front of every provider call (diskcache at C:\\fadata\\cache), session-aware.

The cache is evictable; the raw archive (core/archive.py) is the permanent audit record.
"""
from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from typing import Any

import diskcache

from fa.core.clock import session_state
from fa.core.settings import get_settings
from fa.registry import needs as N

# (ttl during regular trading hours, ttl when closed) in seconds
TTL: dict[str, tuple[int, int]] = {
    N.QUOTE: (60, 900),
    N.OHLCV: (60, 3600),
    N.TICKS: (0, 0),
    N.DEPTH: (0, 0),
    N.OPTION_EXPIRATIONS: (3600, 6 * 3600),
    N.OPTION_CHAIN: (900, 3600),
    N.IV_HISTORY: (3600, 12 * 3600),
    N.HV_HISTORY: (3600, 12 * 3600),
    N.XBRL_FACTS: (12 * 3600, 12 * 3600),
    N.FILINGS: (3600, 3600),
    N.STATEMENTS_FALLBACK: (12 * 3600, 12 * 3600),
    N.SEGMENTS: (24 * 3600, 24 * 3600),
    N.COMPANY_PROFILE: (24 * 3600, 24 * 3600),
    N.TICKER_MAP: (7 * 24 * 3600, 7 * 24 * 3600),
    N.EARNINGS_DATES: (6 * 3600, 6 * 3600),
    N.ANALYST_RECS: (6 * 3600, 6 * 3600),
    N.ANALYST_TARGETS: (6 * 3600, 6 * 3600),
    N.ANALYST_ESTIMATES: (6 * 3600, 6 * 3600),
    N.INSIDER_TXNS: (6 * 3600, 6 * 3600),
    N.INSTITUTIONAL_HOLDERS: (24 * 3600, 24 * 3600),
    N.SHORT_INTEREST: (12 * 3600, 12 * 3600),
    N.SHORT_VOLUME: (6 * 3600, 6 * 3600),
    N.NEWS: (600, 1800),
    N.MACRO_NEWS: (600, 1800),
    N.SOCIAL_STOCKTWITS: (300, 1800),
    N.SOCIAL_REDDIT: (600, 1800),
    N.MACRO_SERIES: (12 * 3600, 12 * 3600),
    N.YIELD_CURVE: (6 * 3600, 12 * 3600),
    N.ECON_CALENDAR: (6 * 3600, 6 * 3600),
    N.EARNINGS_CALENDAR: (6 * 3600, 6 * 3600),
    N.DIVIDENDS: (24 * 3600, 24 * 3600),
    N.SPLITS: (24 * 3600, 24 * 3600),
    N.VIX_HISTORY: (3600, 12 * 3600),
    N.FOMC_CALENDAR: (24 * 3600, 24 * 3600),
}


def ttl_for(need: str, override: tuple[int | None, int | None] = (None, None)) -> int:
    rth, closed = TTL.get(need, (600, 3600))
    if override[0] is not None:
        rth = override[0]
    if override[1] is not None:
        closed = override[1]
    return rth if session_state() == "rth" else closed


def key_for(need: str, provider: str, params: dict[str, Any]) -> str:
    blob = json.dumps({"n": need, "p": provider, "a": params}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


@lru_cache(maxsize=1)
def _cache() -> diskcache.Cache:
    return diskcache.Cache(str(get_settings().cache_dir), size_limit=4 * 1024**3)


def get(key: str) -> tuple[Any, dict, float] | None:
    """Returns (data, meta, age_seconds) or None."""
    try:
        hit = _cache().get(key)
    except Exception:
        return None
    if hit is None:
        return None
    data, meta, stored_at = hit
    return data, meta, time.time() - stored_at


def put(key: str, data: Any, meta: dict, ttl_s: int) -> None:
    if ttl_s <= 0:
        return
    try:
        _cache().set(key, (data, meta, time.time()), expire=ttl_s)
    except Exception:
        pass


def invalidate_prefix_symbol(symbol: str) -> int:
    """Best-effort invalidation for a symbol (cache keys are hashed, so we tag entries)."""
    n = 0
    c = _cache()
    for k in list(c.iterkeys()):
        try:
            v = c.get(k)
            if v and isinstance(v[1], dict) and v[1].get("symbol") == symbol:
                c.delete(k)
                n += 1
        except Exception:
            pass
    return n


def stats() -> dict:
    c = _cache()
    return {"entries": len(c), "volume_bytes": c.volume(), "dir": str(get_settings().cache_dir)}

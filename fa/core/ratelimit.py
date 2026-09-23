"""Per-provider async token buckets. SEC's hard cap is 10 req/s; we run 8 to leave headroom."""
from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: int | None = None):
        self.rate = rate_per_s
        self.capacity = burst or max(1, int(rate_per_s))
        self.tokens = float(self.capacity)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


_BUCKETS: dict[str, TokenBucket] = {}

DEFAULT_RATES: dict[str, float] = {
    "sec_edgar": 8.0,
    "yahoo": 3.0,
    "cboe": 2.0,
    "nasdaq": 2.0,
    "finra": 2.0,
    "fred": 5.0,
    "treasury": 3.0,
    "rss": 4.0,
    "stocktwits": 1.0,
    "reddit": 1.0,
    "finnhub": 1.0,
    "ibkr": 40.0,
    "stooq": 2.0,
}


def bucket(provider: str) -> TokenBucket:
    b = _BUCKETS.get(provider)
    if b is None:
        b = _BUCKETS[provider] = TokenBucket(DEFAULT_RATES.get(provider, 2.0))
    return b

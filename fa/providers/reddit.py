"""Reddit via PRAW (free script app). Raw .json endpoints are 403 on this network, so the API is required."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fa.core.errors import NoData
from fa.core.settings import get_settings
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

SUBS = ["stocks", "investing", "wallstreetbets", "options", "StockMarket", "ValueInvesting"]


class Reddit(Provider):
    name = "reddit"
    tier = Tier.C
    latency = Latency.NEAR_REALTIME
    license_note = "Reddit API via PRAW"

    def capabilities(self):
        return {N.SOCIAL_REDDIT: self.search}

    def _client(self):
        import praw
        s = get_settings()
        if not s.reddit_client_id or not s.reddit_client_secret:
            raise NoData(self.name, "reddit credentials not set")
        return praw.Reddit(client_id=s.reddit_client_id, client_secret=s.reddit_client_secret, user_agent=s.reddit_user_agent,
                           check_for_async=False)

    async def search(self, symbol: str, name: str | None = None, limit: int = 40, **_: Any) -> Payload:
        def _f():
            r = self._client()
            q = f'"{symbol.upper()}"' + (f' OR "{name}"' if name else "")
            rows = []
            for sub in SUBS:
                try:
                    for p in r.subreddit(sub).search(q, sort="new", time_filter="month", limit=limit):
                        rows.append(
                            {"id": p.id, "created": datetime.fromtimestamp(p.created_utc, tz=timezone.utc), "subreddit": sub,
                             "title": p.title, "body": (p.selftext or "")[:600], "score": p.score, "comments": p.num_comments,
                             "upvote_ratio": p.upvote_ratio, "url": f"https://reddit.com{p.permalink}", "source": "reddit"}
                        )
                except Exception:
                    continue
            return rows
        rows = await asyncio.to_thread(_f)
        if not rows:
            raise NoData(self.name, f"no reddit posts for {symbol}")
        df = pd.DataFrame(rows).drop_duplicates("id").sort_values("created", ascending=False).reset_index(drop=True)
        return Payload(df, f"praw.search({symbol})", row_count=len(df), as_of=datetime.now(timezone.utc))


PROVIDER = Reddit()

"""RSS/Atom news: per-ticker (Google News, Yahoo, Seeking Alpha, SEC 8-K feed), macro (WSJ, CNBC, Fed), FOMC calendar."""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import feedparser
import pandas as pd

from fa.core import http
from fa.core.errors import NoData
from fa.core.settings import get_settings
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

MACRO_FEEDS = {
    "wsj_markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "wsj_economy": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
    "cnbc_top": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "cnbc_economy": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
    "cnbc_markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "fed_press": "https://www.federalreserve.gov/feeds/press_all.xml",
    "bls": "https://www.bls.gov/feed/bls_latest.rss",
    "prnewswire_fin": "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
}
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def _parse(text: str, source: str) -> list[dict]:
    feed = feedparser.parse(text)
    rows = []
    for e in feed.entries:
        pub = None
        for k in ("published_parsed", "updated_parsed"):
            if getattr(e, k, None):
                import time as _t
                pub = datetime.fromtimestamp(_t.mktime(getattr(e, k)), tz=timezone.utc)
                break
        link = getattr(e, "link", "") or ""
        title = re.sub(r"\s+", " ", getattr(e, "title", "") or "").strip()
        summary = re.sub(r"<[^>]+>", " ", getattr(e, "summary", "") or "")
        summary = re.sub(r"\s+", " ", summary).strip()[:600]
        pubname = None
        if hasattr(e, "source") and isinstance(e.source, dict):
            pubname = e.source.get("title")
        if not pubname and " - " in title and source == "google_news":
            title, pubname = title.rsplit(" - ", 1)
        rows.append(
            {"id": hashlib.sha1((link or title).encode()).hexdigest()[:16], "title": title, "url": link, "published": pub,
             "summary": summary, "publisher": pubname or source, "source": source}
        )
    return rows


class Rss(Provider):
    name = "rss"
    tier = Tier.B
    latency = Latency.NEAR_REALTIME
    license_note = "Public RSS feeds"

    def capabilities(self):
        return {N.NEWS: self.news, N.MACRO_NEWS: self.macro_news, N.FOMC_CALENDAR: self.fomc_calendar}

    async def _fetch(self, url: str, source: str, headers: dict | None = None) -> list[dict]:
        try:
            text = await http.get_text(self.name, url, headers=headers, timeout=25)
            return _parse(text, source)
        except Exception:
            return []

    async def news(self, symbol: str, name: str | None = None, cik: str | None = None, **_: Any) -> Payload:
        s = symbol.upper()
        q = f'"{name}" OR {s} stock' if name else f"{s} stock"
        feeds = [
            (f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en", "google_news", None),
            (f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={s}&region=US&lang=en-US", "yahoo_rss", None),
            (f"https://seekingalpha.com/api/sa/combined/{s}.xml", "seeking_alpha", None),
        ]
        if cik:
            feeds.append((f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=20&output=atom",
                          "sec_8k", {"User-Agent": get_settings().sec_user_agent}))
        results = await asyncio.gather(*[self._fetch(u, src, h) for u, src, h in feeds])
        rows = [r for rs in results for r in rs]
        if not rows:
            raise NoData(self.name, "no news items")
        df = pd.DataFrame(rows)
        df["published"] = pd.to_datetime(df["published"], utc=True, errors="coerce")
        df = df.drop_duplicates("id").sort_values("published", ascending=False, na_position="last").reset_index(drop=True)
        return Payload(df, feeds[0][0], row_count=len(df), as_of=datetime.now(timezone.utc))

    async def macro_news(self, **_: Any) -> Payload:
        results = await asyncio.gather(*[self._fetch(u, k) for k, u in MACRO_FEEDS.items()])
        rows = [r for rs in results for r in rs]
        if not rows:
            raise NoData(self.name, "no macro news")
        df = pd.DataFrame(rows)
        df["published"] = pd.to_datetime(df["published"], utc=True, errors="coerce")
        df = df.drop_duplicates("id").sort_values("published", ascending=False, na_position="last").reset_index(drop=True)
        return Payload(df, MACRO_FEEDS["wsj_markets"], row_count=len(df), as_of=datetime.now(timezone.utc))

    async def fomc_calendar(self, **_: Any) -> Payload:
        html = await http.get_text(self.name, FOMC_URL, timeout=30)
        rows = []
        year = None
        # panels are grouped by year: "<h4>2026 FOMC Meetings</h4>" then month/date pairs
        for m in re.finditer(r"(\d{4}) FOMC Meetings|fomc-meeting__month[^>]*>\s*(?:<strong>)?([A-Za-z/]+)(?:</strong>)?\s*<|fomc-meeting__date[^>]*>\s*([^<]+?)\s*<", html):
            if m.group(1):
                year = int(m.group(1))
                month = None
            elif m.group(2):
                month = m.group(2)
            elif m.group(3) and year and month:
                d = m.group(3).replace("*", "").strip()
                first_month = month.split("/")[0]
                day = re.match(r"(\d+)", d)
                if not day:
                    continue
                try:
                    start = datetime.strptime(f"{first_month[:3]} {day.group(1)} {year}", "%b %d %Y").date()
                except ValueError:
                    continue
                days = re.findall(r"\d+", d)
                end_day = int(days[-1]) if days else start.day
                end_month = month.split("/")[-1]
                try:
                    end = datetime.strptime(f"{end_month[:3]} {end_day} {year}", "%b %d %Y").date()
                except ValueError:
                    end = start
                rows.append({"start": start, "end": end, "label": f"FOMC {month} {d}", "press_conference": "*" in m.group(3)})
        if not rows:
            raise NoData(self.name, "could not parse FOMC calendar")
        df = pd.DataFrame(rows).drop_duplicates("start").sort_values("start").reset_index(drop=True)
        return Payload(df, FOMC_URL, raw=html, row_count=len(df), latency=Latency.RELEASE)


PROVIDER = Rss()

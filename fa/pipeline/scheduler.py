"""Scheduled jobs (APScheduler, inside the API process): the point-in-time history you cannot buy back.

  close_snapshot   16:20 ET weekdays  option chain + IV surface + EOD bars for every watchlist symbol
  short_volume     06:30 ET daily     yesterday's FINRA CNMS file (whole market)
  news_sweep       every 30 min       RSS for watchlist + macro feeds
  macro_sweep      07:00 ET daily     yield curve, VIX, key FRED series
  intraday_bars    every 2h RTH       5m/15m bars for the watchlist (so intraday history outlives Yahoo's window)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from fa.core.clock import ET, is_trading_day, previous_trading_day
from fa.core.provenance import Ledger
from fa.registry import needs as N
from fa.registry.router import get_router
from fa.store import duck, persist, repos

log = logging.getLogger(__name__)


def _watch() -> list[str]:
    try:
        return repos.watchlist()["symbol"].tolist()
    except Exception:
        return []


async def _fetch(need: str, led: Ledger, **params) -> None:
    try:
        res = await get_router().fetch(need, led, force_refresh=True, **params)
        persist.persist(need, params, res)
    except Exception as e:
        log.warning("job fetch %s %s failed: %s", need, params, e)


async def close_snapshot() -> None:
    if not is_trading_day():
        return
    from fa.pipeline.orchestrator import analyze
    syms = _watch()
    log.info("close_snapshot for %d symbols", len(syms))
    for s in syms:
        try:
            # the options section persists a chain snapshot + iv_surface_daily row; technicals persists bars
            await analyze(s, "quick", sections=["fundamentals", "technicals", "options", "analysts", "shorts"])
        except Exception as e:
            log.warning("close_snapshot %s failed: %s", s, e)
    duck.refresh_views()


async def short_volume() -> None:
    led = Ledger("job_short_volume")
    d = previous_trading_day()
    await _fetch(N.SHORT_VOLUME, led, date=str(d))
    duck.refresh_views()


async def news_sweep() -> None:
    led = Ledger("job_news")
    await _fetch(N.MACRO_NEWS, led)
    for s in _watch():
        await _fetch(N.NEWS, led, symbol=s)
        await _fetch(N.SOCIAL_STOCKTWITS, led, symbol=s)
    duck.refresh_views()


async def macro_sweep() -> None:
    led = Ledger("job_macro")
    await _fetch(N.YIELD_CURVE, led)
    await _fetch(N.VIX_HISTORY, led)
    for sid in ("DGS10", "DGS2", "DGS3MO", "T10Y2Y", "T10Y3M"):
        await _fetch(N.MACRO_SERIES, led, series_id=sid)


async def intraday_bars() -> None:
    if not is_trading_day():
        return
    led = Ledger("job_intraday")
    for s in _watch():
        for iv in ("5m", "15m", "1h"):
            await _fetch(N.OHLCV, led, symbol=s, interval=iv)
    duck.refresh_views()


def build_scheduler() -> AsyncIOScheduler:
    sch = AsyncIOScheduler(timezone=ET)
    sch.add_job(close_snapshot, CronTrigger(day_of_week="mon-fri", hour=16, minute=20, timezone=ET), id="close_snapshot", name="Close snapshot (chains, IV surface, bars)", misfire_grace_time=3600)
    sch.add_job(short_volume, CronTrigger(hour=6, minute=30, timezone=ET), id="short_volume", name="FINRA daily short volume", misfire_grace_time=3600)
    sch.add_job(news_sweep, CronTrigger(minute="*/30", hour="6-20", timezone=ET), id="news_sweep", name="News + social sweep", misfire_grace_time=600)
    sch.add_job(macro_sweep, CronTrigger(hour=7, minute=0, timezone=ET), id="macro_sweep", name="Macro series sweep", misfire_grace_time=3600)
    sch.add_job(intraday_bars, CronTrigger(day_of_week="mon-fri", hour="10-16/2", minute=5, timezone=ET), id="intraday_bars", name="Intraday bars", misfire_grace_time=600)
    return sch

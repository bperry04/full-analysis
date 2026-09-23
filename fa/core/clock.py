"""Time helpers: UTC now, NYSE calendar, session state, trading-day arithmetic."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_et() -> datetime:
    return datetime.now(ET)


@lru_cache(maxsize=1)
def _xnys():
    import exchange_calendars as xc
    return xc.get_calendar("XNYS")


def is_trading_day(d: date | None = None) -> bool:
    d = d or now_et().date()
    try:
        return bool(_xnys().is_session(d))
    except Exception:
        return d.weekday() < 5


def last_trading_day(d: date | None = None) -> date:
    d = d or now_et().date()
    for i in range(0, 10):
        c = d - timedelta(days=i)
        if is_trading_day(c):
            return c
    return d


def previous_trading_day(d: date | None = None) -> date:
    d = d or now_et().date()
    return last_trading_day(d - timedelta(days=1))


def next_trading_day(d: date | None = None) -> date:
    d = d or now_et().date()
    for i in range(1, 10):
        c = d + timedelta(days=i)
        if is_trading_day(c):
            return c
    return d + timedelta(days=1)


def session_state(ts: datetime | None = None) -> str:
    """'pre' | 'rth' | 'post' | 'closed'."""
    ts = (ts or utcnow()).astimezone(ET)
    if not is_trading_day(ts.date()):
        return "closed"
    t = ts.time()
    if time(4, 0) <= t < time(9, 30):
        return "pre"
    if time(9, 30) <= t < time(16, 0):
        return "rth"
    if time(16, 0) <= t < time(20, 0):
        return "post"
    return "closed"


def market_open(ts: datetime | None = None) -> bool:
    return session_state(ts) == "rth"


def trading_days_between(a: date, b: date) -> int:
    if b < a:
        return -trading_days_between(b, a)
    try:
        return int(_xnys().sessions_in_range(a, b).size) - 1
    except Exception:
        return max(0, ((b - a).days * 5) // 7)

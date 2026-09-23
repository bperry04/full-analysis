"""Read-side helpers over the lake and control-plane tables."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from fa.store import duck, lake


def ohlcv(symbol: str, interval: str = "1d", years: int | None = None) -> pd.DataFrame:
    df = lake.read_partitions("ohlcv", {"interval": interval, "symbol": symbol.upper()})
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.drop_duplicates("ts", keep="last").sort_values("ts")
    if years:
        df = df[df["ts"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=365 * years)]
    return df.reset_index(drop=True)


def chain_snapshots(symbol: str) -> list[dict[str, Any]]:
    out = []
    for p in lake.list_snapshots("options_snap", {"symbol": symbol.upper()}):
        dt = p.parent.name.split("=")[-1]
        out.append({"dt": dt, "file": str(p), "ts": p.stem.replace("snap_", "")})
    return out


def chain_snapshot(symbol: str, dt: str | None = None, which: str = "last") -> pd.DataFrame:
    """A stored chain snapshot: the latest on `dt` (default: most recent day), or the previous day's if which='prev'."""
    snaps = lake.list_snapshots("options_snap", {"symbol": symbol.upper()})
    if not snaps:
        return pd.DataFrame()
    by_day: dict[str, list] = {}
    for p in snaps:
        by_day.setdefault(p.parent.name.split("=")[-1], []).append(p)
    days = sorted(by_day)
    if dt is None:
        dt = days[-1]
    if which == "prev":
        prior = [d for d in days if d < dt]
        if not prior:
            return pd.DataFrame()
        dt = prior[-1]
    if dt not in by_day:
        return pd.DataFrame()
    df = pd.read_parquet(sorted(by_day[dt])[-1])
    df["dt"] = dt
    return df


def iv_surface_history(symbol: str, days: int = 400) -> pd.DataFrame:
    return duck.q("SELECT * FROM iv_surface_daily WHERE symbol=? AND dt >= ? ORDER BY dt",
                  [symbol.upper(), date.today() - timedelta(days=days)])


def iv_underlying_history(symbol: str, days: int = 800) -> pd.DataFrame:
    return duck.q("SELECT dt, iv, hv, source FROM iv_underlying_daily WHERE symbol=? AND dt >= ? ORDER BY dt",
                  [symbol.upper(), date.today() - timedelta(days=days)])


def short_interest_history(symbol: str) -> pd.DataFrame:
    return duck.q("SELECT * FROM short_interest WHERE symbol=? ORDER BY settlement_date", [symbol.upper()])


def short_volume_history(symbol: str, days: int = 90) -> pd.DataFrame:
    df = lake.read_partitions("short_volume", {})
    if df.empty:
        return df
    df = df[df["symbol"] == symbol.upper()].copy()
    df["date"] = pd.to_datetime(df["dt"]).dt.date
    return df.sort_values("date").tail(days).reset_index(drop=True)


def analyst_consensus_history(symbol: str) -> pd.DataFrame:
    return duck.q("SELECT * FROM analyst_consensus WHERE symbol=? ORDER BY as_of", [symbol.upper()])


def macro(series_id: str, days: int | None = None) -> pd.DataFrame:
    if days:
        return duck.q("SELECT dt, value FROM macro_series WHERE series_id=? AND dt >= ? ORDER BY dt", [series_id, date.today() - timedelta(days=days)])
    return duck.q("SELECT dt, value FROM macro_series WHERE series_id=? ORDER BY dt", [series_id])


def runs(symbol: str | None = None, limit: int = 50) -> pd.DataFrame:
    if symbol:
        return duck.q("SELECT * FROM analysis_runs WHERE symbol=? ORDER BY started_at DESC LIMIT ?", [symbol.upper(), limit])
    return duck.q("SELECT * FROM analysis_runs ORDER BY started_at DESC LIMIT ?", [limit])


def score_history(symbol: str) -> pd.DataFrame:
    return duck.q("SELECT * FROM score_history WHERE symbol=? ORDER BY ts", [symbol.upper()])


def watchlist() -> pd.DataFrame:
    return duck.q("SELECT * FROM watchlist ORDER BY priority, symbol")


def add_watch(symbol: str, note: str = "") -> None:
    duck.upsert_df("watchlist", pd.DataFrame([{"symbol": symbol.upper(), "added_at": datetime.now(timezone.utc), "snapshot_daily": True,
                                               "priority": 5, "note": note}]), ["symbol"])


def remove_watch(symbol: str) -> None:
    duck.execute("DELETE FROM watchlist WHERE symbol=?", [symbol.upper()])


def events(symbol: str, days_ahead: int = 120, days_back: int = 30) -> pd.DataFrame:
    return duck.q("SELECT * FROM events WHERE (symbol=? OR symbol='_MACRO') AND event_date BETWEEN ? AND ? ORDER BY event_date",
                  [symbol.upper(), date.today() - timedelta(days=days_back), date.today() + timedelta(days=days_ahead)])

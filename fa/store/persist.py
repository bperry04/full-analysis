"""Write-through persistence: every router result that is worth keeping lands in the lake or DuckDB.

Looking a ticker up permanently enriches the store — this is how point-in-time history (chains, intraday bars,
short volume, analyst consensus) accumulates without anyone selling it to us.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from fa.core.provenance import Ledger
from fa.registry import needs as N
from fa.registry.router import Result
from fa.store import duck, lake

log = logging.getLogger(__name__)

SNAPSHOT_MIN_GAP = timedelta(minutes=15)


def persist(need: str, params: dict[str, Any], res: Result) -> None:
    if res.from_cache:
        return                       # already persisted when first fetched
    try:
        fn = _DISPATCH.get(need)
        if fn:
            fn(params, res)
    except Exception as e:
        log.warning("persist %s failed: %s", need, e, exc_info=True)


def _sym(params: dict) -> str | None:
    s = params.get("symbol")
    return s.upper() if s else None


def _ohlcv(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    sym = _sym(params) or str(df["symbol"].iloc[0])
    interval = params.get("interval", "1d")
    df = df.copy()
    df["prov_id"] = res.p
    df["source"] = res.provider
    df["year"] = pd.to_datetime(df["ts"], utc=True).dt.year
    for year, part in df.groupby("year"):
        lake.merge_partition("ohlcv", part.drop(columns=["symbol", "interval"], errors="ignore"),
                             {"interval": interval, "symbol": sym, "year": int(year)}, keys=["ts"])


def _option_chain(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    sym = _sym(params)
    if df is None or df.empty or not sym:
        return
    now = datetime.now(timezone.utc)
    last = lake.latest_snapshot_ts("options_snap", {"symbol": sym, "dt": now.date().isoformat()})
    if last and now - last < SNAPSHOT_MIN_GAP:
        return
    out = df.copy()
    out["snap_ts"] = now
    out["source"] = res.provider
    if "prov_id" not in out.columns:
        out["prov_id"] = res.p
    lake.write_snapshot("options_snap", out, {"symbol": sym, "dt": now.date().isoformat()}, ts=now)


def _xbrl(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    cik = str(df["cik"].iloc[0])
    out = df.copy()
    out["prov_id"] = res.p
    out["symbol"] = _sym(params)
    lake.replace_partition("xbrl_facts", out, {"cik": cik})


def _segments(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    out = df.copy()
    out["prov_id"] = res.p
    out["symbol"] = _sym(params)
    cik = params.get("cik") or (res.prov.endpoint.split("/data/")[1].split("/")[0].zfill(10) if "/data/" in res.prov.endpoint else "unknown")
    lake.merge_partition("segment_facts", out, {"cik": cik}, keys=["accn", "report", "line_item", "member", "period"])


def _news(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    out = df.copy()
    out["symbol"] = _sym(params) or "_MACRO"
    out["prov_id"] = res.p
    out["published"] = pd.to_datetime(out["published"], utc=True, errors="coerce")
    out["dt"] = out["published"].dt.date.astype(str).where(out["published"].notna(), datetime.now(timezone.utc).date().isoformat())
    for dt, part in out.groupby("dt"):
        lake.merge_partition("news", part, {"dt": dt}, keys=["id", "symbol"])


def _social(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    out = df.copy()
    out["symbol"] = _sym(params)
    out["prov_id"] = res.p
    tcol = "created"
    out[tcol] = pd.to_datetime(out[tcol], utc=True, errors="coerce")
    out["dt"] = out[tcol].dt.date.astype(str)
    for dt, part in out.groupby("dt"):
        lake.merge_partition("social", part, {"dt": dt}, keys=["id", "source"])


def _short_volume(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    out = df.copy()
    out["prov_id"] = res.p
    for dt, part in out.groupby("date"):
        lake.merge_partition("short_volume", part.drop(columns=["date"]), {"dt": str(dt)}, keys=["symbol", "market"])


def _short_interest(params: dict, res: Result) -> None:
    d = res.data
    if not isinstance(d, dict):
        return
    hist = d.get("history")
    rows: pd.DataFrame
    if isinstance(hist, pd.DataFrame) and not hist.empty:
        rows = hist.copy()
    else:
        rows = pd.DataFrame([{k: d.get(k) for k in ("settlement_date", "shares_short", "shares_short_prior", "avg_daily_volume", "days_to_cover", "pct_of_float")}])
    rows["symbol"] = d.get("symbol") or _sym(params)
    rows["source"] = res.provider
    rows["prov_id"] = res.p
    rows["settlement_date"] = pd.to_datetime(rows["settlement_date"], errors="coerce").dt.date
    rows = rows.dropna(subset=["settlement_date"])
    duck.upsert_df("short_interest", rows, ["symbol", "settlement_date", "source"])


def _analyst_targets(params: dict, res: Result) -> None:
    d = res.data
    if not isinstance(d, dict):
        return
    row = {
        "symbol": _sym(params), "as_of": datetime.now(timezone.utc).date(), "pt_low": d.get("low"), "pt_mean": d.get("mean"),
        "pt_median": d.get("median"), "pt_high": d.get("high"), "current_price": d.get("current"), "source": res.provider, "prov_id": res.p,
    }
    duck.upsert_df("analyst_consensus", pd.DataFrame([row]), ["symbol", "as_of"])


def _analyst_recs(params: dict, res: Result) -> None:
    d = res.data
    if not isinstance(d, dict):
        return
    trend = d.get("trend")
    if isinstance(trend, pd.DataFrame) and not trend.empty and "strongBuy" in trend.columns:
        t0 = trend.iloc[0]
        row = {"symbol": _sym(params), "as_of": datetime.now(timezone.utc).date(), "strong_buy": int(t0.get("strongBuy", 0)),
               "buy": int(t0.get("buy", 0)), "hold": int(t0.get("hold", 0)), "sell": int(t0.get("sell", 0)),
               "strong_sell": int(t0.get("strongSell", 0)), "source": res.provider, "prov_id": res.p}
        row["n_analysts"] = row["strong_buy"] + row["buy"] + row["hold"] + row["sell"] + row["strong_sell"]
        existing = duck.q("SELECT * FROM analyst_consensus WHERE symbol=? AND as_of=?", [row["symbol"], row["as_of"]])
        if not existing.empty:
            merged = existing.iloc[0].to_dict()
            merged.update({k: v for k, v in row.items() if v is not None})
            row = merged
        duck.upsert_df("analyst_consensus", pd.DataFrame([row]), ["symbol", "as_of"])
    actions = d.get("actions")
    if isinstance(actions, pd.DataFrame) and not actions.empty and "date" in actions.columns:
        a = actions.rename(columns={"date": "action_date"}).copy()
        a["symbol"] = _sym(params)
        a["source"] = res.provider
        a["prov_id"] = res.p
        a = a.dropna(subset=["action_date", "firm"])
        duck.upsert_df("analyst_actions", a, ["symbol", "action_date", "firm", "to_grade"])


def _macro_series(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    out = df.rename(columns={"date": "dt"}).copy()
    out["series_id"] = params.get("series_id") or out.get("series_id")
    out["source"] = res.provider
    out["prov_id"] = res.p
    out["fetched_at"] = datetime.now(timezone.utc)
    duck.upsert_df("macro_series", out, ["series_id", "dt"])


def _yield_curve(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    long = df.melt(id_vars=["date"], var_name="series_id", value_name="value").dropna()
    long = long.rename(columns={"date": "dt"})
    long["source"], long["prov_id"], long["fetched_at"] = res.provider, res.p, datetime.now(timezone.utc)
    duck.upsert_df("macro_series", long, ["series_id", "dt"])


def _vix_history(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty or "close" not in df.columns:
        return
    out = pd.DataFrame({"series_id": "VIXCLS", "dt": pd.to_datetime(df["ts"], utc=True).dt.date, "value": df["close"]})
    out["source"], out["prov_id"], out["fetched_at"] = res.provider, res.p, datetime.now(timezone.utc)
    duck.upsert_df("macro_series", out, ["series_id", "dt"])


def _iv_history(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    out = df.rename(columns={"date": "dt"}).copy()
    out["symbol"] = _sym(params)
    out["source"] = res.provider
    if "hv" not in out.columns:
        out["hv"] = None
    if "iv" not in out.columns:
        out["iv"] = None
    duck.upsert_df("iv_underlying_daily", out, ["symbol", "dt", "source"])


def _ticks(params: dict, res: Result) -> None:
    d = res.data
    if not isinstance(d, dict):
        return
    tr = d.get("trades")
    if isinstance(tr, pd.DataFrame) and not tr.empty:
        out = tr.copy()
        out["prov_id"] = res.p
        dt = pd.to_datetime(out["ts"], utc=True).dt.date.max().isoformat()
        lake.merge_partition("ticks", out, {"symbol": _sym(params), "dt": dt}, keys=["ts", "price", "size", "exchange"])


def _earnings(params: dict, res: Result) -> None:
    df: pd.DataFrame = res.data
    if df is None or df.empty:
        return
    rows = []
    sym = _sym(params)
    for r in df.itertuples():
        ts = pd.Timestamp(r.ts)
        rows.append(
            {"id": f"{sym}:earnings:{ts.date()}", "symbol": sym, "event_type": "earnings", "event_date": ts.date(), "event_ts": ts.to_pydatetime(),
             "confirmed": bool(pd.notna(getattr(r, "eps_reported", None))), "importance": 5,
             "detail": json.dumps({"eps_estimate": _f(getattr(r, "eps_estimate", None)), "eps_reported": _f(getattr(r, "eps_reported", None)),
                                   "surprise_pct": _f(getattr(r, "surprise_pct", None))}),
             "source": res.provider, "prov_id": res.p, "updated_at": datetime.now(timezone.utc)}
        )
    duck.upsert_df("events", pd.DataFrame(rows), ["id"])


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def save_ledger(ledger: Ledger) -> None:
    rows = []
    for p in ledger.records.values():
        rows.append(
            {"prov_id": p.prov_id, "run_id": ledger.run_id, "need": p.need, "provider": p.provider, "endpoint": p.endpoint[:500],
             "fetched_at": p.fetched_at, "as_of": p.as_of, "latency": str(p.latency), "tier": str(p.tier), "is_delayed": p.is_delayed,
             "fallback_depth": p.fallback_depth, "from_cache": p.from_cache, "cache_age_s": p.cache_age_s, "row_count": p.row_count,
             "duration_ms": p.duration_ms, "payload_sha256": p.payload_sha256, "raw_path": p.raw_path, "quality_flags": p.quality_flags,
             "attempts": json.dumps([a.__dict__ if hasattr(a, "__dict__") else {"provider": a.provider, "result": a.result, "reason": a.reason} for a in p.attempts])}
        )
    if rows:
        duck.upsert_df("provenance", pd.DataFrame(rows), ["run_id", "prov_id"])


_DISPATCH = {
    N.OHLCV: _ohlcv, N.OPTION_CHAIN: _option_chain, N.XBRL_FACTS: _xbrl, N.SEGMENTS: _segments, N.NEWS: _news,
    N.MACRO_NEWS: _news, N.SOCIAL_STOCKTWITS: _social, N.SOCIAL_REDDIT: _social, N.SHORT_VOLUME: _short_volume,
    N.SHORT_INTEREST: _short_interest, N.ANALYST_TARGETS: _analyst_targets, N.ANALYST_RECS: _analyst_recs,
    N.MACRO_SERIES: _macro_series, N.YIELD_CURVE: _yield_curve, N.VIX_HISTORY: _vix_history, N.IV_HISTORY: _iv_history,
    N.HV_HISTORY: _iv_history, N.TICKS: _ticks, N.EARNINGS_DATES: _earnings,
}

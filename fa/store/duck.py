"""DuckDB connection factory + schema bootstrap + parquet-lake views.

One writer per process. If another process holds the write lock (API running while the CLI runs), we fall back to a
read-only connection and control-plane writes become no-ops with a warning — lake (parquet) writes never need DuckDB.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from fa.core.settings import get_settings

log = logging.getLogger(__name__)

_conn: duckdb.DuckDBPyConnection | None = None
_read_only = False
_unavailable = False          # another process holds the file and Windows refuses even a read-only open
_strict = False               # the API sets this: it must own the store or fail loudly
_lock = threading.RLock()


def set_strict(v: bool) -> None:
    global _strict
    _strict = v

LAKE_TABLES = {
    # table -> (glob under lake dir, hive partitioned?)
    "ohlcv": ("ohlcv/**/*.parquet", True),
    "options_snap": ("options_snap/**/*.parquet", True),
    "xbrl_facts": ("xbrl_facts/**/*.parquet", True),
    "segment_facts": ("segment_facts/**/*.parquet", True),
    "news": ("news/**/*.parquet", True),
    "social": ("social/**/*.parquet", True),
    "short_volume": ("short_volume/**/*.parquet", True),
    "ticks": ("ticks/**/*.parquet", True),
}


def connect() -> duckdb.DuckDBPyConnection:
    global _conn, _read_only, _unavailable
    with _lock:
        if _conn is not None or _unavailable:
            return _conn
        s = get_settings()
        try:
            _conn = duckdb.connect(str(s.duckdb_path))
            _read_only = False
        except duckdb.IOException as e:
            msg = str(e)
            try:
                _conn = duckdb.connect(str(s.duckdb_path), read_only=True)
                _read_only = True
                log.warning("DuckDB write lock held by another process; opened read-only (control-plane writes skipped)")
            except duckdb.IOException:
                import re
                pid = re.search(r"PID (\d+)", msg)
                hint = (f"{s.duckdb_path} is already open in another Full Analysis process{' (PID ' + pid.group(1) + ')' if pid else ''}. "
                        "Only one process can write the store; this one continues WITHOUT the control-plane database "
                        "(history/scores from DuckDB unavailable, lake and cache still work). Use the running API instead, or stop it.")
                if _strict:
                    raise RuntimeError(hint) from None
                log.warning(hint)
                _conn = None
                _unavailable = True
                return None
        _conn.execute(f"SET temp_directory='{str(s.tmp_dir).replace(chr(92), '/')}'")
        _conn.execute("SET threads=4")
        if not _read_only:
            _apply_ddl(_conn)
        refresh_views(_conn)
        return _conn


def available() -> bool:
    return connect() is not None


def is_read_only() -> bool:
    return _read_only


def _apply_ddl(con: duckdb.DuckDBPyConnection) -> None:
    ddl = (Path(__file__).parent / "ddl.sql").read_text(encoding="utf-8")
    for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
        con.execute(stmt)
    v = con.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    if v is None:
        con.execute("INSERT INTO schema_version VALUES (1, now())")


def refresh_views(con: duckdb.DuckDBPyConnection | None = None) -> None:
    """(Re)create a view per lake table over whatever parquet files exist right now."""
    con = con or connect()
    if con is None:
        return
    lake = get_settings().lake_dir
    for table, (glob, hive) in LAKE_TABLES.items():
        path = str(lake / glob).replace("\\", "/")
        has_files = any((lake / table).rglob("*.parquet")) if (lake / table).exists() else False
        try:
            if has_files:
                con.execute(
                    f"CREATE OR REPLACE VIEW lake_{table} AS SELECT * FROM read_parquet('{path}', hive_partitioning={1 if hive else 0}, union_by_name=1)"
                )
            else:
                con.execute(f"CREATE OR REPLACE VIEW lake_{table} AS SELECT NULL::VARCHAR AS symbol WHERE 1=0")
        except Exception as e:
            log.debug("view %s: %s", table, e)


def q(sql: str, params: list | tuple | None = None) -> pd.DataFrame:
    with _lock:
        con = connect()
        if con is None:
            return pd.DataFrame()
        return con.execute(sql, params or []).df()


def execute(sql: str, params: list | tuple | None = None) -> None:
    with _lock:
        con = connect()
        if con is None or _read_only:
            log.debug("store unavailable/read-only: skipped %s", sql[:60])
            return
        con.execute(sql, params or [])


def upsert_df(table: str, df: pd.DataFrame, keys: list[str]) -> int:
    """INSERT OR REPLACE a DataFrame into a native table (columns aligned to the table)."""
    if df is None or df.empty:
        return 0
    with _lock:
        con = connect()
        if con is None or _read_only:
            log.debug("store unavailable/read-only: skipped upsert into %s", table)
            return 0
        cols = [r[1] for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()]
        use = [c for c in cols if c in df.columns]
        tmp = df[use].copy()
        con.register("_tmp_upsert", tmp)
        con.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(use)}) SELECT {', '.join(use)} FROM _tmp_upsert")
        con.unregister("_tmp_upsert")
        return len(tmp)


def stats() -> dict[str, Any]:
    con = connect()
    out: dict[str, Any] = {"duckdb_path": str(get_settings().duckdb_path), "read_only": _read_only, "available": con is not None, "tables": {}}
    for t in ("provenance", "analysis_runs", "iv_surface_daily", "iv_underlying_daily", "fundamentals_normalized", "short_interest",
              "analyst_consensus", "macro_series", "events", "watchlist", "score_history"):
        try:
            out["tables"][t] = int(con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) if con is not None else None
        except Exception:
            out["tables"][t] = None
    lake = get_settings().lake_dir
    out["lake"] = {}
    for t in LAKE_TABLES:
        d = lake / t
        files = list(d.rglob("*.parquet")) if d.exists() else []
        out["lake"][t] = {"files": len(files), "bytes": sum(f.stat().st_size for f in files)}
    return out

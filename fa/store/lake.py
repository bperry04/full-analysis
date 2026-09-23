"""Parquet lake writer (C:\\fadata\\lake), hive-partitioned, atomic on Windows (write tmp -> os.replace).

    merge_partition("ohlcv", df, {"interval": "1d", "symbol": "AAPL", "year": 2026}, keys=["ts"])
    write_snapshot("options_snap", df, {"symbol": "AAPL", "dt": "2026-09-21"})   # never overwrites

Merge partitions are read-modify-write with dedupe on keys (keep last). Snapshots are one immutable file each.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from fa.core.settings import get_settings

log = logging.getLogger(__name__)


def _partition_dir(table: str, partition: dict[str, Any]) -> Path:
    d = get_settings().lake_dir / table
    for k, v in partition.items():
        d = d / f"{k}={v}"
    return d


def _atomic_write(df: pd.DataFrame, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = get_settings().tmp_dir / f"{uuid.uuid4().hex}.parquet"
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, tmp, compression="zstd", compression_level=3)
    os.replace(tmp, dest)


def _strip_partition_cols(df: pd.DataFrame, partition: dict[str, Any]) -> pd.DataFrame:
    # hive partition values come back from the directory name; keep the columns out of the file to avoid duplicates
    return df.drop(columns=[c for c in partition if c in df.columns], errors="ignore")


def merge_partition(table: str, df: pd.DataFrame, partition: dict[str, Any], keys: list[str]) -> int:
    if df is None or df.empty:
        return 0
    d = _partition_dir(table, partition)
    dest = d / "data.parquet"
    new = _strip_partition_cols(df.copy(), partition)
    if dest.exists():
        try:
            old = pd.read_parquet(dest)
            new = pd.concat([old, new], ignore_index=True)
        except Exception as e:
            log.warning("could not read %s (%s); overwriting", dest, e)
    keep = [k for k in keys if k in new.columns]
    if keep:
        new = new.drop_duplicates(subset=keep, keep="last")
        try:
            new = new.sort_values(keep)
        except Exception:
            pass
    _atomic_write(new.reset_index(drop=True), dest)
    return len(new)


def replace_partition(table: str, df: pd.DataFrame, partition: dict[str, Any]) -> int:
    if df is None or df.empty:
        return 0
    d = _partition_dir(table, partition)
    _atomic_write(_strip_partition_cols(df.copy(), partition).reset_index(drop=True), d / "data.parquet")
    return len(df)


def write_snapshot(table: str, df: pd.DataFrame, partition: dict[str, Any], ts: datetime | None = None) -> Path | None:
    if df is None or df.empty:
        return None
    ts = ts or datetime.now(timezone.utc)
    d = _partition_dir(table, partition)
    dest = d / f"snap_{ts:%Y%m%dT%H%M%SZ}.parquet"
    _atomic_write(_strip_partition_cols(df.copy(), partition).reset_index(drop=True), dest)
    return dest


def list_snapshots(table: str, partition_prefix: dict[str, Any]) -> list[Path]:
    d = _partition_dir(table, partition_prefix)
    return sorted(d.rglob("snap_*.parquet")) if d.exists() else []


def latest_snapshot_ts(table: str, partition_prefix: dict[str, Any]) -> datetime | None:
    snaps = list_snapshots(table, partition_prefix)
    if not snaps:
        return None
    name = snaps[-1].stem.replace("snap_", "")
    try:
        return datetime.strptime(name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_partitions(table: str, partition_prefix: dict[str, Any]) -> pd.DataFrame:
    d = _partition_dir(table, partition_prefix)
    if not d.exists():
        return pd.DataFrame()
    files = sorted(d.rglob("*.parquet"))
    if not files:
        return pd.DataFrame()
    frames = []
    for f in files:
        try:
            x = pd.read_parquet(f)
            # recover hive partition values below the prefix
            rel = f.relative_to(d)
            for part in rel.parts[:-1]:
                if "=" in part:
                    k, v = part.split("=", 1)
                    x[k] = v
            for k, v in partition_prefix.items():
                x[k] = v
            frames.append(x)
        except Exception as e:
            log.warning("read %s failed: %s", f, e)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

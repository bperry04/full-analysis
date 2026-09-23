"""Shared provider helpers: OCC symbol parsing, canonical option-chain columns, number parsing."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from fa.core.clock import ET

OCC_RE = re.compile(r"^([A-Z.\-]{1,6})\s*(\d{6})([CP])(\d{8})$")

CHAIN_COLUMNS = [
    "contract_symbol", "expiry", "strike", "right", "bid", "ask", "bid_size", "ask_size", "mid", "last",
    "last_ts", "volume", "open_interest", "iv", "delta", "gamma", "theta", "vega", "rho", "theo",
    "underlying_price", "dte", "moneyness", "spread_bps", "iv_source", "greeks_source",
]


def parse_occ(sym: str) -> tuple[str, date, str, float] | None:
    m = OCC_RE.match(sym.strip().upper())
    if not m:
        return None
    root, ymd, right, strike = m.groups()
    return root, datetime.strptime(ymd, "%y%m%d").date(), right, int(strike) / 1000.0


def finish_chain(df: pd.DataFrame, underlying_price: float | None, as_of: datetime | None) -> pd.DataFrame:
    """Fill derived columns (mid, dte, moneyness, spread_bps) and enforce the canonical column set/order."""
    for c in CHAIN_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan if c not in ("iv_source", "greeks_source", "contract_symbol", "right") else None
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    for c in ("bid", "ask", "bid_size", "ask_size", "last", "volume", "open_interest", "iv", "delta", "gamma",
              "theta", "vega", "rho", "theo", "strike"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["mid"] = np.where((df["bid"] > 0) & (df["ask"] > 0), (df["bid"] + df["ask"]) / 2, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["spread_bps"] = np.where(df["mid"] > 0, (df["ask"] - df["bid"]) / df["mid"] * 1e4, np.nan)
    ref = (as_of or datetime.now(timezone.utc)).astimezone(ET).date()
    df["dte"] = [(e - ref).days for e in df["expiry"]]
    if underlying_price:
        df["underlying_price"] = underlying_price
        with np.errstate(divide="ignore", invalid="ignore"):
            df["moneyness"] = np.log(df["strike"] / float(underlying_price))
    df = df[df["dte"] >= 0]
    return df[CHAIN_COLUMNS].sort_values(["expiry", "strike", "right"]).reset_index(drop=True)


def num(x: Any) -> float | None:
    """Parse '$1,234.5', '12.3%', '(45)', 'N/A' -> float."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return None if (isinstance(x, float) and np.isnan(x)) else float(x)
    s = str(x).strip().replace("$", "").replace(",", "").replace("%", "").replace("&nbsp;", "")
    if s in ("", "N/A", "NA", "-", "--", "—", "null", "None"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    mult = 1.0
    if s and s[-1] in "KMBT":
        mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[s[-1]]
        s = s[:-1]
    try:
        v = float(s) * mult
        return -v if neg else v
    except ValueError:
        return None


def to_utc(ts: Any) -> datetime | None:
    if ts is None or (isinstance(ts, float) and np.isnan(ts)):
        return None
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert("UTC").to_pydatetime()


def frame_ts_utc(df: pd.DataFrame, col: str = "ts") -> pd.DataFrame:
    """Ensure a timestamp column is tz-aware UTC."""
    s = pd.to_datetime(df[col], errors="coerce", utc=True)
    df[col] = s
    return df

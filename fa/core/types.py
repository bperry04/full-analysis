"""Shared value types.

`Val` is the envelope every scalar wears on its way to the UI: value + provenance id + quality flags.
The full Provenance record lives once, in the result's top-level `provenance` dict, keyed by `p`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class Latency(StrEnum):
    REALTIME = "realtime"
    NEAR_REALTIME = "near_realtime"   # < 1 min
    DELAYED_15 = "delayed_15"
    EOD = "eod"
    RELEASE = "release"               # macro releases on a schedule
    FILING = "filing"                 # SEC filings
    COMPUTED = "computed"             # derived from other Tagged values


class Horizon(StrEnum):
    LONG = "long"       # 6-24 months
    MEDIUM = "medium"   # 1-6 months
    SHORT = "short"     # days to weeks


class Tier(StrEnum):
    """Accuracy tier of a provider for a given need."""
    A = "A"   # authoritative / exchange / regulator
    B = "B"   # reliable aggregator (Yahoo, Nasdaq)
    C = "C"   # scraped / unofficial / proxy


class Q(StrEnum):
    """Quality flags attached to values."""
    DELAYED = "DELAYED"
    STALE = "STALE"
    DEGRADED = "DEGRADED"           # came from a fallback provider
    ESTIMATED = "ESTIMATED"
    DERIVED = "DERIVED"             # e.g. Q4 = FY - 9M
    RESTATED = "RESTATED"
    TAG_SPLICE = "TAG_SPLICE"       # XBRL series spliced across tags
    SHORT_HISTORY = "SHORT_HISTORY"
    SOURCE_DISAGREEMENT = "SOURCE_DISAGREEMENT"
    UNCONFIRMED = "UNCONFIRMED"
    PROXY = "PROXY"                 # a proxy for something not freely available
    ASSUMPTION = "ASSUMPTION"


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return float(v)          # numpy.float64 is a float subclass; cast so payloads carry plain floats
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "item"):          # numpy scalar
        try:
            return _clean(v.item())
        except Exception:
            return None
    return v


@dataclass(slots=True)
class Val:
    """A traceable scalar: value `v`, provenance id `p`, quality flags `q`."""
    v: Any
    p: str | None = None
    q: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {"v": _clean(self.v), "p": self.p, "q": [str(x) for x in self.q]}

    def flag(self, *flags: Q | str) -> "Val":
        for f in flags:
            s = str(f)
            if s not in self.q:
                self.q.append(s)
        return self

    @property
    def is_missing(self) -> bool:
        v = _clean(self.v)
        return v is None


def val(v: Any, p: str | None = None, *flags: Q | str) -> Val:
    return Val(_clean(v), p, [str(f) for f in flags])


def jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses / Val / numpy / pandas objects into plain JSON-safe structures."""
    if obj is None:
        return None
    if isinstance(obj, Val):
        return obj.to_json()
    if isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return _clean(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, StrEnum):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(x) for x in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: jsonable(getattr(obj, k)) for k in obj.__dataclass_fields__}  # type: ignore[attr-defined]
    if hasattr(obj, "to_dict") and hasattr(obj, "columns"):      # DataFrame
        import pandas as pd
        # a plain positional index is noise; a named / date / string index is data and becomes a column
        drop = isinstance(obj.index, pd.RangeIndex) or (obj.index.name is None and obj.index.dtype.kind in "iu")
        df = obj.reset_index(drop=drop)
        cols = list(df.columns)
        return [jsonable(dict(zip(cols, row))) for row in zip(*(df[c].tolist() for c in cols))]
    if hasattr(obj, "to_dict"):                                  # Series
        return jsonable(obj.to_dict())
    if hasattr(obj, "item"):
        return _clean(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)

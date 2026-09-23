"""Factor registry — the traceability backbone.

A factor is a decorated function `fn(ctx) -> FactorValue | None`. It reads section outputs from `ctx`, normalizes its raw
value to [-1, 1], and records every input it used (with provenance ids) so a score can be walked down to raw bytes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np


@dataclass(slots=True)
class InputRef:
    name: str
    value: Any
    unit: str = ""
    prov_id: str | None = None
    formula: str | None = None


@dataclass
class FactorValue:
    key: str
    label: str
    category: str
    status: str = "OK"                       # OK | MISSING | DEGRADED | ESTIMATED | SUPPRESSED
    raw: float | None = None
    raw_display: str = ""
    unit: str = ""
    normalized: float | None = None          # [-1, 1], already direction-adjusted (+ = good for the stock)
    percentile: float | None = None
    confidence: float = 1.0
    horizons: dict[str, float] = field(default_factory=dict)   # long/medium/short weight multipliers (0 = not used)
    inputs: list[InputRef] = field(default_factory=list)
    prov_ids: list[str] = field(default_factory=list)
    narrative: str = ""
    comparison_basis: str = ""
    history: list[list[Any]] | None = None
    # filled by the engine
    weight: dict[str, float] = field(default_factory=dict)
    contribution: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class FactorDef:
    key: str
    label: str
    category: str
    horizons: dict[str, float]
    fn: Callable[[Any], FactorValue | None]


REGISTRY: dict[str, FactorDef] = {}


def factor(key: str, label: str, category: str, horizons: dict[str, float] | None = None):
    def deco(fn):
        REGISTRY[key] = FactorDef(key, label, category, horizons or {"long": 1, "medium": 1, "short": 1}, fn)
        return fn
    return deco


# ---------------------------------------------------------------------------- normalizers
def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def bounded(x: float | None, lo: float, hi: float, direction: int = 1) -> float | None:
    """Linear map lo -> -1, hi -> +1 (clipped)."""
    if x is None or not np.isfinite(x):
        return None
    v = (x - lo) / (hi - lo) * 2 - 1
    return clamp(v * direction)


def scaled(x: float | None, scale: float, direction: int = 1, center: float = 0.0) -> float | None:
    """tanh((x - center) / scale) — saturates smoothly; scale = value that maps to ~0.76."""
    if x is None or not np.isfinite(x):
        return None
    return clamp(math.tanh((x - center) / scale) * direction)


def zhist(x: float | None, hist: Any, direction: int = 1) -> tuple[float | None, float | None]:
    """z-score vs the factor's own history → tanh(z/2); also returns percentile."""
    if x is None:
        return None, None
    try:
        h = np.asarray([v for v in hist if v is not None and np.isfinite(v)], dtype=float)
    except Exception:
        return None, None
    if len(h) < 8 or h.std() == 0:
        return None, None
    z = (x - h.mean()) / h.std()
    return clamp(math.tanh(z / 2) * direction), float((h < x).mean())


def fmt(v: Any, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "n/a"
    try:
        if unit == "pct":
            return f"{v * 100:+.1f}%" if abs(v) < 5 else f"{v:+.1f}"
        if unit == "x":
            return f"{v:.1f}x"
        if unit == "USD":
            a = abs(v)
            for s, d in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
                if a >= d:
                    return f"${v / d:,.1f}{s}"
            return f"${v:,.0f}"
        if unit == "days":
            return f"{v:.0f}d"
        if unit == "score":
            return f"{v:.2f}"
        return f"{v:,.2f}" if isinstance(v, float) else str(v)
    except Exception:
        return str(v)


def mk(key: str, label: str, category: str, raw: float | None, normalized: float | None, *, unit: str = "", inputs: list[InputRef] | None = None,
       narrative: str = "", basis: str = "", confidence: float = 1.0, percentile: float | None = None, history: list | None = None,
       status: str | None = None) -> FactorValue:
    prov = sorted({i.prov_id for i in (inputs or []) if i.prov_id})
    st = status or ("OK" if normalized is not None else "MISSING")
    return FactorValue(key=key, label=label, category=category, status=st, raw=raw, raw_display=fmt(raw, unit), unit=unit,
                       normalized=normalized, percentile=percentile, confidence=confidence, inputs=inputs or [], prov_ids=prov,
                       narrative=narrative, comparison_basis=basis, history=history)

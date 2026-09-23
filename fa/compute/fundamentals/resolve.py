"""Resolve canonical concepts from raw XBRL facts.

For each concept: pick the candidate tag with the best period coverage (first candidate whose coverage is >= 80% of the
best), use it for the WHOLE series, fill remaining gaps from other candidates (flagged TAG_SPLICE), keep both the
as-first-filed and the latest-filed value when a period was restated, then evaluate formulas for anything unresolved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from fa.compute.fundamentals.concepts import Concept, ConceptMap, load_concepts
from fa.compute.fundamentals.periods import classify, fiscal_quarter_of, fiscal_year_end_month, fiscal_year_of, records

ALLOWED_FORMS = {"10-K", "10-Q", "20-F", "40-F", "10-K/A", "10-Q/A", "20-F/A", "10-KT", "10-QT"}
UNIT_ALIASES = {"USD": {"USD"}, "shares": {"shares"}, "USD/shares": {"USD/shares"}, "pure": {"pure"}}


@dataclass(slots=True)
class Resolution:
    concept: str
    tag: str | None
    taxonomy: str | None
    coverage: int
    candidates: dict[str, int]
    spliced_from: list[str] = field(default_factory=list)
    via_formula: str | None = None
    flags: list[str] = field(default_factory=list)


STR_COLS = ("taxonomy", "tag", "unit", "form", "accn", "frame", "fp")


def _prep(facts: pd.DataFrame) -> pd.DataFrame:
    f = facts[facts["form"].isin(ALLOWED_FORMS)].copy()
    f = f.dropna(subset=["end", "val"])
    # Arrow-backed string/date columns make row-wise work very slow; plain object/float columns are what we want here
    for c in STR_COLS:
        if c in f.columns:
            f[c] = f[c].astype(object)
    f["start"] = pd.to_datetime(f["start"], errors="coerce").dt.date.astype(object)
    f["end"] = pd.to_datetime(f["end"], errors="coerce").dt.date.astype(object)
    f["filed"] = pd.to_datetime(f["filed"], errors="coerce").dt.date.astype(object)
    f["val"] = pd.to_numeric(f["val"], errors="coerce").astype(float)
    f["kind"] = pd.Series([classify(s, e) for s, e in zip(f["start"], f["end"])], index=f.index, dtype=object)
    f = f[f["kind"] != "OTHER"]
    f["tagkey"] = pd.Series(np.where(f["taxonomy"] == "us-gaap", f["tag"], f["taxonomy"].astype(str) + ":" + f["tag"].astype(str)), index=f.index, dtype=object)
    return f


def _group_by_tag(f: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {k: g for k, g in f.groupby("tagkey", sort=False)}


def _series_for_tag(groups: dict[str, pd.DataFrame], tagkey: str, unit: str, period: str) -> pd.DataFrame:
    s = groups.get(tagkey)
    if s is None or s.empty:
        return pd.DataFrame()
    s = s[s["unit"].isin(UNIT_ALIASES.get(unit, {unit}))]
    if period == "instant":
        s = s[s["kind"] == "INSTANT"]
    else:
        s = s[s["kind"].isin(["Q", "H", "NM", "FY"])]
    return s


def _collapse_restatements(s: pd.DataFrame) -> pd.DataFrame:
    """Per (start,end): keep the first-filed value and the latest-filed value; mark restated when they differ.
    The 'current' row per period is the latest filing; an as-filed row is only kept when a later filing changed the value."""
    if s.empty:
        return s
    recs = records(s)
    instant = recs[0]["kind"] == "INSTANT"
    key = (lambda r: (r["end"],)) if instant else (lambda r: (r["start"], r["end"]))
    recs.sort(key=lambda r: (r["end"], r["filed"] or date.min))
    first: dict[tuple, dict] = {}
    last: dict[tuple, dict] = {}
    for r in recs:
        k = key(r)
        first.setdefault(k, r)
        last[k] = r
    out: list[dict] = []
    for k, l in last.items():
        f0 = first[k]
        changed = abs(l["val"] - f0["val"]) > 1e-6 * max(1.0, abs(f0["val"]))
        out.append(dict(l, is_restated=changed, as_filed=False))
        if changed:
            out.append(dict(f0, is_restated=False, as_filed=True))
    return pd.DataFrame(out)


def resolve_all(facts: pd.DataFrame, cmap: ConceptMap | None = None) -> tuple[pd.DataFrame, dict[str, Resolution], int]:
    """Returns (long df, resolutions, fiscal-year-end month).

    long df columns: concept, kind, period_start, period_end, fy, fq, value, unit, source_tag, taxonomy, derived, derivation,
                     is_restated, as_filed, filed, accn, flags
    """
    cmap = cmap or load_concepts()
    f = _prep(facts)
    groups = _group_by_tag(f)
    fye = fiscal_year_end_month(f.loc[f["kind"] == "FY", "end"])
    frames: list[pd.DataFrame] = []
    resolutions: dict[str, Resolution] = {}

    for key, c in cmap.concepts.items():
        cov: dict[str, int] = {}
        series: dict[str, pd.DataFrame] = {}
        for t in c.tags:
            s = _series_for_tag(groups, t, c.unit, c.period)
            if s.empty:
                continue
            series[t] = s
            cov[t] = int(s["end"].nunique())
        if not cov:
            resolutions[key] = Resolution(key, None, None, 0, {})
            continue
        best_cov = max(cov.values())
        chosen = next(t for t in c.tags if t in cov and cov[t] >= 0.8 * best_cov)
        base = _collapse_restatements(series[chosen])
        base["source_tag"] = chosen
        spliced: list[str] = []
        have = set(zip(base["start"], base["end"]))
        for t, s in series.items():
            if t == chosen:
                continue
            extra = s[[(a, b) not in have for a, b in zip(s["start"], s["end"])]]
            if extra.empty:
                continue
            extra = _collapse_restatements(extra)
            extra["source_tag"] = t
            base = pd.concat([base, extra], ignore_index=True)
            have |= set(zip(extra["start"], extra["end"]))
            spliced.append(t)
        base["concept"] = key
        base["value"] = base["val"] * c.sign
        base["flags"] = [(["TAG_SPLICE"] if t != chosen else []) for t in base["source_tag"].tolist()]
        frames.append(base)
        resolutions[key] = Resolution(key, chosen, "us-gaap" if ":" not in chosen else chosen.split(":")[0], cov[chosen], cov, spliced)

    if not frames:
        return pd.DataFrame(), resolutions, fye
    long = pd.concat(frames, ignore_index=True)
    long = long.rename(columns={"start": "period_start", "end": "period_end"})
    for c in ("concept", "kind", "period_start", "period_end", "source_tag", "accn", "filed", "unit", "taxonomy"):
        if c in long.columns:
            long[c] = long[c].astype(object)
    ends = long["period_end"].tolist()
    long["fy"] = [fiscal_year_of(e, fye) for e in ends]
    long["fq"] = [fiscal_quarter_of(e, fye) for e in ends]
    long["derived"] = False
    long["derivation"] = None
    if "as_filed" not in long.columns:
        long["as_filed"] = False
    long["as_filed"] = long["as_filed"].fillna(False).astype(bool)
    keep = ["concept", "kind", "period_start", "period_end", "fy", "fq", "value", "unit", "source_tag", "taxonomy", "derived", "derivation",
            "is_restated", "as_filed", "filed", "accn", "flags"]
    return long[keep], resolutions, fye


# ----------------------------------------------------------------------------- formulas
_OPS = {"+", "-", "*", "/"}


def eval_formula(formula: str, get: Any) -> tuple[pd.Series | None, list[str]]:
    """Small left-to-right evaluator over concept keys joined by + - * /.

    A component prefixed with `?` is optional: it contributes 0 where missing, and the formula still needs at least one
    non-missing component per period. Required components make the formula fail if absent.
    `get(key)` returns a Series indexed by period_end, or None.
    """
    toks = formula.replace("(", " ").replace(")", " ").split()
    if not toks:
        return None, []
    acc: pd.Series | None = None
    present: pd.Series | None = None      # count of non-missing components per index
    op = "+"
    used: list[str] = []
    for t in toks:
        if t in _OPS:
            op = t
            continue
        optional = t.startswith("?")
        key = t.lstrip("?")
        s = get(key)
        if s is None or len(s) == 0:
            if optional:
                continue
            return None, used
        used.append(key)
        if acc is None:
            acc = s.astype(float).copy()
            present = pd.Series(1, index=acc.index)
            continue
        idx = acc.index.union(s.index)
        a, b = acc.reindex(idx), s.reindex(idx).astype(float)
        pres = present.reindex(idx).fillna(0) + b.notna().astype(int)
        if op == "+":
            acc = a.add(b, fill_value=0) if optional else (a + b)
        elif op == "-":
            acc = a.sub(b, fill_value=0) if optional else (a - b)
        elif op == "*":
            acc = a * b
        elif op == "/":
            acc = a / b
        present = pres
    if acc is None:
        return None, used
    acc = acc[present.reindex(acc.index).fillna(0) > 0].dropna()
    return acc, used

"""Interpret the long-form segment table (from SEC R-files) into product/geographic revenue breakdowns with growth."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

REV_RE = re.compile(r"^(net sales|revenue|revenues|total revenue|net revenue|total net sales|sales)\b", re.I)
EXCLUDE_RE = re.compile(r"deferred|cost|expense|margin|income|asset|profit|percentage|%", re.I)


def _parse_period(p: str) -> tuple[str | None, pd.Timestamp | None]:
    """'3 Months Ended | Jun. 27, 2026' -> ('3M', 2026-06-27)"""
    m = re.search(r"(\d+)\s+Months\s+Ended", p, flags=re.I)
    kind = f"{m.group(1)}M" if m else None
    d = re.search(r"([A-Z][a-z]{2})\.?\s+(\d{1,2}),\s+(\d{4})", p)
    ts = pd.to_datetime(f"{d.group(1)} {d.group(2)} {d.group(3)}", errors="coerce") if d else None
    return kind, ts


def summarize(seg: pd.DataFrame) -> dict[str, Any]:
    if seg is None or seg.empty:
        return {"available": False}
    df = seg.copy()
    df = df[df["line_item"].astype(str).str.match(REV_RE) & ~df["line_item"].astype(str).str.contains(EXCLUDE_RE)]
    df = df[df["member"].notna()]
    if df.empty:
        return {"available": False}
    parsed = df["period"].map(_parse_period)
    df["kind"] = [k for k, _ in parsed]
    df["ts"] = [t for _, t in parsed]
    df = df.dropna(subset=["ts"])
    df["member"] = df["member"].astype(str).str.replace(r"\s*\|\s*Operating segments$", "", regex=True).str.strip()
    # exclude totals and eliminations
    df = df[~df["member"].str.contains(r"^total|elimination|corporate|reconcil|segment reporting|all other$", case=False, regex=True)]

    out: dict[str, Any] = {"available": True, "breakdowns": {}}
    for report, part in df.groupby("report"):
        kinds = part["kind"].dropna().unique().tolist()
        # prefer the longest cumulative period in the latest filing for the mix, plus the latest quarter for growth
        latest_ts = part["ts"].max()
        latest = part[part["ts"] == latest_ts]
        mix_kind = "12M" if "12M" in kinds else ("9M" if "9M" in kinds else ("6M" if "6M" in kinds else "3M"))
        mix = latest[latest["kind"] == mix_kind].groupby("member")["value"].first().sort_values(ascending=False)
        if mix.empty:
            continue
        total = float(mix.sum())
        yoy = {}
        q = part[part["kind"] == "3M"]
        if not q.empty:
            for member, m in q.groupby("member"):
                m = m.sort_values("ts")
                if len(m) >= 2:
                    prev = m[m["ts"] <= m["ts"].max() - pd.Timedelta(days=350)]
                    if len(prev):
                        p0, p1 = float(m.iloc[-1]["value"]), float(prev.iloc[-1]["value"])
                        if p1:
                            yoy[member] = p0 / p1 - 1
        label = "geographic" if re.search(r"geograph|americas|europe|china|region", report + " " + " ".join(mix.index), re.I) else "product"
        key = f"{label}:{report[:60]}"
        out["breakdowns"][key] = {
            "report": report, "kind": label, "period": mix_kind, "as_of": str(latest_ts.date()), "total": total,
            "members": [{"member": m, "value": float(v), "share": float(v) / total if total else None, "yoy": yoy.get(m)} for m, v in mix.items()],
        }
    # concentration: share of the largest member across the first product breakdown
    prod = next((b for b in out["breakdowns"].values() if b["kind"] == "product"), None)
    if prod and prod["members"]:
        out["top_product_share"] = prod["members"][0]["share"]
        out["top_product"] = prod["members"][0]["member"]
        shares = [m["share"] for m in prod["members"] if m["share"]]
        out["hhi"] = sum(s * s for s in shares)
    geo = next((b for b in out["breakdowns"].values() if b["kind"] == "geographic"), None)
    if geo and geo["members"]:
        out["top_region_share"] = geo["members"][0]["share"]
        out["top_region"] = geo["members"][0]["member"]
    return out

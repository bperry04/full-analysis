"""Run every valuation model, decide applicability from the company profile, and blend with profile-specific weights."""
from __future__ import annotations

from typing import Any

import numpy as np

from fa.compute.valuation.profile import WEIGHTS, Profile

LABELS = {
    "dcf": "FCFF DCF (Gordon terminal)", "fcfe": "FCFE (equity DCF)", "dcf_exit": "DCF with exit EV/EBITDA multiple", "dcf_scenarios": "Scenario DCF (bear/base/bull)",
    "mc_dcf": "Monte Carlo DCF (median)", "comps": "Peer comparables (median multiples)", "hist_multiples": "Own historical multiples", "epv": "Earnings power value",
    "rim": "Residual income", "ddm": "Dividend discount (2-stage)", "justified_pe": "Justified P/E", "justified_pb": "Justified P/B", "peg": "PEG-based",
    "graham": "Graham number", "ncav": "Net current asset value", "tangible_book": "Tangible book value", "ffo_cap": "FFO capitalization (REIT)",
}

# which models are structurally inapplicable for a tag (beyond "could not compute")
NOT_FOR = {
    "bank": {"dcf", "fcfe", "dcf_exit", "dcf_scenarios", "mc_dcf", "epv", "ncav", "ffo_cap", "peg"},
    "insurer": {"dcf", "fcfe", "dcf_exit", "dcf_scenarios", "mc_dcf", "epv", "ncav", "ffo_cap", "peg"},
    "reit": {"justified_pe", "peg", "graham", "epv", "ncav"},
    "pre_revenue": {"dcf", "fcfe", "dcf_exit", "dcf_scenarios", "mc_dcf", "epv", "rim", "ddm", "justified_pe", "justified_pb", "peg", "graham", "hist_multiples", "ffo_cap"},
    "loss_making": {"justified_pe", "peg", "graham"},
    "negative_equity": {"justified_pb", "rim", "graham", "tangible_book", "ncav"},
}
REASON_FOR = {"bank": "bank — cash-flow models are not meaningful", "insurer": "insurer — book/ROE models apply instead", "reit": "REIT — earnings understate cash generation",
              "pre_revenue": "pre-revenue", "loss_making": "net loss — no positive earnings to capitalize", "negative_equity": "negative book equity"}


def assemble(price: float | None, profile: Profile, results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """results: model key -> model output dict (must contain available / value_per_share / reason)."""
    weights = WEIGHTS.get(profile.primary, WEIGHTS["mature_profitable"])
    banned: dict[str, str] = {}
    for tag in profile.tags:
        for m in NOT_FOR.get(tag, ()):
            banned.setdefault(m, REASON_FOR.get(tag, tag))
    if "reit" not in profile.tags:
        banned.setdefault("ffo_cap", "only meaningful for REITs (FFO capitalization)")
    models: list[dict[str, Any]] = []
    usable: dict[str, float] = {}
    for key, label in LABELS.items():
        r = results.get(key) or {"available": False, "reason": "not run"}
        v = r.get("value_per_share")
        ok = bool(r.get("available")) and v is not None and np.isfinite(v)
        if ok and v <= 0:
            ok = False
            r = {**r, "reason": f"model yields a negative value ({v:,.2f}/share) — not meaningful under current assumptions"}
        applies = key not in banned
        entry = {"key": key, "label": label, "applies": applies, "computed": ok, "value_per_share": v if ok else None,
                 "upside_pct": (v / price - 1) if ok and price else None, "weight": weights.get(key, 0.0) if applies and ok else 0.0,
                 "reason": banned.get(key) if not applies else (None if ok else r.get("reason") or "could not compute"),
                 "flags": r.get("flags") or [], "formula": r.get("formula") or r.get("note")}
        models.append(entry)
        if applies and ok and weights.get(key, 0.0) > 0 and v > 0:
            usable[key] = v
    if not usable:
        return {"available": False, "reason": "no applicable model produced a value", "models": models, "profile": profile.primary, "tags": profile.tags, "notes": profile.notes}
    med = float(np.median(list(usable.values())))
    kept = {k: v for k, v in usable.items() if med / 3 <= v <= 3 * med}       # a model 3x away from the pack is telling a different story
    dropped = sorted(set(usable) - set(kept))
    w = {k: weights[k] for k in kept}
    tot = sum(w.values())
    fair = sum(v * w[k] for k, v in kept.items()) / tot
    vals = np.array(list(kept.values()))
    disp = float(vals.std() / vals.mean()) if len(vals) > 1 and vals.mean() else 0.0
    for m in models:
        m["weight"] = (w.get(m["key"], 0.0) / tot) if m["key"] in kept else 0.0
        if m["key"] in dropped:
            m["reason"] = "outlier vs other models — excluded from blend"
    return {"available": True, "fair_value": fair, "low": float(vals.min()), "high": float(vals.max()), "median": med, "models": models, "kept": kept,
            "weights": {k: w[k] / tot for k in kept}, "dropped_outliers": dropped, "dispersion": disp, "confidence": float(max(0.2, 1 - disp)),
            "upside_pct": (fair / price - 1) if price else None, "profile": profile.primary, "tags": profile.tags, "notes": profile.notes, "n_models_used": len(kept)}


def blend(price, dcf_v, fcfe_v, comps_v, mc_median, rim_v, ddm_v, epv_v, profile: str = "default") -> dict[str, Any]:
    """Backward-compatible simple blend (kept for callers that don't have a Profile)."""
    from fa.compute.valuation.profile import Profile as _P
    res = {"dcf": {"available": dcf_v is not None, "value_per_share": dcf_v}, "fcfe": {"available": fcfe_v is not None, "value_per_share": fcfe_v},
           "comps": {"available": comps_v is not None, "value_per_share": comps_v}, "mc_dcf": {"available": mc_median is not None, "value_per_share": mc_median},
           "rim": {"available": rim_v is not None, "value_per_share": rim_v}, "ddm": {"available": ddm_v is not None, "value_per_share": ddm_v},
           "epv": {"available": epv_v is not None, "value_per_share": epv_v}}
    return assemble(price, _P("bank" if profile == "bank" else "mature_profitable", [profile]), res)

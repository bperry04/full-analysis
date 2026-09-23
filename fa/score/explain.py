"""Turn scored factors into the JSON the UI renders: horizon cards, ranked drivers, per-factor drill-down."""
from __future__ import annotations

from typing import Any

from fa.core.types import jsonable
from fa.score.factors import FactorValue


def factor_json(f: FactorValue) -> dict[str, Any]:
    return {
        "key": f.key, "label": f.label, "category": f.category, "status": f.status, "raw": jsonable(f.raw), "raw_display": f.raw_display, "unit": f.unit,
        "normalized": f.normalized, "percentile": f.percentile, "confidence": f.confidence, "horizons": f.horizons, "weight": f.weight,
        "contribution": f.contribution, "narrative": f.narrative, "comparison_basis": f.comparison_basis, "prov_ids": f.prov_ids,
        "inputs": [{"name": i.name, "value": jsonable(i.value), "unit": i.unit, "prov_id": i.prov_id, "formula": i.formula} for i in f.inputs],
        "history": jsonable(f.history),
    }


def to_json(scored: dict[str, Any]) -> dict[str, Any]:
    factors: list[FactorValue] = scored["factors"]
    fj = {f.key: factor_json(f) for f in factors}
    out: dict[str, Any] = {"factors": fj, "weights_hash": scored["weights_hash"], "disclaimer": scored["disclaimer"], "horizons": {}}
    for h in ("long", "medium", "short"):
        hs = scored[h]
        drivers = sorted([f for f in factors if f.contribution.get(h)], key=lambda f: -abs(f.contribution[h]))
        out["horizons"][h] = {
            **{k: v for k, v in hs.items() if k not in ("top_positive", "top_negative")},
            "top_positive": hs["top_positive"], "top_negative": hs["top_negative"],
            "drivers": [{"key": f.key, "label": f.label, "category": f.category, "contribution": f.contribution[h], "normalized": f.normalized,
                         "raw_display": f.raw_display, "narrative": f.narrative, "confidence": f.confidence} for f in drivers[:24]],
            "n_factors": sum(1 for f in factors if f.horizons.get(h, 0) > 0),
            "n_present": sum(1 for f in factors if f.horizons.get(h, 0) > 0 and f.normalized is not None),
        }
    return out

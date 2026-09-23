"""Coverage-aware weighted aggregation of factor values into long / medium / short horizon scores."""
from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

import yaml

from fa.core.settings import CONFIG_DIR
from fa.score.context import Ctx
from fa.score.factors import REGISTRY, FactorValue

log = logging.getLogger(__name__)
HORIZONS = ("long", "medium", "short")
WINDOWS = {"long": "6-24 months", "medium": "1-6 months", "short": "2-20 trading days (swing)"}


@lru_cache(maxsize=1)
def load_weights() -> dict[str, Any]:
    with open(CONFIG_DIR / "weights.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def weights_hash() -> str:
    return hashlib.sha256(json.dumps(load_weights(), sort_keys=True).encode()).hexdigest()[:8]


def evaluate_factors(ctx: Ctx) -> list[FactorValue]:
    out: list[FactorValue] = []
    for key, fd in REGISTRY.items():
        try:
            fv = fd.fn(ctx)
        except Exception as e:
            log.debug("factor %s failed: %s", key, e, exc_info=True)
            fv = None
        if fv is None:
            fv = FactorValue(key=key, label=fd.label, category=fd.category, status="MISSING", narrative="no data")
        fv.key, fv.label, fv.category = key, fd.label, fd.category
        fv.horizons = dict(fd.horizons)
        out.append(fv)
    return out


def score(ctx: Ctx) -> dict[str, Any]:
    cfg = load_weights()
    cat_w: dict[str, dict[str, float]] = cfg["categories"]
    f_mult: dict[str, float] = cfg.get("factors") or {}
    factors = evaluate_factors(ctx)
    by_cat: dict[str, list[FactorValue]] = {}
    for f in factors:
        by_cat.setdefault(f.category, []).append(f)

    result: dict[str, Any] = {}
    for h in HORIZONS:
        num = den = den_all = 0.0
        cat_scores: dict[str, dict[str, float | None]] = {}
        for cat, fs in by_cat.items():
            cw = float((cat_w.get(cat) or {}).get(h, 0))
            if cw <= 0:
                continue
            applicable = [f for f in fs if f.horizons.get(h, 0) > 0]
            if not applicable:
                continue
            base = cw / sum(f.horizons[h] * f_mult.get(f.key, 1.0) for f in applicable)
            c_num = c_den = 0.0
            for f in applicable:
                w = base * f.horizons[h] * f_mult.get(f.key, 1.0)
                den_all += w
                if f.normalized is None:
                    f.weight[h] = 0.0
                    f.contribution[h] = 0.0
                    continue
                w_eff = w * max(0.0, min(1.0, f.confidence))
                f.weight[h] = w_eff
                num += w_eff * f.normalized
                den += w_eff
                c_num += w_eff * f.normalized
                c_den += w_eff
            cat_scores[cat] = {"score": (50 + 50 * c_num / c_den) if c_den else None, "weight": cw, "coverage": (c_den / (base * sum(f.horizons[h] * f_mult.get(f.key, 1.0) for f in applicable))) if applicable else 0.0}
        raw_score = (50 + 50 * num / den) if den else None
        coverage = (den / den_all) if den_all else 0.0
        for f in factors:
            if f.weight.get(h) and den:
                f.contribution[h] = 50 * f.weight[h] * (f.normalized or 0.0) / den
        confidence = float(min(1.0, coverage) * (sum(f.confidence * f.weight.get(h, 0) for f in factors) / den if den else 0.0))
        min_cov = float(cfg.get("min_coverage_for_verdict", 0.5))
        verdict_ok = raw_score is not None and coverage >= min_cov
        result[h] = {
            "horizon": h, "window": WINDOWS[h], "score": raw_score if verdict_ok else None, "raw_score": raw_score, "label": _band(raw_score, cfg) if verdict_ok else "insufficient data",
            "coverage": coverage, "confidence": confidence, "category_scores": cat_scores,
            "top_positive": _top(factors, h, positive=True), "top_negative": _top(factors, h, positive=False),
            "missing": [[f.key, f.narrative or f.status] for f in factors if f.horizons.get(h, 0) > 0 and f.normalized is None],
        }
    result["factors"] = factors
    result["weights_hash"] = weights_hash()
    result["disclaimer"] = "Heuristic composite of weighted factors. Not backtested. Not a recommendation."
    return result


def _band(s: float | None, cfg: dict) -> str | None:
    if s is None:
        return None
    for lo, hi, label in cfg["bands"]:
        if lo <= s < hi:
            return label
    return None


def _top(factors: list[FactorValue], h: str, positive: bool, n: int = 8) -> list[str]:
    fs = [f for f in factors if f.contribution.get(h) and ((f.contribution[h] > 0) == positive)]
    fs.sort(key=lambda f: -abs(f.contribution[h]))
    return [f.key for f in fs[:n]]

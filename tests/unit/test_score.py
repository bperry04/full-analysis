from fa.score import library  # noqa: F401
from fa.score.context import Ctx
from fa.score.engine import score
from fa.score.factors import REGISTRY, bounded, scaled, zhist


def test_normalizers():
    assert bounded(5, 0, 10) == 0.0 and bounded(10, 0, 10) == 1.0 and bounded(-3, 0, 10) == -1.0
    assert bounded(0, 0, 10, direction=-1) == 1.0
    assert abs(scaled(0.0, 1.0)) < 1e-9 and 0.75 < scaled(1.0, 1.0) < 0.77
    n, p = zhist(3.0, [1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2], direction=-1)
    assert n < 0 and p == 1.0


def test_engine_with_empty_context_reports_no_verdict():
    out = score(Ctx("XYZ"))
    for h in ("long", "medium", "short"):
        assert out[h]["score"] is None
        assert out[h]["label"] == "insufficient data"
        assert out[h]["coverage"] == 0.0
    assert len(out["factors"]) == len(REGISTRY) > 50


def test_engine_partial_context_scores_and_coverage():
    ctx = Ctx("XYZ")
    ctx.sections["market"] = {"risk_appetite": {"score": 1.0, "label": "risk-on", "votes": 5}, "indices": {"SPY": {"above_50d": True, "above_200d": True}}, "vix": {"level": 14, "regime": "normal", "percentile_1y": 0.2}}
    ctx.prov["market"] = "p_0001"
    out = score(ctx)
    m = out["medium"]
    assert 0 < m["coverage"] < 0.3
    assert m["raw_score"] is not None and m["raw_score"] > 50
    assert m["score"] is None            # coverage below the verdict threshold → no verdict, raw score still reported
    f = {x.key: x for x in out["factors"]}
    assert f["macro.risk_appetite"].normalized == 1.0
    assert f["macro.risk_appetite"].contribution["medium"] > 0
    assert f["macro.risk_appetite"].prov_ids == ["p_0001"]

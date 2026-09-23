from fa.compute.events import impact as IM
from fa.report.excel import technicals_workbook, valuation_workbook


def _channels(tags, tlt_beta, beta_mkt=1.0):
    sens = {"univariate": {"TLT": {"beta": tlt_beta}, "UUP": {"beta": 0.0}, "USO": {"beta": 0.0}, "HYG": {"beta": 0.5}}}
    return IM.stock_channels(sens, tags, beta_mkt)


def test_hot_inflation_hurts_long_duration_growth_and_helps_banks():
    growth = IM.macro_event_impact("Core PCE Price Index", _channels(["high_growth"], tlt_beta=2.0, beta_mkt=1.6), 4)
    bank = IM.macro_event_impact("CPI (YoY)", _channels(["bank"], tlt_beta=-1.0, beta_mkt=0.9), 4)
    assert growth["if_strong"] == "negative" and growth["if_weak"] == "positive"
    assert bank["if_strong"] == "positive"
    assert growth["strong_means"] == "above consensus"


def test_jobless_claims_are_inverse_of_payrolls():
    ch = _channels(["high_growth"], tlt_beta=2.0, beta_mkt=1.5)
    claims = IM.macro_event_impact("Initial Jobless Claims", ch, 2)
    payrolls = IM.macro_event_impact("Nonfarm Payrolls", ch, 5)
    assert claims["kind"] == "labor_inverse" and payrolls["kind"] == "labor"
    assert claims["if_strong"] != payrolls["if_strong"]


def test_unknown_event_and_opex():
    assert IM.macro_event_impact("Some random thing", _channels([], 0.0), 1) is None
    opx = IM.company_event_impact({"type": "opex"}, {"max_pain": 100.0})
    assert opx["kind"] == "opex" and "100" in opx["why"]
    earn = IM.company_event_impact({"type": "earnings"}, {"implied_move": 0.08, "hist_move": 0.1})
    assert earn["if_strong"] == "positive" and earn["magnitude"] == 0.4


def test_narrative_impact_uses_sentiment_then_kind_default():
    assert IM.narrative_impact({"kind": "financing", "sentiment": None})["verdict"] == "likely negative"
    assert IM.narrative_impact({"kind": "financing", "sentiment": 0.6})["verdict"] == "likely positive"
    assert IM.narrative_impact({"kind": "strategy"})["verdict"] == "mixed / depends"


def test_workbooks_build_from_minimal_result():
    res = {"symbol": "XYZ", "valuation": {"inputs": {"price": {"value": 10.0, "source": "t"}, "shares": {"value": 100.0, "source": "t"}, "revenue_ttm": {"value": 1000.0, "source": "t"},
                                                      "extra": {}}, "blend": {"models": [{"key": "dcf", "label": "DCF", "applies": True, "weight": 1.0}]}, "profile": {"primary": "generic"}},
           "technicals": {"indicator_frame_1d": [{"ts": "2026-01-02T00:00:00", "close": 10.0, "sma_50": 9.5, "rsi_14": 55.0}], "bars": {"1d": [{"ts": "2026-01-02T00:00:00", "open": 9.9, "high": 10.1, "low": 9.8, "close": 10.0, "volume": 1000}]},
                          "intervals": {"1d": {"latest": {"rsi_14": 55.0}, "signals": {"trend": "up"}}}}}
    v = valuation_workbook(res)
    t = technicals_workbook(res, ["sma_50"], [["rsi_14"]])
    assert v[:2] == b"PK" and t[:2] == b"PK"
    assert valuation_workbook({"symbol": "EMPTY"})[:2] == b"PK"

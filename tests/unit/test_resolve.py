from datetime import date

import pandas as pd

from fa.compute.fundamentals.resolve import eval_formula, resolve_all


def _fact(tag, start, end, val, filed, form="10-K", accn="a1", unit="USD", taxonomy="us-gaap"):
    return dict(taxonomy=taxonomy, tag=tag, unit=unit, start=start, end=end, val=val, fy=end.year, fp="FY", form=form, filed=filed, accn=accn, frame=None)


def test_tag_choice_and_splice_and_restatement():
    facts = pd.DataFrame([
        # older years only under Revenues; newer under RevenueFromContract... → chosen tag = the one with better coverage, gap filled + spliced
        _fact("Revenues", date(2016, 1, 1), date(2016, 12, 31), 10.0, date(2017, 2, 1)),
        _fact("Revenues", date(2017, 1, 1), date(2017, 12, 31), 11.0, date(2018, 2, 1)),
        _fact("RevenueFromContractWithCustomerExcludingAssessedTax", date(2018, 1, 1), date(2018, 12, 31), 12.0, date(2019, 2, 1), accn="a2"),
        _fact("RevenueFromContractWithCustomerExcludingAssessedTax", date(2019, 1, 1), date(2019, 12, 31), 13.0, date(2020, 2, 1), accn="a3"),
        _fact("RevenueFromContractWithCustomerExcludingAssessedTax", date(2020, 1, 1), date(2020, 12, 31), 14.0, date(2021, 2, 1), accn="a4"),
        # restated 2019 in a later filing
        _fact("RevenueFromContractWithCustomerExcludingAssessedTax", date(2019, 1, 1), date(2019, 12, 31), 13.5, date(2021, 2, 1), accn="a4"),
        _fact("Assets", None, date(2020, 12, 31), 100.0, date(2021, 2, 1), accn="a4"),
    ])
    long, res, fye = resolve_all(facts)
    assert fye == 12
    r = res["revenue"]
    assert r.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert "Revenues" in r.spliced_from
    rev = long[(long["concept"] == "revenue") & (~long["as_filed"])].set_index("period_end")["value"]
    assert rev[date(2016, 12, 31)] == 10.0 and rev[date(2020, 12, 31)] == 14.0
    assert rev[date(2019, 12, 31)] == 13.5                     # latest filing wins for display
    asf = long[(long["concept"] == "revenue") & (long["as_filed"])]
    assert len(asf) == 1 and asf["value"].iloc[0] == 13.0        # as-filed value kept for point-in-time use
    flags = long[(long["concept"] == "revenue") & (long["period_end"] == date(2016, 12, 31))]["flags"].iloc[0]
    assert "TAG_SPLICE" in flags


def test_formula_optional_components():
    s = {"a": pd.Series([1.0, 2.0], index=[date(2024, 12, 31), date(2025, 12, 31)]), "b": pd.Series([10.0], index=[date(2025, 12, 31)])}
    out, used = eval_formula("?a + ?b", lambda k: s.get(k))
    assert list(out.values) == [1.0, 12.0]
    out2, _ = eval_formula("a - b", lambda k: s.get(k))
    assert list(out2.dropna().values) == [-8.0]                 # required component: 2024 drops (b missing)
    out3, _ = eval_formula("a + zzz", lambda k: s.get(k))
    assert out3 is None

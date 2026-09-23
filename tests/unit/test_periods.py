from datetime import date

import pandas as pd

from fa.compute.fundamentals.periods import classify, derive_quarters, fiscal_quarter_of, fiscal_year_end_month, fiscal_year_of, ttm


def test_classify():
    assert classify(date(2025, 1, 1), date(2025, 3, 31)) == "Q"
    assert classify(date(2025, 1, 1), date(2025, 6, 30)) == "H"
    assert classify(date(2025, 1, 1), date(2025, 9, 30)) == "NM"
    assert classify(date(2024, 10, 1), date(2025, 9, 27)) == "FY"
    assert classify(None, date(2025, 9, 27)) == "INSTANT"


def test_fiscal_year_apple_style():
    fye = fiscal_year_end_month([date(2023, 9, 30), date(2024, 9, 28), date(2025, 9, 27)])
    assert fye == 9
    assert fiscal_year_of(date(2025, 12, 27), 9) == 2026     # Q1 FY26
    assert fiscal_quarter_of(date(2025, 12, 27), 9) == 1
    assert fiscal_quarter_of(date(2026, 6, 27), 9) == 3
    assert fiscal_quarter_of(date(2025, 9, 27), 9) == 4
    # 52/53-week years can end a few days into the next month
    assert fiscal_year_end_month([date(2022, 10, 1), date(2023, 9, 30)]) == 9


def test_ytd_to_quarter_derivation():
    # filer reports Q1 directly, then 6M and 9M cumulative, then FY — Q2..Q4 must be derived by differencing
    rows = [
        dict(period_start=date(2025, 1, 1), period_end=date(2025, 3, 31), value=100.0, kind="Q"),
        dict(period_start=date(2025, 1, 1), period_end=date(2025, 6, 30), value=230.0, kind="H"),
        dict(period_start=date(2025, 1, 1), period_end=date(2025, 9, 30), value=390.0, kind="NM"),
        dict(period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), value=600.0, kind="FY"),
    ]
    q = derive_quarters(pd.DataFrame(rows))
    vals = dict(zip(q["period_end"], q["value"]))
    assert vals[date(2025, 3, 31)] == 100.0
    assert vals[date(2025, 6, 30)] == 130.0
    assert vals[date(2025, 9, 30)] == 160.0
    assert vals[date(2025, 12, 31)] == 210.0
    assert q[q["period_end"] == date(2025, 12, 31)]["derived"].iloc[0]
    v, end, ends = ttm(q)
    assert v == 600.0 and end == date(2025, 12, 31) and len(ends) == 4


def test_ttm_requires_consecutive_quarters():
    rows = [dict(period_start=date(2024, 1, 1), period_end=date(2024, 3, 31), value=1.0, kind="Q", derived=False),
            dict(period_start=date(2025, 1, 1), period_end=date(2025, 3, 31), value=1.0, kind="Q", derived=False),
            dict(period_start=date(2025, 4, 1), period_end=date(2025, 6, 30), value=1.0, kind="Q", derived=False),
            dict(period_start=date(2025, 7, 1), period_end=date(2025, 9, 30), value=1.0, kind="Q", derived=False)]
    assert ttm(pd.DataFrame(rows))[0] is None

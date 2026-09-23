from datetime import date, datetime, timezone

import pandas as pd

from fa.compute.events.merge import opex_dates, third_friday
from fa.compute.sentiment.lexicon import score as sent
from fa.compute.sentiment.news import relevance
from fa.store import lake


def test_merge_partition_dedupes_and_snapshot_is_immutable(tmp_path, monkeypatch):
    from fa.core import settings as S
    monkeypatch.setenv("FA_DATA_ROOT", str(tmp_path))
    S.get_settings.cache_clear()
    df1 = pd.DataFrame({"ts": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True), "close": [1.0, 2.0]})
    df2 = pd.DataFrame({"ts": pd.to_datetime(["2026-01-02", "2026-01-03"], utc=True), "close": [2.5, 3.0]})
    lake.merge_partition("ohlcv", df1, {"interval": "1d", "symbol": "T", "year": 2026}, keys=["ts"])
    n = lake.merge_partition("ohlcv", df2, {"interval": "1d", "symbol": "T", "year": 2026}, keys=["ts"])
    out = lake.read_partitions("ohlcv", {"interval": "1d", "symbol": "T"})
    assert n == 3 and len(out) == 3
    assert float(out.sort_values("ts")["close"].iloc[1]) == 2.5      # keep last
    p1 = lake.write_snapshot("options_snap", df1, {"symbol": "T", "dt": "2026-01-01"}, ts=datetime(2026, 1, 1, 21, tzinfo=timezone.utc))
    p2 = lake.write_snapshot("options_snap", df2, {"symbol": "T", "dt": "2026-01-01"}, ts=datetime(2026, 1, 1, 22, tzinfo=timezone.utc))
    assert p1 != p2 and len(lake.list_snapshots("options_snap", {"symbol": "T"})) == 2
    S.get_settings.cache_clear()


def test_opex_and_third_friday():
    assert third_friday(2026, 9) == date(2026, 9, 18)
    d = opex_dates(date(2026, 9, 1), months=2)
    assert d[0]["date"] == date(2026, 9, 18) and d[0]["label"] == "Quad witching"


def test_financial_lexicon_beats_vader_on_finance_words():
    assert sent("Company beats estimates, raises guidance") > 0.3
    assert sent("Analyst downgrades stock after guidance cut") < -0.3


def test_news_relevance_filter():
    df = pd.DataFrame({"title": ["Apple unveils new iPhone", "Pixalate launches CTV product", "Tech stocks rally"], "summary": ["", "…including Apple TV", ""], "source": ["g", "g", "g"]})
    r = relevance(df, "AAPL", "Apple Inc.")
    assert list(r) == [1.0, 0.5, 0.0]

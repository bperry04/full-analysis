"""US Treasury: daily par yield curve CSV (home.treasury.gov) and Fiscal Data API series. No key."""
from __future__ import annotations

import io
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.errors import NoData
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

YC = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
FISCAL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

TENOR_MAP = {"1 Mo": "DGS1MO", "2 Mo": "DGS2MO", "3 Mo": "DGS3MO", "4 Mo": "DGS4MO", "6 Mo": "DGS6MO", "1 Yr": "DGS1", "2 Yr": "DGS2",
             "3 Yr": "DGS3", "5 Yr": "DGS5", "7 Yr": "DGS7", "10 Yr": "DGS10", "20 Yr": "DGS20", "30 Yr": "DGS30"}

# a few macro series ids this provider can serve as a FRED fallback
SERIES = {
    "DGS10": ("yield_curve", "DGS10"), "DGS2": ("yield_curve", "DGS2"), "DGS3MO": ("yield_curve", "DGS3MO"),
    "DGS30": ("yield_curve", "DGS30"), "DGS5": ("yield_curve", "DGS5"), "DGS1": ("yield_curve", "DGS1"),
    "T10Y2Y": ("spread", ("DGS10", "DGS2")), "T10Y3M": ("spread", ("DGS10", "DGS3MO")),
}


class Treasury(Provider):
    name = "treasury"
    tier = Tier.A
    latency = Latency.RELEASE
    license_note = "US Treasury public data"

    def capabilities(self):
        return {N.YIELD_CURVE: self.yield_curve, N.MACRO_SERIES: self.series}

    async def _curve_year(self, year: int) -> pd.DataFrame:
        url = YC.format(year=year)
        text = await http.get_text(self.name, url, params={"type": "daily_treasury_yield_curve", "field_tdr_date_value": str(year), "page": "", "_format": "csv"}, timeout=40)
        df = pd.read_csv(io.StringIO(text))
        df = df.rename(columns={"Date": "date", **TENOR_MAP})
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        keep = ["date"] + [c for c in TENOR_MAP.values() if c in df.columns]
        return df[keep].dropna(subset=["date"])

    async def yield_curve(self, years: int = 2, **_: Any) -> Payload:
        y = date.today().year
        frames = []
        for yy in range(y - years + 1, y + 1):
            try:
                frames.append(await self._curve_year(yy))
            except Exception:
                continue
        if not frames:
            raise NoData(self.name, "no yield curve")
        df = pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
        return Payload(df, YC.format(year=y), row_count=len(df),
                       as_of=datetime.combine(df["date"].max(), datetime.min.time(), tzinfo=timezone.utc))

    async def series(self, series_id: str, **_: Any) -> Payload:
        spec = SERIES.get(series_id)
        if not spec:
            raise NoData(self.name, f"{series_id} not served by treasury")
        p = await self.yield_curve(years=5)
        yc = p.data
        if spec[0] == "yield_curve":
            col = spec[1]
            df = yc[["date", col]].rename(columns={col: "value"})
        else:
            a, b = spec[1]
            df = pd.DataFrame({"date": yc["date"], "value": yc[a] - yc[b]})
        df = df.dropna()
        df["series_id"] = series_id
        return Payload(df, p.endpoint, row_count=len(df), as_of=p.as_of)


PROVIDER = Treasury()

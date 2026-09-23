"""FRED (St. Louis Fed) keyed API: any macro series, the Treasury curve, and the release calendar."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.errors import NoData
from fa.core.settings import get_settings
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

BASE = "https://api.stlouisfed.org/fred"
CURVE = ["DGS1MO", "DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30"]


class Fred(Provider):
    name = "fred"
    tier = Tier.A
    latency = Latency.RELEASE
    license_note = "FRED API (St. Louis Fed)"

    def capabilities(self):
        return {N.MACRO_SERIES: self.series, N.YIELD_CURVE: self.yield_curve}

    async def series(self, series_id: str, start: str | None = None, **_: Any) -> Payload:
        key = get_settings().fred_api_key
        if not key:
            raise NoData(self.name, "FA_FRED_API_KEY not set")
        params: dict[str, Any] = {"series_id": series_id, "api_key": key, "file_type": "json"}
        if start:
            params["observation_start"] = start
        url = f"{BASE}/series/observations"
        j = await http.get_json(self.name, url, params=params, timeout=30)
        obs = j.get("observations") or []
        if not obs:
            raise NoData(self.name, f"no observations for {series_id}")
        df = pd.DataFrame(obs)[["date", "value"]]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.dropna(subset=["value"])
        df["series_id"] = series_id
        endpoint = f"{url}?series_id={series_id}"
        return Payload(df, endpoint, raw=j, row_count=len(df),
                       as_of=datetime.combine(df["date"].max(), datetime.min.time(), tzinfo=timezone.utc))

    async def yield_curve(self, **_: Any) -> Payload:
        frames = []
        for sid in CURVE:
            try:
                p = await self.series(sid, start=str(date.today().replace(year=date.today().year - 2)))
                frames.append(p.data.rename(columns={"value": sid})[["date", sid]].set_index("date"))
            except Exception:
                continue
        if not frames:
            raise NoData(self.name, "no curve data")
        df = pd.concat(frames, axis=1).sort_index().ffill().reset_index()
        return Payload(df, f"{BASE}/series/observations?series_id=DGS*", row_count=len(df))


PROVIDER = Fred()

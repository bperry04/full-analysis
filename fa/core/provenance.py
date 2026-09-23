"""Provenance: who gave us this data, when, how fresh, and what was tried before it worked.

One `Provenance` record is minted per successful fetch. Values reference it by short id (`p_0007`).
The ledger is per analysis run; the API returns the whole dict once at the top level.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from fa.core.types import Latency, Tier


@dataclass(slots=True)
class Attempt:
    provider: str
    result: str            # ok | skipped | failed | timeout | invalid | circuit_open
    reason: str = ""
    duration_ms: int = 0


@dataclass(slots=True)
class Provenance:
    prov_id: str
    need: str
    provider: str
    endpoint: str
    fetched_at: datetime
    as_of: datetime | None
    latency: Latency
    tier: Tier
    is_delayed: bool = False
    delay_seconds: int | None = None
    fallback_depth: int = 0
    from_cache: bool = False
    cache_age_s: float = 0.0
    row_count: int | None = None
    duration_ms: int = 0
    payload_sha256: str | None = None
    raw_path: str | None = None
    quality_flags: list[str] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    license_note: str = ""
    derived_from: list[str] = field(default_factory=list)   # prov_ids of inputs, for COMPUTED

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["fetched_at"] = self.fetched_at.isoformat()
        d["as_of"] = self.as_of.isoformat() if self.as_of else None
        d["latency"] = str(self.latency)
        d["tier"] = str(self.tier)
        return d


class Ledger:
    """Mints provenance ids for one run and holds the records."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._counter = itertools.count(1)
        self.records: dict[str, Provenance] = {}

    def mint(
        self,
        need: str,
        provider: str,
        endpoint: str,
        latency: Latency,
        tier: Tier,
        *,
        as_of: datetime | None = None,
        fetched_at: datetime | None = None,
        **kw: Any,
    ) -> Provenance:
        pid = f"p_{next(self._counter):04d}"
        rec = Provenance(
            prov_id=pid,
            need=need,
            provider=provider,
            endpoint=endpoint,
            fetched_at=fetched_at or datetime.now(timezone.utc),
            as_of=as_of,
            latency=latency,
            tier=tier,
            is_delayed=latency in (Latency.DELAYED_15,),
            delay_seconds=900 if latency == Latency.DELAYED_15 else (0 if latency == Latency.REALTIME else None),
            **kw,
        )
        self.records[pid] = rec
        return rec

    def computed(self, need: str, *inputs: str | None, note: str = "") -> Provenance:
        """A provenance record for a value derived from other tracked values."""
        ins = [i for i in inputs if i]
        return self.mint(
            need, "computed", note or f"derived({','.join(ins)})", Latency.COMPUTED, Tier.A, derived_from=ins
        )

    def to_json(self) -> dict[str, Any]:
        return {k: v.to_json() for k, v in self.records.items()}

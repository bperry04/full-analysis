"""Provider contract.

A provider exposes `capabilities`: {need: async callable(**params) -> Payload}. The router handles
caching, rate limiting, circuit breaking, validation, archiving and provenance — providers only fetch
and normalize.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable

from fa.core.types import Latency, Tier


@dataclass(slots=True)
class Payload:
    data: Any                                  # DataFrame | dict | list
    endpoint: str                              # exact URL or call description
    as_of: datetime | None = None              # what time the source says the data represents
    raw: bytes | str | dict | list | None = None   # archived verbatim
    row_count: int | None = None
    latency: Latency | None = None             # override provider default (e.g. IBKR delayed)
    flags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


Fetcher = Callable[..., Awaitable[Payload]]


class Provider:
    name: str = "base"
    tier: Tier = Tier.B
    latency: Latency = Latency.DELAYED_15
    license_note: str = ""

    def capabilities(self) -> dict[str, Fetcher]:
        return {}

    async def healthy(self) -> bool:
        return True

    def condition_context(self) -> dict[str, Any]:
        """Extra facts for route conditions (e.g. ibkr_connected)."""
        return {}

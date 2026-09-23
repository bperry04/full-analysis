"""Pydantic models for the declarative source registry (config/sources.yaml)."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from fa.core.types import Latency, Tier


class Mode(StrEnum):
    FAILOVER = "failover"     # first binding that validates wins
    OVERLAY = "overlay"       # base wins, overlay bindings update a subset of rows/fields
    CONSENSUS = "consensus"   # call several, compare a field, flag disagreement


class ProviderSpec(BaseModel):
    tier: Tier = Tier.B
    latency: Latency = Latency.DELAYED_15
    requires: list[str] = Field(default_factory=list)   # condition names that must hold
    license_note: str = ""


class Binding(BaseModel):
    provider: str
    when: str | None = None                  # condition expression
    timeout_s: float = 30.0
    min_rows: int = 0
    degraded: bool = False                   # mark results DEGRADED even when it is the first to succeed
    latency: Latency | None = None           # override provider default
    # overlay only
    key: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    # consensus only
    compare: str | None = None


class Route(BaseModel):
    mode: Mode = Mode.FAILOVER
    base: list[Binding]
    overlay: list[Binding] = Field(default_factory=list)
    tolerance_pct: float = 2.0
    ttl_rth_s: int | None = None
    ttl_closed_s: int | None = None


class Registry(BaseModel):
    providers: dict[str, ProviderSpec]
    routes: dict[str, Route]

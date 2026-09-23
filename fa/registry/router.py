"""The router: resolves a data need to the best available provider, with failover / overlay / consensus.

    result = await router.fetch(N.OPTION_CHAIN, ledger, symbol="AAPL")
    result.data   -> DataFrame / dict
    result.prov   -> Provenance (also registered in the ledger)

Every fetch: condition check -> circuit check -> cache -> rate limit -> call -> validate -> archive -> provenance.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import pandas as pd

from fa.core import archive
from fa.core.errors import AllRoutesFailed, NoData, RealtimeRequired
from fa.core.provenance import Attempt, Ledger, Provenance
from fa.core.settings import get_settings
from fa.core.types import Latency, Q, Tier
from fa.providers.base import Payload, Provider
from fa.registry import cache as C
from fa.registry.circuit import CircuitBreaker
from fa.registry.conditions import evaluate
from fa.registry.loader import load_registry
from fa.registry.spec import Binding, Mode, Registry

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Result:
    data: Any
    prov: Provenance
    provider: str
    from_cache: bool = False
    candidates: list[dict] = field(default_factory=list)   # consensus mode: all provider answers

    @property
    def p(self) -> str:
        return self.prov.prov_id


class Router:
    def __init__(self, registry: Registry, providers: dict[str, Provider]):
        self.registry = registry
        self.providers = providers
        self.circuit = CircuitBreaker()
        self.fetch_log: list[dict] = []

    # ------------------------------------------------------------------ public
    def context(self) -> dict[str, Any]:
        ctx: dict[str, Any] = {}
        for p in self.providers.values():
            try:
                ctx.update(p.condition_context())
            except Exception:
                pass
        return ctx

    async def fetch(self, need: str, ledger: Ledger, *, force_refresh: bool = False, **params: Any) -> Result:
        route = self.registry.routes.get(need)
        if route is None:
            raise AllRoutesFailed(need, [Attempt("registry", "failed", "no route configured")])
        ctx = self.context()
        attempts: list[Attempt] = []
        successes: list[tuple[Binding, int, Result]] = []

        for depth, binding in enumerate(route.base):
            res = await self._try_binding(need, binding, depth, ledger, params, ctx, attempts, force_refresh, route)
            if res is None:
                continue
            successes.append((binding, depth, res))
            if route.mode != Mode.CONSENSUS:
                break

        if not successes:
            self._log(need, params, None, attempts)
            raise AllRoutesFailed(need, attempts)

        binding, depth, result = successes[0]
        result.prov.attempts = attempts
        # fallback depth counts providers that actually FAILED before this one answered; a provider skipped
        # because its condition is false (IB Gateway not running) is unavailable, not a failure.
        real_failures = sum(1 for a in attempts if a.result in ("failed", "timeout", "invalid", "circuit_open", "nodata"))
        result.prov.fallback_depth = real_failures
        if real_failures > 0 or binding.degraded:
            _flag(result.prov, Q.DEGRADED)

        if route.mode == Mode.CONSENSUS and len(successes) > 1:
            self._consensus(route, successes, result)
        if route.mode == Mode.OVERLAY and route.overlay:
            await self._overlay(need, route, result, ledger, params, ctx)

        if get_settings().require_realtime and result.prov.latency != Latency.REALTIME:
            if any(self.registry.providers[b.provider].latency == Latency.REALTIME for b in route.base):
                raise RealtimeRequired(f"{need}: only {result.prov.latency} data available from {result.provider}")

        self._log(need, params, result, attempts)
        return result

    async def health(self) -> list[dict]:
        out = []
        ctx = self.context()
        for name, spec in self.registry.providers.items():
            p = self.providers.get(name)
            avail = p is not None and all(evaluate(r, ctx) for r in spec.requires)
            out.append(
                {
                    "provider": name, "loaded": p is not None, "available": bool(avail),
                    "tier": str(spec.tier), "latency": str(spec.latency), "requires": spec.requires,
                    "needs": sorted(p.capabilities().keys()) if p else [],
                }
            )
        return out

    # ------------------------------------------------------------------ internals
    async def _try_binding(
        self, need: str, b: Binding, depth: int, ledger: Ledger, params: dict, ctx: dict,
        attempts: list[Attempt], force_refresh: bool, route,
    ) -> Result | None:
        spec = self.registry.providers[b.provider]
        provider = self.providers.get(b.provider)
        if provider is None:
            attempts.append(Attempt(b.provider, "skipped", "provider not loaded"))
            return None
        cond = " and ".join([*spec.requires, *( [b.when] if b.when else [])])
        if cond and not evaluate(cond, ctx):
            attempts.append(Attempt(b.provider, "skipped", f"condition '{cond}' false"))
            return None
        fetcher = provider.capabilities().get(need)
        if fetcher is None:
            attempts.append(Attempt(b.provider, "skipped", f"does not serve {need}"))
            return None
        if self.circuit.is_open(b.provider, need):
            attempts.append(Attempt(b.provider, "circuit_open", self.circuit._get(b.provider, need).last_error))
            return None

        latency = b.latency or spec.latency
        key = C.key_for(need, b.provider, params)
        ttl = C.ttl_for(need, (route.ttl_rth_s, route.ttl_closed_s))
        if not force_refresh:
            hit = C.get(key)
            if hit is not None:
                data, meta, age = hit
                prov = ledger.mint(
                    need, b.provider, meta["endpoint"], Latency(meta.get("latency", latency)), spec.tier,
                    as_of=_parse_dt(meta.get("as_of")), fetched_at=_parse_dt(meta.get("fetched_at")),
                    from_cache=True, cache_age_s=round(age, 1), row_count=meta.get("row_count"),
                    payload_sha256=meta.get("sha"), raw_path=meta.get("raw_path"),
                    quality_flags=list(meta.get("flags", [])), license_note=spec.license_note,
                )
                attempts.append(Attempt(b.provider, "ok", f"cache hit age={age:.0f}s"))
                return Result(data, prov, b.provider, from_cache=True)

        t0 = time.monotonic()
        try:
            payload: Payload = await asyncio.wait_for(fetcher(**params), timeout=b.timeout_s)
        except asyncio.TimeoutError:
            ms = int((time.monotonic() - t0) * 1000)
            attempts.append(Attempt(b.provider, "timeout", f"> {b.timeout_s}s", ms))
            self.circuit.record_failure(b.provider, need, "timeout")
            return None
        except NoData as e:
            ms = int((time.monotonic() - t0) * 1000)
            attempts.append(Attempt(b.provider, "nodata", str(e)[:200], ms))
            return None            # not an outage; do not trip the circuit
        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            log.debug("provider %s failed for %s: %s", b.provider, need, e, exc_info=True)
            attempts.append(Attempt(b.provider, "failed", f"{type(e).__name__}: {str(e)[:200]}", ms))
            self.circuit.record_failure(b.provider, need, f"{type(e).__name__}: {e}")
            return None
        ms = int((time.monotonic() - t0) * 1000)

        rows = payload.row_count
        if rows is None and isinstance(payload.data, pd.DataFrame):
            rows = len(payload.data)
        if b.min_rows and (rows or 0) < b.min_rows:
            attempts.append(Attempt(b.provider, "invalid", f"{rows} rows < min {b.min_rows}", ms))
            self.circuit.record_failure(b.provider, need, f"too few rows ({rows})")
            return None

        raw_path = sha = None
        if payload.raw is not None:
            try:
                nm = str(params.get("symbol") or params.get("series_id") or params.get("cik") or need)
                raw_path, sha = archive.write_raw(b.provider, f"{need}_{nm}", payload.raw)
            except Exception as e:
                log.warning("archive failed: %s", e)

        lat = payload.latency or latency
        fetched_at = datetime.now(timezone.utc)
        prov = ledger.mint(
            need, b.provider, payload.endpoint, lat, spec.tier, as_of=payload.as_of, fetched_at=fetched_at,
            row_count=rows, duration_ms=ms, payload_sha256=sha, raw_path=raw_path,
            quality_flags=list(payload.flags), license_note=spec.license_note,
        )
        meta = {
            "endpoint": payload.endpoint, "as_of": payload.as_of.isoformat() if payload.as_of else None,
            "fetched_at": fetched_at.isoformat(), "row_count": rows, "sha": sha, "raw_path": raw_path,
            "latency": str(lat), "flags": list(payload.flags), "symbol": params.get("symbol"),
        }
        C.put(key, payload.data, meta, ttl)
        self.circuit.record_success(b.provider, need, ms)
        attempts.append(Attempt(b.provider, "ok", "", ms))
        return Result(payload.data, prov, b.provider)

    def _consensus(self, route, successes: list[tuple[Binding, int, Result]], primary: Result) -> None:
        field_name = successes[0][0].compare
        vals = []
        for b, _, r in successes:
            v = _extract(r.data, b.compare or field_name)
            asof = _extract(r.data, "settlement_date") or _extract(r.data, "as_of")
            vals.append({"provider": r.provider, "value": _pyfloat(v), "as_of": str(asof) if asof else None, "prov_id": r.prov.prov_id})
        primary.candidates = vals
        # only compare answers that describe the same point in time (e.g. same settlement date)
        ref_asof = vals[0]["as_of"]
        comparable = [v for v in vals if v["as_of"] == ref_asof or v["as_of"] is None or ref_asof is None]
        nums = [v["value"] for v in comparable if isinstance(v["value"], (int, float)) and v["value"]]
        if len(nums) >= 2:
            base = nums[0]
            worst = max(abs(x - base) / abs(base) * 100 for x in nums[1:])
            if worst > route.tolerance_pct:
                _flag(primary.prov, Q.SOURCE_DISAGREEMENT)
                primary.prov.attempts.append(Attempt("consensus", "invalid", f"disagreement {worst:.1f}% > {route.tolerance_pct}%"))

    async def _overlay(self, need: str, route, result: Result, ledger: Ledger, params: dict, ctx: dict) -> None:
        if not isinstance(result.data, pd.DataFrame):
            return
        base = result.data
        if "prov_id" not in base.columns:
            base = base.assign(prov_id=result.prov.prov_id)
        for b in route.overlay:
            spec = self.registry.providers[b.provider]
            provider = self.providers.get(b.provider)
            cond = " and ".join([*spec.requires, *([b.when] if b.when else [])])
            if provider is None or (cond and not evaluate(cond, ctx)):
                continue
            fetcher = provider.capabilities().get(need)
            if fetcher is None or self.circuit.is_open(b.provider, need):
                continue
            t0 = time.monotonic()
            try:
                payload: Payload = await asyncio.wait_for(fetcher(**params, base=base), timeout=b.timeout_s)
            except Exception as e:
                ms = int((time.monotonic() - t0) * 1000)
                result.prov.attempts.append(Attempt(f"overlay:{b.provider}", "failed", str(e)[:200], ms))
                self.circuit.record_failure(b.provider, need, str(e))
                continue
            ms = int((time.monotonic() - t0) * 1000)
            ov = payload.data
            if not isinstance(ov, pd.DataFrame) or ov.empty or not b.key:
                continue
            oprov = ledger.mint(
                need, b.provider, payload.endpoint, payload.latency or spec.latency, spec.tier,
                as_of=payload.as_of, row_count=len(ov), duration_ms=ms, license_note=spec.license_note,
            )
            fields = [f for f in (b.fields or ov.columns) if f in ov.columns and f in base.columns]
            merged = base.set_index(b.key)
            ovi = ov.drop_duplicates(b.key).set_index(b.key)[fields].apply(pd.to_numeric, errors="coerce")
            common = merged.index.intersection(ovi.index)
            # only replace where the overlay actually has a value — a faster source with no data must never blank a good one
            touched = 0
            if len(common):
                sub = ovi.loc[common]
                has_any = sub.notna().any(axis=1)
                rows_ok = common[has_any.values]
                for f in fields:
                    vals = sub.loc[rows_ok, f]
                    ok = vals.notna()
                    if ok.any():
                        merged.loc[rows_ok[ok.values], f] = vals[ok].astype(float).values
                if len(rows_ok):
                    merged.loc[rows_ok, "prov_id"] = oprov.prov_id
                    touched = int(len(rows_ok))
            base = merged.reset_index()
            if touched == 0:
                oprov.quality_flags.append("NO_DATA")
                result.prov.attempts.append(Attempt(f"overlay:{b.provider}", "nodata", "overlay returned no values (market data not subscribed?)", ms))
            else:
                result.prov.attempts.append(Attempt(f"overlay:{b.provider}", "ok", f"{touched} rows updated", ms))
                self.circuit.record_success(b.provider, need, ms)
        result.data = base

    def _log(self, need: str, params: dict, result: Result | None, attempts: list[Attempt]) -> None:
        self.fetch_log.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(), "need": need,
                "symbol": params.get("symbol"), "provider": result.provider if result else None,
                "ok": result is not None, "from_cache": result.from_cache if result else None,
                "attempts": [asdict(a) for a in attempts],
            }
        )
        self.fetch_log = self.fetch_log[-5000:]


def _flag(prov: Provenance, q: Q) -> None:
    if str(q) not in prov.quality_flags:
        prov.quality_flags.append(str(q))


def _pyfloat(v: Any) -> Any:
    try:
        if v is None:
            return None
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return v


def _extract(data: Any, field_name: str | None) -> Any:
    if not field_name:
        return None
    if isinstance(data, dict):
        return data.get(field_name)
    if isinstance(data, pd.DataFrame) and field_name in data.columns and len(data):
        return data[field_name].iloc[0]
    return None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


# ---------------------------------------------------------------------- singleton
def _build_providers() -> dict[str, Provider]:
    """Instantiate every provider module; failure to construct one never blocks the rest."""
    from fa.providers import (
        cboe, finra, fred, ibkr, nasdaq, rss, sec_edgar, stocktwits, stooq, treasury, yahoo, reddit, finnhub, schwab,
    )
    out: dict[str, Provider] = {}
    for mod in (sec_edgar, cboe, yahoo, nasdaq, finra, fred, treasury, stooq, rss, stocktwits, reddit, finnhub, ibkr, schwab):
        try:
            p = mod.PROVIDER
            out[p.name] = p
        except Exception as e:  # pragma: no cover
            log.warning("provider %s failed to load: %s", mod.__name__, e)
    return out


@lru_cache(maxsize=1)
def get_router() -> Router:
    return Router(load_registry(), _build_providers())

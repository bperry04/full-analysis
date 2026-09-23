"""Runs the section DAG concurrently with per-section timeouts, emits progress, assembles and persists the result.

Stages (each stage's sections run in parallel; a stage starts when the previous one finishes):
  0  profile, quote
  1  fundamentals, technicals, market, analysts, ownership, shorts, news, social
  2  risk, options, orderflow, events
  3  valuation
  4  scoring
A failed section becomes {"status": "failed"} and everything else still completes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import pandas as pd

from fa import __version__
from fa.core.provenance import Ledger
from fa.core.settings import get_settings
from fa.core.types import jsonable
from fa.pipeline import sections as S
from fa.pipeline.progress import Progress
from fa.registry.router import get_router
from fa.score import library  # noqa: F401  (registers factors)
from fa.score.context import Ctx
from fa.score.engine import score as score_engine
from fa.score.explain import to_json as score_json
from fa.store import duck, persist

log = logging.getLogger(__name__)

STAGES: list[list[tuple[str, Callable[[S.Run], Awaitable[dict]], float]]] = [
    [("profile", S.profile, 60), ("quote", S.quote, 30)],
    [("fundamentals", S.fundamentals, 180), ("technicals", S.technicals, 180), ("market", S.market, 240), ("analysts", S.analysts, 90),
     ("ownership", S.ownership, 90), ("shorts", S.shorts, 90), ("news", S.news, 90), ("social", S.social, 90)],
    [("risk", S.risk, 60), ("options", S.options, 240), ("flow", S.orderflow, 120), ("events", S.events, 120)],
    [("valuation", S.valuation, 240), ("narrative", S.narrative, 60)],
    [("impact", S.impact, 30)],
]

RUNS: dict[str, "AnalysisRun"] = {}


class AnalysisRun:
    def __init__(self, symbol: str, depth: str = "standard", sections: list[str] | None = None):
        self.run_id = f"r_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{symbol.upper()}_{uuid.uuid4().hex[:4]}"
        self.symbol = symbol.upper()
        self.depth = depth
        self.only = set(sections) if sections else None
        self.progress = Progress()
        self.ledger = Ledger(self.run_id)
        self.ctx = Ctx(self.symbol)
        self.run = S.Run(self.symbol, depth, get_router(), self.ledger, self.ctx)
        self.status = "running"
        self.started = datetime.now(timezone.utc)
        self.finished: datetime | None = None
        self.section_status: dict[str, dict[str, Any]] = {}
        self.result: dict[str, Any] | None = None
        self.task: asyncio.Task | None = None
        RUNS[self.run_id] = self

    # ------------------------------------------------------------------ execution
    async def execute(self) -> dict[str, Any]:
        self.progress.emit("run.start", run_id=self.run_id, symbol=self.symbol, depth=self.depth,
                           sections=[n for st in STAGES for n, _, _ in st if self._wanted(n)] + ["scoring"])
        for stage in STAGES:
            await asyncio.gather(*[self._section(n, fn, to) for n, fn, to in stage if self._wanted(n)])
        await self._scoring()
        self.finished = datetime.now(timezone.utc)
        self.status = "complete" if all(s["status"] == "ok" for s in self.section_status.values()) else "partial"
        self.result = self._assemble()
        self._persist()
        self.progress.emit("run.done", run_id=self.run_id, status=self.status, total_ms=int((self.finished - self.started).total_seconds() * 1000))
        return self.result

    def _wanted(self, name: str) -> bool:
        return self.only is None or name in self.only or name in ("profile", "quote")

    async def _section(self, name: str, fn, timeout: float) -> None:
        self.progress.emit("section.start", section=name)
        t0 = time.monotonic()
        try:
            payload = await asyncio.wait_for(fn(self.run), timeout=timeout)
            self.ctx.sections[name] = payload
            ms = int((time.monotonic() - t0) * 1000)
            self.section_status[name] = {"status": "ok", "ms": ms, "prov_id": payload.get("prov_id") if isinstance(payload, dict) else None}
            self.progress.emit("section.done", section=name, ms=ms, payload=jsonable(_slim(payload)))
        except asyncio.TimeoutError:
            ms = int((time.monotonic() - t0) * 1000)
            self.section_status[name] = {"status": "failed", "ms": ms, "reason": f"timeout after {timeout}s"}
            self.progress.emit("section.error", section=name, ms=ms, reason=f"timeout after {timeout}s")
        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            log.warning("section %s failed: %s", name, e, exc_info=True)
            self.section_status[name] = {"status": "failed", "ms": ms, "reason": f"{type(e).__name__}: {str(e)[:300]}"}
            self.progress.emit("section.error", section=name, ms=ms, reason=f"{type(e).__name__}: {str(e)[:300]}")

    async def _scoring(self) -> None:
        self.progress.emit("section.start", section="scoring")
        t0 = time.monotonic()
        try:
            scored = await asyncio.to_thread(score_engine, self.ctx)
            js = score_json(scored)
            self.ctx.sections["scores"] = js
            ms = int((time.monotonic() - t0) * 1000)
            self.section_status["scoring"] = {"status": "ok", "ms": ms}
            self.progress.emit("score.update", **{h: {k: js["horizons"][h][k] for k in ("score", "label", "coverage", "confidence")} for h in ("long", "medium", "short")})
            self.progress.emit("section.done", section="scoring", ms=ms, payload=js)
        except Exception as e:
            log.exception("scoring failed")
            self.section_status["scoring"] = {"status": "failed", "ms": int((time.monotonic() - t0) * 1000), "reason": str(e)[:300]}
            self.progress.emit("section.error", section="scoring", reason=str(e)[:300])

    # ------------------------------------------------------------------ result
    def _assemble(self) -> dict[str, Any]:
        secs = {k: jsonable(_slim(v)) for k, v in self.ctx.sections.items()}
        scores = secs.pop("scores", None)
        quote = secs.get("quote") or {}
        overview = {
            "price": _v(quote.get("price"), quote.get("prov_id"), quote.get("is_delayed")), "change_pct": _v(quote.get("change_pct"), quote.get("prov_id"), quote.get("is_delayed")),
            "market_cap": _v((secs.get("fundamentals") or {}).get("market_cap"), (secs.get("fundamentals") or {}).get("prov_id")),
            "pe": _v(_m(secs, "pe"), (secs.get("fundamentals") or {}).get("prov_id")), "ev_ebitda": _v(_m(secs, "ev_ebitda"), (secs.get("fundamentals") or {}).get("prov_id")),
            "fcf_yield": _v(_m(secs, "fcf_yield"), (secs.get("fundamentals") or {}).get("prov_id")),
            "iv30": _v(((secs.get("options") or {}).get("surface") or {}).get("atm_iv", {}).get("d30"), (secs.get("options") or {}).get("prov_id"), True),
            "iv_rank": _v(((secs.get("options") or {}).get("ranks") or {}).get("iv_rank"), (secs.get("options") or {}).get("prov_id"), flags=[((secs.get("options") or {}).get("ranks") or {}).get("flag")]),
            "beta": _v(((secs.get("risk") or {}).get("beta_weekly_2y") or {}).get("beta_adjusted"), (secs.get("risk") or {}).get("prov_id")),
            "next_earnings": _v((secs.get("events") or {}).get("next_earnings"), (secs.get("events") or {}).get("prov_id")),
            "short_pct_float": _v((secs.get("shorts") or {}).get("pct_of_float"), (secs.get("shorts") or {}).get("prov_id")),
            "dcf_upside": _v(((secs.get("valuation") or {}).get("dcf") or {}).get("upside_pct"), (secs.get("valuation") or {}).get("prov_id")),
            "blended_fair_value": _v(((secs.get("valuation") or {}).get("blend") or {}).get("fair_value"), (secs.get("valuation") or {}).get("prov_id")),
            "avg_volume_20d": _v(((secs.get("technicals") or {}).get("intervals", {}).get("1d", {}).get("latest") or {}).get("vol_sma_20"), (secs.get("technicals") or {}).get("prov_id")),
            "r_1m": _v(((secs.get("technicals") or {}).get("returns") or {}).get("r_1m"), (secs.get("technicals") or {}).get("prov_id")),
            "r_1y": _v(((secs.get("technicals") or {}).get("returns") or {}).get("r_1y"), (secs.get("technicals") or {}).get("prov_id")),
        }
        return {
            "run_id": self.run_id, "symbol": self.symbol, "depth": self.depth, "as_of": (self.finished or datetime.now(timezone.utc)).isoformat(), "status": self.status,
            "sections": self.section_status, "scores": scores, "overview": overview, **secs,
            "provenance": self.ledger.to_json(), "warnings": self.run.warnings, "fetch_log": self.run.router.fetch_log[-200:],
            "meta": {"code_version": __version__, "weights_hash": (scores or {}).get("weights_hash"), "started_at": self.started.isoformat(),
                     "total_ms": int(((self.finished or datetime.now(timezone.utc)) - self.started).total_seconds() * 1000),
                     "cache_hit_rate": _cache_rate(self.ledger), "n_fetches": len(self.ledger.records)},
        }

    def _persist(self) -> None:
        try:
            path = get_settings().runs_dir / f"{self.run_id}.json"
            path.write_text(json.dumps(self.result, default=str), encoding="utf-8")
            persist.save_ledger(self.ledger)
            sc = (self.result.get("scores") or {}).get("horizons", {})
            row = {"run_id": self.run_id, "symbol": self.symbol, "depth": self.depth, "started_at": self.started, "finished_at": self.finished, "status": self.status,
                   "code_version": __version__, "weights_hash": (self.result.get("scores") or {}).get("weights_hash"),
                   **{f"coverage_{h}": sc.get(h, {}).get("coverage") for h in ("long", "medium", "short")}, **{f"score_{h}": sc.get(h, {}).get("score") for h in ("long", "medium", "short")},
                   "sections_ok": [k for k, v in self.section_status.items() if v["status"] == "ok"], "sections_failed": [k for k, v in self.section_status.items() if v["status"] != "ok"],
                   "result_path": str(path)}
            duck.upsert_df("analysis_runs", pd.DataFrame([row]), ["run_id"])
            hist = [{"symbol": self.symbol, "run_id": self.run_id, "ts": self.finished, "horizon": h, "score": sc.get(h, {}).get("raw_score"), "coverage": sc.get(h, {}).get("coverage"), "confidence": sc.get(h, {}).get("confidence")} for h in ("long", "medium", "short")]
            duck.upsert_df("score_history", pd.DataFrame(hist), ["run_id", "horizon"])
        except Exception as e:
            log.warning("persist run failed: %s", e)


def _v(v: Any, p: str | None, delayed: bool | None = False, flags: list | None = None) -> dict:
    q = [f for f in (flags or []) if f]
    if delayed:
        q.append("DELAYED")
    return {"v": jsonable(v), "p": p, "q": q}


def _m(secs: dict, key: str):
    return (((secs.get("fundamentals") or {}).get("metrics") or {}).get(key) or {}).get("value")


def _cache_rate(ledger: Ledger) -> float | None:
    if not ledger.records:
        return None
    return sum(1 for r in ledger.records.values() if r.from_cache) / len(ledger.records)


def _slim(payload: Any) -> Any:
    """Trim very large frames before serialization (full frames remain available via dedicated endpoints)."""
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if isinstance(v, pd.DataFrame) and len(v) > 600 and k not in ("chain",):
                out[k] = v.tail(600)
            else:
                out[k] = v
        return out
    return payload


def load_result(run_id: str) -> dict[str, Any] | None:
    r = RUNS.get(run_id)
    if r and r.result:
        return r.result
    path = get_settings().runs_dir / f"{run_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


async def analyze(symbol: str, depth: str = "standard", sections: list[str] | None = None) -> dict[str, Any]:
    run = AnalysisRun(symbol, depth, sections)
    return await run.execute()


def start(symbol: str, depth: str = "standard", sections: list[str] | None = None) -> AnalysisRun:
    run = AnalysisRun(symbol, depth, sections)
    run.task = asyncio.create_task(run.execute())
    return run

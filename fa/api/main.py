"""FastAPI application: analysis jobs with SSE progress, per-section endpoints, provenance/raw access, admin, watchlist."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from fa import __version__
from fa.core import archive
from fa.core.logging import setup_logging
from fa.core.settings import get_settings
from fa.core.types import jsonable
from fa.pipeline import orchestrator as O
from fa.pipeline.scheduler import build_scheduler
from fa.registry import cache as C
from fa.registry.router import get_router
from fa.store import duck, repos

log = logging.getLogger(__name__)


class _JSON(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(jsonable(content), default=str, allow_nan=False).encode("utf-8")


def J(x: Any) -> _JSON:
    """Return a Response directly so FastAPI's jsonable_encoder (which cannot handle DataFrames/numpy) is bypassed."""
    return _JSON(content=x)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    s = get_settings()
    duck.set_strict(s.store_strict)   # the API normally must own the store; FA_STORE_STRICT=0 allows a degraded second instance
    duck.connect()
    get_router()
    app.state.scheduler = build_scheduler()
    app.state.scheduler.start()
    log.info("Full Analysis API %s — data root %s", __version__, s.data_root)
    yield
    app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="Full Analysis", version=__version__, lifespan=lifespan, default_response_class=_JSON)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class AnalyzeRequest(BaseModel):
    symbol: str
    depth: str = "standard"
    sections: list[str] | None = None


# ---------------------------------------------------------------------------- analysis
@app.post("/api/analyze")
async def analyze(req: AnalyzeRequest):
    if req.depth not in ("quick", "standard", "deep"):
        raise HTTPException(400, "depth must be quick|standard|deep")
    run = O.start(req.symbol.strip().upper(), req.depth, req.sections)
    return J({"run_id": run.run_id, "symbol": run.symbol, "depth": run.depth})


@app.get("/api/analyze/{run_id}")
async def get_run(run_id: str):
    r = O.RUNS.get(run_id)
    if r and r.result is None:
        return J({"run_id": run_id, "symbol": r.symbol, "status": r.status, "sections": r.section_status,
                  "partial": {k: jsonable(O._slim(v)) for k, v in r.ctx.sections.items()},
                  "provenance": r.ledger.to_json(), "warnings": r.run.warnings})
    res = O.load_result(run_id)
    if res is None:
        raise HTTPException(404, "run not found")
    return J(res)


@app.get("/api/analyze/{run_id}/stream")
async def stream(run_id: str):
    r = O.RUNS.get(run_id)
    if r is None:
        raise HTTPException(404, "run not found (only in-process runs can be streamed)")
    q = r.progress.subscribe()

    async def gen():
        try:
            while True:
                try:
                    e = await asyncio.wait_for(q.get(), timeout=25)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": e["event"], "data": json.dumps(jsonable(e), default=str)}
                if e["event"] in ("run.done", "run.error"):
                    break
        finally:
            r.progress.unsubscribe(q)
    return EventSourceResponse(gen())


@app.delete("/api/analyze/{run_id}")
async def cancel(run_id: str):
    r = O.RUNS.get(run_id)
    if r and r.task and not r.task.done():
        r.task.cancel()
        r.status = "cancelled"
        return J({"cancelled": True})
    return J({"cancelled": False})


@app.get("/api/runs")
async def runs(symbol: str | None = None, limit: int = 50):
    return J(repos.runs(symbol, limit))


@app.get("/api/ticker/{symbol}/scores/history")
async def score_history(symbol: str):
    return J(repos.score_history(symbol))


# ---------------------------------------------------------------------------- per-section data (from the latest completed run or the store)
def _latest(symbol: str) -> dict[str, Any] | None:
    df = repos.runs(symbol, 1)
    if not df.empty:
        return O.load_result(str(df["run_id"].iloc[0]))
    # store unavailable (degraded instance) — fall back to the newest result file on disk
    files = sorted(get_settings().runs_dir.glob(f"r_*_{symbol.upper()}_*.json"), key=lambda p: p.stat().st_mtime)
    if files:
        try:
            return json.loads(files[-1].read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


@app.get("/api/ticker/{symbol}/latest")
async def latest(symbol: str):
    res = _latest(symbol)
    if res is None:
        raise HTTPException(404, "no completed run for symbol; POST /api/analyze first")
    return J(res)


@app.get("/api/ticker/{symbol}/section/{name}")
async def section(symbol: str, name: str):
    res = _latest(symbol)
    if res is None or name not in res:
        raise HTTPException(404, "section not available")
    return J({"run_id": res["run_id"], "as_of": res["as_of"], name: res[name], "provenance": res.get("provenance")})


@app.get("/api/ticker/{symbol}/ohlcv")
async def ohlcv(symbol: str, interval: str = "1d", limit: int = 1000):
    df = repos.ohlcv(symbol, interval)
    if df.empty:
        from fa.core.provenance import Ledger
        from fa.registry import needs as N
        res = await get_router().fetch(N.OHLCV, Ledger("adhoc"), symbol=symbol.upper(), interval=interval)
        df = res.data
    return J({"symbol": symbol.upper(), "interval": interval, "bars": df.tail(limit)[["ts", "open", "high", "low", "close", "volume"]]})


@app.get("/api/ticker/{symbol}/options/chain")
async def chain(symbol: str, dt: str | None = None, expiry: str | None = None):
    df = repos.chain_snapshot(symbol, dt) if dt else None
    if df is None or df.empty:
        from fa.core.provenance import Ledger
        from fa.registry import needs as N
        res = await get_router().fetch(N.OPTION_CHAIN, Ledger("adhoc"), symbol=symbol.upper())
        df = res.data
        src = {"provider": res.provider, "latency": str(res.prov.latency), "as_of": res.prov.as_of}
    else:
        src = {"provider": "snapshot", "dt": dt}
    if expiry:
        df = df[df["expiry"].astype(str) == expiry]
    return J({"symbol": symbol.upper(), "source": src, "n": int(len(df)), "chain": df})


@app.get("/api/ticker/{symbol}/options/snapshots")
async def snapshots(symbol: str):
    return J({"symbol": symbol.upper(), "snapshots": repos.chain_snapshots(symbol), "surface_history": repos.iv_surface_history(symbol)})


@app.get("/api/ticker/{symbol}/shorts/history")
async def shorts_history(symbol: str):
    return J({"short_interest": repos.short_interest_history(symbol), "short_volume": repos.short_volume_history(symbol)})


class DcfReq(BaseModel):
    wacc: float | None = None
    cost_of_equity: float | None = None
    growth_stage1: float | None = None
    growth_terminal: float | None = None
    fcf_margin: float | None = None
    target_margin: float | None = None
    erp: float | None = None
    beta: float | None = None
    rf: float | None = None
    fade_years: float | None = None
    exit_multiple: float | None = None


@app.post("/api/ticker/{symbol}/valuation/dcf")
async def dcf_recompute(symbol: str, req: DcfReq):
    """Re-run the DCF (and its sensitivity / reverse DCF) with user-overridden assumptions on the latest run's inputs."""
    from fa.compute.valuation import dcf as DCF
    from fa.compute.valuation.inputs import ValuationInputs
    res = _latest(symbol)
    if res is None or not (res.get("valuation") or {}).get("inputs"):
        raise HTTPException(404, "no completed run with valuation inputs for this symbol")
    inp = ValuationInputs.from_json(res["valuation"]["inputs"])
    ov = {k: v for k, v in req.model_dump().items() if k not in ("target_margin", "exit_multiple")}
    inp.override(**ov)
    d = DCF.dcf(inp, exit_multiple=req.exit_multiple, target_margin=req.target_margin)
    return J({"inputs": inp.to_json(), "dcf": d, "sensitivity": DCF.sensitivity(inp, target_margin=req.target_margin) if d.get("available") else None,
              "reverse_dcf": DCF.reverse_dcf(inp), "implied_margin": DCF.implied_margin(inp), "scenarios": DCF.scenarios(inp, target_margin=req.target_margin),
              "run_id": res["run_id"]})


@app.get("/api/ticker/{symbol}/options/evaluate")
async def options_evaluate(symbol: str, right: str = "C", expiry: str | None = None, horizon: str = "short", hold_days: int | None = None, target: float | None = None,
                           direction: int | None = None):
    """Rank every liquid contract of one expiry for a holding period, using the latest run's stock setup as the thesis."""
    from datetime import date as _date
    from fa.compute.options import evaluate as EVL
    from fa.compute.options import pricing, ranks
    from fa.core.provenance import Ledger
    from fa.registry import needs as N
    sym = symbol.upper()
    res = _latest(sym) or {}
    led = Ledger("evaluate")
    try:
        ch = await get_router().fetch(N.OPTION_CHAIN, led, symbol=sym)
        chain = ch.data
        q = await get_router().fetch(N.QUOTE, led, symbol=sym)
    except Exception as e:
        return J({"available": False, "reason": f"could not load the option chain: {type(e).__name__}: {str(e)[:200]}"})
    spot = q.data.get("price") or float(chain["underlying_price"].dropna().iloc[0])
    rf = 0.04
    try:
        m = repos.macro("DGS3MO")
        rf = float(m["value"].iloc[-1]) / 100 if len(m) else rf
    except Exception:
        pass
    prof_raw = (res.get("profile") or {}).get("profile_raw", {}) if res else {}
    dy = float(prof_raw.get("dividendYield") or 0)
    dy = dy / 100 if dy > 1 else dy
    g = pricing.fill_greeks(chain, r=rf, q=dy)
    daily = repos.ohlcv(sym, "1d")
    hv20 = ranks.realized_vol(daily["close"], 20) if not daily.empty else None
    opts = res.get("options") or {}
    iv_atm = ((opts.get("surface") or {}).get("atm_iv") or {}).get("d30")
    iv_rank = (opts.get("ranks") or {}).get("iv_rank")
    setup = ((res.get("technicals") or {}).get("patterns") or {}).get("setup") or {}
    dirn = direction if direction is not None else int(setup.get("direction") or 0)
    quality = float(setup.get("quality") or 0.0)
    dte_earn = (res.get("events") or {}).get("days_to_earnings")
    expiries = sorted({str(e) for e in g["expiry"].astype(str).unique()})
    exp = expiry or EVL.suggest_expiry(expiries, horizon, _date.today())
    try:
        out = EVL.evaluate(g, spot, exp, right, horizon, hold_days, target, dirn, quality, iv_atm, hv20, dte_earn, rf, dy, iv_rank)
    except Exception as e:
        log.exception("option evaluate failed")
        return J({"available": False, "reason": f"evaluation failed: {type(e).__name__}: {str(e)[:200]}", "expiries": expiries})
    out["expiries"] = expiries
    out["setup"] = {"setup": setup.get("setup"), "direction": setup.get("direction"), "quality": setup.get("quality"), "trend": setup.get("trend")}
    out["context"] = {"hv20": hv20, "iv_atm30": iv_atm, "iv_rank": iv_rank, "days_to_earnings": dte_earn, "rf": rf, "dividend_yield": dy, "quote_provider": q.provider, "chain_provider": ch.provider,
                      "chain_latency": str(ch.prov.latency), "run_id": res.get("run_id")}
    return J(out)


# ---------------------------------------------------------------------------- provenance / raw
@app.get("/api/provenance/{run_id}/{prov_id}")
async def provenance(run_id: str, prov_id: str):
    r = O.RUNS.get(run_id)
    if r and prov_id in r.ledger.records:
        return J(r.ledger.records[prov_id].to_json())
    df = duck.q("SELECT * FROM provenance WHERE run_id=? AND prov_id=?", [run_id, prov_id])
    if df.empty:
        raise HTTPException(404, "provenance record not found")
    return J(df.iloc[0].to_dict())


@app.get("/api/raw/{run_id}/{prov_id}")
async def raw(run_id: str, prov_id: str):
    rec = None
    r = O.RUNS.get(run_id)
    if r and prov_id in r.ledger.records:
        rec = r.ledger.records[prov_id].raw_path
    else:
        df = duck.q("SELECT raw_path FROM provenance WHERE run_id=? AND prov_id=?", [run_id, prov_id])
        rec = str(df["raw_path"].iloc[0]) if not df.empty and df["raw_path"].iloc[0] else None
    if not rec:
        raise HTTPException(404, "no archived payload for this record")
    data = archive.read_raw(rec)
    media = "application/json" if rec.endswith(".json.gz") else "text/plain"
    return Response(content=data[:5_000_000], media_type=media)


# ---------------------------------------------------------------------------- market / macro / admin
@app.get("/api/market/context")
async def market_context():
    from fa.core.provenance import Ledger
    from fa.pipeline.sections import Run, market
    run = Run("SPY", "quick", get_router(), Ledger("market"), __import__("fa.score.context", fromlist=["Ctx"]).Ctx("SPY"))
    return J(await market(run))


@app.get("/api/macro/series/{series_id}")
async def macro_series(series_id: str, days: int | None = None):
    df = repos.macro(series_id, days)
    if df.empty:
        from fa.core.provenance import Ledger
        from fa.registry import needs as N
        from fa.store import persist
        res = await get_router().fetch(N.MACRO_SERIES, Ledger("adhoc"), series_id=series_id)
        persist.persist(N.MACRO_SERIES, {"series_id": series_id}, res)
        df = res.data.rename(columns={"date": "dt"})
    return J({"series_id": series_id, "data": df})


@app.get("/api/health")
async def health():
    return J({"version": __version__, "providers": await get_router().health(), "circuits": get_router().circuit.snapshot(), "store": duck.stats(), "cache": C.stats(),
              "settings": {"data_root": str(get_settings().data_root), "require_realtime": get_settings().require_realtime}})


@app.get("/api/admin/fetch-log")
async def fetch_log(limit: int = 200):
    return J(get_router().fetch_log[-limit:])


@app.post("/api/admin/providers/{name}/reset")
async def reset_provider(name: str):
    get_router().circuit.reset(name)
    return J({"reset": name})


@app.get("/api/admin/jobs")
async def jobs():
    sch = app.state.scheduler
    return J([{"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None, "name": j.name} for j in sch.get_jobs()])


@app.post("/api/admin/jobs/{job_id}/run")
async def run_job(job_id: str):
    sch = app.state.scheduler
    j = sch.get_job(job_id)
    if j is None:
        raise HTTPException(404, "job not found")
    asyncio.create_task(j.func())
    return J({"started": job_id})


# ---------------------------------------------------------------------------- watchlist
@app.get("/api/watchlist")
async def watchlist():
    return J(repos.watchlist())


class WatchReq(BaseModel):
    symbol: str
    note: str = ""


@app.post("/api/watchlist")
async def add_watch(req: WatchReq):
    repos.add_watch(req.symbol, req.note)
    return J(repos.watchlist())


@app.delete("/api/watchlist/{symbol}")
async def del_watch(symbol: str):
    repos.remove_watch(symbol)
    return J(repos.watchlist())


@app.get("/api/symbols/search")
async def search(q: str = Query(min_length=1), limit: int = 10):
    from fa.core.provenance import Ledger
    from fa.registry import needs as N
    res = await get_router().fetch(N.TICKER_MAP, Ledger("adhoc"))
    df = res.data
    ql = q.upper()
    hit = df[df["ticker"].str.startswith(ql) | df["name"].str.upper().str.contains(ql, regex=False)].head(limit)
    return J([{"symbol": r.ticker, "name": r.name, "cik": r.cik} for r in hit.itertuples()])

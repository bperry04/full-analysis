"""One coroutine per analysis section: fetch (router) -> persist -> compute -> payload.

Each section returns a dict payload (DataFrames allowed; serialized later) and registers its primary provenance id
on the context. Failures inside a section are the orchestrator's problem — sections just raise.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from fa.compute import peers as PR
from fa.compute import risk as RK
from fa.compute import segments as SG
from fa.compute.events import merge as EV
from fa.compute.fundamentals import build_fundamentals
from fa.compute.fundamentals.coverage import summarize as cov_summary
from fa.compute.fundamentals.quality import all_quality
from fa.compute.fundamentals.statements import long_for_db
from fa.compute.market import context as MK
from fa.compute.options import exposure, expected_move, flow, pricing, ranks, surface
from fa.compute.orderflow import proxies as OF
from fa.compute.ratios import build_metrics
from fa.compute.sentiment import news as SN
from fa.compute.technical import indicators as TI
from fa.compute.technical import levels as LV
from fa.compute.technical import regime as RG
from fa.compute.valuation import aggregate as AG
from fa.compute.valuation import comps as CP
from fa.compute.valuation import dcf as DCF
from fa.compute.valuation import inputs as VI
from fa.compute.valuation import models as VM
from fa.compute.valuation import montecarlo as MC
from fa.core.errors import AllRoutesFailed
from fa.core.provenance import Ledger
from fa.core.settings import get_settings
from fa.core.types import Q, val
from fa.registry import needs as N
from fa.registry.router import Result, Router
from fa.score.context import Ctx
from fa.store import duck, persist, repos

log = logging.getLogger(__name__)

MARKET_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC", "TLT", "UUP", "USO", "HYG", "LQD", "GLD", "^VIX", "^VIX3M"]


class Run:
    """Shared state for one analysis run."""

    def __init__(self, symbol: str, depth: str, router: Router, ledger: Ledger, ctx: Ctx):
        self.symbol = symbol.upper()
        self.depth = depth
        self.router = router
        self.ledger = ledger
        self.ctx = ctx
        self.warnings: list[str] = []

    async def fetch(self, need: str, **params) -> Result:
        params.setdefault("symbol", self.symbol) if need not in (N.MACRO_NEWS, N.YIELD_CURVE, N.MACRO_SERIES, N.ECON_CALENDAR, N.EARNINGS_CALENDAR, N.VIX_HISTORY, N.FOMC_CALENDAR, N.TICKER_MAP) else None
        res = await self.router.fetch(need, self.ledger, **params)
        persist.persist(need, params, res)
        return res

    async def try_fetch(self, need: str, **params) -> Result | None:
        try:
            return await self.fetch(need, **params)
        except AllRoutesFailed as e:
            self.warnings.append(str(e)[:200])
            return None
        except Exception as e:
            self.warnings.append(f"{need}: {type(e).__name__}: {str(e)[:150]}")
            return None


# ---------------------------------------------------------------------------- stage 0: identity + quote
async def profile(run: Run) -> dict[str, Any]:
    prof = await run.try_fetch(N.COMPANY_PROFILE)
    filings = await run.try_fetch(N.FILINGS)
    p = dict(prof.data) if prof else {}
    meta = (filings.data or {}).get("meta", {}) if filings else {}
    out = {
        "symbol": run.symbol, "name": p.get("longName") or p.get("shortName") or meta.get("name"), "sector": p.get("sector"), "industry": p.get("industry"),
        "country": p.get("country"), "website": p.get("website") or meta.get("website"), "employees": p.get("fullTimeEmployees"), "exchange": p.get("exchange"),
        "summary": (p.get("longBusinessSummary") or "")[:2000], "cik": meta.get("cik"), "sic": meta.get("sic"), "sic_description": meta.get("sic_description"),
        "fiscal_year_end": meta.get("fiscal_year_end"), "state_of_inc": meta.get("state_of_inc"), "filer_category": meta.get("category"),
        "officers": p.get("companyOfficers"), "risk_scores": {k: p.get(k) for k in ("auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk")},
        "shares_outstanding": p.get("sharesOutstanding"), "float_shares": p.get("floatShares"), "held_insiders": p.get("heldPercentInsiders"), "held_institutions": p.get("heldPercentInstitutions"),
        "recent_filings": (filings.data["filings"].head(25) if filings else pd.DataFrame()),
        "profile_raw": {k: v for k, v in p.items() if k not in ("longBusinessSummary", "companyOfficers")},
    }
    run.ctx.prov["profile"] = prof.p if prof else (filings.p if filings else None)
    run.ctx.objects["cik"] = meta.get("cik")
    if get_settings().auto_watch:
        try:
            repos.add_watch(run.symbol, "auto: analysed")   # so the daily close-snapshot job accrues chain / IV / bar history
        except Exception:
            pass
    run.ctx.objects["name"] = out["name"]
    run.ctx.objects["sector"] = out["sector"]
    if filings:
        try:
            duck.upsert_df("symbols", pd.DataFrame([{"symbol": run.symbol, "cik": meta.get("cik"), "name": out["name"], "exchange": out["exchange"], "sic": meta.get("sic"),
                                                     "sic_description": meta.get("sic_description"), "sector": out["sector"], "industry": out["industry"], "country": out["country"],
                                                     "fiscal_year_end": meta.get("fiscal_year_end"), "shares_out": p.get("sharesOutstanding"), "float_shares": p.get("floatShares"),
                                                     "currency": p.get("currency"), "first_seen": datetime.now(timezone.utc), "last_refreshed": datetime.now(timezone.utc)}]), ["symbol"])
        except Exception:
            pass
    return out


async def quote(run: Run) -> dict[str, Any]:
    q = await run.fetch(N.QUOTE)
    d = dict(q.data)
    run.ctx.prov["quote"] = q.p
    d["prov_id"] = q.p
    d["latency"] = str(q.prov.latency)
    d["is_delayed"] = q.prov.is_delayed
    d["provider"] = q.provider
    d["as_of"] = q.prov.as_of.isoformat() if q.prov.as_of else None
    run.ctx.objects["price"] = d.get("price")
    return d


# ---------------------------------------------------------------------------- fundamentals
async def fundamentals(run: Run) -> dict[str, Any]:
    facts = await run.fetch(N.XBRL_FACTS)
    fund = build_fundamentals(facts.data, run.symbol)
    run.ctx.objects["fund"] = fund
    run.ctx.prov["fundamentals"] = facts.p
    price = run.ctx.objects.get("price")
    shares = fund.ttm.get("shares_outstanding_latest") or fund.latest("shares_outstanding") or fund.latest("shares_diluted")
    mcap = price * shares if price and shares else None
    metrics = build_metrics(fund, price, mcap, shares)
    run.ctx.objects["metrics"] = metrics
    run.ctx.objects["shares"] = shares
    run.ctx.objects["market_cap"] = mcap
    quality = all_quality(fund, mcap)
    seg = await run.try_fetch(N.SEGMENTS, max_filings={"quick": 1, "standard": 2, "deep": 4}.get(run.depth, 2))
    segments = SG.summarize(seg.data) if seg else {"available": False}
    run.ctx.prov["segments"] = seg.p if seg else None
    fallback = None
    if cov_summary(fund)["core_coverage"] < 0.6:
        fb = await run.try_fetch(N.STATEMENTS_FALLBACK)
        fallback = {k: v for k, v in (fb.data or {}).items()} if fb else None
        run.warnings.append("XBRL coverage thin; Yahoo statements attached as fallback (DEGRADED)")
    try:
        rows = long_for_db(fund, facts.p)
        duck.upsert_df("fundamentals_normalized", rows, ["symbol", "metric", "period_type", "period_end", "is_restated"])
    except Exception as e:
        log.debug("fundamentals_normalized upsert failed: %s", e)
    return {
        "prov_id": facts.p, "fye_month": fund.fye_month, "cik": fund.cik, "ttm_end": fund.ttm_end,
        "annual": fund.annual, "quarterly": fund.quarterly, "ttm": {k: v for k, v in fund.ttm.items() if not isinstance(v, date)}, "labels": fund.labels,
        "coverage": cov_summary(fund), "restatements": fund.restatements[:40], "quality": quality, "segments": segments,
        "metrics": {k: {"label": m.label, "group": m.group, "value": m.value, "formula": m.formula, "inputs": m.inputs, "unit": m.unit, "history": m.history} for k, m in metrics.items()},
        "market_cap": mcap, "shares": shares, "fallback_statements": fallback,
    }


# ---------------------------------------------------------------------------- prices / technicals
async def technicals(run: Run) -> dict[str, Any]:
    intervals = {"1d": ("1d", "max"), "1wk": ("1wk", "max"), "1h": ("1h", "730d"), "15m": ("15m", "60d"), "5m": ("5m", "60d")}
    if run.depth == "quick":
        intervals = {"1d": ("1d", "5y"), "1wk": ("1wk", "max")}
    results: dict[str, Result | None] = {}
    for k, (iv, per) in intervals.items():
        results[k] = await run.try_fetch(N.OHLCV, interval=iv, period=per)
    daily_res = results.get("1d")
    if daily_res is None:
        raise AllRoutesFailed(N.OHLCV, [])
    daily = daily_res.data
    run.ctx.objects["daily"] = daily
    run.ctx.prov["technicals"] = daily_res.p
    out: dict[str, Any] = {"prov_id": daily_res.p, "intervals": {}, "bars": {}}
    for k, res in results.items():
        if res is None or res.data.empty or len(res.data) < 30:
            continue
        ind = TI.compute_all(res.data)
        out["intervals"][k] = {**TI.snapshot(ind), "prov_id": res.p, "n_bars": int(len(res.data))}
        tail = 400 if k in ("1d", "1wk") else 300
        out["bars"][k] = res.data.tail(tail)[["ts", "open", "high", "low", "close", "volume"]]
        if k == "1d":
            out["indicator_frame_1d"] = ind.tail(400)[["ts", "close", "sma_10", "sma_20", "sma_50", "sma_100", "sma_200", "ema_9", "ema_21", "ema_50", "ema_200", "hma_20", "bb_upper", "bb_mid", "bb_lower",
                                                        "kc_upper", "kc_lower", "dc_upper", "dc_lower", "tenkan", "kijun", "senkou_a", "senkou_b", "supertrend", "vwap_cum", "rsi_14", "rsi_2", "stoch_k", "stoch_d",
                                                        "stoch_rsi", "williams_r", "cci_20", "macd", "macd_signal", "macd_hist", "adx", "plus_di", "minus_di", "atr_14", "natr_14", "obv", "cmf_20", "mfi_14", "ad",
                                                        "rel_volume", "hv_cc_20", "hv_yz_20", "roc_21", "z_sma_50", "bb_pct_b", "bb_width"]]
            out["regime"] = RG.classify(ind, res.data)
            out["structure"] = LV.structure(res.data, float(res.data["close"].iloc[-1]))
    c = daily["close"].astype(float)
    rets = {"r_5d": _r(c, 5), "r_10d": _r(c, 10), "r_20d": _r(c, 20), "r_1m": _r(c, 21), "r_3m": _r(c, 63), "r_6m": _r(c, 126), "r_1y": _r(c, 252),
            "r_6m_ex_1m": (float(c.iloc[-22] / c.iloc[-127] - 1) if len(c) > 127 else None)}
    out["returns"] = rets
    # candlestick + chart patterns and the swing setup (2-20 day horizon); market/options context is added in the risk stage
    from fa.compute.technical import patterns as PT
    try:
        wk = out["intervals"].get("1wk", {}).get("signals", {}).get("supertrend")
        hr = out["intervals"].get("1h", {}).get("signals", {}).get("supertrend")
        out["patterns"] = PT.analyze(daily, out.get("structure"), None, None if wk is None else wk == "bullish", None if hr is None else hr == "bullish", None)
    except Exception as e:
        log.warning("pattern analysis failed: %s", e, exc_info=True)
        out["patterns"] = {}
    return out


def _r(c: pd.Series, n: int) -> float | None:
    return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else None


async def market(run: Run) -> dict[str, Any]:
    bars: dict[str, pd.DataFrame] = {}
    syms = MARKET_SYMBOLS if run.depth != "quick" else ["SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC", "TLT", "UUP", "USO", "HYG", "LQD", "^VIX", "^VIX3M"]
    sem = asyncio.Semaphore(4)
    async def one(s):
        async with sem:
            r = await run.try_fetch(N.OHLCV, symbol=s, interval="1d", period="2y")
            if r is not None:
                bars[s] = r.data
    await asyncio.gather(*[one(s) for s in syms])
    vix = await run.try_fetch(N.VIX_HISTORY)
    yc = await run.try_fetch(N.YIELD_CURVE)
    macro_news = await run.try_fetch(N.MACRO_NEWS)
    run.ctx.objects["market_bars"] = bars
    ctx = MK.market_context(bars, vix.data if vix else None, yc.data if yc else None, run.ctx.objects.get("sector"))
    run.ctx.prov["market"] = (bars and next(iter(run.ledger.records))) or None
    for name in ("SPY", "QQQ"):
        pass
    ctx["prov_id"] = next((r.prov_id for r in run.ledger.records.values() if r.need == N.OHLCV and "SPY" in r.endpoint), None)
    run.ctx.prov["market"] = ctx["prov_id"]
    if macro_news is not None:
        mn = SN.analyze(macro_news.data)
        ctx["macro_news"] = {"score": mn.get("medium_term", {}).get("score"), "n": mn.get("n_stories"), "items": mn.get("items")}
    if yc is not None:
        ctx["yield_curve_history"] = yc.data.tail(260)
        ctx["yield_curve_prov"] = yc.p
    if vix is not None:
        ctx["vix_history"] = vix.data.tail(500)[["ts", "close"]]
    # macro series for the panel (from the store if already there, else fetch a few)
    series = {}
    for sid in ("DGS10", "DGS2", "T10Y2Y"):
        r = await run.try_fetch(N.MACRO_SERIES, series_id=sid)
        if r is not None:
            series[sid] = r.data.tail(500)
    ctx["macro_series"] = series
    return ctx


async def risk(run: Run) -> dict[str, Any]:
    daily = run.ctx.objects.get("daily")
    spy = (run.ctx.objects.get("market_bars") or {}).get("SPY")
    if daily is None:
        raise RuntimeError("no daily bars")
    rf = None
    try:
        m = repos.macro("DGS10")
        rf = float(m["value"].iloc[-1]) / 100 if len(m) else None
    except Exception:
        pass
    out = RK.summary(daily, spy, rf_annual=rf or 0.04)
    out["rf_used"] = rf or 0.04
    # relative strength needs both the name's bars (technicals) and the benchmarks (market) — both exist by this stage
    tech = run.ctx.sections.get("technicals")
    bars = run.ctx.objects.get("market_bars") or {}
    if isinstance(tech, dict) and tech.get("returns"):
        r3 = tech["returns"].get("r_3m")
        sec_etf = MK.SECTOR_BY_YAHOO.get(run.ctx.objects.get("sector") or "")
        def _r3(df):
            c = df["close"].astype(float)
            return float(c.iloc[-1] / c.iloc[-64] - 1) if len(c) > 64 else None
        if r3 is not None and spy is not None and not spy.empty:
            tech["returns"]["rs_3m_vs_spy"] = r3 - (_r3(spy) or 0.0)
        if r3 is not None and sec_etf in bars and not bars[sec_etf].empty:
            tech["returns"]["rs_3m_vs_sector"] = r3 - (_r3(bars[sec_etf]) or 0.0)
            tech["returns"]["sector_etf"] = sec_etf
        r20 = tech["returns"].get("r_20d")
        if r20 is not None and spy is not None and not spy.empty and len(spy) > 21:
            sc = spy["close"].astype(float)
            tech["returns"]["rs_20d_vs_spy"] = r20 - float(sc.iloc[-1] / sc.iloc[-21] - 1)
        # re-run the swing setup now that market regime is known (SPY above its 20d and 50d)
        if spy is not None and not spy.empty and len(spy) > 50 and daily is not None:
            sc = spy["close"].astype(float)
            regime_ok = bool(sc.iloc[-1] > sc.rolling(20).mean().iloc[-1] and sc.iloc[-1] > sc.rolling(50).mean().iloc[-1])
            tech["market_regime_swing_ok"] = regime_ok
            try:
                from fa.compute.technical import patterns as PT
                wk = tech.get("intervals", {}).get("1wk", {}).get("signals", {}).get("supertrend")
                hr = tech.get("intervals", {}).get("1h", {}).get("signals", {}).get("supertrend")
                tech["patterns"] = PT.analyze(daily, tech.get("structure"), None, None if wk is None else wk == "bullish", None if hr is None else hr == "bullish", regime_ok)
            except Exception as e:
                log.debug("pattern re-run failed: %s", e)
    out["prov_id"] = run.ctx.prov.get("technicals")
    run.ctx.prov["risk"] = out["prov_id"]
    sens = MK.sensitivity(daily, run.ctx.objects.get("market_bars") or {}, sector_etf=MK.SECTOR_BY_YAHOO.get(run.ctx.objects.get("sector") or ""))
    run.ctx.sections["sensitivity"] = sens
    run.ctx.prov["sensitivity"] = out["prov_id"]
    out["sensitivity"] = sens
    return out


# ---------------------------------------------------------------------------- options
async def options(run: Run) -> dict[str, Any]:
    ch = await run.fetch(N.OPTION_CHAIN)
    chain = ch.data
    spot = run.ctx.objects.get("price") or (float(chain["underlying_price"].dropna().iloc[0]) if chain["underlying_price"].notna().any() else None)
    run.ctx.prov["options"] = ch.p
    rf = 0.04
    try:
        m = repos.macro("DGS3MO")
        rf = float(m["value"].iloc[-1]) / 100 if len(m) else rf
    except Exception:
        pass
    q_yield = 0.0
    prof = run.ctx.sections.get("profile", {}).get("profile_raw", {}) if isinstance(run.ctx.sections.get("profile"), dict) else {}
    if prof.get("dividendYield"):
        q_yield = float(prof["dividendYield"]) / (100 if prof["dividendYield"] > 1 else 1)
    g = pricing.fill_greeks(chain, r=rf, q=q_yield)
    surf = surface.surface_summary(g, spot, (run.ctx.sections.get("quote") or {}).get("iv30"))
    iv30 = surf["atm_iv"].get("d30")
    ivh = await run.try_fetch(N.IV_HISTORY, days=730) if run.depth != "quick" else None
    hist = ranks.combine_history(repos.iv_surface_history(run.symbol, 400), ivh.data if ivh else repos.iv_underlying_history(run.symbol))
    rk = ranks.iv_rank(hist, iv30)
    daily = run.ctx.objects.get("daily")
    ivrv = ranks.iv_vs_rv(daily["close"], iv30) if daily is not None else {}
    prev = repos.chain_snapshot_prev_distinct(run.symbol, g.assign(dt=str(date.today())))
    hist_pc = repos.iv_surface_history(run.symbol, 120)
    fl = flow.flow_summary(g, prev, spot, hist_pc["put_call_vol"] if len(hist_pc) else None)
    mp = exposure.max_pain(g)
    gx = exposure.gex_profile(g, spot)
    em = expected_move.straddle_moves(g, spot)
    ed = run.ctx.objects.get("earnings_df")
    nxt = None
    if ed is not None and len(ed):
        fut = [pd.Timestamp(t).date() for t in ed["ts"] if pd.Timestamp(t).date() >= date.today()]
        nxt = min(fut) if fut else None
        past = [pd.Timestamp(t).date() for t in ed["ts"]]
    else:
        past = []
    eim = expected_move.earnings_implied_move(em, nxt, date.today())
    rem = expected_move.realized_earnings_moves(daily, past) if daily is not None else {"n": 0}
    # persist today's surface row (this is how IV rank history accrues)
    try:
        sk = surf.get("skew") or {}
        row = {"symbol": run.symbol, "dt": date.today(), "snap_ts": datetime.now(timezone.utc), "spot": spot, **{f"atm_iv_{d}": surf["atm_iv"].get(f"d{d}") for d in (7, 30, 60, 90, 180, 365)},
               "iv30_vendor": surf.get("iv30_vendor"), "term_slope_30_90": surf.get("term_slope_30_90"), "term_slope_7_30": surf.get("term_slope_7_30"),
               "rr25_30": sk.get("rr25"), "fly25_30": sk.get("fly25"), "skew_slope_30": sk.get("skew_slope"), "put_call_oi": surf.get("put_call_oi"), "put_call_vol": surf.get("put_call_vol"),
               "total_oi": surf.get("total_oi"), "total_volume": surf.get("total_volume"), "call_oi": surf.get("call_oi"), "put_oi": surf.get("put_oi"), "max_pain": mp.get("max_pain"),
               "gex_total": gx.get("gex_total"), "gex_flip": gx.get("gex_flip"), "dex_total": gx.get("dex_total"), "hv20": ivrv.get("hv20"), "hv60": ivrv.get("hv60"), "iv_rv_30": ivrv.get("iv_rv_20"),
               "em_next_exp": float(em["implied_move_pct"].iloc[0]) if len(em) else None, "next_exp": pd.Timestamp(em["expiry"].iloc[0]).date() if len(em) else None,
               "contracts_n": int(len(g)), "source": ch.provider, "prov_id": ch.p}
        duck.upsert_df("iv_surface_daily", pd.DataFrame([row]), ["symbol", "dt"])
    except Exception as e:
        log.warning("iv_surface_daily upsert failed: %s", e)
    ntm = g[(g["moneyness"].abs() <= 0.25) & (g["dte"] <= 120)]
    # give the swing setup the option-implied 10-day move
    tech = run.ctx.sections.get("technicals")
    if isinstance(tech, dict) and tech.get("patterns", {}).get("setup") and iv30 and spot:
        em10 = iv30 * (10 / 252) ** 0.5 * spot
        tech["patterns"]["setup"]["implied_10d_move"] = em10
        tech["patterns"]["setup"]["implied_10d_move_pct"] = em10 / spot
    return {
        "prov_id": ch.p, "provider": ch.provider, "latency": str(ch.prov.latency), "spot": spot, "rf": rf, "dividend_yield": q_yield,
        "surface": {k: v for k, v in surf.items() if k != "term"}, "term": surf["term"], "ranks": rk, "iv_history": hist.tail(400).reset_index().rename(columns={"index": "dt", 0: "iv"}) if len(hist) else pd.DataFrame(),
        "iv_vs_rv": ivrv, "flow": {k: v for k, v in fl.items()}, "max_pain": {k: v for k, v in mp.items() if k != "profile"}, "max_pain_profile": mp.get("profile"),
        "exposure": {k: v for k, v in gx.items() if k != "profile"}, "gex_profile": gx.get("profile"),
        "expected_move": {"by_expiry": em, "earnings": eim, "realized_earnings": rem},
        "chain": ntm[["contract_symbol", "expiry", "strike", "right", "bid", "ask", "mid", "last", "volume", "open_interest", "iv", "delta", "gamma", "theta", "vega", "dte", "moneyness", "spread_bps", "iv_source", "greeks_source", "delta_mismatch"] + (["prov_id"] if "prov_id" in ntm.columns else [])],
        "chain_stats": {"contracts": int(len(g)), "expiries": int(g["expiry"].nunique()), "delta_mismatch_share": float(g["delta_mismatch"].mean()) if "delta_mismatch" in g.columns else None,
                        "iv_computed_share": float((g["iv_source"] == "computed").mean())},
        "snapshots": repos.chain_snapshots(run.symbol)[-30:],
    }


# ---------------------------------------------------------------------------- flow
async def orderflow(run: Run) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m5 = repos.ohlcv(run.symbol, "5m")
    if m5.empty:
        r = await run.try_fetch(N.OHLCV, interval="5m", period="60d")
        m5 = r.data if r else pd.DataFrame()
    out["bars"] = OF.bar_cvd(m5) if not m5.empty else {}
    # short volume: what the lake already holds plus only the missing recent days
    have = repos.short_volume_history(run.symbol, 120)
    need_days = {"quick": 10, "standard": 30, "deep": 60}.get(run.depth, 30)
    missing = need_days - (int(len(have)) if not have.empty else 0)
    sv = await run.try_fetch(N.SHORT_VOLUME, days=max(missing, 3))
    have = repos.short_volume_history(run.symbol, 120)
    svdf = have if not have.empty else (sv.data if sv else None)
    out["short_volume"] = OF.short_volume_stats(svdf) if svdf is not None and not svdf.empty else {}
    out["prov_id"] = sv.p if sv else run.ctx.prov.get("technicals")
    run.ctx.prov["flow"] = out["prov_id"]
    if run.depth == "deep":
        t = await run.try_fetch(N.TICKS, n=2000)
        if t is not None:
            out["tape"] = OF.tape_stats(t.data.get("trades"), t.data.get("quotes"))
            out["tape_prov_id"] = t.p
        d = await run.try_fetch(N.DEPTH)
        if d is not None:
            out["depth"] = OF.depth_stats(d.data)
    if "tape" not in out:
        out["tape"] = {"available": False, "reason": "IBKR tick tape requires IB Gateway connected and depth=deep"}
    return out


# ---------------------------------------------------------------------------- estimates, analysts, ownership, shorts
async def analysts(run: Run) -> dict[str, Any]:
    recs = await run.try_fetch(N.ANALYST_RECS)
    tg = await run.try_fetch(N.ANALYST_TARGETS)
    ed = await run.try_fetch(N.EARNINGS_DATES)
    out: dict[str, Any] = {"prov_id": recs.p if recs else (tg.p if tg else None)}
    run.ctx.prov["analysts"] = out["prov_id"]
    if recs:
        trend = recs.data.get("trend")
        actions = recs.data.get("actions")
        if isinstance(trend, pd.DataFrame) and not trend.empty and "strongBuy" in trend.columns:
            t0 = trend.iloc[0]
            c = {k: int(t0.get(src, 0) or 0) for k, src in (("strong_buy", "strongBuy"), ("buy", "buy"), ("hold", "hold"), ("sell", "sell"), ("strong_sell", "strongSell"))}
            c["n"] = sum(c.values())
            out["consensus"] = c
            out["consensus_trend"] = trend
        if isinstance(actions, pd.DataFrame) and not actions.empty:
            a = actions.copy()
            a["date"] = pd.to_datetime(a["date"], errors="coerce")
            recent = a[a["date"] >= pd.Timestamp.now() - pd.Timedelta(days=90)]
            out["recent_actions"] = {"upgrades": int(recent["action"].astype(str).str.lower().str.contains("up").sum()), "downgrades": int(recent["action"].astype(str).str.lower().str.contains("down").sum()),
                                     "inits": int(recent["action"].astype(str).str.lower().str.contains("init").sum())}
            out["actions"] = a.sort_values("date", ascending=False).head(40)
    if tg:
        out["targets"] = dict(tg.data)
        t = tg.data
        if t.get("mean") and t.get("high") and t.get("low"):
            out["target_dispersion"] = (t["high"] - t["low"]) / t["mean"]
    if ed:
        out["earnings_history"] = ed.data.head(16)
        run.ctx.objects["earnings_df"] = ed.data
        run.ctx.objects["earnings_meta"] = getattr(ed, "meta", None)
        # post-earnings-announcement drift inputs: last reported surprise and how long ago
        past = ed.data[ed.data["eps_reported"].notna()] if "eps_reported" in ed.data.columns else pd.DataFrame()
        if len(past):
            last = past.iloc[0]
            lts = pd.Timestamp(last["ts"])
            lts = lts.tz_localize("UTC") if lts.tzinfo is None else lts.tz_convert("UTC")
            out["last_surprise"] = {"date": str(lts.date()), "eps_estimate": _fl(last.get("eps_estimate")), "eps_reported": _fl(last.get("eps_reported")),
                                    "surprise_pct": _fl(last.get("surprise_pct")), "days_ago": int((pd.Timestamp.now(tz="UTC") - lts).days)}
    # consensus shift (this month vs 1-3 months ago) — works for every covered ticker even when no upgrade/downgrade rows exist
    trend = out.get("consensus_trend")
    if isinstance(trend, pd.DataFrame) and len(trend) >= 2 and "strongBuy" in trend.columns:
        def score_row(r):
            n = sum(int(r.get(k, 0) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell"))
            return ((2 * int(r.get("strongBuy", 0) or 0) + int(r.get("buy", 0) or 0) - int(r.get("sell", 0) or 0) - 2 * int(r.get("strongSell", 0) or 0)) / (2 * n)) if n else None
        now_s, prev_s = score_row(trend.iloc[0]), score_row(trend.iloc[min(len(trend) - 1, 2)])
        if now_s is not None and prev_s is not None:
            out["consensus_shift"] = {"now": now_s, "prior": prev_s, "delta": now_s - prev_s, "periods": int(len(trend))}
    # EPS estimate revisions and trend (Yahoo)
    est = await run.try_fetch(N.ANALYST_ESTIMATES)
    if est:
        d = est.data
        rev, tr = d.get("eps_revisions"), d.get("eps_trend")
        try:
            def cell(df, row, col):
                # yfinance returns periods (0q, +1q, 0y, +1y) as the index and metrics as columns; column names vary in case
                if not isinstance(df, pd.DataFrame) or df.empty or row not in df.index:
                    return None
                cols = {c.lower(): c for c in df.columns}
                c = cols.get(col.lower())
                return _fl(df.loc[row, c]) if c else None
            if isinstance(rev, pd.DataFrame) and not rev.empty:
                out["eps_revisions"] = {"up_30d": cell(rev, "0q", "upLast30days"), "down_30d": cell(rev, "0q", "downLast30days"), "up_7d": cell(rev, "0q", "upLast7days"), "down_7d": cell(rev, "0q", "downLast7days"),
                                        "next_q_up_30d": cell(rev, "+1q", "upLast30days"), "next_q_down_30d": cell(rev, "+1q", "downLast30days"),
                                        "fy_up_30d": cell(rev, "0y", "upLast30days"), "fy_down_30d": cell(rev, "0y", "downLast30days")}
            if isinstance(tr, pd.DataFrame) and not tr.empty:
                cur, ago30, ago90 = cell(tr, "0y", "current"), cell(tr, "0y", "30daysAgo"), cell(tr, "0y", "90daysAgo")
                qcur, q90 = cell(tr, "0q", "current"), cell(tr, "0q", "90daysAgo")
                out["eps_trend"] = {"current_fy": cur, "30d_ago": ago30, "90d_ago": ago90, "chg_90d": (cur / ago90 - 1) if cur and ago90 else None, "chg_30d": (cur / ago30 - 1) if cur and ago30 else None,
                                    "current_q": qcur, "q_chg_90d": (qcur / q90 - 1) if qcur and q90 else None}
            ee = d.get("earnings_estimate")
            if isinstance(ee, pd.DataFrame) and not ee.empty:
                out["earnings_estimate"] = ee
            out["estimates_prov_id"] = est.p
        except Exception as e:
            log.debug("estimates parse failed: %s", e)
    out["consensus_history"] = repos.analyst_consensus_history(run.symbol)
    return out


def _fl(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


async def ownership(run: Run) -> dict[str, Any]:
    ins = await run.try_fetch(N.INSIDER_TXNS)
    inst = await run.try_fetch(N.INSTITUTIONAL_HOLDERS)
    out: dict[str, Any] = {"prov_id": ins.p if ins else (inst.p if inst else None)}
    run.ctx.prov["ownership"] = out["prov_id"]
    if ins:
        d = ins.data.copy()
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        six = d[d["date"] >= pd.Timestamp.now() - pd.Timedelta(days=182)]
        def col(name: str, default=0.0) -> pd.Series:
            return pd.to_numeric(six[name], errors="coerce").fillna(default) if name in six.columns else pd.Series(default, index=six.index, dtype=float)
        ad = six["acq_disp"] if "acq_disp" in six.columns else pd.Series(None, index=six.index, dtype=object)
        sign = np.where(ad == "A", 1, np.where(ad == "D", -1, 0))
        shares = col("shares")
        value = col("value", np.nan).fillna(shares * col("price"))
        out["insiders"] = {"n_txns_6m": int(len(six)), "net_shares_6m": float((sign * shares).sum()), "net_value_6m": float((sign * value).sum()),
                           "buys_6m": int((sign > 0).sum()), "sells_6m": int((sign < 0).sum()), "transactions": d.sort_values("date", ascending=False).head(40)}
    if inst:
        out["institutional"] = inst.data.get("institutional")
        out["major"] = inst.data.get("major")
    return out


async def shorts(run: Run) -> dict[str, Any]:
    si = await run.try_fetch(N.SHORT_INTEREST)
    if si is None:
        return {"available": False}
    d = {k: v for k, v in si.data.items() if k != "history"}
    d["prov_id"] = si.p
    d["candidates"] = si.candidates
    d["flags"] = si.prov.quality_flags
    run.ctx.prov["shorts"] = si.p
    fl = run.ctx.objects.get("float") or (run.ctx.sections.get("profile") or {}).get("float_shares")
    if d.get("shares_short") and fl:
        d["pct_of_float"] = d["shares_short"] / fl
    hist = si.data.get("history")
    d["history"] = hist.head(40) if isinstance(hist, pd.DataFrame) else repos.short_interest_history(run.symbol).tail(40)
    return d


# ---------------------------------------------------------------------------- news / social / events
async def news(run: Run) -> dict[str, Any]:
    r = await run.fetch(N.NEWS, name=run.ctx.objects.get("name"), cik=run.ctx.objects.get("cik"))
    out = SN.analyze(r.data, symbol=run.symbol, name=run.ctx.objects.get("name"))
    out["prov_id"] = r.p
    run.ctx.prov["news"] = r.p
    # news-volume anomaly from our own lake once it spans two weeks (the scheduled sweep stores every story we see)
    if out.get("news_volume_z") is None:
        try:
            from fa.store import lake
            hist = lake.read_partitions("news", {})
            if not hist.empty and "symbol" in hist.columns:
                h = hist[hist["symbol"] == run.symbol].copy()
                h["day"] = pd.to_datetime(h["dt"]).dt.date
                daily = h.groupby("day")["id"].nunique()
                if len(daily) >= 14:
                    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=56).date
                    s = daily.reindex(idx).fillna(0)
                    weekly = s.groupby([i // 7 for i in range(len(s))]).sum()      # 8 weekly buckets, last = this week
                    recent, prior = float(weekly.iloc[-1]), weekly.iloc[:-1]
                    prior = prior[prior > 0]
                    if len(prior) >= 3:
                        med = float(prior.median()); mad = float((prior - med).abs().median()) or max(med * 0.5, 1.0)
                        out["news_volume_z"] = float(max(min((recent - med) / (1.4826 * mad), 4.0), -4.0))
                        out["news_volume_source"] = f"lake history ({len(daily)} days): {recent:.0f} stories this week vs median {med:.0f}/week"
        except Exception as e:
            log.debug("lake news volume failed: %s", e)
    return out


async def social(run: Run) -> dict[str, Any]:
    st = await run.try_fetch(N.SOCIAL_STOCKTWITS)
    rd = await run.try_fetch(N.SOCIAL_REDDIT, name=run.ctx.objects.get("name")) if run.depth != "quick" else None
    out = SN.social(st.data if st else None, rd.data if rd else None)
    out["prov_id"] = st.p if st else (rd.p if rd else None)
    run.ctx.prov["social"] = out["prov_id"]
    if st:
        out["stocktwits"]["messages"] = st.data.head(30)[["created", "user", "sentiment", "body", "likes"]]
    return out


async def events(run: Run) -> dict[str, Any]:
    fomc = await run.try_fetch(N.FOMC_CALENDAR)
    econ_frames = []
    for i in range(0, 15):
        d = date.today() + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        r = await run.try_fetch(N.ECON_CALENDAR, date=str(d))
        if r is not None:
            econ_frames.append(r.data)
    econ = pd.concat(econ_frames, ignore_index=True) if econ_frames else None
    div = await run.try_fetch(N.DIVIDENDS)
    div_meta = getattr(div, "meta", None) if div else None
    prof_raw = (run.ctx.sections.get("profile") or {}).get("profile_raw", {})
    dmeta = {"exDividendDate": pd.Timestamp(prof_raw["exDividendDate"], unit="s").date().isoformat() if prof_raw.get("exDividendDate") else None}
    fye = (run.ctx.sections.get("fundamentals") or {}).get("fye_month")
    rem = (run.ctx.sections.get("options") or {}).get("expected_move", {}).get("realized_earnings") if run.ctx.sections.get("options") else None
    out = EV.merge(run.symbol, run.ctx.objects.get("earnings_df"), run.ctx.objects.get("earnings_meta"), dmeta, fomc.data if fomc else None, econ, fye, realized_moves=rem)
    out["prov_id"] = fomc.p if fomc else None
    nf = out.get("next_fomc")
    out["days_to_fomc"] = (nf - date.today()).days if nf else None
    run.ctx.prov["events"] = out["prov_id"]
    try:
        rows = [{"id": f"{e['symbol']}:{e['type']}:{e['date']}:{e['label'][:40]}", "symbol": e["symbol"], "event_type": e["type"], "event_date": e["date"], "event_ts": None,
                 "confirmed": e["confirmed"], "importance": e["importance"], "detail": None, "source": e["source"], "prov_id": out["prov_id"], "updated_at": datetime.now(timezone.utc)} for e in out["events"]]
        if rows:
            duck.upsert_df("events", pd.DataFrame(rows), ["id"])
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------- impact labels (needs risk + events + narrative)
async def impact(run: Run) -> dict[str, Any]:
    from fa.compute.events import impact as IM
    secs = run.ctx.sections
    sens = (secs.get("risk") or {}).get("sensitivity") or {}
    tags = ((secs.get("valuation") or {}).get("profile") or {}).get("tags") or []
    beta = ((secs.get("risk") or {}).get("beta_weekly_2y") or {}).get("beta_adjusted")
    channels = IM.stock_channels(sens, tags, beta)
    ev = secs.get("events") or {}
    opts = secs.get("options") or {}
    ctx = {"implied_move": ((opts.get("expected_move") or {}).get("earnings") or {}).get("implied_move_pct"),
           "hist_move": ((opts.get("expected_move") or {}).get("realized_earnings") or {}).get("mean_abs_move_pct"), "max_pain": (opts.get("max_pain") or {}).get("max_pain")}
    n_lab = 0
    for e in ev.get("events") or []:
        lab = IM.company_event_impact(e, ctx) if e.get("type") != "macro" else None
        if lab is None:
            lab = IM.macro_event_impact(e.get("label", ""), channels, int(e.get("importance") or 1))
        if lab:
            e["impact"] = lab
            n_lab += 1
    nar = secs.get("narrative") or {}
    for h in ("long", "medium", "short"):
        for it in nar.get(h) or []:
            it["impact"] = IM.narrative_impact(it)
    # extra 2-20 day context: seasonality and overnight/intraday split for the swing factors
    daily = run.ctx.objects.get("daily")
    extra: dict[str, Any] = {}
    if daily is not None and len(daily) > 300:
        d = daily.copy()
        d["ts"] = pd.to_datetime(d["ts"], utc=True)
        d["ret"] = d["close"].astype(float).pct_change()
        d["month"] = d["ts"].dt.month
        this_m = int(pd.Timestamp.utcnow().month)
        by_m = d.groupby("month")["ret"].agg(["mean", "count"])
        if this_m in by_m.index and by_m.loc[this_m, "count"] >= 40:
            extra["month_avg_daily_ret"] = float(by_m.loc[this_m, "mean"])
            extra["month_hit_rate"] = float((d[d["month"] == this_m].groupby(d["ts"].dt.year)["ret"].sum() > 0).mean())
        d["dom"] = d["ts"].dt.day
        tom = d[(d["dom"] >= 28) | (d["dom"] <= 3)]["ret"].mean()
        rest = d[(d["dom"] > 3) & (d["dom"] < 28)]["ret"].mean()
        extra["turn_of_month_edge"] = float(tom - rest) if pd.notna(tom) and pd.notna(rest) else None
        extra["in_turn_of_month"] = bool(pd.Timestamp.utcnow().day >= 28 or pd.Timestamp.utcnow().day <= 3)
        o = d["open"].astype(float); c = d["close"].astype(float)
        overnight = (o / c.shift(1) - 1).tail(120)
        intraday = (c / o - 1).tail(120)
        extra["overnight_ret_120d"] = float(overnight.sum()); extra["intraday_ret_120d"] = float(intraday.sum())
        r5 = float(c.iloc[-1] / c.iloc[-6] - 1) if len(c) > 6 else None
        r5_hist = (c / c.shift(5) - 1).dropna().tail(504)
        extra["r5_z"] = float((r5 - r5_hist.mean()) / r5_hist.std()) if r5 is not None and r5_hist.std() else None
        dv = float((c * daily["volume"].astype(float)).tail(20).mean())
        extra["dollar_volume_20d"] = dv
    tech = secs.get("technicals")
    if isinstance(tech, dict):
        tech["swing_extra"] = extra
    return {"channels": channels, "n_events_labelled": n_lab, "prov_id": run.ctx.prov.get("events")}


# ---------------------------------------------------------------------------- narrative (qualitative drivers)
async def narrative(run: Run) -> dict[str, Any]:
    from fa.compute import narrative as NR
    secs = run.ctx.sections
    news_items = (secs.get("news") or {}).get("items")
    filings = (secs.get("profile") or {}).get("recent_filings")
    fund = secs.get("fundamentals") or {}
    out = NR.build(run.symbol, run.ctx.objects.get("name"), news_items if isinstance(news_items, pd.DataFrame) else None,
                   filings if isinstance(filings, pd.DataFrame) else None, fund.get("segments"), run.ctx.objects.get("metrics"),
                   secs.get("events"), secs.get("analysts"))
    out["prov_id"] = run.ctx.prov.get("news") or run.ctx.prov.get("profile")
    return out


# ---------------------------------------------------------------------------- valuation
async def valuation(run: Run) -> dict[str, Any]:
    fund = run.ctx.objects.get("fund")
    if fund is None:
        raise RuntimeError("fundamentals unavailable")
    price, shares, mcap = run.ctx.objects.get("price"), run.ctx.objects.get("shares"), run.ctx.objects.get("market_cap")
    beta = (run.ctx.sections.get("risk") or {}).get("beta_weekly_2y", {}).get("beta_adjusted")
    rf = (run.ctx.sections.get("risk") or {}).get("rf_used")
    from fa.compute.valuation import profile as VP
    inp = VI.build_inputs(fund, price, mcap, shares, beta, rf)
    run.ctx.objects["val_inputs"] = inp
    prof_sec = run.ctx.sections.get("profile") or {}
    quality = (run.ctx.sections.get("fundamentals") or {}).get("quality") or {}
    profile = VP.classify(fund, prof_sec.get("sic"), prof_sec.get("industry"), prof_sec.get("sector"), inp.payout.value,
                          (quality.get("altman") or {}).get("zone"), run.ctx.mval("revenue_growth_1y"), mcap)
    daily = run.ctx.objects.get("daily")
    # --- peers first: the exit multiple and comps both use them
    comps = None
    if run.depth != "quick":
        peers_list, src = await PR.discover(run.symbol)
        if peers_list:
            profiles = await PR.peer_profiles(peers_list)
            prof_raw = prof_sec.get("profile_raw", {})
            sm = {k: run.ctx.mval(k) for k in ("pe", "ev_ebitda", "ev_sales", "pb")}
            sm["price"] = price
            comps = CP.comps_table(run.symbol, {**prof_raw, "currentPrice": price}, profiles, sm)
            comps["source"] = src
            comps["peer_list"] = peers_list
    # --- cash-flow models
    d = DCF.dcf(inp)
    sens = DCF.sensitivity(inp) if d.get("available") else None
    fcfe = DCF.fcfe(inp)
    rev = DCF.reverse_dcf(inp)
    imargin = DCF.implied_margin(inp)
    scen = DCF.scenarios(inp)
    hist = VM.historical_multiples(fund, daily, price, shares, {"eps_diluted": fund.latest("eps_diluted"), "revenue": fund.latest("revenue"), "ebitda": fund.latest("ebitda"),
                                                             "equity": fund.latest("equity"), "net_debt": inp.net_debt.value})
    # exit multiple: mean-revert between what peers trade at and what this company has historically commanded
    peer_m = float(comps["stats"]["ev_ebitda"]["median"]) if comps and (comps.get("stats") or {}).get("ev_ebitda", {}).get("median") else None
    own_m = float(hist["median_multiples"]["ev_ebitda"]) if hist.get("available") and hist.get("median_multiples", {}).get("ev_ebitda") else None
    if peer_m and own_m:
        exit_mult, exit_src = float((peer_m * own_m) ** 0.5), f"geometric mean of peer median {peer_m:.1f}x and own {hist['n_years']}y median {own_m:.1f}x"
    elif peer_m:
        exit_mult, exit_src = peer_m, "peer median EV/EBITDA"
    elif own_m:
        exit_mult, exit_src = own_m, "own historical median EV/EBITDA"
    else:
        exit_mult, exit_src = 12.0, "default 12x"
    exit_mult = min(max(exit_mult, 4.0), 25.0)
    d_exit = DCF.dcf(inp, exit_multiple=exit_mult)
    dcf_exit = {"available": d_exit.get("available") and d_exit.get("value_per_share_exit") is not None, "value_per_share": d_exit.get("value_per_share_exit"),
                "exit_multiple": d_exit.get("exit_multiple"), "exit_multiple_source": exit_src, "exit_ebitda_margin": d_exit.get("exit_ebitda_margin"),
                "reason": d_exit.get("reason"), "flags": d_exit.get("flags"), "formula": f"PV(FCF years 1-10) + year-10 EBITDA × {exit_mult:.1f}x ({exit_src})"}
    # --- earnings / book / dividend / asset models
    ddm_ = VM.ddm(inp)
    rim = VM.residual_income(inp)
    epv_ = VM.epv(inp)
    graham = VM.graham_number(inp)
    jpe, jpb, peg = VM.justified_pe(inp), VM.justified_pb(inp), VM.peg_value(inp)
    ncav_, tbv = VM.ncav(fund, shares), VM.tangible_book(fund, shares)
    ffo = VM.ffo_cap(fund, shares, inp.rf.value or 0.042, dps=inp.dps.value)
    runway = VM.cash_runway(fund)
    # --- simulations
    n_mc = {"quick": 0, "standard": 4000, "deep": 10000}.get(run.depth, 4000)
    mc_dcf = MC.dcf_distribution(inp, n=n_mc, margin_history=inp.extra.get("fcf_margin_history")) if n_mc and d.get("available") else {"available": False, "reason": "skipped at quick depth" if not n_mc else d.get("reason")}
    iv30 = ((run.ctx.sections.get("options") or {}).get("surface") or {}).get("atm_iv", {}).get("d30")
    mc_px = MC.price_paths(daily["close"], price, iv_annual=iv30, n={"quick": 5000, "standard": 20000, "deep": 50000}.get(run.depth, 20000)) if daily is not None and price else {"available": False}
    if mc_dcf.get("available"):
        mc_dcf["value_per_share"] = mc_dcf["percentiles"]["p50"]
    comps_model = {"available": bool(comps and comps.get("blended_implied_price")), "value_per_share": comps.get("blended_implied_price") if comps else None,
                   "reason": None if comps else "skipped at quick depth / no peers", "formula": "median of the prices implied by each peer-median multiple"}
    results = {"dcf": {**d, "value_per_share": d.get("value_per_share_gordon")}, "fcfe": fcfe, "dcf_exit": dcf_exit, "dcf_scenarios": scen, "mc_dcf": mc_dcf, "comps": comps_model,
               "hist_multiples": hist, "epv": epv_, "rim": rim, "ddm": ddm_, "justified_pe": jpe, "justified_pb": jpb, "peg": peg, "graham": graham, "ncav": ncav_,
               "tangible_book": tbv, "ffo_cap": ffo}
    blend = AG.assemble(price, profile, results)
    run.ctx.prov["valuation"] = run.ctx.prov.get("fundamentals")
    return {"prov_id": run.ctx.prov["valuation"], "inputs": inp.to_json(), "profile": {"primary": profile.primary, "tags": profile.tags, "notes": profile.notes},
            "dcf": d, "sensitivity": sens, "fcfe": fcfe, "reverse_dcf": rev, "implied_margin": imargin, "scenarios": scen, "dcf_exit": dcf_exit,
            "ddm": ddm_, "rim": rim, "epv": epv_, "graham": graham, "justified_pe": jpe, "justified_pb": jpb, "peg": peg, "ncav": ncav_, "tangible_book": tbv, "ffo_cap": ffo,
            "cash_runway": runway, "hist_multiples": {k: v for k, v in hist.items() if k != "history"}, "hist_multiples_history": hist.get("history"),
            "mc_dcf": mc_dcf, "mc_price": mc_px, "comps": comps, "blend": blend, "profile_kind": profile.primary}

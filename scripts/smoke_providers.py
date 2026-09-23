"""Exercise every keyless need through the router against live data."""
import asyncio, sys, time, traceback
sys.path.insert(0, ".")
from fa.core.logging import setup_logging
from fa.core.provenance import Ledger
from fa.registry import needs as N
from fa.registry.router import get_router

SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "AAPL"

async def main():
    setup_logging()
    r = get_router()
    led = Ledger("smoke")
    print("providers:", [h["provider"] + ("*" if h["available"] else "") for h in await r.health()])
    tests = [
        (N.QUOTE, {}), (N.OHLCV, {"interval": "1d", "period": "2y"}), (N.OHLCV, {"interval": "5m"}),
        (N.OPTION_EXPIRATIONS, {}), (N.OPTION_CHAIN, {}), (N.XBRL_FACTS, {}), (N.FILINGS, {}),
        (N.COMPANY_PROFILE, {}), (N.EARNINGS_DATES, {}), (N.ANALYST_RECS, {}), (N.ANALYST_TARGETS, {}),
        (N.INSIDER_TXNS, {}), (N.INSTITUTIONAL_HOLDERS, {}), (N.SHORT_INTEREST, {}), (N.SHORT_VOLUME, {"days": 10}),
        (N.NEWS, {"name": "Apple"}), (N.MACRO_NEWS, {}), (N.SOCIAL_STOCKTWITS, {}), (N.YIELD_CURVE, {}),
        (N.MACRO_SERIES, {"series_id": "DGS10"}), (N.ECON_CALENDAR, {}), (N.EARNINGS_CALENDAR, {"date": "2026-10-30"}),
        (N.DIVIDENDS, {}), (N.SPLITS, {}), (N.VIX_HISTORY, {}), (N.FOMC_CALENDAR, {}), (N.STATEMENTS_FALLBACK, {}),
        (N.SEGMENTS, {"max_filings": 2}),
    ]
    ok = 0
    for need, kw in tests:
        params = dict(kw)
        if need not in (N.MACRO_NEWS, N.YIELD_CURVE, N.MACRO_SERIES, N.ECON_CALENDAR, N.EARNINGS_CALENDAR, N.VIX_HISTORY, N.FOMC_CALENDAR):
            params["symbol"] = SYMBOL
        t0 = time.time()
        try:
            res = await r.fetch(need, led, **params)
            d = res.data
            shape = getattr(d, "shape", None) or (f"dict[{len(d)}]" if isinstance(d, dict) else f"list[{len(d)}]" if isinstance(d, list) else type(d).__name__)
            print(f"OK   {need:22s} {res.provider:10s} {time.time()-t0:5.1f}s {str(shape):14s} lat={res.prov.latency} depth={res.prov.fallback_depth} flags={res.prov.quality_flags} cache={res.from_cache}")
            ok += 1
        except Exception as e:
            print(f"FAIL {need:22s} {time.time()-t0:5.1f}s {type(e).__name__}: {str(e)[:220]}")
    print(f"\n{ok}/{len(tests)} needs OK; provenance records: {len(led.records)}")

asyncio.run(main())

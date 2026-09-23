# Full Analysis

Type a ticker, get a complete long / medium / short-term picture of the company and the stock — every number traceable
to the exact source payload it came from. Free data only.

- **Fundamentals** straight from SEC XBRL (every 10-K/10-Q, as-filed and restated, quarters derived from YTD figures), ~100 ratios, Piotroski / Altman / Beneish, segment mix from the filings' own tables.
- **Valuation**: FCFF/FCFE DCF with a stated assumption for every input, reverse DCF, residual income, EPV, DDM, comps with growth-adjusted regression, two Monte Carlo engines (price paths + DCF driver space), blended fair-value band.
- **Options**: full chain with exchange greeks (CBOE, free), our own Black-Scholes cross-check, ATM term structure, 25Δ skew, IV rank (suppressed until 60 days of history), IV vs realized, max pain, GEX/DEX with the sign convention stated, expected moves, earnings-implied move vs history, unusual activity, OI change.
- **Technicals**: 60+ native indicators on 5m / 15m / 1h / daily / weekly, swing structure, volume profile, anchored VWAPs, regime (ADX, Hurst, vol cone, drawdown).
- **Flow**: tick-rule CVD proxy from bars, FINRA off-exchange short-volume ratio, and with IB Gateway connected the real tick tape (Lee-Ready, large prints, off-exchange share, L2 depth).
- **News & social**: RSS union with syndication collapse, source weights and a financial lexicon; StockTwits; Reddit.
- **Macro & events**: index/sector trends, VIX term, curve, credit, dollar, oil; the name's rolling betas to each; earnings, FOMC, CPI/NFP/PCE, OPEX, filing due dates.
- **Verdict**: long / medium / short-term scores from ~85 factors with coverage and confidence, ranked drivers, and a drill-down from every score to raw values and source URLs. *Heuristic composite — not backtested.*

Every fetch is archived (gzipped, sha256) and every value carries a provenance id; the UI shows a badge (provider, delay, fallback depth) on each number.

## Setup (Windows)

```powershell
scripts\bootstrap.ps1        # venv on Python 3.13 at C:\fadata\venv, data root C:\fadata, web deps
notepad .env                 # FA_SEC_USER_AGENT="Your Name you@email" is required by SEC; FRED/Reddit/Finnhub keys optional (free)
scripts\run_api.ps1          # http://127.0.0.1:8000  (API + scheduler)
scripts\run_web.ps1          # http://localhost:5173
```

CLI: `C:\fadata\venv\fa313\Scripts\python.exe -m fa analyze AAPL --depth standard` writes JSON + a markdown dossier to `C:\fadata\runs`.
`python -m fa doctor` checks providers and the store. `python -m fa watch add AAPL` puts a symbol on the daily close-snapshot job.

**The data root must be outside OneDrive** (default `C:\fadata`) — the parquet lake and DuckDB file will be corrupted by sync.

## Live data tiers

| Tier | Source | What it adds | Setup |
|---|---|---|---|
| default | SEC EDGAR, CBOE delayed chains, Yahoo, Nasdaq, FINRA, Treasury, RSS, StockTwits | everything, ~15 min delayed quotes/chains | none |
| IBKR | IB Gateway + `ib_async` | live quotes (with subscriptions), broker greeks on NTM contracts, 2y of underlying IV/HV history, tick tape, L2 | start IB Gateway; set `FA_IB_PORT` (4001 live / 4002 paper) |
| Schwab | thinkorswim developer API | live quotes + chains with greeks | register an app, `python -m fa schwab-login` weekly |
| keyed free | FRED, Reddit, Finnhub | macro series + release calendar, Reddit mentions, extra analyst data | free signups, keys in `.env` |

The router (`config/sources.yaml`) picks the best available provider per data need and records which one answered; nothing silently degrades — the badge changes.

## What is NOT free (and what we do instead)

- Dark-pool prints / sweeps / full OPRA tape → IBKR tick tape with exchange codes, FINRA daily short volume, CBOE volume-vs-OI heuristics, all labelled PROXY.
- Retroactive option-chain history → we snapshot every day from now (watchlist + close-snapshot job); IBKR backfills underlying-level IV.
- Real-time L2 → needs IBKR market-data subscriptions.
- 13F holdings are 45 days lagged by law; short interest is bi-monthly (daily short *volume* fills the gap).

## Layout

```
config/    sources.yaml (failover registry) · concepts.yaml (XBRL tag map) · weights.yaml (factor weights) · peers.yaml
fa/core    settings · provenance · types (Val envelope) · clock · http · archive
fa/registry router (failover / overlay / consensus) · cache · circuit breaker
fa/providers sec_edgar cboe yahoo nasdaq finra fred treasury stooq rss stocktwits reddit finnhub ibkr schwab
fa/store   duckdb control plane · parquet lake · write-through persistence · repos
fa/compute fundamentals · ratios · segments · valuation · options · technical · orderflow · risk · sentiment · events · market · peers
fa/score   factor registry + library (~85 factors) · engine · explain
fa/pipeline sections · orchestrator (SSE progress) · scheduler
fa/api     FastAPI        web/   Vite + React        tests/   pytest
```

## Tests

```powershell
C:\fadata\venv\fa313\Scripts\python.exe -m pytest tests -q
```

## Reddit API usage

The Reddit integration (`fa/providers/reddit.py`, via PRAW) is read-only and non-commercial: for a ticker being
analysed it searches r/stocks, r/investing, r/wallstreetbets, r/options, r/StockMarket and r/ValueInvesting for recent
mentions (about six `search` calls per analysis, far below the free-tier rate limit). It never posts, votes, messages or
collects user data, and post text is used only to compute a mention-count and sentiment factor for the current analysis.
Credentials come from `.env` (`FA_REDDIT_CLIENT_ID`, `FA_REDDIT_CLIENT_SECRET`) and are never committed.

## License

MIT — see `LICENSE`.

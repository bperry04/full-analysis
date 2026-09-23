"""The vocabulary of the system: every data need has one canonical name.

No module calls a provider directly; it asks the router for a need. Providers advertise the needs they
serve; sources.yaml orders providers per need; provenance is keyed by need.
"""
from __future__ import annotations

# --- market data ---
QUOTE = "quote"                       # {symbol}
OHLCV = "ohlcv"                       # {symbol, interval, period|start,end}
TICKS = "ticks"                       # {symbol, n}           IBKR only
DEPTH = "depth"                       # {symbol}              IBKR only
# --- options ---
OPTION_EXPIRATIONS = "option_expirations"
OPTION_CHAIN = "option_chain"         # {symbol} full chain, canonical schema
IV_HISTORY = "iv_history"             # {symbol, days}        IBKR only (underlying-level IV bars)
HV_HISTORY = "hv_history"             # {symbol, days}        IBKR only
# --- fundamentals / filings ---
XBRL_FACTS = "xbrl_facts"             # {symbol|cik}
FILINGS = "filings"                   # {symbol|cik}
STATEMENTS_FALLBACK = "statements_fallback"   # {symbol} yfinance 5-period tables
SEGMENTS = "segments"                 # {symbol|cik}
COMPANY_PROFILE = "company_profile"   # {symbol}
TICKER_MAP = "ticker_map"             # {} SEC ticker->cik
# --- estimates / analysts / ownership ---
EARNINGS_DATES = "earnings_dates"
ANALYST_RECS = "analyst_recs"
ANALYST_TARGETS = "analyst_targets"
INSIDER_TXNS = "insider_txns"
INSTITUTIONAL_HOLDERS = "institutional_holders"
# --- shorts ---
SHORT_INTEREST = "short_interest"     # {symbol}
SHORT_VOLUME = "short_volume"         # {date} whole-market FINRA file, or {symbol, days}
# --- news / social ---
NEWS = "news"                         # {symbol, name}
MACRO_NEWS = "macro_news"
SOCIAL_STOCKTWITS = "social_stocktwits"
SOCIAL_REDDIT = "social_reddit"
# --- macro / calendar ---
MACRO_SERIES = "macro_series"         # {series_id}
YIELD_CURVE = "yield_curve"
ECON_CALENDAR = "econ_calendar"       # {date}
EARNINGS_CALENDAR = "earnings_calendar"
DIVIDENDS = "dividends"
SPLITS = "splits"
VIX_HISTORY = "vix_history"
FOMC_CALENDAR = "fomc_calendar"

ALL = [v for k, v in globals().items() if k.isupper() and isinstance(v, str)]

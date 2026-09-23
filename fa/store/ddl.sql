-- Control-plane and small derived tables live natively in DuckDB (C:\fadata\fa.duckdb).
-- High-volume facts (bars, chain snapshots, XBRL, news, ticks) live in the parquet lake and are exposed as views.

CREATE TABLE IF NOT EXISTS schema_version(version INTEGER, applied_at TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS symbols(
  symbol VARCHAR PRIMARY KEY, cik VARCHAR, name VARCHAR, exchange VARCHAR, sic VARCHAR, sic_description VARCHAR,
  sector VARCHAR, industry VARCHAR, country VARCHAR, fiscal_year_end VARCHAR, shares_out DOUBLE, float_shares DOUBLE,
  currency VARCHAR, first_seen TIMESTAMPTZ, last_refreshed TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS provenance(
  prov_id VARCHAR, run_id VARCHAR, need VARCHAR, provider VARCHAR, endpoint VARCHAR, fetched_at TIMESTAMPTZ,
  as_of TIMESTAMPTZ, latency VARCHAR, tier VARCHAR, is_delayed BOOLEAN, fallback_depth INTEGER, from_cache BOOLEAN,
  cache_age_s DOUBLE, row_count BIGINT, duration_ms INTEGER, payload_sha256 VARCHAR, raw_path VARCHAR,
  quality_flags VARCHAR[], attempts JSON, PRIMARY KEY(run_id, prov_id)
);

CREATE TABLE IF NOT EXISTS analysis_runs(
  run_id VARCHAR PRIMARY KEY, symbol VARCHAR, depth VARCHAR, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
  status VARCHAR, code_version VARCHAR, weights_hash VARCHAR, coverage_long DOUBLE, coverage_medium DOUBLE,
  coverage_short DOUBLE, score_long DOUBLE, score_medium DOUBLE, score_short DOUBLE, sections_ok VARCHAR[],
  sections_failed VARCHAR[], result_path VARCHAR
);

CREATE TABLE IF NOT EXISTS iv_surface_daily(
  symbol VARCHAR, dt DATE, snap_ts TIMESTAMPTZ, spot DOUBLE,
  atm_iv_7 DOUBLE, atm_iv_30 DOUBLE, atm_iv_60 DOUBLE, atm_iv_90 DOUBLE, atm_iv_180 DOUBLE, atm_iv_365 DOUBLE,
  iv30_vendor DOUBLE, term_slope_30_90 DOUBLE, term_slope_7_30 DOUBLE, rr25_30 DOUBLE, fly25_30 DOUBLE, skew_slope_30 DOUBLE,
  put_call_oi DOUBLE, put_call_vol DOUBLE, total_oi BIGINT, total_volume BIGINT, call_oi BIGINT, put_oi BIGINT,
  max_pain DOUBLE, gex_total DOUBLE, gex_flip DOUBLE, dex_total DOUBLE, hv20 DOUBLE, hv60 DOUBLE, iv_rv_30 DOUBLE,
  em_next_exp DOUBLE, next_exp DATE, contracts_n INTEGER, source VARCHAR, prov_id VARCHAR,
  PRIMARY KEY(symbol, dt)
);

CREATE TABLE IF NOT EXISTS iv_underlying_daily(
  symbol VARCHAR, dt DATE, iv DOUBLE, hv DOUBLE, source VARCHAR, PRIMARY KEY(symbol, dt, source)
);

CREATE TABLE IF NOT EXISTS fundamentals_normalized(
  symbol VARCHAR, cik VARCHAR, metric VARCHAR, period_type VARCHAR, period_end DATE, period_start DATE, fy INTEGER,
  fp VARCHAR, value DOUBLE, unit VARCHAR, source_tag VARCHAR, taxonomy VARCHAR, derived BOOLEAN, derivation VARCHAR,
  is_restated BOOLEAN, filed DATE, accn VARCHAR, confidence DOUBLE, prov_id VARCHAR,
  PRIMARY KEY(symbol, metric, period_type, period_end, is_restated)
);

CREATE TABLE IF NOT EXISTS short_interest(
  symbol VARCHAR, settlement_date DATE, shares_short DOUBLE, shares_short_prior DOUBLE, avg_daily_volume DOUBLE,
  days_to_cover DOUBLE, pct_of_float DOUBLE, source VARCHAR, prov_id VARCHAR, PRIMARY KEY(symbol, settlement_date, source)
);

CREATE TABLE IF NOT EXISTS analyst_consensus(
  symbol VARCHAR, as_of DATE, n_analysts INTEGER, strong_buy INTEGER, buy INTEGER, hold INTEGER, sell INTEGER, strong_sell INTEGER,
  pt_low DOUBLE, pt_mean DOUBLE, pt_median DOUBLE, pt_high DOUBLE, current_price DOUBLE, source VARCHAR, prov_id VARCHAR,
  PRIMARY KEY(symbol, as_of)
);

CREATE TABLE IF NOT EXISTS analyst_actions(
  symbol VARCHAR, action_date DATE, firm VARCHAR, action VARCHAR, from_grade VARCHAR, to_grade VARCHAR, source VARCHAR, prov_id VARCHAR,
  PRIMARY KEY(symbol, action_date, firm, to_grade)
);

CREATE TABLE IF NOT EXISTS macro_series(
  series_id VARCHAR, dt DATE, value DOUBLE, source VARCHAR, prov_id VARCHAR, fetched_at TIMESTAMPTZ, PRIMARY KEY(series_id, dt)
);

CREATE TABLE IF NOT EXISTS events(
  id VARCHAR PRIMARY KEY, symbol VARCHAR, event_type VARCHAR, event_date DATE, event_ts TIMESTAMPTZ, confirmed BOOLEAN,
  importance INTEGER, detail JSON, source VARCHAR, prov_id VARCHAR, updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS watchlist(
  symbol VARCHAR PRIMARY KEY, added_at TIMESTAMPTZ, snapshot_daily BOOLEAN DEFAULT TRUE, priority INTEGER DEFAULT 5, note VARCHAR
);

CREATE TABLE IF NOT EXISTS fetch_log(
  ts TIMESTAMPTZ, need VARCHAR, symbol VARCHAR, provider VARCHAR, ok BOOLEAN, from_cache BOOLEAN, attempts JSON
);

CREATE TABLE IF NOT EXISTS score_history(
  symbol VARCHAR, run_id VARCHAR, ts TIMESTAMPTZ, horizon VARCHAR, score DOUBLE, coverage DOUBLE, confidence DOUBLE,
  PRIMARY KEY(run_id, horizon)
);

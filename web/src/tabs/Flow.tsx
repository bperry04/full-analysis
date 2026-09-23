import React from "react";
import type { RunState } from "../api";
import { Card, Line, ProvBadge, Section, Table } from "../components";
import { big, num, pct, rows } from "../fmt";

export function Flow({ s }: { s: RunState }) {
  const f = s.data.flow;
  const r = s.data.risk || {};
  if (!f) return <Section name="flow" status={s.sections.flow}><div /></Section>;
  const b = f.bars || {};
  const sv = f.short_volume || {};
  const tape = f.tape || {};
  const daily = rows(b.daily);
  const svs = rows(sv.series);
  return (
    <Section name="flow" status={s.sections.flow}>
      <div className="grid" style={{ gap: 12 }}>
        <div className="banner">Order flow: the tick tape (Lee-Ready classification, large prints, off-exchange share) needs IB Gateway connected and depth=deep. Everything else on this tab is a PROXY and is labelled as such.</div>
        <div className="grid g3">
          <Card title="Bar-based order flow" sub={<>{b.method} <ProvBadge p={f.prov_id} /></>}>
            <div className="kv">
              <span>today imbalance</span><span className={`mono ${b.today_imbalance > 0 ? "pos" : "neg"}`}>{pct(b.today_imbalance)}</span>
              <span>today delta (shares)</span><span className="mono">{big(b.today_delta, 1)}</span>
              <span>5-day imbalance</span><span className={`mono ${b.imbalance_5d > 0 ? "pos" : "neg"}`}>{pct(b.imbalance_5d)}</span>
              <span>20-day CVD trend</span><span className={`mono ${b.cvd_trend_20d > 0 ? "pos" : "neg"}`}>{pct(b.cvd_trend_20d)}</span>
              <span>relative volume (time of day)</span><span className="mono">{num(b.rel_volume_time_of_day)}x</span>
            </div>
            {daily.length ? <Line series={[{ name: "cvd", color: "var(--cyan)", data: daily.map((d: any) => [new Date(d.date).getTime(), d.cvd]) }]} yfmt={(v) => big(v, 0)} zero /> : null}
          </Card>
          <Card title="FINRA off-exchange short volume" sub={sv.note}>
            <div className="kv">
              <span>date</span><span className="mono">{sv.date}</span>
              <span>short-sale share</span><span className="mono">{pct(sv.short_ratio, 1, false)}</span>
              <span>20d mean</span><span className="mono">{pct(sv.short_ratio_mean_20d, 1, false)}</span>
              <span>z vs 60d</span><span className={`mono ${sv.short_ratio_z_60d > 1 ? "neg" : sv.short_ratio_z_60d < -1 ? "pos" : ""}`}>{num(sv.short_ratio_z_60d)}</span>
              <span>short / total off-exchange</span><span className="mono">{big(sv.short_volume, 1)} / {big(sv.off_exchange_volume, 1)}</span>
            </div>
            {svs.length ? <Line series={[{ name: "ratio", color: "var(--amber)", data: svs.map((d: any) => [new Date(d.date).getTime(), d.ratio]) }]} yfmt={(v) => pct(v, 0, false)} /> : null}
          </Card>
          <Card title="Tick tape (IBKR)" sub={tape.method || ""}>
            {tape.n_trades ? (
              <>
                <div className="kv">
                  <span>trades</span><span className="mono">{tape.n_trades}</span>
                  <span>buy / sell volume</span><span className="mono">{big(tape.buy_volume, 1)} / {big(tape.sell_volume, 1)}</span>
                  <span>imbalance</span><span className={`mono ${tape.imbalance > 0 ? "pos" : "neg"}`}>{pct(tape.imbalance)}</span>
                  <span>large-print share (p99)</span><span className="mono">{pct(tape.large_print_share, 1, false)}</span>
                  <span>off-exchange share</span><span className="mono">{pct(tape.off_exchange_share, 1, false)}</span>
                  <span>median quoted spread</span><span className="mono">{num(tape.median_spread_bps, 1)} bps</span>
                  <span>avg trade size</span><span className="mono">{num(tape.avg_trade_size, 0)}</span>
                </div>
                <Table data={tape.large_prints} />
              </>
            ) : <div className="dim small">{tape.reason || "not available"}</div>}
            {f.depth?.levels ? <div className="kv" style={{ marginTop: 8 }}><span>L2 depth imbalance</span><span className="mono">{pct(f.depth.depth_imbalance)}</span><span>bid / ask depth</span><span className="mono">{big(f.depth.bid_depth, 0)} / {big(f.depth.ask_depth, 0)}</span></div> : null}
          </Card>
        </div>
        <div className="grid g2">
          <Card title="Risk statistics (1y daily)">
            <div className="kv">
              <span>annualized vol</span><span className="mono">{pct(r.ann_vol_1y, 1, false)}</span>
              <span>Sharpe / Sortino</span><span className="mono">{num(r.sharpe_1y)} / {num(r.sortino_1y)}</span>
              <span>skew / kurtosis</span><span className="mono">{num(r.skew_1y)} / {num(r.kurtosis_1y)}</span>
              <span>VaR95 / CVaR95 (1d)</span><span className="mono">{pct(r.var_95_1d?.var, 2, false)} / {pct(r.var_95_1d?.cvar, 2, false)}</span>
              <span>VaR99 / CVaR99 (1d)</span><span className="mono">{pct(r.var_99_1d?.var, 2, false)} / {pct(r.var_99_1d?.cvar, 2, false)}</span>
              <span>worst / best day</span><span className="mono">{pct(r.worst_day_1y)} / {pct(r.best_day_1y)}</span>
              <span>beta (2y weekly, adj.)</span><span className="mono">{num(r.beta_weekly_2y?.beta_adjusted)} (R² {num(r.beta_weekly_2y?.r2)})</span>
              <span>beta (1y daily)</span><span className="mono">{num(r.beta_daily_1y?.beta_adjusted)}</span>
              <span>up / down capture</span><span className="mono">{num(r.capture?.up_capture)} / {num(r.capture?.down_capture)}</span>
            </div>
          </Card>
          <Card title="Daily buy/sell proxy (last 30 sessions)">
            <Table data={daily.slice(-30).reverse()} cols={["date", "volume", "buy", "sell", "delta", "imbalance", "cvd"]} fmt={{ imbalance: (v) => pct(v), volume: (v) => big(v, 1), buy: (v) => big(v, 1), sell: (v) => big(v, 1), delta: (v) => big(v, 1), cvd: (v) => big(v, 1) }} />
          </Card>
        </div>
      </div>
    </Section>
  );
}

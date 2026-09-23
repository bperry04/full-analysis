import React, { useState } from "react";
import type { RunState } from "../api";
import { Bars, Card, Line, ProvBadge, Section, Table } from "../components";
import { isNum, num, pct, rows, usd } from "../fmt";
import { OptionEvaluator } from "./OptionEvaluator";

export function Options({ s }: { s: RunState }) {
  const o = s.data.options;
  const [exp, setExp] = useState<string>("");
  if (!o) return <Section name="options" status={s.sections.options}><div /></Section>;
  const su = o.surface || {};
  const term = rows(o.term);
  const rk = o.ranks || {};
  const fl = o.flow || {};
  const ex = o.exposure || {};
  const em = o.expected_move || {};
  const chain = rows(o.chain);
  const expiries = Array.from(new Set(chain.map((c: any) => String(c.expiry)))).sort();
  const sel = exp || expiries[0];
  const rowsSel = chain.filter((c: any) => String(c.expiry) === sel);
  const strikes = Array.from(new Set(rowsSel.map((c: any) => c.strike))).sort((a: any, b: any) => a - b);
  const byK: Record<string, any> = {};
  for (const c of rowsSel) byK[`${c.strike}${c.right}`] = c;
  const ivh = rows(o.iv_history);
  const gex = rows(o.gex_profile);
  return (
    <Section name="options" status={s.sections.options}>
      <div className="grid" style={{ gap: 12 }}>
        <OptionEvaluator symbol={s.symbol} horizon="short" direction={s.data.technicals?.patterns?.setup?.direction} />
        <div className="grid g4">
          <Card title="Implied vol" sub={<><ProvBadge p={o.prov_id} /> {o.provider} · {o.latency}</>}>
            <div className="kv">
              <span>ATM IV 7 / 30 / 60 / 90 / 180 / 365</span><span className="mono">{["d7", "d30", "d60", "d90", "d180", "d365"].map((k) => pct(su.atm_iv?.[k], 0, false)).join(" / ")}</span>
              <span>term structure</span><span className="mono">{su.term_shape} ({pct(su.term_slope_30_90, 1)} 30→90)</span>
              <span>vendor IV30</span><span className="mono">{isNum(su.iv30_vendor) ? (su.iv30_vendor > 1 ? su.iv30_vendor.toFixed(1) + "%" : pct(su.iv30_vendor, 1, false)) : "—"}</span>
              <span>IV rank / percentile</span><span className="mono">{rk.iv_rank != null ? `${pct(rk.iv_rank, 0, false)} / ${pct(rk.iv_percentile, 0, false)} (${rk.history_days}d)` : <span className="warn">{rk.flag}</span>}</span>
              <span>HV20 / HV60 / HV252</span><span className="mono">{pct(o.iv_vs_rv?.hv20, 0, false)} / {pct(o.iv_vs_rv?.hv60, 0, false)} / {pct(o.iv_vs_rv?.hv252, 0, false)}</span>
              <span>IV/RV (20d) · VRP</span><span className="mono">{num(o.iv_vs_rv?.iv_rv_20)} · {pct(o.iv_vs_rv?.vol_risk_premium, 1)}</span>
            </div>
          </Card>
          <Card title="Skew (30d)">
            <div className="kv">
              <span>25Δ risk reversal</span><span className={`mono ${su.skew?.rr25 > 0 ? "pos" : "neg"}`}>{pct(su.skew?.rr25, 1)}</span>
              <span>25Δ butterfly</span><span className="mono">{pct(su.skew?.fly25, 1)}</span>
              <span>10Δ risk reversal</span><span className="mono">{pct(su.skew?.rr10, 1)}</span>
              <span>skew slope (dIV/dlnK)</span><span className="mono">{num(su.skew?.skew_slope)}</span>
              <span>25Δ put / call IV</span><span className="mono">{pct(su.skew?.put25_iv, 0, false)} / {pct(su.skew?.call25_iv, 0, false)}</span>
              <span>expiries used</span><span className="mono small">{su.skew?.expiry}</span>
            </div>
          </Card>
          <Card title="Positioning">
            <div className="kv">
              <span>P/C open interest</span><span className="mono">{num(su.put_call_oi)}</span>
              <span>P/C volume</span><span className="mono">{num(fl.put_call_vol)}{isNum(fl.put_call_vol_z) ? ` (${fl.put_call_vol_z > 0 ? "+" : ""}${fl.put_call_vol_z.toFixed(1)}σ)` : ""}</span>
              <span>total OI · volume</span><span className="mono">{num(su.total_oi, 0)} · {num(su.total_volume, 0)}</span>
              <span>call / put wall</span><span className="mono">{usd(fl.call_wall, 0)} / {usd(fl.put_wall, 0)}</span>
              <span>max pain ({o.max_pain?.expiry})</span><span className="mono">{usd(o.max_pain?.max_pain, 0)}</span>
              <span>net premium (C−P)</span><span className={`mono ${fl.net_premium_call_minus_put > 0 ? "pos" : "neg"}`}>${(fl.net_premium_call_minus_put / 1e6).toFixed(1)}M</span>
              <span>OI Δ calls / puts</span><span className="mono">{fl.has_prev_snapshot ? `${num(fl.oi_change_calls, 0)} / ${num(fl.oi_change_puts, 0)}` : <span className="dim">needs 2 snapshots</span>}</span>
            </div>
          </Card>
          <Card title="Dealer gamma (proxy)" sub="sign convention assumed">
            <div className="kv">
              <span>regime</span><span className={`mono ${ex.regime === "positive_gamma" ? "pos" : "neg"}`}>{ex.regime}</span>
              <span>net GEX ($/1%)</span><span className="mono">${(ex.gex_total / 1e6).toFixed(0)}M</span>
              <span>gamma flip</span><span className="mono">{usd(ex.gex_flip, 0)}</span>
              <span>net DEX</span><span className="mono">${(ex.dex_total / 1e9).toFixed(1)}B</span>
              <span>largest +/− strike</span><span className="mono">{usd(ex.largest_positive_gex_strike, 0)} / {usd(ex.largest_negative_gex_strike, 0)}</span>
            </div>
            <div className="small dim" style={{ marginTop: 6 }}>{ex.assumption}</div>
          </Card>
        </div>
        <div className="grid g3">
          <Card title="ATM IV term structure">
            <Line series={[{ name: "atm", color: "var(--cyan)", data: term.map((t: any) => [t.dte, t.atm_iv]) }]} yfmt={(v) => pct(v, 0, false)} />
            <Table data={term.slice(0, 12)} cols={["expiry", "dte", "atm_iv", "call_oi", "put_oi", "call_vol", "put_vol"]} fmt={{ atm_iv: (v) => pct(v, 1, false) }} />
          </Card>
          <Card title="IV history (own snapshots + IBKR)" sub={ivh.length ? `${ivh.length} days` : "accrues daily from the close-snapshot job"}>
            {ivh.length > 1 ? <Line series={[{ name: "iv", color: "var(--purple)", data: ivh.map((r: any) => [new Date(r.dt).getTime(), r.iv]) }]} yfmt={(v) => pct(v, 0, false)} /> : <div className="dim small">No history yet. Add this symbol to the watchlist (Sources tab) and the 16:20 ET job will record a surface row every trading day. Connecting IB Gateway backfills 2 years of underlying IV.</div>}
          </Card>
          <Card title="GEX by strike (≤60 DTE)">
            <Bars items={gex.filter((g: any) => Math.abs(g.gex) > 0).slice(0, 30).map((g: any) => ({ label: usd(g.strike, 0), value: g.gex / 1e6 }))} h={300} labelFmt={(v) => v.toFixed(0) + "M"} />
          </Card>
        </div>
        <div className="grid g2">
          <Card title="Expected moves (ATM straddle)" sub={em.earnings?.available ? `earnings: ${pct(em.earnings.implied_move_pct, 1, false)} implied (${em.earnings.front_expiry}) vs ${pct(em.realized_earnings?.mean_abs_move_pct, 1, false)} avg realized over ${em.realized_earnings?.n} reports` : "no earnings inside the expiry window"}>
            <Table data={em.by_expiry} cols={["expiry", "dte", "atm_strike", "straddle", "implied_move_pct", "one_sigma_pct", "lower", "upper"]} fmt={{ implied_move_pct: (v) => pct(v, 1, false), one_sigma_pct: (v) => pct(v, 1, false) }} />
          </Card>
          <Card title="Unusual activity (volume > OI, liquid)">
            <Table data={fl.unusual} cols={["contract_symbol", "expiry", "strike", "right", "volume", "open_interest", "vol_oi", "premium_vol", "iv", "delta"]} fmt={{ premium_vol: (v) => "$" + (v / 1e3).toFixed(0) + "K", iv: (v) => pct(v, 0, false) }} />
          </Card>
        </div>
        <Card title="Chain (near the money, ≤120 DTE)" sub={<>{o.chain_stats?.contracts} contracts · greeks mismatch {pct(o.chain_stats?.delta_mismatch_share, 1, false)} · IV computed {pct(o.chain_stats?.iv_computed_share, 0, false)}</>}>
          <div style={{ marginBottom: 6 }}><select value={sel} onChange={(e) => setExp(e.target.value)} style={{ background: "var(--bg3)", color: "var(--text)", border: "1px solid var(--line)", padding: 4 }}>{expiries.map((e) => <option key={e} value={e}>{e}</option>)}</select></div>
          <div className="scroll" style={{ maxHeight: 520 }}>
            <table className="tbl">
              <thead><tr><th>C bid</th><th>C ask</th><th>C IV</th><th>C Δ</th><th>C vol</th><th>C OI</th><th style={{ textAlign: "center" }}>strike</th><th>P OI</th><th>P vol</th><th>P Δ</th><th>P IV</th><th>P bid</th><th>P ask</th></tr></thead>
              <tbody>{strikes.map((k: any) => { const c = byK[`${k}C`] || {}, p = byK[`${k}P`] || {}; const atm = Math.abs(k - o.spot) < (o.spot * 0.005); return (
                <tr key={k} style={atm ? { background: "var(--bg3)" } : undefined}>
                  <td>{num(c.bid)}</td><td>{num(c.ask)}</td><td>{pct(c.iv, 0, false)}</td><td>{num(c.delta)}</td><td>{c.volume ?? "—"}</td><td>{c.open_interest ?? "—"}</td>
                  <td style={{ textAlign: "center" }} className="mono"><b>{k}</b></td>
                  <td>{p.open_interest ?? "—"}</td><td>{p.volume ?? "—"}</td><td>{num(p.delta)}</td><td>{pct(p.iv, 0, false)}</td><td>{num(p.bid)}</td><td>{num(p.ask)}</td>
                </tr>); })}</tbody>
            </table>
          </div>
        </Card>
      </div>
    </Section>
  );
}

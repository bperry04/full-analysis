import React, { useEffect, useState } from "react";
import { api } from "../api";
import { Card, Line, Table } from "../components";
import { isNum, num, pct, rows, usd } from "../fmt";

const DEFAULT_HOLD: Record<string, number> = { short: 10, medium: 45, long: 180 };

export function OptionEvaluator({ symbol, horizon, direction }: { symbol: string; horizon: "short" | "medium" | "long"; direction?: number }) {
  const [right, setRight] = useState<"C" | "P">(direction != null && direction < 0 ? "P" : "C");
  const [expiry, setExpiry] = useState<string>("");
  const [hold, setHold] = useState<string>(String(DEFAULT_HOLD[horizon]));
  const [target, setTarget] = useState<string>("");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (exp?: string) => {
    if (!symbol) return;
    setBusy(true); setErr(null);
    try {
      const qs = new URLSearchParams({ right, horizon, hold_days: hold || String(DEFAULT_HOLD[horizon]) });
      if (exp ?? expiry) qs.set("expiry", exp ?? expiry);
      if (target) qs.set("target", target);
      const r = await api(`/api/ticker/${symbol}/options/evaluate?${qs}`);
      setRes(r);
      if (r.expiry && !expiry) setExpiry(r.expiry);
    } catch (e: any) { setErr(String(e)); } finally { setBusy(false); }
  };
  useEffect(() => { setRes(null); setExpiry(""); run(); }, [symbol, horizon]);   // eslint-disable-line react-hooks/exhaustive-deps
  const b = res?.best;
  const comps = b?.components || {};
  const sel = (label: string, el: React.ReactNode) => <label className="small" style={{ display: "flex", flexDirection: "column", gap: 2 }}><span className="muted">{label}</span>{el}</label>;
  const inputStyle = { background: "var(--bg3)", color: "var(--text)", border: "1px solid var(--line)", padding: "4px 6px", borderRadius: 4 };
  return (
    <Card title={`Option evaluator · ${res?.horizon_label || horizon}`} sub={res ? <span className="dim">{res.context?.chain_provider} · {res.context?.chain_latency} · {res.n_evaluated} contracts scored</span> : null}>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 8 }}>
        {sel("Type", <div className="toggle"><button className={right === "C" ? "on" : ""} onClick={() => setRight("C")}>Call</button><button className={right === "P" ? "on" : ""} onClick={() => setRight("P")}>Put</button></div>)}
        {sel("Expiration", <select style={inputStyle} value={expiry} onChange={(e) => { setExpiry(e.target.value); run(e.target.value); }}>{(res?.expiries || (expiry ? [expiry] : [])).map((e: string) => <option key={e} value={e}>{e}</option>)}</select>)}
        {sel("Hold (trading days)", <input className="num" style={{ width: 70 }} value={hold} onChange={(e) => setHold(e.target.value)} />)}
        {sel("Price target (optional)", <input className="num" style={{ width: 90 }} placeholder={res?.thesis_price ? usd(res.thesis_price) : ""} value={target} onChange={(e) => setTarget(e.target.value)} />)}
        <button style={{ ...inputStyle, background: "var(--blue)", color: "#061020", fontWeight: 600, cursor: "pointer" }} onClick={() => run()} disabled={busy}>{busy ? "…" : "Evaluate"}</button>
      </div>
      {err ? <div className="err">{err}</div> : null}
      {res && !res.available ? <div className="err">{res.reason}</div> : null}
      {res?.available ? (
        <>
          <div className="small muted" style={{ marginBottom: 6 }}>
            Spot {usd(res.spot)} · {res.dte} DTE, hold {res.hold_days}d · σ used {pct(res.sigma_used, 0, false)} (blend of ATM IV {pct(res.context?.iv_atm30, 0, false)} and HV20 {pct(res.context?.hv20, 0, false)}) → 1σ over the hold ±{pct(res.one_sigma_move_hold_pct, 1, false)} ·
            thesis: {res.thesis} → {usd(res.thesis_price)}{res.iv_crush_modelled ? <span className="warn"> · earnings inside hold: IV crush modelled</span> : ""} · delta sweet spot {res.delta_sweet_spot.map((d: number) => d.toFixed(2)).join("–")}
            {res.setup?.setup ? <> · stock setup: <b>{res.setup.setup}</b></> : null}
          </div>
          <div className="grid g2">
            <div className="card" style={{ background: "var(--bg3)" }}>
              <div style={{ fontSize: 16, fontWeight: 600 }}>Best: {b.contract_symbol} <span className="dim small">({right === "C" ? "call" : "put"} {usd(b.strike, 0)} strike)</span> <span className="pill ok">score {num(b.score, 0)}</span></div>
              <div className="kv" style={{ marginTop: 6 }}>
                <span>mid (bid/ask)</span><span className="mono">{usd(b.mid)} <span className="dim">({usd(b.bid)} / {usd(b.ask)}, spread {pct(b.spread_pct, 1, false)})</span></span>
                <span>expected P&L over hold — thesis / neutral</span><span className={`mono ${b.ev_thesis > 0 ? "pos" : "neg"}`}>{pct(b.ev_thesis_pct, 0)} / <span className={b.ev_neutral > 0 ? "pos" : "neg"}>{pct(b.ev_neutral_pct, 0)}</span></span>
                <span>P(profit) at end of hold — thesis / neutral</span><span className="mono">{pct(b.pop_thesis, 0, false)} / {pct(b.pop_neutral, 0, false)}</span>
                <span>payoff if thesis price is hit</span><span className={`mono ${b.payoff_at_thesis > 0 ? "pos" : "neg"}`}>{usd(b.payoff_at_thesis)} ({pct(b.payoff_at_thesis_pct, 0)})</span>
                <span>breakeven at expiry</span><span className="mono">{usd(b.breakeven)} ({pct(b.breakeven_move_pct, 1)}) · P(ITM) {pct(b.prob_itm_expiry, 0, false)}</span>
                <span>Δ / Γ / Θ / V</span><span className="mono">{num(b.delta)} / {num(b.gamma, 4)} / {num(b.theta, 3)}/day / {num(b.vega, 3)}</span>
                <span>theta burn over hold</span><span className={`mono ${b.theta_burn_pct > 0.35 ? "neg" : ""}`}>{pct(b.theta_burn_pct, 0, false)} of premium</span>
                <span>IV / IV at exit / vs RV / skew premium</span><span className="mono">{pct(b.iv, 0, false)} / {pct(b.iv_exit, 0, false)} / {num(b.iv_vs_rv)} / {b.skew_premium != null ? pct(b.skew_premium, 1) : "—"}</span>
                <span>leverage · OI · volume</span><span className="mono">{num(b.leverage, 1)}x · {b.open_interest} · {b.volume}</span>
                <span>max loss</span><span className="mono neg">{usd(b.max_loss * 100, 0)} per contract</span>
              </div>
              {b.warnings?.length ? <div className="warn small" style={{ marginTop: 6 }}>⚠ {b.warnings.join(" · ")}</div> : null}
              <div className="small muted" style={{ marginTop: 8 }}>Score components: {Object.entries<number>(comps).map(([k, v]) => `${k} ${(v * 100).toFixed(0)}`).join(" · ")}</div>
              {res.alternative_spread ? (
                <div className="drill" style={{ marginTop: 8 }}>
                  <b>Alternative — {res.alternative_spread.type}:</b> buy {usd(res.alternative_spread.long_strike, 0)} / sell {usd(res.alternative_spread.short_strike, 0)} for {usd(res.alternative_spread.debit)} debit · max profit {usd(res.alternative_spread.max_profit)} ({pct(res.alternative_spread.max_profit_pct, 0, false)}) · breakeven {usd(res.alternative_spread.breakeven)}
                  <div className="dim small">{res.alternative_spread.why}</div>
                </div>
              ) : null}
            </div>
            <div>
              <div className="muted small">P&L of the best contract at the end of the hold vs underlying price (thesis distribution)</div>
              {b.pnl_curve ? <Line series={[{ name: "pnl", color: b.ev_thesis > 0 ? "var(--green)" : "var(--red)", data: b.pnl_curve.s.map((s: number, i: number) => [s, b.pnl_curve.pnl[i] * 100] as [number, number]) }]} yfmt={(v) => "$" + v.toFixed(0)} zero h={200} /> : null}
              <div className="dim small">x-axis spans ±5σ of the underlying at the end of the hold; spot {usd(res.spot)}</div>
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <div className="muted small" style={{ marginBottom: 4 }}>All liquid strikes, ranked</div>
            <Table data={res.ranked} cols={["contract_symbol", "strike", "mid", "spread_pct", "open_interest", "volume", "iv", "delta", "theta_burn_pct", "breakeven_move_pct", "pop_thesis", "ev_thesis_pct", "ev_neutral_pct", "score"]}
              fmt={{ mid: (v) => usd(v), spread_pct: (v) => pct(v, 1, false), iv: (v) => pct(v, 0, false), delta: (v) => num(v), theta_burn_pct: (v) => pct(v, 0, false), breakeven_move_pct: (v) => pct(v, 1), pop_thesis: (v) => pct(v, 0, false),
                ev_thesis_pct: (v) => <span className={v > 0 ? "pos" : "neg"}>{pct(v, 0)}</span>, ev_neutral_pct: (v) => <span className={v > 0 ? "pos" : "neg"}>{pct(v, 0)}</span>, score: (v) => <b>{num(v, 0)}</b> }} />
          </div>
          <div className="dim small" style={{ marginTop: 6 }}>{res.method}. {res.disclaimer}</div>
        </>
      ) : busy ? <div className="skeleton" style={{ height: 80 }} /> : null}
    </Card>
  );
}

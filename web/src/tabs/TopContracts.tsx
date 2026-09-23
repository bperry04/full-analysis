import React, { useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../components";
import { num, pct, usd } from "../fmt";

export function TopContracts({ symbol, horizon = "short", dteMin = 20, dteMax = 30, n = 3 }: { symbol: string; horizon?: string; dteMin?: number; dteMax?: number; n?: number }) {
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!symbol) return;
    setBusy(true); setRes(null);
    api(`/api/ticker/${symbol}/options/evaluate/top?horizon=${horizon}&dte_min=${dteMin}&dte_max=${dteMax}&n=${n}`).then(setRes).catch((e) => setRes({ available: false, reason: String(e) })).finally(() => setBusy(false));
  }, [symbol, horizon, dteMin, dteMax, n]);
  return (
    <Card title={`Best ${n} contracts · ${dteMin}–${dteMax} days to expiration`} sub={res?.available ? <span className="dim">{res.n_scored} contracts scored across {new Set((res.expiries || []).map((e: any) => e.expiry)).size} expirations · thesis: {res.expiries?.[0]?.thesis}{res.setup?.setup ? ` · setup: ${res.setup.setup}` : ""}</span> : null}>
      {busy ? <div className="skeleton" style={{ height: 90 }} /> : null}
      {res && !res.available ? <div className="err">{res.reason}</div> : null}
      {res?.available ? (
        <div className="grid g3">
          {res.top.map((b: any, i: number) => (
            <div key={b.contract_symbol} className="card" style={{ background: "var(--bg3)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <span style={{ fontSize: 15, fontWeight: 600 }}>#{i + 1} {b.right === "C" ? "Call" : "Put"} {usd(b.strike, 0)} · {b.expiry}</span>
                <span className="pill ok">score {num(b.score, 0)}</span>
              </div>
              <div className="dim small mono">{b.contract_symbol} · {b.dte} DTE</div>
              <div className="kv small" style={{ marginTop: 6 }}>
                <span>mid (spread)</span><span className="mono">{usd(b.mid)} ({pct(b.spread_pct, 1, false)})</span>
                <span>expected P&L thesis / neutral</span><span className="mono"><span className={b.ev_thesis_pct > 0 ? "pos" : "neg"}>{pct(b.ev_thesis_pct, 0)}</span> / <span className={b.ev_neutral_pct > 0 ? "pos" : "neg"}>{pct(b.ev_neutral_pct, 0)}</span></span>
                <span>P(profit) thesis / neutral</span><span className="mono">{pct(b.pop_thesis, 0, false)} / {pct(b.pop_neutral, 0, false)}</span>
                <span>Δ · θ burn · breakeven</span><span className="mono">{num(b.delta)} · {pct(b.theta_burn_pct, 0, false)} · {pct(b.breakeven_move_pct, 1)}</span>
                <span>IV · IV/RV · OI</span><span className="mono">{pct(b.iv, 0, false)} · {num(b.iv_vs_rv)} · {b.open_interest}</span>
                <span>max loss / contract</span><span className="mono neg">{usd(b.max_loss * 100, 0)}</span>
              </div>
              {b.warnings?.length ? <div className="warn small" style={{ marginTop: 4 }}>⚠ {b.warnings.join(" · ")}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
      {res?.available ? <div className="dim small" style={{ marginTop: 6 }}>{res.note}. Delayed quotes — verify live before trading.</div> : null}
    </Card>
  );
}

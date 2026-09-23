import React, { useEffect, useState } from "react";
import { useAnalysis, api } from "./api";
import { ProvCtx } from "./components";
import { Overview } from "./tabs/Overview";
import { Financials } from "./tabs/Financials";
import { Valuation } from "./tabs/Valuation";
import { Options } from "./tabs/Options";
import { Technicals } from "./tabs/Technicals";
import { Flow } from "./tabs/Flow";
import { News } from "./tabs/News";
import { Events } from "./tabs/Events";
import { Ownership } from "./tabs/Ownership";
import { Macro } from "./tabs/Macro";
import { Sources } from "./tabs/Sources";
import { Horizon } from "./tabs/Horizon";

const TABS = ["Overview", "Short", "Medium", "Long", "Financials", "Valuation", "Options", "Technicals", "Flow", "News", "Events", "Ownership", "Macro", "Sources"] as const;

export default function App() {
  const { state, start, load } = useAnalysis();
  const [symbol, setSymbol] = useState(() => { try { return localStorage.getItem("fa.symbol") || "AAPL"; } catch { return "AAPL"; } });
  const [depth, setDepth] = useState("standard");
  const [tab, setTab] = useState<(typeof TABS)[number]>("Overview");
  const [runs, setRuns] = useState<any[]>([]);
  useEffect(() => { api("/api/runs?limit=15").then(setRuns).catch(() => {}); }, [state.status]);
  const go = () => { try { localStorage.setItem("fa.symbol", symbol.toUpperCase()); } catch {} start(symbol, depth); setTab("Overview"); };
  const secs = Object.entries(state.sections);
  const done = secs.filter(([, s]) => s.status === "ok").length;

  return (
    <ProvCtx.Provider value={{ prov: state.provenance, runId: state.runId }}>
      <div className="app">
        <div className="header">
          <span className="brand">FULL ANALYSIS</span>
          <div className="search">
            <input value={symbol} onChange={(e) => setSymbol(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()} placeholder="TICKER" />
            <select value={depth} onChange={(e) => setDepth(e.target.value)}><option value="quick">quick</option><option value="standard">standard</option><option value="deep">deep</option></select>
            <button className="primary" onClick={go} disabled={state.status === "running"}>{state.status === "running" ? "Running…" : "Analyze"}</button>
            <select value="" onChange={(e) => e.target.value && load(e.target.value)} title="previous runs">
              <option value="">history…</option>
              {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.symbol} {String(r.started_at).slice(0, 16)} L{r.score_long?.toFixed?.(0) ?? "—"}/M{r.score_medium?.toFixed?.(0) ?? "—"}/S{r.score_short?.toFixed?.(0) ?? "—"}</option>)}
            </select>
          </div>
          <div className="status">
            {state.symbol ? <span className="mono">{state.symbol}</span> : null}
            {state.status !== "idle" ? <span className={`pill ${state.status === "running" ? "run" : state.status === "error" ? "fail" : "ok"}`}>{state.status}{state.totalMs ? ` · ${(state.totalMs / 1000).toFixed(0)}s` : ""}</span> : null}
            {secs.length ? <span>{done}/{secs.length} sections</span> : null}
            {secs.map(([n, s]) => <span key={n} className={`pill ${s.status === "ok" ? "ok" : s.status === "failed" ? "fail" : s.status === "running" ? "run" : ""}`} title={s.reason || ""}>{n}</span>)}
            {state.error ? <span className="neg">{state.error}</span> : null}
          </div>
        </div>
        <div className="tabs">{TABS.map((t) => <div key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>{t}</div>)}</div>
        <div className="main">
          {state.status === "idle" ? <div className="card"><h3>Start</h3><div className="muted">Type a ticker and press Analyze. <b>quick</b> ≈ 30s (cached, no Monte Carlo/peers), <b>standard</b> ≈ 1–3 min, <b>deep</b> adds IBKR tick tape + larger simulations.</div></div> : null}
          {state.scores?.disclaimer ? <div className="banner">{state.scores.disclaimer}</div> : null}
          {tab === "Overview" && <Overview s={state} />}
          {tab === "Short" && <Horizon s={state} h="short" />}
          {tab === "Medium" && <Horizon s={state} h="medium" />}
          {tab === "Long" && <Horizon s={state} h="long" />}
          {tab === "Financials" && <Financials s={state} />}
          {tab === "Valuation" && <Valuation s={state} />}
          {tab === "Options" && <Options s={state} />}
          {tab === "Technicals" && <Technicals s={state} />}
          {tab === "Flow" && <Flow s={state} />}
          {tab === "News" && <News s={state} />}
          {tab === "Events" && <Events s={state} />}
          {tab === "Ownership" && <Ownership s={state} />}
          {tab === "Macro" && <Macro s={state} />}
          {tab === "Sources" && <Sources s={state} />}
        </div>
      </div>
    </ProvCtx.Provider>
  );
}

import React, { useEffect, useState } from "react";
import { api, type RunState } from "../api";
import { Card, Table } from "../components";

export function Sources({ s }: { s: RunState }) {
  const [health, setHealth] = useState<any>(null);
  const [watch, setWatch] = useState<any[]>([]);
  const [sym, setSym] = useState("");
  const refresh = () => { api("/api/health").then(setHealth).catch(() => {}); api("/api/watchlist").then(setWatch).catch(() => {}); };
  useEffect(refresh, []);
  const prov = Object.values(s.provenance || {});
  const byProv: Record<string, any> = {};
  for (const p of prov) { const b = (byProv[p.provider] ||= { provider: p.provider, fetches: 0, cache: 0, degraded: 0, ms: 0, latency: new Set<string>() }); b.fetches++; b.cache += p.from_cache ? 1 : 0; b.degraded += p.quality_flags.includes("DEGRADED") ? 1 : 0; b.ms += p.duration_ms; b.latency.add(p.latency); }
  return (
    <div className="grid" style={{ gap: 12 }}>
      <div className="grid g2">
        <Card title="Providers" sub={health ? `v${health.version} · data root ${health.settings?.data_root}` : ""}>
          <Table data={health?.providers || []} cols={["provider", "available", "tier", "latency", "requires"]} fmt={{ requires: (v) => (v || []).join(", ") }} />
          <div className="small muted" style={{ marginTop: 6 }}>IBKR: start IB Gateway (port {"4001/4002"}) and it becomes available on the next run — live quotes, broker greeks, IV history, tick tape. Schwab: `python -m fa schwab-login`.</div>
        </Card>
        <Card title="Watchlist" sub="symbols recorded by the 16:20 ET close-snapshot job">
          <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
            <input className="num" style={{ width: 100, textTransform: "uppercase" }} value={sym} onChange={(e) => setSym(e.target.value)} placeholder="TICKER" />
            <button onClick={() => api("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol: sym }) }).then(setWatch)}>add</button>
            {s.symbol ? <button onClick={() => api("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol: s.symbol }) }).then(setWatch)}>add {s.symbol}</button> : null}
          </div>
          <div>{watch.map((w) => <span key={w.symbol} className="pill" style={{ marginRight: 6 }}>{w.symbol} <a onClick={() => api(`/api/watchlist/${w.symbol}`, { method: "DELETE" }).then(setWatch)} style={{ cursor: "pointer" }}>×</a></span>)}</div>
          <div className="small muted" style={{ marginTop: 10 }}>Jobs: {health ? "" : "…"}</div>
          <Jobs />
        </Card>
      </div>
      <Card title="This run's fetches" sub={`${prov.length} provenance records · ${s.data.meta ? `${(s.data.meta.cache_hit_rate * 100).toFixed(0)}% cache hits · ${(s.data.meta.total_ms / 1000).toFixed(0)}s` : ""}`}>
        <Table data={Object.values(byProv).map((b: any) => ({ ...b, latency: Array.from(b.latency).join(",") }))} cols={["provider", "fetches", "cache", "degraded", "ms", "latency"]} />
        <div style={{ marginTop: 8 }}>
          <Table data={prov.map((p) => ({ id: p.prov_id, need: p.need, provider: p.provider, latency: p.latency, delayed: p.is_delayed, depth: p.fallback_depth, cache: p.from_cache, rows: p.row_count, ms: p.duration_ms, flags: p.quality_flags.join(","), as_of: p.as_of, endpoint: p.endpoint, raw: p.raw_path ? `/api/raw/${s.runId}/${p.prov_id}` : "" }))}
            cols={["id", "need", "provider", "latency", "delayed", "depth", "cache", "rows", "ms", "flags", "as_of", "endpoint", "raw"]} fmt={{ raw: (v) => (v ? <a href={v} target="_blank" rel="noreferrer">payload</a> : "—"), endpoint: (v) => <span className="small" title={v}>{String(v).slice(0, 70)}</span> }} max={400} />
        </div>
      </Card>
      <Card title="Store">
        {health ? <div className="kv small"><span>DuckDB</span><span className="mono">{health.store?.duckdb_path} {health.store?.read_only ? "(read-only)" : ""}</span><span>tables</span><span className="mono">{Object.entries(health.store?.tables || {}).map(([k, v]) => `${k}:${v}`).join("  ")}</span><span>lake</span><span className="mono">{Object.entries<any>(health.store?.lake || {}).map(([k, v]) => `${k}:${v.files} files/${(v.bytes / 1e6).toFixed(1)}MB`).join("  ")}</span><span>cache</span><span className="mono">{health.cache?.entries} entries · {(health.cache?.volume_bytes / 1e6).toFixed(0)}MB</span></div> : null}
        <Table data={health?.circuits || []} cols={["provider", "need", "ok", "fail", "circuit", "p50_ms", "p95_ms", "last_error"]} />
      </Card>
    </div>
  );
}

function Jobs() {
  const [jobs, setJobs] = useState<any[]>([]);
  useEffect(() => { api("/api/admin/jobs").then(setJobs).catch(() => {}); }, []);
  return <ul className="small" style={{ margin: 0, paddingLeft: 16 }}>{jobs.map((j) => <li key={j.id}>{j.name} <span className="dim">next {j.next_run ? String(j.next_run).slice(0, 16) : "—"}</span> <a style={{ cursor: "pointer" }} onClick={() => api(`/api/admin/jobs/${j.id}/run`, { method: "POST" })}>run now</a></li>)}</ul>;
}

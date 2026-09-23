/* Shared UI pieces: provenance-aware values, score gauges, driver lists with drill-down, tables, small SVG charts. */
import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { createChart, ColorType } from "lightweight-charts";
import type { Prov } from "./api";
import { cls, isNum, num, pct, rows, scoreColor, unwrap } from "./fmt";

export const ProvCtx = createContext<{ prov: Record<string, Prov>; runId: string | null }>({ prov: {}, runId: null });

export function ProvBadge({ p, q }: { p?: string | null; q?: string[] }) {
  const { prov, runId } = useContext(ProvCtx);
  const [open, setOpen] = useState(false);
  const rec = p ? prov[p] : undefined;
  const flags = q || [];
  const lat = rec?.latency || (flags.includes("DELAYED") ? "delayed_15" : "");
  const klass = lat.startsWith("delayed") ? "delayed" : lat === "realtime" ? "realtime" : lat === "filing" ? "filing" : lat === "computed" ? "computed" : "";
  const deg = flags.includes("DEGRADED") || (rec?.quality_flags || []).includes("DEGRADED");
  const label = rec ? rec.provider : flags.length ? flags[0].split(":")[0] : null;
  if (!label && !rec) return null;
  return (
    <span className="val" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <span className={`badge ${deg ? "degraded" : klass}`}>{label}{lat.startsWith("delayed") ? " ·15m" : ""}</span>
      {open && rec && (
        <div className="popover">
          <div className="row"><span>need</span><span>{rec.need}</span></div>
          <div className="row"><span>provider</span><span>{rec.provider} (tier {rec.tier})</span></div>
          <div className="row"><span>latency</span><span>{rec.latency}{rec.is_delayed ? ` (${rec.delay_seconds}s)` : ""}</span></div>
          <div className="row"><span>as of</span><span>{rec.as_of || "—"}</span></div>
          <div className="row"><span>fetched</span><span>{rec.fetched_at}{rec.from_cache ? ` (cache, ${Math.round(rec.cache_age_s)}s old)` : ""}</span></div>
          <div className="row"><span>rows / ms</span><span>{rec.row_count ?? "—"} / {rec.duration_ms}</span></div>
          <div className="row"><span>fallback depth</span><span>{rec.fallback_depth}</span></div>
          {rec.quality_flags?.length ? <div className="row"><span>flags</span><span className="warn">{rec.quality_flags.join(", ")}</span></div> : null}
          {flags.length ? <div className="row"><span>value flags</span><span className="warn">{flags.join(", ")}</span></div> : null}
          <div className="ep">{rec.endpoint}</div>
          {rec.attempts?.length ? <div className="dim" style={{ marginTop: 4 }}>{rec.attempts.map((a) => `${a.provider}:${a.result}${a.reason ? "(" + a.reason.slice(0, 40) + ")" : ""}`).join(" → ")}</div> : null}
          {rec.raw_path && runId ? <div style={{ marginTop: 4 }}><a href={`/api/raw/${runId}/${rec.prov_id}`} target="_blank" rel="noreferrer">open archived payload</a></div> : null}
          {rec.license_note ? <div className="dim">{rec.license_note}</div> : null}
        </div>
      )}
    </span>
  );
}

export function V({ x, f = (v: any) => num(v), color = false }: { x: any; f?: (v: any) => string; color?: boolean }) {
  const v = unwrap(x);
  const isVal = x && typeof x === "object" && "v" in x;
  return (
    <span className="val">
      <span className={`mono ${color ? cls(v) : ""}`}>{f(v)}</span>
      {isVal ? <ProvBadge p={x.p} q={x.q} /> : null}
    </span>
  );
}

export function Tile({ k, x, f, color, p }: { k: string; x: any; f?: (v: any) => string; color?: boolean; p?: string | null }) {
  return (
    <div className="tile">
      <span className="k">{k}</span>
      <span className="v"><V x={x} f={f} color={color} />{p && !(x && typeof x === "object" && "v" in x) ? <ProvBadge p={p} /> : null}</span>
    </div>
  );
}

export function Card({ title, sub, children, style }: { title?: string; sub?: React.ReactNode; children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="card" style={style}>
      {title ? <h3>{title}{sub ? <span className="sub">{sub}</span> : null}</h3> : null}
      {children}
    </div>
  );
}

export function Section({ name, status, children }: { name: string; status?: { status: string; reason?: string; ms?: number }; children: React.ReactNode }) {
  if (!status || status.status === "pending" || status.status === "running") return <div className="skeleton" />;
  if (status.status === "failed") return <div className="err">{name} failed: {status.reason}</div>;
  return <>{children}</>;
}

export function Gauge({ h, s }: { h: string; s: any }) {
  const score = s?.score;
  return (
    <div className="card gauge">
      <div className="muted" style={{ textTransform: "uppercase", letterSpacing: 1, fontSize: 11 }}>{h} · {s?.window}</div>
      <div className="score" style={{ color: scoreColor(score) }}>{isNum(score) ? score.toFixed(0) : "—"}</div>
      <div className="label" style={{ color: scoreColor(score) }}>{s?.label || "—"}</div>
      <div className="bar"><div style={{ width: `${(score ?? 0)}%`, background: scoreColor(score) }} /></div>
      <div className="meta">coverage {pct(s?.coverage, 0, false)} · confidence {pct(s?.confidence, 0, false)} · {s?.n_present}/{s?.n_factors} factors</div>
    </div>
  );
}

export function Drivers({ drivers, factors, n = 10 }: { drivers: any[]; factors: Record<string, any>; n?: number }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      {(drivers || []).slice(0, n).map((d) => (
        <div key={d.key}>
          <div className="driver" onClick={() => setOpen(open === d.key ? null : d.key)}>
            <div className={`c ${cls(d.contribution)}`}>{d.contribution > 0 ? "+" : ""}{d.contribution.toFixed(1)}</div>
            <div><div className="l">{d.label} <span className="dim small">· {d.category}</span></div><div className="n">{d.narrative}</div></div>
          </div>
          {open === d.key && factors[d.key] ? <FactorDrill f={factors[d.key]} /> : null}
        </div>
      ))}
    </div>
  );
}

export function FactorDrill({ f }: { f: any }) {
  return (
    <div className="drill">
      <div className="kv">
        <span>raw</span><span className="mono">{f.raw_display} <span className="dim">({f.unit})</span></span>
        <span>normalized</span><span className="mono">{isNum(f.normalized) ? f.normalized.toFixed(2) : "—"}</span>
        <span>confidence</span><span className="mono">{pct(f.confidence, 0, false)}</span>
        <span>weights</span><span className="mono">{Object.entries(f.weight || {}).map(([h, w]: any) => `${h}:${w.toFixed(2)}`).join("  ")}</span>
        {f.comparison_basis ? <><span>basis</span><span>{f.comparison_basis}</span></> : null}
        <span>status</span><span>{f.status}</span>
      </div>
      {f.inputs?.length ? (
        <div style={{ marginTop: 6 }}>
          <div className="muted small">inputs</div>
          <div className="in">
            {f.inputs.map((i: any, k: number) => (
              <React.Fragment key={k}><span>{i.name}{i.formula ? <span className="dim"> = {i.formula}</span> : null}</span><span>{typeof i.value === "number" ? num(i.value, 4) : String(i.value ?? "—").slice(0, 60)}</span><span><ProvBadge p={i.prov_id} /></span></React.Fragment>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function Table({ data, cols, fmt = {}, max = 200 }: { data: any; cols?: string[]; fmt?: Record<string, (v: any, r: any) => React.ReactNode>; max?: number }) {
  const rs = rows(data).slice(0, max);
  if (!rs.length) return <div className="dim small">no rows</div>;
  const cs = cols || Object.keys(rs[0]);
  return (
    <div className="scroll">
      <table className="tbl">
        <thead><tr>{cs.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>
          {rs.map((r, i) => (
            <tr key={i}>{cs.map((c) => <td key={c}>{fmt[c] ? fmt[c](r[c], r) : cell(r[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function cell(v: any): React.ReactNode {
  if (v === null || v === undefined) return <span className="dim">—</span>;
  if (typeof v === "number") return Math.abs(v) >= 1e6 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : Number.isInteger(v) ? v : v.toFixed(Math.abs(v) < 1 ? 4 : 2);
  if (typeof v === "boolean") return v ? "✓" : "✗";
  const s = String(v);
  return s.length > 60 ? s.slice(0, 60) + "…" : s;
}

/* ---------------------------------------------------------------- SVG charts */
export function Sparkline({ values, w = 120, h = 28, color = "var(--blue)" }: { values: number[]; w?: number; h?: number; color?: string }) {
  const v = values.filter(isNum);
  if (v.length < 2) return null;
  const min = Math.min(...v), max = Math.max(...v);
  const pts = v.map((y, i) => `${(i / (v.length - 1)) * w},${h - ((y - min) / (max - min || 1)) * (h - 2) - 1}`).join(" ");
  return <svg width={w} height={h}><polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} /></svg>;
}

export function Bars({ items, w = 520, h = 200, color = (v: number) => (v >= 0 ? "var(--green)" : "var(--red)"), labelFmt = (v: number) => v.toFixed(2) }:
  { items: { label: string; value: number }[]; w?: number; h?: number; color?: (v: number) => string; labelFmt?: (v: number) => string }) {
  const it = items.filter((i) => isNum(i.value));
  if (!it.length) return <div className="dim small">no data</div>;
  const max = Math.max(...it.map((i) => Math.abs(i.value)), 1e-9);
  const bh = Math.max(12, Math.min(22, (h - 10) / it.length));
  const lw = 150;
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${it.length * bh + 10}`} preserveAspectRatio="none" style={{ height: it.length * bh + 10 }}>
      {it.map((i, k) => {
        const zero = lw + (w - lw - 60) / 2;
        const len = (Math.abs(i.value) / max) * ((w - lw - 60) / 2);
        return (
          <g key={k} transform={`translate(0,${k * bh + 5})`}>
            <text x={lw - 6} y={bh * 0.7} textAnchor="end">{i.label.slice(0, 26)}</text>
            <rect x={i.value >= 0 ? zero : zero - len} y={2} width={len} height={bh - 4} fill={color(i.value)} />
            <text x={i.value >= 0 ? zero + len + 4 : zero - len - 4} y={bh * 0.7} textAnchor={i.value >= 0 ? "start" : "end"}>{labelFmt(i.value)}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function Line({ series, w = 600, h = 220, yfmt = (v: number) => v.toFixed(2), zero = false }:
  { series: { name: string; data: [number, number][]; color: string }[]; w?: number; h?: number; yfmt?: (v: number) => string; zero?: boolean }) {
  const all = series.flatMap((s) => s.data);
  if (all.length < 2) return <div className="dim small">no data</div>;
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (zero) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
  const pad = { l: 48, r: 8, t: 8, b: 20 };
  const X = (x: number) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (w - pad.l - pad.r);
  const Y = (y: number) => pad.t + (1 - (y - y0) / (y1 - y0 || 1)) * (h - pad.t - pad.b);
  const ticks = [y0, (y0 + y1) / 2, y1];
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ height: h }}>
      {ticks.map((t, i) => <g key={i}><line x1={pad.l} x2={w - pad.r} y1={Y(t)} y2={Y(t)} stroke="var(--line)" /><text x={pad.l - 4} y={Y(t) + 3} textAnchor="end">{yfmt(t)}</text></g>)}
      {zero ? <line x1={pad.l} x2={w - pad.r} y1={Y(0)} y2={Y(0)} stroke="var(--dim)" strokeDasharray="3 3" /> : null}
      {series.map((s) => <polyline key={s.name} fill="none" stroke={s.color} strokeWidth={1.5} points={s.data.map((p) => `${X(p[0])},${Y(p[1])}`).join(" ")} />)}
      <text x={pad.l} y={h - 6}>{new Date(x0).toISOString().slice(0, 10)}</text>
      <text x={w - pad.r} y={h - 6} textAnchor="end">{new Date(x1).toISOString().slice(0, 10)}</text>
    </svg>
  );
}

export function Heat({ rowsL, colsL, values, fmt = (v: number) => v.toFixed(0), center }: { rowsL: string[]; colsL: string[]; values: (number | null)[][]; fmt?: (v: number) => string; center?: number }) {
  const flat = values.flat().filter(isNum) as number[];
  const lo = Math.min(...flat), hi = Math.max(...flat);
  const colorFor = (v: number) => {
    const t = center !== undefined ? (v >= center ? Math.min(1, (v - center) / (hi - center || 1)) : -Math.min(1, (center - v) / (center - lo || 1))) : ((v - lo) / (hi - lo || 1)) * 2 - 1;
    return t >= 0 ? `rgba(63,185,80,${0.15 + 0.6 * t})` : `rgba(248,81,73,${0.15 + 0.6 * -t})`;
  };
  return (
    <table className="tbl">
      <thead><tr><th></th>{colsL.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>{rowsL.map((r, i) => <tr key={r}><td>{r}</td>{values[i].map((v, j) => <td key={j} style={{ background: isNum(v) ? colorFor(v) : undefined }}>{isNum(v) ? fmt(v) : "—"}</td>)}</tr>)}</tbody>
    </table>
  );
}

/* ---------------------------------------------------------------- lightweight-charts candles */
export function Candles({ bars, overlays = [], height = 360 }: { bars: any[]; overlays?: { name: string; color: string; data: { time: any; value: number }[] }[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !bars?.length) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: "#121821" }, textColor: "#8b98a8" }, grid: { vertLines: { color: "#1a2230" }, horzLines: { color: "#1a2230" } },
      height, timeScale: { timeVisible: true, secondsVisible: false }, rightPriceScale: { borderColor: "#243040" }, crosshair: { mode: 0 },
    });
    const toT = (ts: string) => Math.floor(new Date(ts).getTime() / 1000) as any;
    const cs = chart.addCandlestickSeries({ upColor: "#3fb950", downColor: "#f85149", borderVisible: false, wickUpColor: "#3fb950", wickDownColor: "#f85149" });
    const data = bars.map((b) => ({ time: toT(b.ts), open: b.open, high: b.high, low: b.low, close: b.close })).filter((b) => isNum(b.close));
    cs.setData(data);
    const vs = chart.addHistogramSeries({ priceScaleId: "vol", color: "#2f3d4f", priceFormat: { type: "volume" } });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vs.setData(bars.map((b) => ({ time: toT(b.ts), value: b.volume, color: b.close >= b.open ? "#3fb95055" : "#f8514955" })));
    for (const o of overlays) {
      const ls = chart.addLineSeries({ color: o.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      ls.setData(o.data.filter((d) => isNum(d.value)).map((d) => ({ time: toT(d.time), value: d.value })));
    }
    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => chart.applyOptions({ width: ref.current?.clientWidth || 600 }));
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.remove(); };
  }, [bars, overlays, height]);
  return <div ref={ref} style={{ width: "100%", height }} />;
}

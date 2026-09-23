/* API client + SSE hook. Every number in the analysis result is either a {v,p,q} Val or lives in a frame/section
   whose prov_id links to the top-level `provenance` dictionary. */
import { useEffect, useRef, useState } from "react";

export type Val = { v: any; p: string | null; q: string[] };
export type Prov = {
  prov_id: string; need: string; provider: string; endpoint: string; fetched_at: string; as_of: string | null; latency: string; tier: string;
  is_delayed: boolean; delay_seconds: number | null; fallback_depth: number; from_cache: boolean; cache_age_s: number; row_count: number | null;
  duration_ms: number; raw_path: string | null; quality_flags: string[]; attempts: { provider: string; result: string; reason: string; duration_ms: number }[];
  license_note: string;
};
export type Result = any;

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export type RunState = {
  runId: string | null; symbol: string; status: "idle" | "running" | "complete" | "partial" | "error";
  sections: Record<string, { status: string; ms?: number; reason?: string }>;
  data: Record<string, any>; provenance: Record<string, Prov>; scores: any; events: any[]; error?: string; totalMs?: number;
};

export const emptyState = (symbol = ""): RunState => ({ runId: null, symbol, status: "idle", sections: {}, data: {}, provenance: {}, scores: null, events: [] });

/** Starts an analysis and streams section payloads into state as they arrive. */
export function useAnalysis() {
  const [state, setState] = useState<RunState>(emptyState());
  const es = useRef<EventSource | null>(null);

  const start = async (symbol: string, depth: string) => {
    es.current?.close();
    const sym = symbol.trim().toUpperCase();
    setState({ ...emptyState(sym), status: "running" });
    let runId: string;
    try {
      const r = await api<{ run_id: string }>("/api/analyze", { method: "POST", body: JSON.stringify({ symbol: sym, depth }) });
      runId = r.run_id;
    } catch (e: any) {
      setState((s) => ({ ...s, status: "error", error: String(e) }));
      return;
    }
    setState((s) => ({ ...s, runId }));
    const src = new EventSource(`/api/analyze/${runId}/stream`);
    es.current = src;
    const on = (name: string, fn: (d: any) => void) => src.addEventListener(name, (ev: any) => fn(JSON.parse(ev.data)));
    on("run.start", (d) => setState((s) => ({ ...s, sections: Object.fromEntries((d.sections || []).map((n: string) => [n, { status: "pending" }])) })));
    on("section.start", (d) => setState((s) => ({ ...s, sections: { ...s.sections, [d.section]: { status: "running" } } })));
    on("section.done", (d) =>
      setState((s) => ({
        ...s, sections: { ...s.sections, [d.section]: { status: "ok", ms: d.ms } },
        data: d.section === "scoring" ? s.data : { ...s.data, [d.section]: d.payload }, scores: d.section === "scoring" ? d.payload : s.scores,
      }))
    );
    on("section.error", (d) => setState((s) => ({ ...s, sections: { ...s.sections, [d.section]: { status: "failed", ms: d.ms, reason: d.reason } } })));
    on("run.done", async (d) => {
      src.close();
      try {
        const full = await api<Result>(`/api/analyze/${runId}`);
        const { sections, scores, provenance, run_id, ...rest } = full;
        setState((s) => ({ ...s, status: full.status, sections, scores, provenance: provenance || {}, data: { ...s.data, ...rest }, totalMs: d.total_ms }));
      } catch (e: any) {
        setState((s) => ({ ...s, status: "complete", totalMs: d.total_ms }));
      }
    });
    src.onerror = () => { /* keep-alive pings handle idle; a hard failure ends the stream */ };
  };

  const load = async (runId: string) => {
    es.current?.close();
    const full = await api<Result>(`/api/analyze/${runId}`);
    const { sections, scores, provenance, run_id, symbol, ...rest } = full;
    setState({ runId: run_id, symbol, status: full.status, sections, scores, provenance: provenance || {}, data: rest, events: [] });
  };

  useEffect(() => () => es.current?.close(), []);
  return { state, start, load };
}

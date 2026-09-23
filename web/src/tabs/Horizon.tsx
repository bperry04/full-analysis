import React from "react";
import type { RunState } from "../api";
import { Bars, Card, Drivers, Gauge, Section, Table } from "../components";
import { date, num, pct, rows, usd, x } from "../fmt";
import { OptionEvaluator } from "./OptionEvaluator";
import { SwingPanel } from "./Technicals";

const KIND_COLOR: Record<string, string> = { "m&a": "var(--purple)", capacity: "var(--cyan)", strategy: "var(--blue)", capital_return: "var(--green)", demand: "var(--cyan)", product: "var(--blue)", contract: "var(--green)",
  guidance: "var(--amber)", financing: "var(--red)", legal: "var(--red)", management: "var(--amber)", macro: "var(--amber)", earnings: "var(--cyan)", analyst: "var(--muted)", stock_move: "var(--muted)", other: "var(--dim)" };

export function Narrative({ items, n = 8 }: { items: any[]; n?: number }) {
  if (!items?.length) return <div className="dim small">nothing material found</div>;
  return (
    <ul className="news" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {items.slice(0, n).map((it, i) => (
        <li key={i}>
          <span className="pill" style={{ borderColor: KIND_COLOR[it.kind] || "var(--line)", color: KIND_COLOR[it.kind] || "var(--muted)", marginRight: 6 }}>{it.label}</span>
          {it.url ? <a href={it.url} target="_blank" rel="noreferrer">{it.title}</a> : <span>{it.title}</span>}
          {it.sentiment != null ? <span className={`mono small ${it.sentiment > 0.2 ? "pos" : it.sentiment < -0.2 ? "neg" : "dim"}`}> {it.sentiment > 0 ? "+" : ""}{Number(it.sentiment).toFixed(2)}</span> : null}
          <div className="dim small">{it.detail ? it.detail + " · " : ""}{it.source} · {date(it.date)}</div>
        </li>
      ))}
    </ul>
  );
}

export function Horizon({ s, h }: { s: RunState; h: "short" | "medium" | "long" }) {
  const sc = s.scores?.horizons?.[h];
  const factors = s.scores?.factors || {};
  const nar = s.data.narrative || {};
  const tech = s.data.technicals || {};
  const ev = s.data.events || {};
  const an = s.data.analysts || {};
  const v = s.data.valuation || {};
  const f = s.data.fundamentals || {};
  const m = f.metrics || {};
  const setup = tech.patterns?.setup || {};
  const cats = Object.entries(sc?.category_scores || {}).map(([k, val]: any) => ({ label: `${k} (w${val.weight})`, value: (val.score ?? 50) - 50 }));
  const title = { short: "Short — 2–20 trading days (swing)", medium: "Medium — 1–6 months", long: "Long — 6–24 months" }[h];
  if (!s.scores && s.status === "idle") return <div className="card"><div className="muted">Run an analysis first.</div></div>;
  return (
    <div className="grid" style={{ gap: 12 }}>
      <div className="grid g3">
        <Gauge h={title} s={sc} />
        <Card title="Quantitative drivers" sub={`${sc?.n_present ?? 0}/${sc?.n_factors ?? 0} factors scored — click one to drill down`}>
          <Drivers drivers={sc?.drivers || []} factors={factors} n={14} />
        </Card>
        <Card title="What the company is doing" sub="context, not scored">
          <Section name="narrative" status={s.sections.narrative}><Narrative items={nar[h]} n={10} /></Section>
        </Card>
      </div>
      <div className="grid g2">
        <Card title="Category scores (±50)"><Bars items={cats} h={Math.max(120, cats.length * 20)} labelFmt={(val) => (val + 50).toFixed(0)} /></Card>
        <Card title="Missing / suppressed factors" sub="why coverage is not 100%">
          <ul className="small muted" style={{ paddingLeft: 16, margin: 0, maxHeight: 220, overflow: "auto" }}>{(sc?.missing || []).map((mm: any, i: number) => <li key={i}><b>{mm[0]}</b> — {mm[1]}</li>)}</ul>
        </Card>
      </div>

      {h === "short" ? (
        <>
          <Section name="technicals" status={s.sections.technicals}><SwingPanel pat={tech.patterns} /></Section>
          <OptionEvaluator symbol={s.symbol} horizon="short" direction={setup.direction} />
          <div className="grid g3">
            <Card title="Flow snapshot">
              <div className="kv">
                <span>5-day imbalance (proxy)</span><span className={`mono ${(s.data.flow?.bars?.imbalance_5d || 0) > 0 ? "pos" : "neg"}`}>{pct(s.data.flow?.bars?.imbalance_5d)}</span>
                <span>relative volume (time of day)</span><span className="mono">{num(s.data.flow?.bars?.rel_volume_time_of_day)}x</span>
                <span>short-sale share (FINRA)</span><span className="mono">{pct(s.data.flow?.short_volume?.short_ratio, 0, false)} ({num(s.data.flow?.short_volume?.short_ratio_z_60d, 1)}σ)</span>
                <span>P/C volume · net premium</span><span className="mono">{num(s.data.options?.flow?.put_call_vol)} · ${((s.data.options?.flow?.net_premium_call_minus_put || 0) / 1e6).toFixed(0)}M</span>
                <span>gamma regime</span><span className="mono">{s.data.options?.exposure?.regime} · flip {usd(s.data.options?.exposure?.gex_flip, 0)}</span>
              </div>
            </Card>
            <Card title="Event risk inside the window">
              <ul className="small" style={{ paddingLeft: 16, margin: 0 }}>{(ev.events || []).filter((e: any) => e.days_until <= 20).slice(0, 10).map((e: any, i: number) => <li key={i}><span className="mono">{date(e.date)} +{e.days_until}d</span> [{e.importance}] {e.label}</li>)}</ul>
            </Card>
            <Card title="Vol context">
              <div className="kv">
                <span>IV30 / HV20 / IV rank</span><span className="mono">{pct(s.data.options?.surface?.atm_iv?.d30, 0, false)} / {pct(s.data.options?.iv_vs_rv?.hv20, 0, false)} / {s.data.options?.ranks?.iv_rank != null ? pct(s.data.options.ranks.iv_rank, 0, false) : <span className="warn">{s.data.options?.ranks?.flag}</span>}</span>
                <span>expected move next expiry</span><span className="mono">{pct(rows(s.data.options?.expected_move?.by_expiry)[0]?.implied_move_pct, 1, false)}</span>
                <span>ATR (daily)</span><span className="mono">{usd(setup.atr)} ({pct(setup.atr_pct, 1, false)})</span>
                <span>HV20 percentile (2y)</span><span className="mono">{pct(tech.regime?.hv20_percentile_2y, 0, false)} · {tech.regime?.regime}</span>
              </div>
            </Card>
          </div>
        </>
      ) : null}

      {h === "medium" ? (
        <>
          <OptionEvaluator symbol={s.symbol} horizon="medium" direction={setup.direction} />
          <div className="grid g3">
            <Card title="Trend & momentum">
              <div className="kv">
                <span>MA stack (20/50/200)</span><span className="mono">{tech.intervals?.["1d"]?.signals?.ma_stack_bullish ? <span className="pos">bullish</span> : tech.intervals?.["1d"]?.signals?.ma_stack_bearish ? <span className="neg">bearish</span> : "mixed"}</span>
                <span>weekly supertrend / Ichimoku</span><span className="mono">{tech.intervals?.["1wk"]?.signals?.supertrend} / {tech.intervals?.["1wk"]?.signals?.ichimoku}</span>
                <span>1m / 3m / 6m returns</span><span className="mono">{pct(tech.returns?.r_1m)} / {pct(tech.returns?.r_3m)} / {pct(tech.returns?.r_6m)}</span>
                <span>RS vs SPY / sector (3m)</span><span className="mono">{pct(tech.returns?.rs_3m_vs_spy)} / {pct(tech.returns?.rs_3m_vs_sector)}</span>
                <span>52-week position · drawdown</span><span className="mono">{pct(tech.intervals?.["1d"]?.latest?.pos_52w, 0, false)} · {pct(tech.regime?.drawdown?.current_dd)}</span>
              </div>
            </Card>
            <Card title="Catalysts (next 6 months)">
              <ul className="small" style={{ paddingLeft: 16, margin: 0, maxHeight: 240, overflow: "auto" }}>{(ev.events || []).filter((e: any) => e.importance >= 2).slice(0, 14).map((e: any, i: number) => <li key={i}><span className="mono">{date(e.date)} +{e.days_until}d</span> {e.label}{e.confirmed ? "" : " (est.)"}</li>)}</ul>
            </Card>
            <Card title="Analysts & positioning">
              <div className="kv">
                <span>consensus</span><span className="mono">{an.consensus ? `${an.consensus.strong_buy}SB/${an.consensus.buy}B/${an.consensus.hold}H/${an.consensus.sell}S/${an.consensus.strong_sell}SS` : "—"}</span>
                <span>mean target</span><span className="mono">{usd(an.targets?.mean, 0)} ({pct(an.targets?.mean && s.data.quote?.price ? an.targets.mean / s.data.quote.price - 1 : null)})</span>
                <span>upgrades / downgrades (90d)</span><span className="mono">{an.recent_actions?.upgrades ?? "—"} / {an.recent_actions?.downgrades ?? "—"}</span>
                <span>short % float · days to cover</span><span className="mono">{pct(s.data.shorts?.pct_of_float, 1, false)} · {num(s.data.shorts?.days_to_cover, 1)}</span>
                <span>insider net (6m)</span><span className={`mono ${(s.data.ownership?.insiders?.net_value_6m || 0) > 0 ? "pos" : "neg"}`}>{usd(s.data.ownership?.insiders?.net_value_6m, 0)}</span>
                <span>latest quarter revenue YoY · acceleration</span><span className="mono">{pct(m.revenue_growth_yoy_q?.value)} · {pct(m.revenue_acceleration?.value)}</span>
              </div>
            </Card>
          </div>
        </>
      ) : null}

      {h === "long" ? (
        <>
          <div className="grid g3">
            <Card title="Valuation" sub={v.profile?.primary?.replace(/_/g, " ")}>
              <div className="kv">
                <span>blended fair value</span><span className={`mono ${(v.blend?.upside_pct || 0) > 0 ? "pos" : "neg"}`}>{usd(v.blend?.fair_value)} ({pct(v.blend?.upside_pct)})</span>
                <span>range · models · dispersion</span><span className="mono">{usd(v.blend?.low, 0)}–{usd(v.blend?.high, 0)} · {v.blend?.n_models_used} · {num(v.blend?.dispersion)}</span>
                <span>DCF (Gordon)</span><span className="mono">{v.dcf?.available ? `${usd(v.dcf.value_per_share_gordon)} (${pct(v.dcf.upside_pct)})` : <span className="dim small">{v.dcf?.reason}</span>}</span>
                <span>reverse DCF implied growth</span><span className="mono">{pct(v.reverse_dcf?.implied_growth)} vs {pct(v.inputs?.growth_stage1?.value)} delivered</span>
                <span>P/E · EV/EBITDA · FCF yield</span><span className="mono">{x(m.pe?.value)} · {x(m.ev_ebitda?.value)} · {pct(m.fcf_yield?.value, 1, false)}</span>
              </div>
              <Table data={(v.blend?.models || []).filter((mm: any) => mm.computed && mm.applies)} cols={["label", "value_per_share", "upside_pct", "weight"]} fmt={{ value_per_share: (val) => usd(val), upside_pct: (val) => pct(val, 0), weight: (val) => pct(val, 0, false) }} max={12} />
            </Card>
            <Card title="Business quality & growth">
              <div className="kv">
                {["gross_margin", "operating_margin", "fcf_margin", "roic", "roe", "revenue_growth_1y", "revenue_cagr_3y", "eps_diluted_growth_1y", "fcf_cagr_3y", "net_debt_to_ebitda", "interest_coverage", "shareholder_yield", "share_count_change_1y"].map((k) => {
                  const mm = m[k]; if (!mm || mm.value == null) return null;
                  return <React.Fragment key={k}><span>{mm.label}</span><span className={`mono ${mm.unit === "pct" && mm.value < 0 ? "neg" : ""}`}>{mm.unit === "pct" ? pct(mm.value, 1, false) : mm.unit === "x" ? x(mm.value) : num(mm.value)}</span></React.Fragment>;
                })}
                <span>Piotroski · Altman · Beneish</span><span className="mono">{f.quality?.piotroski?.score}/{f.quality?.piotroski?.of} · {num(f.quality?.altman?.z, 1)} ({f.quality?.altman?.zone}) · {num(f.quality?.beneish?.m)}</span>
              </div>
            </Card>
            <Card title="Segments & concentration">
              {Object.values<any>(f.segments?.breakdowns || {}).map((b: any) => (
                <div key={b.report} style={{ marginBottom: 8 }}>
                  <div className="small muted">{b.kind} · {b.period} to {b.as_of}</div>
                  <Bars items={b.members.slice(0, 6).map((mm: any) => ({ label: `${mm.member} (${pct(mm.yoy, 0)})`, value: mm.share }))} h={120} color={() => "var(--blue)"} labelFmt={(val) => pct(val, 0, false)} />
                </div>
              ))}
              {!f.segments?.available ? <div className="dim small">no segment tables found in recent filings</div> : null}
            </Card>
          </div>
          <OptionEvaluator symbol={s.symbol} horizon="long" direction={(v.blend?.upside_pct || 0) > 0.1 ? 1 : (v.blend?.upside_pct || 0) < -0.1 ? -1 : 0} />
        </>
      ) : null}
    </div>
  );
}

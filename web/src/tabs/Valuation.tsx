import React, { useEffect, useState } from "react";
import { api, type RunState } from "../api";
import { Bars, Card, Heat, ProvBadge, Section, Table, Line } from "../components";
import { isNum, num, pct, rows, usd, x } from "../fmt";

const EDITABLE: [string, string, boolean][] = [
  ["wacc", "WACC", true], ["growth_stage1", "Stage-1 growth", true], ["growth_terminal", "Terminal growth", true], ["fcf_margin", "FCF margin (today)", true],
  ["target_margin", "Target FCF margin (year 10)", true], ["rf", "Risk-free", true], ["erp", "Equity risk premium", true], ["beta", "Beta", false], ["fade_years", "Fade years", false], ["exit_multiple", "Exit FCF multiple (optional)", false],
];

export function Valuation({ s }: { s: RunState }) {
  const v0 = s.data.valuation;
  const [ov, setOv] = useState<Record<string, string>>({});
  const [re, setRe] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRe(null); setOv({}); }, [s.runId]);
  if (!v0) return <Section name="valuation" status={s.sections.valuation}><div /></Section>;
  const v = re ? { ...v0, inputs: re.inputs, dcf: re.dcf, sensitivity: re.sensitivity, reverse_dcf: re.reverse_dcf, implied_margin: re.implied_margin } : v0;
  const inp = v.inputs || {};
  const price = inp.price?.value;
  const bl = v0.blend || {};
  const modelRows: any[] = bl.models || [];
  const models = modelRows.filter((m) => m.computed && m.applies && m.weight > 0).map((m) => ({ label: `${m.label.split(" (")[0]} (${pct(m.upside_pct, 0)})`, value: m.value_per_share }));
  const prof = v0.profile || {};
  const sens = v.sensitivity;
  const mc = v0.mc_dcf || {};
  const mcp = v0.mc_price || {};
  const comps = v0.comps;
  const fan = mcp.fan;
  const proj = rows(v.dcf?.projection);
  const A = (k: string) => inp[k] || {};
  const dcfOk = v.dcf?.available;

  const recompute = async () => {
    const body: Record<string, number> = {};
    for (const [k, , isPct] of EDITABLE) {
      const raw = ov[k];
      if (raw === undefined || raw === "") continue;
      const n = Number(raw);
      if (!Number.isFinite(n)) continue;
      body[k] = isPct ? n / 100 : n;
    }
    setBusy(true);
    try { setRe(await api(`/api/ticker/${s.symbol}/valuation/dcf`, { method: "POST", body: JSON.stringify(body) })); } catch (e) { alert(String(e)); } finally { setBusy(false); }
  };
  const cur = (k: string, isPct: boolean) => {
    const val = k === "target_margin" ? v.dcf?.margin_target : k === "exit_multiple" ? v.dcf?.exit_multiple : A(k).value;
    return isNum(val) ? (isPct ? (val * 100).toFixed(2) : String(val)) : "";
  };

  return (
    <Section name="valuation" status={s.sections.valuation}>
      <div className="grid" style={{ gap: 12 }}>
        {!dcfOk ? <div className="err"><b>DCF not computed:</b> {v.dcf?.reason || "unknown"} — edit the assumptions below and press Recompute to force a valuation.</div> : null}
        {dcfOk && v.dcf?.flags?.includes("ESTIMATED") ? <div className="banner"><b>Estimated DCF.</b> {v.dcf.notes?.join(" ")}</div> : null}
        <div><a href={`/api/ticker/${s.symbol}/valuation.xlsx`} className="pill ok" style={{ textDecoration: "none" }}>⬇ Download all models as Excel (live formulas)</a> <span className="dim small">Inputs sheet drives every model; yellow cells are editable.</span></div>
        {re ? <div className="banner">Showing your recomputed DCF (overrides marked <i>user_override</i>). The blend, Monte Carlo and comps still reflect the original run. <a style={{ cursor: "pointer" }} onClick={() => { setRe(null); setOv({}); }}>reset</a></div> : null}
        <div className="grid g3">
          <Card title="Fair value blend" sub={<ProvBadge p={v0.prov_id} />}>
            <div className="small" style={{ marginBottom: 6 }}><b>Profile: {prof.primary?.replace(/_/g, " ")}</b> <span className="dim">· {(prof.tags || []).join(", ")}</span></div>
            {bl.available ? (
              <>
                <div style={{ fontSize: 26 }} className={`mono ${bl.upside_pct > 0 ? "pos" : "neg"}`}>{usd(bl.fair_value)} <span style={{ fontSize: 14 }}>({pct(bl.upside_pct)})</span></div>
                <div className="small muted">{bl.n_models_used} models · range {usd(bl.low, 0)} – {usd(bl.high, 0)} · dispersion {num(bl.dispersion)} · confidence {pct(bl.confidence, 0, false)}{bl.dropped_outliers?.length ? ` · outliers dropped: ${bl.dropped_outliers.join(", ")}` : ""}</div>
                <Bars items={[{ label: "price", value: price }, ...models]} h={Math.max(120, 22 * (models.length + 1))} color={(val) => (val >= price ? "var(--green)" : "var(--red)")} labelFmt={(val) => usd(val, 0)} />
              </>
            ) : <div className="dim">{bl.reason || "no applicable model produced a value"}</div>}
            {(prof.notes || []).length ? <ul className="small muted" style={{ paddingLeft: 16, margin: "6px 0 0" }}>{prof.notes.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul> : null}
          </Card>
          <Card title="Assumptions — edit and recompute" sub="each shows where it came from">
            <table className="tbl"><tbody>
              {EDITABLE.map(([k, label, isPct]) => (
                <tr key={k}>
                  <td>{label}</td>
                  <td><input className="num" placeholder={cur(k, isPct)} value={ov[k] ?? ""} onChange={(e) => setOv({ ...ov, [k]: e.target.value })} /> <span className="dim small">{isPct ? "%" : ""}</span></td>
                  <td className="dim small" style={{ textAlign: "left" }}>{k === "target_margin" ? (v.dcf?.flags?.includes("ESTIMATED") ? "normalized margin ramp" : "= FCF margin unless set") : A(k).source}</td>
                </tr>
              ))}
              {["cost_of_equity", "cost_of_debt_pre_tax", "tax_rate", "shares", "net_debt"].map((k) => (
                <tr key={k}><td className="dim">{k}</td><td className="mono dim">{["shares", "net_debt"].includes(k) ? num(A(k).value, 0) : pct(A(k).value, 2, false)}</td><td className="dim small" style={{ textAlign: "left" }}>{A(k).source}</td></tr>
              ))}
            </tbody></table>
            <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
              <button className="primary" style={{ background: "var(--blue)", border: "none", color: "#061020", padding: "6px 12px", borderRadius: 6, cursor: "pointer", fontWeight: 600 }} onClick={recompute} disabled={busy}>{busy ? "…" : "Recompute DCF"}</button>
              <button style={{ background: "var(--bg3)", border: "1px solid var(--line)", color: "var(--text)", padding: "6px 12px", borderRadius: 6, cursor: "pointer" }} onClick={() => { setRe(null); setOv({}); }}>Reset</button>
            </div>
            <div className="small dim" style={{ marginTop: 6 }}>Leave a field blank to keep the model's value. Setting WACC directly pins it; otherwise it is re-derived from rf + β·ERP.</div>
          </Card>
          <Card title="DCF result & reverse DCF" sub="what does the price already assume?">
            <div className="kv">
              <span>DCF (Gordon)</span><span className="mono" style={{ fontSize: 18 }}>{usd(v.dcf?.value_per_share_gordon)} <span className={v.dcf?.upside_pct > 0 ? "pos" : "neg"}>{pct(v.dcf?.upside_pct)}</span></span>
              {v.dcf?.value_per_share_exit != null ? <><span>DCF (exit multiple {v.dcf.exit_multiple}x)</span><span className="mono">{usd(v.dcf.value_per_share_exit)}</span></> : null}
              <span>terminal share of EV</span><span className="mono">{pct(v.dcf?.terminal_share_gordon, 0, false)}</span>
              <span>margin path</span><span className="mono">{pct(v.dcf?.margin, 1, false)} → {pct(v.dcf?.margin_target, 1, false)}</span>
              <span>Implied stage-1 growth</span><span className="mono" style={{ fontSize: 16 }}>{v.reverse_dcf?.available ? pct(v.reverse_dcf.implied_growth) : <span className="dim small">{v.reverse_dcf?.reason}</span>}</span>
              <span>Delivered (blend)</span><span className="mono">{pct(A("growth_stage1").value)}</span>
              <span>3y CAGR / last FY / last Q</span><span className="mono">{pct(inp.extra?.revenue_cagr_3y)} / {pct(inp.extra?.revenue_growth_fy)} / {pct(inp.extra?.revenue_growth_q_yoy)}</span>
              <span>Implied FCF margin at delivered growth</span><span className="mono">{v.implied_margin?.available ? `${pct(v.implied_margin.implied_fcf_margin, 1, false)} vs ${pct(v.implied_margin.current_fcf_margin, 1, false)} today` : "—"}</span>
            </div>
            <div className="small dim" style={{ marginTop: 6 }}>{v.reverse_dcf?.note}</div>
          </Card>
        </div>
        <Card title="Every valuation model — applicability, value, weight" sub="models that don't fit this kind of company are listed with the reason">
          <table className="tbl">
            <thead><tr><th>model</th><th>applies</th><th>value / share</th><th>vs price</th><th>blend weight</th><th style={{ textAlign: "left" }}>how / why not</th></tr></thead>
            <tbody>
              {modelRows.map((m) => (
                <tr key={m.key} style={!m.applies ? { opacity: 0.55 } : undefined}>
                  <td>{m.label}{m.flags?.includes("ESTIMATED") ? <span className="badge computed" style={{ marginLeft: 4 }}>est.</span> : null}</td>
                  <td>{m.applies ? (m.computed ? <span className="pos">✓</span> : <span className="warn">–</span>) : <span className="dim">✗</span>}</td>
                  <td className="mono">{m.computed ? usd(m.value_per_share) : "—"}</td>
                  <td className={`mono ${m.upside_pct > 0 ? "pos" : m.upside_pct < 0 ? "neg" : ""}`}>{m.computed ? pct(m.upside_pct, 0) : "—"}</td>
                  <td className="mono">{m.weight ? pct(m.weight, 0, false) : "—"}</td>
                  <td style={{ textAlign: "left" }} className="small dim">{m.reason || m.formula}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="grid g3" style={{ marginTop: 10 }}>
            {v0.scenarios?.available ? <div><div className="muted small">Scenario DCF</div><table className="tbl"><thead><tr><th>case</th><th>p</th><th>growth</th><th>margin</th><th>WACC</th><th>value</th></tr></thead><tbody>{Object.entries<any>(v0.scenarios.cases).map(([k, c]) => <tr key={k}><td>{k}</td><td>{pct(c.probability, 0, false)}</td><td>{pct(c.growth, 0)}</td><td>{pct(c.target_margin, 1, false)}</td><td>{pct(c.wacc, 1, false)}</td><td className="mono">{usd(c.value_per_share)}</td></tr>)}</tbody></table></div> : null}
            {v0.hist_multiples?.available ? <div><div className="muted small">Own historical multiples ({v0.hist_multiples.n_years} FY) → implied</div><table className="tbl"><thead><tr><th></th><th>median</th><th>now</th><th>implied</th></tr></thead><tbody>{Object.entries<any>(v0.hist_multiples.median_multiples).map(([k, med]) => <tr key={k}><td>{k}</td><td>{x(med)}</td><td>{x(v0.hist_multiples.current_multiples?.[k])}</td><td className="mono">{usd(v0.hist_multiples.implied?.[k])}</td></tr>)}</tbody></table></div> : <div className="dim small">{v0.hist_multiples?.reason}</div>}
            <div><div className="muted small">Other</div><div className="kv small">
              {v0.dcf_exit?.available ? <><span>exit multiple</span><span className="mono">{x(v0.dcf_exit.exit_multiple)} EV/EBITDA <span className="dim">({v0.dcf_exit.exit_multiple_source})</span></span></> : null}
              {v0.cash_runway?.available ? <><span>cash runway</span><span className="mono">{num(v0.cash_runway.runway_years, 1)} years <span className="dim">(burn ${(v0.cash_runway.annual_burn / 1e6).toFixed(0)}M/yr)</span></span></> : null}
              {v0.ffo_cap?.available ? <><span>FFO / share</span><span className="mono">{usd(v0.ffo_cap.ffo_per_share)} @ {pct(v0.ffo_cap.cap_yield, 1, false)} yield</span></> : null}
              {v0.justified_pb?.available ? <><span>justified P/B</span><span className="mono">{x(v0.justified_pb.justified_pb, 2)}</span></> : null}
              {v0.justified_pe?.available ? <><span>justified P/E</span><span className="mono">{x(v0.justified_pe.justified_pe)}</span></> : null}
              {v0.ncav?.available ? <><span>NCAV / share</span><span className="mono">{usd(v0.ncav.value_per_share)}</span></> : null}
              {v0.tangible_book?.available ? <><span>tangible book / share</span><span className="mono">{usd(v0.tangible_book.value_per_share)}</span></> : null}
            </div></div>
          </div>
        </Card>
        <div className="grid g2">
          <Card title="DCF sensitivity — value/share by WACC × terminal growth">
            {sens ? <Heat rowsL={sens.wacc.map((w: number) => pct(w, 1, false))} colsL={sens.g.map((g: number) => pct(g, 1, false))} values={sens.values} fmt={(val) => usd(val, 0)} center={price} /> : <div className="dim">— (DCF unavailable)</div>}
          </Card>
          <Card title="DCF projection">
            <Table data={proj} cols={["year", "growth", "margin", "revenue", "fcf"]} fmt={{ growth: (val) => pct(val), margin: (val) => pct(val, 1, false), revenue: (val) => "$" + (val / 1e9).toFixed(2) + "B", fcf: (val) => "$" + (val / 1e9).toFixed(2) + "B" }} />
          </Card>
        </div>
        <div className="grid g2">
          <Card title="Monte Carlo — DCF driver space" sub={mc.available ? `${mc.n} draws · growth σ ${pct(mc.inputs_sd?.growth_sd, 1, false)} · margin σ ${pct(mc.inputs_sd?.margin_sd, 1, false)}` : "n/a"}>
            {mc.available ? (
              <>
                <div className="kv"><span>P(fair value &gt; price)</span><span className="mono">{pct(mc.prob_above_price, 0, false)}</span><span>p10 / p50 / p90</span><span className="mono">{usd(mc.percentiles.p10, 0)} / {usd(mc.percentiles.p50, 0)} / {usd(mc.percentiles.p90, 0)}</span></div>
                <Histogram h={mc.histogram} marker={price} />
              </>
            ) : <div className="dim">skipped at this depth or DCF unavailable</div>}
          </Card>
          <Card title="Monte Carlo — price paths (Student-t fan, zero drift)" sub={mcp.available ? `t dof ${num(mcp.t_dof, 1)} · daily σ ${pct(mcp.daily_sigma, 2, false)}` : ""}>
            {fan ? <Line series={[
              { name: "p95", color: "#3fb95088", data: fan.days.map((d: number, i: number) => [d, fan.p95[i]]) }, { name: "p75", color: "#3fb950", data: fan.days.map((d: number, i: number) => [d, fan.p75[i]]) },
              { name: "p50", color: "#e6edf3", data: fan.days.map((d: number, i: number) => [d, fan.p50[i]]) }, { name: "p25", color: "#f85149", data: fan.days.map((d: number, i: number) => [d, fan.p25[i]]) },
              { name: "p5", color: "#f8514988", data: fan.days.map((d: number, i: number) => [d, fan.p5[i]]) }]} yfmt={(val) => usd(val, 0)} /> : null}
            {mcp.available ? <table className="tbl"><thead><tr><th>engine</th><th>21d p5</th><th>21d p95</th><th>63d p5</th><th>63d p95</th><th>1y P(&gt;+10%)</th><th>1y P(&gt;-10%)</th><th>1y CVaR95</th></tr></thead>
              <tbody>{Object.entries<any>(mcp.engines).map(([e, r]) => <tr key={e}><td>{e}</td><td>{usd(r.h21?.percentiles.p5, 0)}</td><td>{usd(r.h21?.percentiles.p95, 0)}</td><td>{usd(r.h63?.percentiles.p5, 0)}</td><td>{usd(r.h63?.percentiles.p95, 0)}</td><td>{pct(r.h252?.prob_above["1.1"], 0, false)}</td><td>{pct(r.h252?.prob_above["0.9"], 0, false)}</td><td>{pct(r.h252?.cvar95_pct, 0, false)}</td></tr>)}</tbody></table> : null}
          </Card>
        </div>
        <Card title="Comparables" sub={comps ? `${comps.n_peers} peers via ${comps.source}` : "skipped (quick depth)"}>
          {comps ? (
            <div className="grid g2">
              <div>
                <table className="tbl"><thead><tr><th>multiple</th><th>subject</th><th>p25</th><th>median</th><th>p75</th><th>pct</th><th>premium</th><th>implied @median</th></tr></thead>
                  <tbody>{Object.entries<any>(comps.stats).map(([k, st]) => <tr key={k}><td>{st.label}</td><td className="mono">{x(st.subject)}</td><td>{x(st.p25)}</td><td>{x(st.median)}</td><td>{x(st.p75)}</td><td>{pct(st.subject_percentile, 0, false)}</td><td className={st.premium_to_median > 0 ? "neg" : "pos"}>{pct(st.premium_to_median, 0)}</td><td>{usd(comps.implied?.[k]?.at_median, 0)}</td></tr>)}</tbody></table>
                {comps.regression ? <div className="small muted" style={{ marginTop: 6 }}>Growth/margin-adjusted EV/S: fitted {x(comps.regression.fitted_ev_sales)} vs actual {x(comps.regression.actual_ev_sales)} → implied {usd(comps.regression.implied_price, 0)} (n={comps.regression.n})</div> : <div className="small dim" style={{ marginTop: 6 }}>regression needs ≥ 8 peers</div>}
              </div>
              <Table data={comps.peers} cols={["symbol", "name", "market_cap", "rev_growth", "gross_margin", "pe", "fwd_pe", "ev_ebitda", "ev_sales", "pb", "peg"]} fmt={{ market_cap: (val) => "$" + (val / 1e9).toFixed(0) + "B", rev_growth: (val) => pct(val), gross_margin: (val) => pct(val, 0, false) }} />
            </div>
          ) : null}
        </Card>
      </div>
    </Section>
  );
}

function Histogram({ h, marker }: { h: { edges: number[]; counts: number[] }; marker: number }) {
  if (!h) return null;
  const w = 520, ht = 140;
  const max = Math.max(...h.counts, 1);
  const x0 = h.edges[0], x1 = h.edges[h.edges.length - 1];
  const X = (val: number) => ((val - x0) / (x1 - x0 || 1)) * w;
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${ht}`} style={{ height: ht }}>
      {h.counts.map((c, i) => <rect key={i} x={X(h.edges[i])} y={ht - 16 - (c / max) * (ht - 20)} width={Math.max(1, X(h.edges[i + 1]) - X(h.edges[i]) - 1)} height={(c / max) * (ht - 20)} fill={h.edges[i] >= marker ? "var(--green)" : "var(--red)"} opacity={0.7} />)}
      {isNum(marker) ? <line x1={X(marker)} x2={X(marker)} y1={0} y2={ht - 16} stroke="#e6edf3" strokeDasharray="4 3" /> : null}
      <text x={2} y={ht - 4}>{usd(x0, 0)}</text><text x={w - 2} y={ht - 4} textAnchor="end">{usd(x1, 0)}</text>
    </svg>
  );
}

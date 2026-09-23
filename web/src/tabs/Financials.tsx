import React, { useState } from "react";
import type { RunState } from "../api";
import { Card, ProvBadge, Section, Sparkline, Table, Bars } from "../components";
import { big, isNum, pct, rows, num } from "../fmt";

const STATEMENTS: Record<string, string[]> = {
  income: ["revenue", "cogs", "gross_profit", "rnd", "sga", "opex", "operating_income", "interest_expense", "pretax_income", "income_tax", "net_income", "eps_basic", "eps_diluted", "shares_diluted", "ebitda"],
  balance: ["cash", "st_investments", "receivables", "inventory", "current_assets", "ppe_net", "goodwill", "intangibles", "total_assets", "payables", "current_liabilities", "st_debt", "lt_debt", "total_debt", "total_liabilities", "equity", "shares_outstanding"],
  cashflow: ["cfo", "da", "sbc", "capex", "fcf", "cfi", "acquisitions", "cff", "dividends_paid", "buybacks", "debt_issued", "debt_repaid"],
};

function Grid({ grid, keys, labels, freq }: { grid: any[]; keys: string[]; labels: Record<string, string>; freq: string }) {
  const rs = rows(grid);
  if (!rs.length) return <div className="dim">no data</div>;
  const byConcept: Record<string, any> = Object.fromEntries(rs.map((r: any) => [r.index ?? r.concept ?? r[Object.keys(r)[0]], r]));
  const cols = Object.keys(rs[0]).filter((c) => c !== "index" && c !== "concept").slice(-(freq === "annual" ? 8 : 10));
  return (
    <div className="scroll">
      <table className="tbl">
        <thead><tr><th>{freq}</th>{cols.map((c) => <th key={c}>{String(c).slice(0, 10)}</th>)}</tr></thead>
        <tbody>
          {keys.map((k) => {
            const r = byConcept[k];
            if (!r) return null;
            const vals = cols.map((c) => r[c]);
            const perShare = k.startsWith("eps");
            return (
              <tr key={k}>
                <td>{labels[k] || k} <Sparkline values={vals.filter(isNum)} w={60} h={14} /></td>
                {vals.map((v, i) => <td key={i} className={isNum(v) && v < 0 ? "neg" : ""}>{isNum(v) ? (perShare ? v.toFixed(2) : Math.abs(v) > 1e5 ? big(v) : num(v, 0)) : "—"}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Financials({ s }: { s: RunState }) {
  const f = s.data.fundamentals;
  const [freq, setFreq] = useState<"annual" | "quarterly">("annual");
  const [stmt, setStmt] = useState<"income" | "balance" | "cashflow">("income");
  if (!f) return <Section name="fundamentals" status={s.sections.fundamentals}><div /></Section>;
  const m = f.metrics || {};
  const groups: Record<string, string[]> = {};
  for (const [k, v] of Object.entries<any>(m)) (groups[v.group] ||= []).push(k);
  const cov = f.coverage || {};
  const q = f.quality || {};
  const seg = f.segments || {};
  return (
    <Section name="fundamentals" status={s.sections.fundamentals}>
      <div className="grid" style={{ gap: 12 }}>
        <Card title="Statements" sub={<><ProvBadge p={f.prov_id} /> FYE month {f.fye_month} · TTM to {f.ttm_end} · {cov.annual_periods} FY / {cov.quarterly_periods} Q periods</>}>
          <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <div className="toggle">{(["income", "balance", "cashflow"] as const).map((k) => <button key={k} className={stmt === k ? "on" : ""} onClick={() => setStmt(k)}>{k}</button>)}</div>
            <div className="toggle">{(["annual", "quarterly"] as const).map((k) => <button key={k} className={freq === k ? "on" : ""} onClick={() => setFreq(k)}>{k}</button>)}</div>
          </div>
          <Grid grid={freq === "annual" ? f.annual : f.quarterly} keys={STATEMENTS[stmt]} labels={f.labels || {}} freq={freq} />
        </Card>
        <div className="grid g3">
          <Card title="Quality models">
            <div className="kv">
              <span>Piotroski F</span><span className="mono">{q.piotroski?.score}/{q.piotroski?.of}</span>
              <span>Altman Z</span><span className="mono">{num(q.altman?.z)} <span className="dim">{q.altman?.zone} · {q.altman?.model}</span></span>
              <span>Beneish M</span><span className={`mono ${q.beneish?.flag ? "warn" : ""}`}>{num(q.beneish?.m)} <span className="dim">{q.beneish?.flag ? "flag (> -1.78)" : "clean"}</span></span>
              <span>Sloan accruals</span><span className="mono">{pct(q.accruals?.sloan_ratio)}</span>
              <span>Cash conversion</span><span className="mono">{num(q.accruals?.cash_conversion)}x</span>
            </div>
            <div className="small muted" style={{ marginTop: 8 }}>Piotroski tests</div>
            <div className="small">{Object.entries<any>(q.piotroski?.tests || {}).map(([k, t]) => <div key={k}><span className={t.pass ? "pos" : t.pass === false ? "neg" : "dim"}>{t.pass ? "✓" : t.pass === false ? "✗" : "·"}</span> {k} <span className="dim">{t.detail}</span></div>)}</div>
          </Card>
          <Card title="XBRL coverage" sub={`${cov.resolved} resolved · ${cov.formula} formula · ${cov.missing} missing`}>
            <div className="small">core line items: <b>{pct(cov.core_coverage, 0, false)}</b> · restatements {cov.restatements} · spliced tags {cov.spliced?.length}</div>
            <div className="scroll" style={{ maxHeight: 260, marginTop: 6 }}>
              <table className="tbl"><thead><tr><th>concept</th><th>status</th><th>tag / formula</th><th>FY</th><th>Q</th><th>derived Q</th></tr></thead>
                <tbody>{rows(cov.rows).map((r: any) => <tr key={r.concept}><td>{r.label}</td><td className={r.status === "missing" ? "dim" : r.status === "formula" ? "warn" : "pos"}>{r.status}</td><td className="mono small">{r.tag || r.formula || ""}{r.spliced_from?.length ? <span className="warn"> +{r.spliced_from.length} spliced</span> : null}</td><td>{r.annual_periods}</td><td>{r.quarterly_periods}</td><td>{r.derived_quarters}</td></tr>)}</tbody>
              </table>
            </div>
          </Card>
          <Card title="Segments" sub={seg.available ? `HHI ${num(seg.hhi)}` : "not available"}>
            {Object.values<any>(seg.breakdowns || {}).map((b: any) => (
              <div key={b.report} style={{ marginBottom: 10 }}>
                <div className="small muted">{b.kind} · {b.period} to {b.as_of} · total {big(b.total)}</div>
                <Bars items={b.members.slice(0, 8).map((x: any) => ({ label: `${x.member} (${pct(x.yoy, 0)})`, value: x.share }))} h={150} color={() => "var(--blue)"} labelFmt={(v) => pct(v, 0, false)} />
              </div>
            ))}
          </Card>
        </div>
        <Card title="Metric library" sub="every value traces to its formula and XBRL tags">
          <div className="grid g3">
            {Object.entries(groups).map(([g, keys]) => (
              <div key={g}>
                <div className="muted small" style={{ textTransform: "uppercase", margin: "6px 0" }}>{g}</div>
                <table className="tbl"><tbody>
                  {keys.map((k) => { const v = m[k]; const val = v.value; return (
                    <tr key={k} title={`${v.formula}\n${Object.entries(v.inputs || {}).map(([a, b]) => `${a}=${b}`).join("\n")}`}>
                      <td>{v.label}</td>
                      <td className={isNum(val) && val < 0 ? "neg" : ""}>{!isNum(val) ? "—" : v.unit === "pct" ? pct(val, 1, false) : v.unit === "x" ? val.toFixed(2) + "x" : v.unit === "USD" ? "$" + big(val) : v.unit === "days" ? val.toFixed(0) + "d" : num(val)}</td>
                      <td>{v.history ? <Sparkline values={Object.values<number>(v.history)} w={50} h={14} /> : null}</td>
                    </tr>); })}
                </tbody></table>
              </div>
            ))}
          </div>
        </Card>
        {f.restatements?.length ? <Card title="Restatements (as-filed vs latest)"><Table data={f.restatements.slice(0, 30)} cols={["concept", "period_end", "original", "restated", "change_pct", "reason", "original_filed", "restated_filed"]} /></Card> : null}
      </div>
    </Section>
  );
}

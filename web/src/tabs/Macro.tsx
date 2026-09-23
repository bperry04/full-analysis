import React from "react";
import type { RunState } from "../api";
import { Bars, Card, Line, ProvBadge, Section } from "../components";
import { date, num, pct, rows } from "../fmt";

export function Macro({ s }: { s: RunState }) {
  const m = s.data.market;
  const sens = s.data.risk?.sensitivity || {};
  if (!m) return <Section name="market" status={s.sections.market}><div /></Section>;
  const yc = rows(m.yield_curve_history);
  const last = yc[yc.length - 1] || {};
  const tenors = ["DGS1MO", "DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30"].filter((t) => last[t] != null);
  const vixh = rows(m.vix_history);
  const uni = sens.univariate || {};
  return (
    <Section name="market" status={s.sections.market}>
      <div className="grid" style={{ gap: 12 }}>
        <div className="grid g4">
          <Card title="Risk appetite" sub={<ProvBadge p={m.prov_id} />}>
            <div style={{ fontSize: 22 }} className={`mono ${m.risk_appetite?.score > 0.3 ? "pos" : m.risk_appetite?.score < -0.3 ? "neg" : "warn"}`}>{m.risk_appetite?.label}</div>
            <div className="small muted">{num(m.risk_appetite?.score)} from {m.risk_appetite?.votes} signals · sector breadth {pct(m.breadth_sectors_above_50d, 0, false)} above 50d</div>
            <div className="kv" style={{ marginTop: 8 }}>{Object.entries<any>(m.indices || {}).map(([k, v]) => <React.Fragment key={k}><span>{k} {v.name}</span><span className="mono">{v.above_50d ? <span className="pos">▲50</span> : <span className="neg">▼50</span>} {v.above_200d ? <span className="pos">▲200</span> : <span className="neg">▼200</span>} · 1m {pct(v.r_1m)} · 3m {pct(v.r_3m)} · ytd {pct(v.r_ytd)}</span></React.Fragment>)}</div>
          </Card>
          <Card title="Volatility">
            <div className="kv">
              <span>VIX</span><span className="mono">{num(m.vix?.level, 1)} <span className="dim">{m.vix?.regime} · {pct(m.vix?.percentile_1y, 0, false)} pct 1y · {pct(m.vix?.percentile_5y, 0, false)} pct 5y</span></span>
              <span>5d change</span><span className={`mono ${m.vix?.change_5d > 0 ? "neg" : "pos"}`}>{num(m.vix?.change_5d, 1)}</span>
              <span>VIX / VIX3M</span><span className="mono">{num(m.vix_term?.ratio)} <span className="dim">{m.vix_term?.structure}</span></span>
            </div>
            {vixh.length ? <Line series={[{ name: "vix", color: "var(--amber)", data: vixh.map((r: any) => [new Date(r.ts).getTime(), r.close]) }]} yfmt={(v) => v.toFixed(0)} h={150} /> : null}
          </Card>
          <Card title="Rates & credit" sub={<ProvBadge p={m.yield_curve_prov} />}>
            <div className="kv">
              <span>3m / 2y / 10y / 30y</span><span className="mono">{num(m.rates?.dgs3mo)} / {num(m.rates?.dgs2)} / {num(m.rates?.dgs10)} / {num(m.rates?.dgs30)}</span>
              <span>10y−2y / 10y−3m</span><span className="mono">{num(m.rates?.spread_10y_2y)} / {num(m.rates?.spread_10y_3m)}</span>
              <span>10y change (1m)</span><span className="mono">{num(m.rates?.chg_10y_1m)} pts</span>
              <span>HYG/LQD 1m / 3m</span><span className={`mono ${m.credit?.ratio_chg_1m > 0 ? "pos" : "neg"}`}>{pct(m.credit?.ratio_chg_1m)} / {pct(m.credit?.ratio_chg_3m)}</span>
              <span>as of</span><span className="mono">{date(m.rates?.as_of)}</span>
            </div>
            {tenors.length ? <Bars items={tenors.map((t) => ({ label: t.replace("DGS", ""), value: last[t] }))} h={180} color={() => "var(--blue)"} labelFmt={(v) => v.toFixed(2)} /> : null}
          </Card>
          <Card title="Sectors (3m vs SPY)">
            <Bars items={Object.entries<any>(m.sectors || {}).map(([k, v]) => ({ label: `${k} ${v.name}`, value: v.rs_3m_vs_spy })).filter((x) => x.value != null).sort((a, b) => b.value - a.value)} h={260} labelFmt={(v) => pct(v)} />
          </Card>
        </div>
        <div className="grid g2">
          <Card title="What moves this name" sub={`rolling ${sens.window_days}d OLS · R² ${num(sens.r2_multivariate)} · idiosyncratic ${pct(sens.idiosyncratic_share, 0, false)}`}>
            <Bars items={Object.entries<any>(uni).map(([k, v]) => ({ label: `${k} ${v.name}`, value: v.beta }))} h={220} labelFmt={(v) => v.toFixed(2)} />
            <div className="small muted">{Object.entries<any>(uni).map(([k, v]) => `${k} ρ ${num(v.corr)}`).join(" · ")}</div>
            <div className="small dim">multivariate betas: {Object.entries<any>(sens.multivariate_betas || {}).map(([k, v]) => `${k} ${num(v)}`).join(" · ")}</div>
          </Card>
          <Card title="Macro headlines" sub={`sentiment ${num(m.macro_news?.score)} over ${m.macro_news?.n} stories`}>
            <ul className="news small" style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: 300, overflow: "auto" }}>
              {rows(m.macro_news?.items).slice(0, 25).map((it: any, i: number) => <li key={i}><span className={`s ${it.sentiment > 0.2 ? "pos" : it.sentiment < -0.2 ? "neg" : "dim"}`}>{Number(it.sentiment).toFixed(2)}</span> <a href={it.url} target="_blank" rel="noreferrer">{it.title}</a> <span className="dim">{it.publisher}</span></li>)}
            </ul>
          </Card>
        </div>
      </div>
    </Section>
  );
}

import React from "react";
import type { RunState } from "../api";
import { Card, Drivers, Gauge, Section, Tile, V, Candles, Bars } from "../components";
import { big, date, num, pct, rows, usd, x } from "../fmt";
import { SwingPanel } from "./Technicals";

const KIND_COLOR: Record<string, string> = { "m&a": "var(--purple)", capacity: "var(--cyan)", strategy: "var(--blue)", capital_return: "var(--green)", product: "var(--blue)", contract: "var(--green)",
  guidance: "var(--amber)", financing: "var(--red)", legal: "var(--red)", management: "var(--amber)", macro: "var(--amber)", earnings: "var(--cyan)", analyst: "var(--muted)", stock_move: "var(--muted)", other: "var(--dim)" };

function Narrative({ items }: { items: any[] }) {
  if (!items?.length) return <div className="dim small">nothing material found in the last 60 days of news / 180 days of 8-Ks</div>;
  return (
    <ul className="news" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {items.slice(0, 8).map((it, i) => (
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

export function Overview({ s }: { s: RunState }) {
  const ov = s.data.overview || {};
  const prof = s.data.profile || {};
  const sc = s.scores?.horizons || {};
  const factors = s.scores?.factors || {};
  const nar = s.data.narrative || {};
  const tech = s.data.technicals;
  const daily = rows(tech?.bars?.["1d"]);
  const ind = rows(tech?.indicator_frame_1d);
  const overlays = ind.length ? [
    { name: "SMA50", color: "#58a6ff", data: ind.map((r: any) => ({ time: r.ts, value: r.sma_50 })) },
    { name: "SMA200", color: "#bc8cff", data: ind.map((r: any) => ({ time: r.ts, value: r.sma_200 })) },
  ] : [];
  const cats = (h: string) => Object.entries(sc[h]?.category_scores || {}).map(([k, v]: any) => ({ label: `${k} (w${v.weight})`, value: (v.score ?? 50) - 50 }));
  return (
    <div className="grid" style={{ gap: 12 }}>
      <Card>
        <div style={{ display: "flex", gap: 16, alignItems: "baseline", flexWrap: "wrap" }}>
          <span style={{ fontSize: 22, fontWeight: 600 }}>{s.symbol}</span>
          <span className="muted">{prof.name} · {prof.sector} · {prof.industry} · {prof.exchange}</span>
          {prof.cik ? <span className="dim small">CIK {prof.cik} · SIC {prof.sic} {prof.sic_description} · FYE {prof.fiscal_year_end}</span> : null}
        </div>
        <div className="grid g6" style={{ marginTop: 10 }}>
          <Tile k="Price" x={ov.price} f={(v) => usd(v)} />
          <Tile k="Change" x={ov.change_pct} f={(v) => pct(v / 100)} color />
          <Tile k="Market cap" x={ov.market_cap} f={(v) => "$" + big(v)} />
          <Tile k="P/E (TTM)" x={ov.pe} f={(v) => x(v)} />
          <Tile k="EV/EBITDA" x={ov.ev_ebitda} f={(v) => x(v)} />
          <Tile k="FCF yield" x={ov.fcf_yield} f={(v) => pct(v, 1, false)} />
          <Tile k="IV30" x={ov.iv30} f={(v) => pct(v, 1, false)} />
          <Tile k="IV rank" x={ov.iv_rank} f={(v) => pct(v, 0, false)} />
          <Tile k="Beta" x={ov.beta} f={(v) => num(v)} />
          <Tile k="Short % float" x={ov.short_pct_float} f={(v) => pct(v, 1, false)} />
          <Tile k="Next earnings" x={ov.next_earnings} f={(v) => date(v)} />
          <Tile k="1y return" x={ov.r_1y} f={(v) => pct(v)} color />
        </div>
      </Card>
      <div className="grid g3">{["long", "medium", "short"].map((h) => <Gauge key={h} h={h} s={sc[h]} />)}</div>
      <div className="grid g3">
        {["long", "medium", "short"].map((h) => (
          <Card key={h} title={`${h} · quantitative drivers`} sub={`${sc[h]?.n_present ?? 0} factors scored`}>
            <Drivers drivers={sc[h]?.drivers || []} factors={factors} n={10} />
          </Card>
        ))}
      </div>
      <Section name="technicals" status={s.sections.technicals}>
        <SwingPanel pat={tech?.patterns} />
      </Section>
      <Section name="narrative" status={s.sections.narrative}>
        <div className="grid g3">
          {["long", "medium", "short"].map((h) => (
            <Card key={h} title={`${h} · what the company is doing`} sub="context, not scored">
              <Narrative items={nar[h]} />
            </Card>
          ))}
        </div>
        {nar.themes && Object.keys(nar.themes).length ? <Card title="Themes in the flow" sub={`${nar.n_items} items from news, 8-Ks, filings-derived facts and catalysts`}><div>{Object.entries<number>(nar.themes).map(([k, n]) => <span key={k} className="pill" style={{ marginRight: 6, marginBottom: 4, display: "inline-block" }}>{k} ×{n}</span>)}</div><div className="dim small" style={{ marginTop: 6 }}>{nar.note}</div></Card> : null}
      </Section>
      <div className="grid g3">
        {["long", "medium", "short"].map((h) => (
          <Card key={h} title={`${h} · category scores (±50)`}>
            <Bars items={cats(h)} h={160} labelFmt={(v) => (v + 50).toFixed(0)} />
          </Card>
        ))}
      </div>
      <Section name="technicals" status={s.sections.technicals}>
        <Card title="Price (daily, split-adjusted)" sub={<>SMA50 <i style={{ color: "#58a6ff" }}>—</i> SMA200 <i style={{ color: "#bc8cff" }}>—</i></>}>
          {daily.length ? <Candles bars={daily} overlays={overlays} /> : null}
        </Card>
      </Section>
      <div className="grid g2">
        <Card title="Valuation snapshot">
          <div className="kv">
            <span>DCF upside</span>{s.data.valuation?.dcf?.available === false ? <span className="dim small">n/a — {String(s.data.valuation.dcf.reason || "").slice(0, 70)}</span> : <V x={ov.dcf_upside} f={(v) => pct(v)} color />}
            <span>Blended fair value</span><V x={ov.blended_fair_value} f={(v) => usd(v)} />
            <span>Reverse-DCF implied growth</span><span className="mono">{pct(s.data.valuation?.reverse_dcf?.implied_growth)} vs {pct(s.data.valuation?.inputs?.growth_stage1?.value)} delivered</span>
            <span>Avg volume (20d)</span><V x={ov.avg_volume_20d} f={(v) => big(v)} />
            <span>1m return</span><V x={ov.r_1m} f={(v) => pct(v)} color />
          </div>
        </Card>
        <Card title="Business">
          <div className="small" style={{ maxHeight: 180, overflow: "auto", lineHeight: 1.45 }}>{prof.summary}</div>
        </Card>
      </div>
      {s.data.warnings?.length ? <Card title="Warnings"><ul className="small muted">{s.data.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul></Card> : null}
    </div>
  );
}

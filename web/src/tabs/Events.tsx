import React from "react";
import type { RunState } from "../api";
import { Card, ProvBadge, Section, Table } from "../components";
import { date, pct } from "../fmt";
import { ImpactTag } from "./Horizon";

export function Events({ s }: { s: RunState }) {
  const e = s.data.events;
  const an = s.data.analysts || {};
  if (!e) return <Section name="events" status={s.sections.events}><div /></Section>;
  const ev = e.events || [];
  return (
    <Section name="events" status={s.sections.events}>
      <div className="grid g2">
        <Card title="Catalyst timeline" sub={<><ProvBadge p={e.prov_id} /> earnings in {e.days_to_earnings ?? "—"}d · FOMC in {e.days_to_fomc ?? "—"}d</>}>
          <ul className="events" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {ev.map((x: any, i: number) => (
              <li key={i}>
                <span className="mono">{date(x.date)}</span>
                <span className="mono dim">+{x.days_until}d</span>
                <span><span className="imp" title={`importance ${x.importance}`}><span style={{ display: "block", height: "100%", width: `${x.importance * 20}%`, background: x.importance >= 4 ? "var(--red)" : x.importance >= 3 ? "var(--amber)" : "var(--blue)" }} /></span> {x.label}{x.confirmed ? "" : <span className="dim"> (est.)</span>}{x.detail?.historical_mean_abs_move ? <span className="dim small"> · avg move {pct(x.detail.historical_mean_abs_move, 1, false)}</span> : null}{x.detail?.consensus ? <span className="dim small"> · consensus {x.detail.consensus}, prev {x.detail.previous}</span> : null}<div><ImpactTag imp={x.impact} />{x.impact?.why ? <span className="dim small"> — {x.impact.why}</span> : null}</div></span>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Earnings history" sub={<ProvBadge p={an.prov_id} />}>
          <Table data={an.earnings_history} cols={["ts", "eps_estimate", "eps_reported", "surprise_pct"]} fmt={{ ts: (v) => date(v), surprise_pct: (v) => (v == null ? "—" : Number(v).toFixed(1) + "%") }} />
        </Card>
      </div>
    </Section>
  );
}

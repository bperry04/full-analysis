import React from "react";
import type { RunState } from "../api";
import { Card, Line, ProvBadge, Section, Table } from "../components";
import { big, date, num, pct, rows, usd } from "../fmt";

export function Ownership({ s }: { s: RunState }) {
  const o = s.data.ownership || {};
  const sh = s.data.shorts || {};
  const an = s.data.analysts || {};
  const ins = o.insiders || {};
  const ch = rows(an.consensus_history);
  const sih = rows(sh.history);
  return (
    <div className="grid" style={{ gap: 12 }}>
      <div className="grid g3">
        <Section name="analysts" status={s.sections.analysts}>
          <Card title="Analysts" sub={<ProvBadge p={an.prov_id} />}>
            <div className="kv">
              <span>consensus (n)</span><span className="mono">{an.consensus ? `${an.consensus.strong_buy} SB · ${an.consensus.buy} B · ${an.consensus.hold} H · ${an.consensus.sell} S · ${an.consensus.strong_sell} SS (${an.consensus.n})` : "—"}</span>
              <span>price target low / mean / median / high</span><span className="mono">{usd(an.targets?.low, 0)} / {usd(an.targets?.mean, 0)} / {usd(an.targets?.median, 0)} / {usd(an.targets?.high, 0)}</span>
              <span>upgrades / downgrades / inits (90d)</span><span className="mono">{an.recent_actions?.upgrades ?? "—"} / {an.recent_actions?.downgrades ?? "—"} / {an.recent_actions?.inits ?? "—"}</span>
            </div>
            {ch.length > 1 ? <Line series={[{ name: "pt_mean", color: "var(--blue)", data: ch.map((r: any) => [new Date(r.as_of).getTime(), r.pt_mean]) }]} yfmt={(v) => usd(v, 0)} h={140} /> : <div className="dim small">consensus history accrues with each run</div>}
            <Table data={an.actions} cols={["date", "firm", "action", "from_grade", "to_grade"]} fmt={{ date: (v) => date(v) }} max={30} />
          </Card>
        </Section>
        <Section name="ownership" status={s.sections.ownership}>
          <Card title="Insiders (Form 4)" sub={<ProvBadge p={o.prov_id} />}>
            <div className="kv">
              <span>net value (6m)</span><span className={`mono ${ins.net_value_6m > 0 ? "pos" : "neg"}`}>{usd(ins.net_value_6m, 0)}</span>
              <span>net shares (6m)</span><span className="mono">{big(ins.net_shares_6m, 2)}</span>
              <span>buys / sells / txns</span><span className="mono">{ins.buys_6m} / {ins.sells_6m} / {ins.n_txns_6m}</span>
            </div>
            <Table data={ins.transactions} cols={["date", "insider", "title", "text", "shares", "value"]} fmt={{ date: (v) => date(v), value: (v) => usd(v, 0) }} max={30} />
          </Card>
        </Section>
        <Section name="shorts" status={s.sections.shorts}>
          <Card title="Short interest" sub={<><ProvBadge p={sh.prov_id} q={sh.flags} /> settlement {sh.settlement_date}</>}>
            <div className="kv">
              <span>shares short</span><span className="mono">{big(sh.shares_short, 2)} {sh.shares_short_prior ? <span className="dim">(prior {big(sh.shares_short_prior, 2)}, {num(sh.change_pct, 1)}%)</span> : null}</span>
              <span>% of float</span><span className="mono">{pct(sh.pct_of_float, 2, false)}</span>
              <span>days to cover</span><span className="mono">{num(sh.days_to_cover, 1)}</span>
              <span>avg daily volume</span><span className="mono">{big(sh.avg_daily_volume, 1)}</span>
              <span>sources agree</span><span className="mono small">{(sh.candidates || []).map((c: any) => `${c.provider}:${big(c.value, 2)}`).join("  ")}</span>
            </div>
            {sih.length > 1 ? <Line series={[{ name: "si", color: "var(--red)", data: sih.map((r: any) => [new Date(r.settlement_date).getTime(), r.shares_short]) }]} yfmt={(v) => big(v, 0)} h={160} /> : null}
          </Card>
        </Section>
      </div>
      <Section name="ownership" status={s.sections.ownership}>
        <Card title="Institutional holders (13F, 45-day lag)">
          <div className="small muted" style={{ marginBottom: 6 }}>{Object.entries(o.major || {}).map(([k, v]: any) => `${k}: ${typeof v === "number" ? (v > 1 ? v.toFixed(1) + "%" : pct(v, 1, false)) : v}`).join(" · ")}</div>
          <Table data={o.institutional} cols={["holder", "reported", "shares", "pct_held", "value", "pct_change"]} fmt={{ reported: (v) => date(v), shares: (v) => big(v, 1), value: (v) => "$" + big(v, 1), pct_held: (v) => (v > 1 ? v.toFixed(2) + "%" : pct(v, 2, false)), pct_change: (v) => (v == null ? "—" : Number(v).toFixed(1) + "%") }} />
        </Card>
      </Section>
    </div>
  );
}

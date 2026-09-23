import React from "react";
import type { RunState } from "../api";
import { Card, ProvBadge, Section, Table } from "../components";
import { date, num, pct, rows } from "../fmt";

export function News({ s }: { s: RunState }) {
  const n = s.data.news;
  const so = s.data.social || {};
  const st = so.stocktwits || {};
  const rd = so.reddit || {};
  const items = rows(n?.items);
  return (
    <div className="grid" style={{ gap: 12 }}>
      <Section name="news" status={s.sections.news}>
        <div className="grid g3">
          <Card title="News sentiment" sub={<ProvBadge p={n?.prov_id} />}>
            <div className="kv">
              <span>stories (deduped) / items</span><span className="mono">{n?.n_stories} / {n?.n_items}</span>
              <span>48h half-life score</span><span className={`mono ${n?.short_term?.score > 0 ? "pos" : "neg"}`}>{num(n?.short_term?.score)}</span>
              <span>2-week half-life score</span><span className={`mono ${n?.medium_term?.score > 0 ? "pos" : "neg"}`}>{num(n?.medium_term?.score)}</span>
              <span>last 24h / 7d / prior 7d</span><span className="mono">{n?.n_last_24h} / {n?.n_last_7d} / {n?.n_prior_7d}</span>
              <span>positive / negative share (7d)</span><span className="mono">{pct(n?.positive_share_7d, 0, false)} / {pct(n?.negative_share_7d, 0, false)}</span>
              <span>volume anomaly</span><span className="mono">{n?.news_volume_z != null ? num(n.news_volume_z, 1) + "σ" : "n/a (feed span < 14d)"}</span>
            </div>
            <div className="small dim" style={{ marginTop: 6 }}>Sources weighted (Reuters/WSJ/Bloomberg 1.0 … blogs 0.4), syndicated copies collapsed to one vote, VADER + financial lexicon.</div>
          </Card>
          <Card title="StockTwits" sub={<ProvBadge p={so.prov_id} />}>
            <div className="kv">
              <span>messages</span><span className="mono">{st.n} ({num(st.msgs_per_hour, 1)}/h)</span>
              <span>bullish / bearish (tagged)</span><span className="mono">{st.bullish} / {st.bearish} → {pct(st.bull_ratio, 0, false)}</span>
              <span>text sentiment</span><span className="mono">{num(st.text_sentiment)}</span>
              <span>follower-weighted tag sentiment</span><span className="mono">{num(st.followers_weighted_sent)}</span>
            </div>
            <div className="scroll" style={{ maxHeight: 220, marginTop: 6 }}>
              <ul className="news small" style={{ listStyle: "none", padding: 0, margin: 0 }}>{rows(st.messages).slice(0, 20).map((m: any, i: number) => <li key={i}><span className={`s ${m.sentiment === "Bullish" ? "pos" : m.sentiment === "Bearish" ? "neg" : "dim"}`}>{m.sentiment || "—"}</span> <span className="dim">{m.user}</span> {String(m.body).slice(0, 140)}</li>)}</ul>
            </div>
          </Card>
          <Card title="Reddit">
            {rd.n ? (
              <>
                <div className="kv"><span>posts (30d)</span><span className="mono">{rd.n}</span><span>last 7d vs weekly prior</span><span className="mono">{rd.n_last_7d} vs {num(rd.n_prior_14d_weekly, 1)} ({num(rd.mention_z, 1)}σ)</span><span>sentiment / score-weighted</span><span className="mono">{num(rd.sentiment)} / {num(rd.score_weighted_sentiment)}</span></div>
                <Table data={rd.top} cols={["subreddit", "title", "score", "comments", "sent"]} />
              </>
            ) : <div className="dim small">Set FA_REDDIT_CLIENT_ID / SECRET in .env (free script app) to enable.</div>}
          </Card>
        </div>
        <Card title="Headlines" sub="one per story cluster · sentiment · source weight">
          <ul className="news" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {items.map((it: any, i: number) => (
              <li key={i}><span className={`s ${it.sentiment > 0.2 ? "pos" : it.sentiment < -0.2 ? "neg" : "dim"}`}>{it.sentiment > 0 ? "+" : ""}{Number(it.sentiment).toFixed(2)}</span> <a href={it.url} target="_blank" rel="noreferrer">{it.title}</a> <span className="dim small">{it.publisher} · {date(it.published)} · w{Number(it.weight).toFixed(1)}{it.cluster_size > 1 ? ` · ×${it.cluster_size}` : ""}</span></li>
            ))}
          </ul>
        </Card>
      </Section>
    </div>
  );
}

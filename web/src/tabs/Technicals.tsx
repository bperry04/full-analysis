import React, { useMemo, useState } from "react";
import type { RunState } from "../api";
import { Candles, Card, Line, ProvBadge, Section, Table } from "../components";
import { isNum, num, pct, rows, usd } from "../fmt";

const INTERVALS = ["1d", "1wk", "1h", "15m", "5m"];

/* Chart overlays available from the daily indicator frame */
const OVERLAYS: { key: string; label: string; cols: string[]; color: string }[] = [
  { key: "sma20", label: "SMA 20", cols: ["sma_20"], color: "#39c5cf" }, { key: "sma50", label: "SMA 50", cols: ["sma_50"], color: "#58a6ff" },
  { key: "sma100", label: "SMA 100", cols: ["sma_100"], color: "#8b98a8" }, { key: "sma200", label: "SMA 200", cols: ["sma_200"], color: "#bc8cff" },
  { key: "ema9", label: "EMA 9", cols: ["ema_9"], color: "#f0883e" }, { key: "ema21", label: "EMA 21", cols: ["ema_21"], color: "#d29922" },
  { key: "ema50", label: "EMA 50", cols: ["ema_50"], color: "#3fb950" }, { key: "hma20", label: "HMA 20", cols: ["hma_20"], color: "#e6edf3" },
  { key: "bb", label: "Bollinger (20, 2σ)", cols: ["bb_upper", "bb_lower"], color: "#5b6776" }, { key: "kc", label: "Keltner (20, 1.5 ATR)", cols: ["kc_upper", "kc_lower"], color: "#6e5b76" },
  { key: "dc", label: "Donchian 20", cols: ["dc_upper", "dc_lower"], color: "#4b6a5b" }, { key: "st", label: "Supertrend", cols: ["supertrend"], color: "#d29922" },
  { key: "ichi", label: "Ichimoku (tenkan/kijun/cloud)", cols: ["tenkan", "kijun", "senkou_a", "senkou_b"], color: "#bc8cff" }, { key: "vwap", label: "Cumulative VWAP", cols: ["vwap_cum"], color: "#39c5cf" },
];

/* Oscillator panes (below the chart) */
const PANES: { key: string; label: string; cols: string[]; colors: string[]; fmt: (v: number) => string; zero?: boolean; bands?: number[] }[] = [
  { key: "rsi", label: "RSI 14", cols: ["rsi_14"], colors: ["#58a6ff"], fmt: (v) => v.toFixed(0), bands: [30, 70] },
  { key: "macd", label: "MACD (12,26,9)", cols: ["macd", "macd_signal", "macd_hist"], colors: ["#58a6ff", "#f0883e", "#8b98a8"], fmt: (v) => v.toFixed(2), zero: true },
  { key: "stoch", label: "Stochastic %K/%D", cols: ["stoch_k", "stoch_d"], colors: ["#58a6ff", "#f0883e"], fmt: (v) => v.toFixed(0), bands: [20, 80] },
  { key: "adx", label: "ADX / +DI / −DI", cols: ["adx", "plus_di", "minus_di"], colors: ["#e6edf3", "#3fb950", "#f85149"], fmt: (v) => v.toFixed(0) },
  { key: "cci", label: "CCI 20", cols: ["cci_20"], colors: ["#bc8cff"], fmt: (v) => v.toFixed(0), zero: true, bands: [-100, 100] },
  { key: "willr", label: "Williams %R", cols: ["williams_r"], colors: ["#d29922"], fmt: (v) => v.toFixed(0), bands: [-80, -20] },
  { key: "atr", label: "ATR 14 / NATR", cols: ["atr_14"], colors: ["#39c5cf"], fmt: (v) => v.toFixed(2) },
  { key: "hv", label: "Realized vol 20d (close-close vs Yang-Zhang)", cols: ["hv_cc_20", "hv_yz_20"], colors: ["#58a6ff", "#bc8cff"], fmt: (v) => (v * 100).toFixed(0) + "%" },
  { key: "obv", label: "OBV", cols: ["obv"], colors: ["#3fb950"], fmt: (v) => (v / 1e6).toFixed(0) + "M" },
  { key: "cmf", label: "Chaikin money flow 20", cols: ["cmf_20"], colors: ["#3fb950"], fmt: (v) => v.toFixed(2), zero: true },
  { key: "mfi", label: "Money flow index 14", cols: ["mfi_14"], colors: ["#d29922"], fmt: (v) => v.toFixed(0), bands: [20, 80] },
  { key: "rvol", label: "Relative volume (vs 20d)", cols: ["rel_volume"], colors: ["#8b98a8"], fmt: (v) => v.toFixed(2) + "x" },
  { key: "roc", label: "Rate of change 21", cols: ["roc_21"], colors: ["#58a6ff"], fmt: (v) => (v * 100).toFixed(1) + "%", zero: true },
  { key: "z50", label: "Z-score vs SMA 50", cols: ["z_sma_50"], colors: ["#f0883e"], fmt: (v) => v.toFixed(2), zero: true, bands: [-2, 2] },
  { key: "bbw", label: "Bollinger %B / width", cols: ["bb_pct_b", "bb_width"], colors: ["#58a6ff", "#8b98a8"], fmt: (v) => v.toFixed(2) },
];

/* Indicator value groups for the table */
const GROUPS: Record<string, string[]> = {
  Trend: ["sma_20", "sma_50", "sma_200", "ema_9", "ema_21", "ema_50", "hma_20", "adx", "plus_di", "minus_di", "supertrend", "supertrend_dir", "tenkan", "kijun", "lr_slope_20", "lr_r2_20"],
  Momentum: ["rsi_14", "rsi_2", "stoch_k", "stoch_d", "stoch_rsi", "williams_r", "cci_20", "roc_10", "roc_21", "roc_63", "macd", "macd_signal", "macd_hist"],
  Volatility: ["atr_14", "natr_14", "bb_upper", "bb_lower", "bb_pct_b", "bb_width", "kc_upper", "kc_lower", "dc_upper", "dc_lower", "hv_cc_20", "hv_park_20", "hv_gk_20", "hv_yz_20"],
  Volume: ["obv", "cmf_20", "mfi_14", "ad", "vwap_cum", "vol_sma_20", "rel_volume"],
  Position: ["hi_252", "lo_252", "pos_52w", "z_sma_20", "z_sma_50", "z_sma_200", "squeeze_on"],
};

export function SwingPanel({ pat, compact = false }: { pat: any; compact?: boolean }) {
  if (!pat || !pat.setup) return null;
  const s = pat.setup || {};
  const plan = s.plan || {};
  const pats: any[] = pat.patterns || [];
  const dirColor = s.direction > 0 ? "var(--green)" : s.direction < 0 ? "var(--red)" : "var(--amber)";
  return (
    <div className={compact ? "" : "grid g2"}>
      <Card title="Swing setup (2–20 trading days)" sub={<span className="dim">{s.disclaimer}</span>}>
        <div style={{ display: "flex", gap: 12, alignItems: "baseline", flexWrap: "wrap" }}>
          <span style={{ fontSize: 18, fontWeight: 600, color: dirColor }}>{s.setup}</span>
          <span className="pill" style={{ borderColor: dirColor, color: dirColor }}>{s.direction > 0 ? "long bias" : s.direction < 0 ? "short bias" : "no direction"}</span>
          <span className="muted small">quality {num(s.quality)} · trend {s.trend} · RSI14 {num(s.rsi14, 0)} · RSI2 {num(s.rsi2, 0)} · rel. vol {num(s.rel_volume, 1)}x · ATR {usd(s.atr)} ({pct(s.atr_pct, 1, false)})</span>
        </div>
        <ul className="small" style={{ margin: "6px 0", paddingLeft: 16 }}>{(s.why || []).map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
        {plan.entry ? (
          <div className="kv" style={{ marginTop: 6 }}>
            <span>entry / stop / target</span><span className="mono">{usd(plan.entry)} / <span className="neg">{usd(plan.stop)} ({pct(plan.stop_pct)})</span> / <span className="pos">{usd(plan.target)} ({pct(plan.target_pct)})</span></span>
            <span>reward : risk</span><span className={`mono ${plan.rr >= 2 ? "pos" : plan.rr < 1 ? "neg" : ""}`}>{num(plan.rr, 1)}R</span>
            <span>sizing</span><span className="dim small">{plan.position_size_hint}</span>
            {s.implied_10d_move_pct != null ? <><span>option-implied 10-day 1σ move</span><span className="mono">±{pct(s.implied_10d_move_pct, 1, false)} (±{usd(s.implied_10d_move)})</span></> : null}
          </div>
        ) : <div className="dim small">no directional plan — {s.direction === 0 ? "wait for the setup to resolve" : "insufficient level data"}</div>}
        {pat.channel?.bars ? <div className="small muted" style={{ marginTop: 6 }}>60-day regression channel: {pat.channel.direction}, r² {num(pat.channel.r2)}, position {num(pat.channel.position_z, 1)}σ (band {usd(pat.channel.lower, 0)} – {usd(pat.channel.upper, 0)})</div> : null}
      </Card>
      <Card title="Candlestick & chart patterns" sub={<>net last 3 bars <span className={`mono ${pat.recent_net_signal > 0 ? "pos" : pat.recent_net_signal < 0 ? "neg" : ""}`}>{pat.recent_net_signal > 0 ? "+" : ""}{num(pat.recent_net_signal)}</span></>}>
        <div className="scroll" style={{ maxHeight: compact ? 220 : 380 }}>
          <table className="tbl"><thead><tr><th>date</th><th>ago</th><th>kind</th><th>pattern</th><th>bias</th><th>w</th><th style={{ textAlign: "left" }}>context / detail</th></tr></thead>
            <tbody>{pats.slice(0, compact ? 12 : 40).map((p, i) => (
              <tr key={i} style={p.bars_ago > 3 ? { opacity: 0.6 } : undefined}>
                <td className="mono">{p.date}</td><td className="mono">{p.bars_ago}d</td><td className="dim">{p.kind}</td><td style={{ textAlign: "left" }}>{p.name}</td>
                <td className={p.direction > 0 ? "pos" : p.direction < 0 ? "neg" : "dim"}>{p.direction > 0 ? "▲" : p.direction < 0 ? "▼" : "◆"}</td><td className="mono">{num(p.weight)}</td>
                <td style={{ textAlign: "left" }} className="small dim">{p.context}{p.context && p.detail ? " · " : ""}{p.detail}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function useStored<T>(key: string, init: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => { try { const s = localStorage.getItem(key); return s ? JSON.parse(s) : init; } catch { return init; } });
  return [v, (x: T) => { setV(x); try { localStorage.setItem(key, JSON.stringify(x)); } catch {} }];
}

export function Technicals({ s }: { s: RunState }) {
  const t = s.data.technicals;
  const [iv, setIv] = useState("1d");
  const [ovSel, setOvSel] = useStored<string[]>("fa.overlays", ["sma50", "sma200"]);
  const [paneSel, setPaneSel] = useStored<string[]>("fa.panes", ["rsi", "macd"]);
  const [groupSel, setGroupSel] = useStored<string[]>("fa.indgroups", ["Trend", "Momentum"]);
  const [showPicker, setShowPicker] = useState(false);
  if (!t) return <Section name="technicals" status={s.sections.technicals}><div /></Section>;
  const avail = INTERVALS.filter((i) => t.intervals?.[i]);
  const cur = t.intervals?.[iv] || t.intervals?.[avail[0]];
  const bars = rows(t.bars?.[iv] || t.bars?.[avail[0]]);
  const st = t.structure || {};
  const rg = t.regime || {};
  const ind = rows(t.indicator_frame_1d);
  const overlays = useMemo(() => iv === "1d" && ind.length ? OVERLAYS.filter((o) => ovSel.includes(o.key)).flatMap((o) => o.cols.map((c) => ({ name: c, color: o.color, data: ind.map((r: any) => ({ time: r.ts, value: r[c] })) }))) : [], [iv, ind, ovSel]);
  const L = cur?.latest || {};
  const S = cur?.signals || {};
  const toggle = (list: string[], set: (v: string[]) => void, k: string) => set(list.includes(k) ? list.filter((x) => x !== k) : [...list, k]);
  const fmtVal = (k: string, v: any) => (typeof v === "number" ? (k.startsWith("hv_") || k.startsWith("roc") ? pct(v, 1, false) : v.toFixed(Math.abs(v) < 10 ? 3 : 2)) : String(v));
  return (
    <Section name="technicals" status={s.sections.technicals}>
      <div className="grid" style={{ gap: 12 }}>
        <Card title="Chart" sub={<><div className="toggle">{avail.map((i) => <button key={i} className={iv === i ? "on" : ""} onClick={() => setIv(i)}>{i}</button>)}</div> <ProvBadge p={cur?.prov_id} /> {cur?.n_bars} bars · <a style={{ cursor: "pointer" }} onClick={() => setShowPicker(!showPicker)}>{showPicker ? "hide" : "choose indicators"}</a> · <a href={`/api/ticker/${s.symbol}/technicals.xlsx?overlays=${encodeURIComponent(OVERLAYS.filter((o) => ovSel.includes(o.key)).flatMap((o) => o.cols).join(","))}&panes=${encodeURIComponent(PANES.filter((p) => paneSel.includes(p.key)).map((p) => p.cols.join(",")).join("|"))}`}>⬇ Excel (data + charts)</a></>}>
          {showPicker ? (
            <div className="grid g3" style={{ marginBottom: 8 }}>
              <div><div className="muted small" style={{ marginBottom: 4 }}>Overlays on the price chart (daily only)</div>{OVERLAYS.map((o) => <label key={o.key} className="small" style={{ display: "block", cursor: "pointer" }}><input type="checkbox" checked={ovSel.includes(o.key)} onChange={() => toggle(ovSel, setOvSel, o.key)} /> <i style={{ display: "inline-block", width: 10, height: 3, background: o.color, verticalAlign: "middle", marginRight: 4 }} />{o.label}</label>)}</div>
              <div><div className="muted small" style={{ marginBottom: 4 }}>Oscillator panes</div>{PANES.map((p) => <label key={p.key} className="small" style={{ display: "block", cursor: "pointer" }}><input type="checkbox" checked={paneSel.includes(p.key)} onChange={() => toggle(paneSel, setPaneSel, p.key)} /> {p.label}</label>)}</div>
              <div><div className="muted small" style={{ marginBottom: 4 }}>Value table groups</div>{Object.keys(GROUPS).map((g) => <label key={g} className="small" style={{ display: "block", cursor: "pointer" }}><input type="checkbox" checked={groupSel.includes(g)} onChange={() => toggle(groupSel, setGroupSel, g)} /> {g}</label>)}<div className="dim small" style={{ marginTop: 6 }}>Selections are remembered on this browser.</div></div>
            </div>
          ) : null}
          <Candles bars={bars} overlays={overlays} height={420} />
          <div className="legend">{OVERLAYS.filter((o) => ovSel.includes(o.key)).map((o) => <span key={o.key}><i style={{ background: o.color }} />{o.label}</span>)}{iv !== "1d" ? <span className="dim">overlays render on the daily chart</span> : null}</div>
        </Card>
        <SwingPanel pat={t.patterns} />
        {ind.length && paneSel.length ? (
          <div className="grid g2">
            {PANES.filter((p) => paneSel.includes(p.key)).map((p) => (
              <Card key={p.key} title={p.label} sub={<span className="mono">{p.cols.map((c) => `${c} ${fmtVal(c, L[c])}`).join(" · ")}</span>}>
                <Line series={p.cols.map((c, i) => ({ name: c, color: p.colors[i], data: ind.filter((r: any) => isNum(r[c])).map((r: any) => [new Date(r.ts).getTime(), r[c]] as [number, number]) }))} yfmt={p.fmt} zero={!!p.zero} h={160} />
                {p.bands ? <div className="dim small">reference bands {p.bands.join(" / ")}</div> : null}
              </Card>
            ))}
          </div>
        ) : null}
        <div className="grid g4">
          <Card title={`Signals (${iv})`}>
            <div className="kv">{Object.entries(S).map(([k, v]: any) => <React.Fragment key={k}><span>{k}</span><span className={`mono ${["up", "bullish", "above_cloud", true].includes(v) ? "pos" : ["down", "bearish", "below_cloud", "overbought"].includes(v) ? "neg" : ""}`}>{typeof v === "number" ? v.toFixed(2) : String(v)}</span></React.Fragment>)}</div>
          </Card>
          <Card title="Structure (daily)">
            <div className="kv">
              <span>swing trend</span><span>{st.swing_trend}</span>
              <span>resistance</span><span className="mono">{(st.resistance || []).map((r: any) => `${usd(r.level, 1)}×${r.touches}`).join("  ")}</span>
              <span>support</span><span className="mono">{(st.support || []).map((r: any) => `${usd(r.level, 1)}×${r.touches}`).join("  ")}</span>
              <span>volume profile POC / VAH / VAL</span><span className="mono">{usd(st.volume_profile?.poc, 1)} / {usd(st.volume_profile?.vah, 1)} / {usd(st.volume_profile?.val, 1)}</span>
              <span>pivot R1 / P / S1</span><span className="mono">{usd(st.pivots?.r1, 1)} / {usd(st.pivots?.pivot, 1)} / {usd(st.pivots?.s1, 1)}</span>
              <span>anchored VWAP 52w-high / 52w-low / YTD</span><span className="mono">{usd(st.anchored_vwap?.from_52w_high, 1)} / {usd(st.anchored_vwap?.from_52w_low, 1)} / {usd(st.anchored_vwap?.ytd, 1)}</span>
            </div>
          </Card>
          <Card title="Regime">
            <div className="kv">
              <span>trend regime</span><span>{rg.trend_regime} (ADX {num(rg.adx, 0)})</span>
              <span>Hurst</span><span className="mono">{num(rg.hurst)} <span className="dim">{isNum(rg.hurst) ? (rg.hurst > 0.55 ? "trending" : rg.hurst < 0.45 ? "mean-reverting" : "random-walk") : ""}</span></span>
              <span>HV20 percentile (2y)</span><span className="mono">{pct(rg.hv20_percentile_2y, 0, false)} · {rg.regime}</span>
              <span>drawdown / max</span><span className="mono">{pct(rg.drawdown?.current_dd)} / {pct(rg.drawdown?.max_dd)}</span>
              <span>days since high</span><span className="mono">{rg.drawdown?.days_since_high}</span>
              <span>gaps &gt;3% (1y)</span><span className="mono">{rg.gaps?.n_gaps_gt_3pct}</span>
            </div>
          </Card>
          <Card title="Returns">
            <div className="kv">{Object.entries(t.returns || {}).filter(([k]) => k !== "sector_etf").map(([k, v]: any) => <React.Fragment key={k}><span>{k}</span><span className={`mono ${v > 0 ? "pos" : v < 0 ? "neg" : ""}`}>{pct(v)}</span></React.Fragment>)}</div>
          </Card>
        </div>
        <div className="grid g2">
          <Card title={`Indicator values (${iv})`} sub={groupSel.join(" · ") || "choose groups above"}>
            <div className="grid g2">
              {groupSel.map((g) => (
                <div key={g}>
                  <div className="muted small" style={{ textTransform: "uppercase", margin: "4px 0" }}>{g}</div>
                  <table className="tbl"><tbody>{GROUPS[g].filter((k) => L[k] != null).map((k) => <tr key={k}><td>{k}</td><td className="mono">{fmtVal(k, L[k])}</td></tr>)}</tbody></table>
                </div>
              ))}
            </div>
          </Card>
          <Card title="Realized vol cone">
            <Table data={rg.vol_cone} cols={["window", "current", "min", "p10", "p25", "median", "p75", "p90", "max"]} fmt={Object.fromEntries(["current", "min", "p10", "p25", "median", "p75", "p90", "max"].map((k) => [k, (v: any) => pct(v, 0, false)]))} />
          </Card>
        </div>
      </div>
    </Section>
  );
}

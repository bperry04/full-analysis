"""Markdown dossier from an analysis result (the CLI output; the web UI renders the same JSON)."""
from __future__ import annotations

from typing import Any


def _g(d: Any, *path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return cur


def _val(x: Any) -> Any:
    return x.get("v") if isinstance(x, dict) and "v" in x else x


def _pct(x, d=1):
    v = _val(x)
    return "n/a" if v is None else f"{v * 100:+.{d}f}%"


def _num(x, d=2):
    v = _val(x)
    return "n/a" if v is None else f"{v:,.{d}f}"


def to_markdown(res: dict[str, Any]) -> str:
    sym = res["symbol"]
    prof = res.get("profile") or {}
    ov = res.get("overview") or {}
    sc = _g(res, "scores", "horizons", default={}) or {}
    facts = _g(res, "scores", "factors", default={}) or {}
    L = [f"# {sym} — {prof.get('name') or ''}", f"*{prof.get('sector') or ''} · {prof.get('industry') or ''} · run {res['run_id']} · {res['as_of']}*", "",
         f"> {_g(res, 'scores', 'disclaimer', default='')}", ""]
    L.append("## Verdict")
    L.append("| Horizon | Score | Label | Coverage | Confidence |")
    L.append("|---|---|---|---|---|")
    for h in ("long", "medium", "short"):
        x = sc.get(h, {})
        L.append(f"| {h} ({x.get('window', '')}) | {x.get('score') if x.get('score') is not None else '—'} | {x.get('label')} | {x.get('coverage', 0):.0%} | {x.get('confidence', 0):.0%} |")
    for h in ("long", "medium", "short"):
        x = sc.get(h, {})
        L.append(f"\n### {h.title()} drivers")
        for d in (x.get("drivers") or [])[:10]:
            L.append(f"- **{d['label']}** ({d['contribution']:+.1f} pts): {d['narrative']}")
    nar = res.get("narrative") or {}
    if nar:
        L.append("\n## What the company is doing (context, not scored)")
        for h in ("long", "medium", "short"):
            items = nar.get(h) or []
            if items:
                L.append(f"\n**{h}**")
                for it in items[:8]:
                    link = f" [{it['source']}]({it['url']})" if it.get("url") else f" — {it.get('source')}"
                    L.append(f"- *{it['label']}*: {it['title']}{(' — ' + it['detail']) if it.get('detail') else ''}{link} ({it.get('date')})")
    L.append("\n## Overview")
    L.append(f"- Price {_num(ov.get('price'))} ({_pct(ov.get('change_pct'))}) · Mkt cap {_num(ov.get('market_cap'), 0)} · P/E {_num(ov.get('pe'), 1)} · EV/EBITDA {_num(ov.get('ev_ebitda'), 1)} · FCF yield {_pct(ov.get('fcf_yield'))}")
    L.append(f"- IV30 {_pct(ov.get('iv30'))} · IV rank {_pct(ov.get('iv_rank'), 0)} · beta {_num(ov.get('beta'))} · short % float {_pct(ov.get('short_pct_float'))} · next earnings {_val(ov.get('next_earnings'))}")
    L.append(f"- DCF upside {_pct(ov.get('dcf_upside'))} · blended fair value {_num(ov.get('blended_fair_value'))}")
    v = res.get("valuation") or {}
    if v:
        L.append("\n## Valuation")
        inp = v.get("inputs") or {}
        L.append(f"- WACC {_pct(_g(inp, 'wacc', 'value'))} (rf {_pct(_g(inp, 'rf', 'value'))}, beta {_num(_g(inp, 'beta', 'value'))}, ERP {_pct(_g(inp, 'erp', 'value'))}) · stage-1 growth {_pct(_g(inp, 'growth_stage1', 'value'))} · FCF margin {_pct(_g(inp, 'fcf_margin', 'value'))}")
        L.append(f"- DCF {_num(_g(v, 'dcf', 'value_per_share_gordon'))} · FCFE {_num(_g(v, 'fcfe', 'value_per_share'))} · RIM {_num(_g(v, 'rim', 'value_per_share'))} · EPV {_num(_g(v, 'epv', 'value_per_share'))} · comps {_num(_g(v, 'comps', 'blended_implied_price'))} · MC-DCF median {_num(_g(v, 'mc_dcf', 'percentiles', 'p50'))}")
        L.append(f"- Reverse DCF: price implies **{_pct(_g(v, 'reverse_dcf', 'implied_growth'))}** stage-1 growth vs {_pct(_g(inp, 'growth_stage1', 'value'))} delivered")
        bl = v.get("blend") or {}
        if bl.get("available"):
            L.append(f"- Blend ({bl.get('profile')}, {bl.get('n_models_used')} models): **{bl['fair_value']:.2f}** ({bl['upside_pct']:+.1%}), range {bl['low']:.0f}–{bl['high']:.0f}, dispersion {bl['dispersion']:.2f}")
        for m in bl.get("models") or []:
            if m.get("computed"):
                L.append(f"  - {m['label']}: {m['value_per_share']:.2f} ({m['upside_pct']:+.0%}) weight {m['weight']:.0%}" + (" [est.]" if "ESTIMATED" in (m.get("flags") or []) else ""))
            else:
                L.append(f"  - {m['label']}: n/a — {m.get('reason')}")
    f = res.get("fundamentals") or {}
    if f:
        cov = f.get("coverage") or {}
        L.append("\n## Fundamentals")
        L.append(f"- XBRL coverage: {cov.get('resolved')} resolved / {cov.get('formula')} by formula / {cov.get('missing')} missing · FY periods {cov.get('annual_periods')} · Q periods {cov.get('quarterly_periods')} · TTM to {cov.get('ttm_end')}")
        m = f.get("metrics") or {}
        keys = ["gross_margin", "operating_margin", "net_margin", "roic", "roe", "revenue_growth_1y", "revenue_growth_yoy_q", "fcf_margin", "net_debt_to_ebitda", "interest_coverage", "shareholder_yield", "share_count_change_1y"]
        L.append("| Metric | Value | Formula |")
        L.append("|---|---|---|")
        for k in keys:
            x = m.get(k)
            if x and x.get("value") is not None:
                val = f"{x['value']*100:.1f}%" if x.get("unit") == "pct" else f"{x['value']:.2f}{'x' if x.get('unit') == 'x' else ''}"
                L.append(f"| {x['label']} | {val} | `{x['formula']}` |")
        q = f.get("quality") or {}
        L.append(f"- Piotroski {_g(q, 'piotroski', 'score')}/{_g(q, 'piotroski', 'of')} · Altman Z {_g(q, 'altman', 'z')} ({_g(q, 'altman', 'zone')}) · Beneish M {_g(q, 'beneish', 'm')}")
        seg = f.get("segments") or {}
        for b in (seg.get("breakdowns") or {}).values():
            L.append(f"- {b['kind']} mix ({b['period']} to {b['as_of']}): " + ", ".join(f"{x['member']} {x['share']:.0%}" + (f" ({x['yoy']:+.0%} YoY)" if x.get('yoy') is not None else "") for x in b["members"][:6]))
    o = res.get("options") or {}
    if o:
        s = o.get("surface") or {}
        L.append("\n## Options")
        L.append(f"- ATM IV 30/60/90d: {_pct(_g(s, 'atm_iv', 'd30'))} / {_pct(_g(s, 'atm_iv', 'd60'))} / {_pct(_g(s, 'atm_iv', 'd90'))} ({s.get('term_shape')}) · 25Δ RR {_pct(_g(s, 'skew', 'rr25'))} · P/C OI {_num(s.get('put_call_oi'))} · P/C vol {_num(s.get('put_call_vol'))}")
        rank_note = _g(o, "ranks", "flag") or f"{_g(o, 'ranks', 'history_days')}d history"
        L.append(f"- IV rank {_g(o, 'ranks', 'iv_rank')} ({rank_note}) · IV/RV20 {_num(_g(o, 'iv_vs_rv', 'iv_rv_20'))} · max pain {_g(o, 'max_pain', 'max_pain')} ({_g(o, 'max_pain', 'expiry')}) · GEX {_g(o, 'exposure', 'regime')} flip {_num(_g(o, 'exposure', 'gex_flip'), 0)}")
        em = _g(o, "expected_move", "earnings") or {}
        if em.get("available"):
            L.append(f"- Earnings implied move {_pct(em.get('implied_move_pct'))} (front {em.get('front_expiry')}) vs historical avg {_pct(_g(o, 'expected_move', 'realized_earnings', 'mean_abs_move_pct'))}")
    t = res.get("technicals") or {}
    if t:
        sig = _g(t, "intervals", "1d", "signals", default={}) or {}
        L.append("\n## Technicals (daily)")
        L.append(f"- Trend {sig.get('trend_sma')} · MA stack bullish={sig.get('ma_stack_bullish')} · RSI {sig.get('rsi_state')} · MACD {sig.get('macd_state')} · ADX {sig.get('adx_trend')} ({sig.get('di_bias')}) · supertrend {sig.get('supertrend')} · Ichimoku {sig.get('ichimoku')}")
        st = t.get("structure") or {}
        L.append(f"- Support {[round(x['level'], 1) for x in st.get('support', [])]} · resistance {[round(x['level'], 1) for x in st.get('resistance', [])]} · POC {_num(_g(st, 'volume_profile', 'poc'))} · swing {st.get('swing_trend')}")
        rg = t.get("regime") or {}
        L.append(f"- Regime {rg.get('trend_regime')} · HV20 pct {_pct(rg.get('hv20_percentile_2y'), 0)} · Hurst {_num(rg.get('hurst'))} · drawdown {_pct(_g(rg, 'drawdown', 'current_dd'))} (max {_pct(_g(rg, 'drawdown', 'max_dd'))})")
        pat = t.get("patterns") or {}
        su = pat.get("setup") or {}
        if su.get("setup"):
            L.append(f"\n### Swing setup (2–20 days): **{su['setup']}** ({'long' if su.get('direction', 0) > 0 else 'short' if su.get('direction', 0) < 0 else 'no'} bias, quality {_num(su.get('quality'))})")
            for w in su.get("why") or []:
                L.append(f"- {w}")
            pl = su.get("plan") or {}
            if pl.get("entry"):
                L.append(f"- Plan: entry {_num(pl['entry'])} · stop {_num(pl['stop'])} ({_pct(pl['stop_pct'])}) · target {_num(pl['target'])} ({_pct(pl['target_pct'])}) · {_num(pl.get('rr'), 1)}R · option-implied 10d move ±{_pct(su.get('implied_10d_move_pct'), 1)}")
            recent = [p for p in (pat.get("patterns") or []) if p.get("bars_ago", 99) <= 5]
            if recent:
                L.append("- Patterns (last 5 bars): " + "; ".join(f"{p['name']} ({'▲' if p['direction'] > 0 else '▼' if p['direction'] < 0 else '◆'}, {p['date']})" for p in recent[:10]))
    mk = res.get("market") or {}
    if mk:
        L.append("\n## Market & macro")
        L.append(f"- Risk appetite: {_g(mk, 'risk_appetite', 'label')} · VIX {_num(_g(mk, 'vix', 'level'), 1)} ({_g(mk, 'vix', 'regime')}) · VIX term {_g(mk, 'vix_term', 'structure')} · 10y {_num(_g(mk, 'rates', 'dgs10'))} · 10y−3m {_num(_g(mk, 'rates', 'spread_10y_3m'))} · credit 1m {_pct(_g(mk, 'credit', 'ratio_chg_1m'))}")
        sens = _g(res, "risk", "sensitivity", default={}) or {}
        if sens.get("univariate"):
            L.append("- Sensitivities: " + ", ".join(f"{v['name']} β={v['beta']:+.2f} (ρ {v['corr']:+.2f})" for v in sens["univariate"].values()))
    ev = res.get("events") or {}
    if ev.get("events"):
        L.append("\n## Upcoming catalysts")
        for e in ev["events"][:12]:
            L.append(f"- {e['date']} (+{e['days_until']}d) [{e['importance']}] {e['label']}{'' if e['confirmed'] else ' (est.)'}")
    n = res.get("news") or {}
    if n.get("n_stories"):
        L.append("\n## News & sentiment")
        L.append(f"- {n.get('n_stories')} stories · 48h sentiment {_num(_g(n, 'short_term', 'score'))} · 2wk {_num(_g(n, 'medium_term', 'score'))} · positive share {_pct(n.get('positive_share_7d'), 0)}")
        for it in (n.get("items") or [])[:8]:
            L.append(f"- [{it.get('sentiment'):+.2f}] {it.get('title')} — {it.get('publisher')}")
    L.append("\n## Data sources")
    prov = res.get("provenance") or {}
    by = {}
    for p in prov.values():
        by.setdefault(p["provider"], []).append(p)
    for prov_name, recs in sorted(by.items()):
        lat = sorted({r["latency"] for r in recs})
        L.append(f"- **{prov_name}**: {len(recs)} fetches, latency {lat}, cache hits {sum(1 for r in recs if r['from_cache'])}, degraded {sum(1 for r in recs if 'DEGRADED' in r['quality_flags'])}")
    if res.get("warnings"):
        L.append("\n## Warnings")
        for w in res["warnings"][:20]:
            L.append(f"- {w}")
    return "\n".join(L) + "\n"

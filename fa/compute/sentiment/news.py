"""News aggregation: near-duplicate clustering (syndication), source weighting, time-decayed sentiment, volume anomaly."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

from fa.compute.sentiment.lexicon import score

SOURCE_WEIGHT = {
    "reuters": 1.0, "bloomberg": 1.0, "wall street journal": 1.0, "wsj": 1.0, "financial times": 1.0, "cnbc": 0.9, "barron's": 0.9, "barrons": 0.9,
    "associated press": 0.9, "marketwatch": 0.8, "yahoo finance": 0.7, "seeking alpha": 0.6, "motley fool": 0.4, "benzinga": 0.5, "investorplace": 0.4,
    "zacks": 0.5, "simply wall st": 0.4, "globenewswire": 0.6, "pr newswire": 0.6, "business wire": 0.6, "sec_8k": 1.0,
}


def _tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (title or "").lower()) if len(w) > 2}


def cluster(df: pd.DataFrame, threshold: float = 0.6) -> pd.DataFrame:
    """Greedy Jaccard clustering on title tokens; assigns cluster_id and keeps cluster size."""
    d = df.copy().reset_index(drop=True)
    toks = [_tokens(t) for t in d["title"].fillna("")]
    cid = [-1] * len(d)
    reps: list[tuple[int, set[str]]] = []
    for i, tk in enumerate(toks):
        for c, rt in reps:
            inter = len(tk & rt)
            if inter and inter / len(tk | rt) >= threshold:
                cid[i] = c
                break
        if cid[i] == -1:
            cid[i] = len(reps)
            reps.append((cid[i], tk))
    d["cluster_id"] = cid
    d["cluster_size"] = d.groupby("cluster_id")["cluster_id"].transform("size")
    return d


def _weight(publisher: str | None, source: str | None) -> float:
    p = (publisher or "").lower()
    for k, w in SOURCE_WEIGHT.items():
        if k in p:
            return w
    if source == "sec_8k":
        return 1.0
    return 0.5


def relevance(df: pd.DataFrame, symbol: str | None, name: str | None) -> pd.Series:
    """1.0 if the company is named in the title, 0.5 if only in the summary, 0 otherwise (dropped)."""
    keys = [k.lower() for k in (symbol, name) if k]
    short = (name or "").split(" ")[0].lower() if name else None
    if short and len(short) > 3 and short not in ("the",):
        keys.append(short)
    if not keys:
        return pd.Series(1.0, index=df.index)
    def hit(text: Any) -> bool:
        t = str(text or "").lower()
        return any(re.search(rf"\b{re.escape(k)}\b", t) for k in keys)
    title = df["title"].map(hit)
    summ = df.get("summary", pd.Series([None] * len(df), index=df.index)).map(hit)
    src8k = df.get("source", pd.Series([None] * len(df), index=df.index)) == "sec_8k"
    return pd.Series(np.where(title | src8k, 1.0, np.where(summ, 0.5, 0.0)), index=df.index)


def analyze(news: pd.DataFrame, now: datetime | None = None, symbol: str | None = None, name: str | None = None) -> dict[str, Any]:
    if news is None or news.empty:
        return {"n": 0}
    now = now or datetime.now(timezone.utc)
    rel = relevance(news, symbol, name)
    news = news[rel > 0].copy()
    news["relevance"] = rel[rel > 0]
    if news.empty:
        return {"n": 0}
    d = cluster(news)
    d["published"] = pd.to_datetime(d["published"], utc=True, errors="coerce")
    d["age_h"] = (now - d["published"]).dt.total_seconds() / 3600
    d["sentiment"] = [score(f"{t}. {s or ''}") for t, s in zip(d["title"], d.get("summary", pd.Series([None] * len(d))))]
    d["weight"] = [_weight(p, s) * rl for p, s, rl in zip(d.get("publisher"), d.get("source"), d["relevance"])]
    # one vote per cluster: keep the highest-weight item per cluster, credit the cluster size (breadth of coverage)
    rep = d.sort_values("weight", ascending=False).drop_duplicates("cluster_id").copy()
    rep["breadth"] = np.log1p(rep["cluster_size"])
    def agg(half_life_h: float) -> dict[str, float | None]:
        w = rep["weight"] * rep["breadth"] * np.exp(-np.log(2) * rep["age_h"].fillna(24 * 30) / half_life_h)
        s = rep["sentiment"].fillna(0)
        tot = float(w.sum())
        return {"score": float((w * s).sum() / tot) if tot else None, "weight": tot}
    recent_24 = rep[rep["age_h"] <= 24]
    recent_7d = rep[rep["age_h"] <= 24 * 7]
    prior_7d = rep[(rep["age_h"] > 24 * 7) & (rep["age_h"] <= 24 * 14)]
    # RSS feeds are recency-biased, so a volume z-score is only meaningful when the feed genuinely spans two weeks
    vol_z = None
    span_days = float(rep["age_h"].max() / 24) if rep["age_h"].notna().any() else 0.0
    if len(prior_7d) >= 10 and span_days >= 14:
        vol_z = float((len(recent_7d) - len(prior_7d)) / max(np.sqrt(len(prior_7d)), 1.0))
    top = rep.sort_values(["age_h"]).head(40)
    return {
        "n_items": int(len(d)), "n_stories": int(len(rep)), "short_term": agg(48), "medium_term": agg(24 * 14),
        "n_last_24h": int(len(recent_24)), "n_last_7d": int(len(recent_7d)), "n_prior_7d": int(len(prior_7d)), "news_volume_z": vol_z,
        "positive_share_7d": float((recent_7d["sentiment"] > 0.2).mean()) if len(recent_7d) else None,
        "negative_share_7d": float((recent_7d["sentiment"] < -0.2).mean()) if len(recent_7d) else None,
        "items": top[["title", "publisher", "source", "url", "published", "sentiment", "weight", "cluster_size"]],
        "most_negative": rep.sort_values("sentiment").head(5)[["title", "publisher", "published", "sentiment", "url"]],
        "most_positive": rep.sort_values("sentiment", ascending=False).head(5)[["title", "publisher", "published", "sentiment", "url"]],
    }


def social(stocktwits: pd.DataFrame | None, reddit: pd.DataFrame | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if stocktwits is not None and not stocktwits.empty:
        st = stocktwits.copy()
        st["created"] = pd.to_datetime(st["created"], utc=True, errors="coerce")
        tagged = st["sentiment"].dropna()
        bull = int((tagged == "Bullish").sum())
        bear = int((tagged == "Bearish").sum())
        st["text_sent"] = [score(b) for b in st["body"].fillna("")]
        span_h = max((st["created"].max() - st["created"].min()).total_seconds() / 3600, 0.5) if st["created"].notna().any() else None
        out["stocktwits"] = {"n": int(len(st)), "bullish": bull, "bearish": bear, "bull_ratio": bull / (bull + bear) if (bull + bear) else None,
                             "tagged_share": float(len(tagged) / len(st)) if len(st) else None, "text_sentiment": float(st["text_sent"].mean()) if len(st) else None,
                             "msgs_per_hour": float(len(st) / span_h) if span_h else None, "followers_weighted_sent": _fw(st)}
    if reddit is not None and not reddit.empty:
        rd = reddit.copy()
        rd["created"] = pd.to_datetime(rd["created"], utc=True, errors="coerce")
        rd["sent"] = [score(f"{t}. {b}") for t, b in zip(rd["title"], rd["body"].fillna(""))]
        last7 = rd[rd["created"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)]
        prior = rd[(rd["created"] < pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=7)) & (rd["created"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=21))]
        out["reddit"] = {"n": int(len(rd)), "n_last_7d": int(len(last7)), "n_prior_14d_weekly": float(len(prior) / 2) if len(prior) else 0.0,
                         "mention_z": float((len(last7) - len(prior) / 2) / max(np.sqrt(max(len(prior) / 2, 1)), 1)) if len(prior) else None,
                         "sentiment": float(rd["sent"].mean()) if len(rd) else None, "score_weighted_sentiment": float((rd["sent"] * rd["score"].clip(lower=1)).sum() / rd["score"].clip(lower=1).sum()) if len(rd) else None,
                         "top": rd.sort_values("score", ascending=False).head(8)[["title", "subreddit", "score", "comments", "created", "url", "sent"]]}
    return out


def _fw(st: pd.DataFrame) -> float | None:
    m = st["sentiment"].map({"Bullish": 1.0, "Bearish": -1.0})
    w = np.log1p(st["followers"].fillna(0).astype(float))
    ok = m.notna()
    if not ok.any() or w[ok].sum() == 0:
        return None
    return float((m[ok] * w[ok]).sum() / w[ok].sum())

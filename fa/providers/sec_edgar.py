"""SEC EDGAR: XBRL company facts, submissions/filings, ticker map, segment tables, Form 4 insider filings.

All free, no key; the fair-access policy requires a descriptive User-Agent (settings.sec_user_agent) and
<= 10 requests/second (we run 8).
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fa.core import http
from fa.core.errors import NoData, ProviderError
from fa.core.settings import get_settings
from fa.core.types import Latency, Tier
from fa.providers.base import Payload, Provider
from fa.registry import needs as N

log = logging.getLogger(__name__)

BASE = "https://data.sec.gov"
WWW = "https://www.sec.gov"
EFTS = "https://efts.sec.gov/LATEST/search-index"


def _headers() -> dict[str, str]:
    return {"User-Agent": get_settings().sec_user_agent, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"}


def _www_headers() -> dict[str, str]:
    return {"User-Agent": get_settings().sec_user_agent, "Accept-Encoding": "gzip, deflate"}


class SecEdgar(Provider):
    name = "sec_edgar"
    tier = Tier.A
    latency = Latency.FILING
    license_note = "SEC EDGAR public data (fair-access policy)"

    def __init__(self) -> None:
        self._ticker_map: pd.DataFrame | None = None
        self._ticker_map_at = 0.0

    def capabilities(self):
        return {
            N.TICKER_MAP: self.ticker_map,
            N.XBRL_FACTS: self.xbrl_facts,
            N.FILINGS: self.filings,
            N.SEGMENTS: self.segments,
            N.INSIDER_TXNS: self.insider_txns,
        }

    # ------------------------------------------------------------------ ticker map / cik
    async def _load_ticker_map(self) -> pd.DataFrame:
        if self._ticker_map is not None and time.time() - self._ticker_map_at < 6 * 3600:
            return self._ticker_map
        url = f"{WWW}/files/company_tickers.json"
        data = await http.get_json(self.name, url, headers=_www_headers())
        df = pd.DataFrame(list(data.values()))
        df = df.rename(columns={"cik_str": "cik", "title": "name"})
        df["cik"] = df["cik"].astype(int).map(lambda c: f"{c:010d}")
        df["ticker"] = df["ticker"].str.upper()
        self._ticker_map, self._ticker_map_at = df, time.time()
        return df

    async def cik_for(self, symbol: str) -> str:
        symbol = symbol.upper().replace("-", "-")
        df = await self._load_ticker_map()
        hit = df[df["ticker"] == symbol]
        if hit.empty:
            hit = df[df["ticker"] == symbol.replace(".", "-")]
        if hit.empty:
            raise NoData(self.name, f"no CIK for {symbol}")
        return str(hit["cik"].iloc[0])

    async def ticker_map(self, **_: Any) -> Payload:
        df = await self._load_ticker_map()
        return Payload(df, f"{WWW}/files/company_tickers.json", row_count=len(df))

    # ------------------------------------------------------------------ XBRL company facts
    async def xbrl_facts(self, symbol: str | None = None, cik: str | None = None, **_: Any) -> Payload:
        cik = cik or await self.cik_for(symbol or "")
        url = f"{BASE}/api/xbrl/companyfacts/CIK{cik}.json"
        raw = await http.get_bytes(self.name, url, headers=_headers(), timeout=90)
        data = json.loads(raw)
        rows: list[dict] = []
        for taxonomy, tags in (data.get("facts") or {}).items():
            for tag, info in tags.items():
                for unit, pts in (info.get("units") or {}).items():
                    for p in pts:
                        rows.append(
                            {
                                "taxonomy": taxonomy, "tag": tag, "unit": unit,
                                "start": p.get("start"), "end": p.get("end"), "val": p.get("val"),
                                "fy": p.get("fy"), "fp": p.get("fp"), "form": p.get("form"),
                                "filed": p.get("filed"), "accn": p.get("accn"), "frame": p.get("frame"),
                            }
                        )
        if not rows:
            raise NoData(self.name, f"companyfacts empty for CIK{cik}")
        df = pd.DataFrame(rows)
        df["cik"] = cik
        df["entity"] = data.get("entityName")
        for c in ("start", "end", "filed"):
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        df["val"] = pd.to_numeric(df["val"], errors="coerce")
        latest_filed = df["filed"].max()
        as_of = datetime.combine(latest_filed, datetime.min.time(), tzinfo=timezone.utc) if pd.notna(latest_filed) else None
        return Payload(df, url, as_of=as_of, raw=raw, row_count=len(df), meta={"cik": cik, "entity": data.get("entityName")})

    # ------------------------------------------------------------------ submissions / filings
    async def _submissions(self, cik: str) -> dict:
        url = f"{BASE}/submissions/CIK{cik}.json"
        return await http.get_json(self.name, url, headers=_headers(), timeout=60)

    async def filings(self, symbol: str | None = None, cik: str | None = None, **_: Any) -> Payload:
        cik = cik or await self.cik_for(symbol or "")
        sub = await self._submissions(cik)
        rec = sub.get("filings", {}).get("recent", {})
        df = pd.DataFrame(
            {
                "form": rec.get("form", []), "filed": rec.get("filingDate", []),
                "report_date": rec.get("reportDate", []), "accn": rec.get("accessionNumber", []),
                "primary_doc": rec.get("primaryDocument", []), "description": rec.get("primaryDocDescription", []),
                "items": rec.get("items", []), "is_xbrl": rec.get("isXBRL", []),
            }
        )
        df["filed"] = pd.to_datetime(df["filed"], errors="coerce").dt.date
        df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.date
        df["url"] = [
            f"{WWW}/Archives/edgar/data/{int(cik)}/{a.replace('-', '')}/{d}" for a, d in zip(df["accn"], df["primary_doc"])
        ]
        meta = {
            "cik": cik, "name": sub.get("name"), "sic": sub.get("sic"), "sic_description": sub.get("sicDescription"),
            "fiscal_year_end": sub.get("fiscalYearEnd"), "state_of_inc": sub.get("stateOfIncorporation"),
            "category": sub.get("category"), "tickers": sub.get("tickers"), "exchanges": sub.get("exchanges"),
            "ein": sub.get("ein"), "website": sub.get("website"), "entity_type": sub.get("entityType"),
            "former_names": [n.get("name") for n in sub.get("formerNames", [])][:5],
        }
        as_of = None
        if len(df):
            as_of = datetime.combine(df["filed"].max(), datetime.min.time(), tzinfo=timezone.utc)
        return Payload({"meta": meta, "filings": df}, f"{BASE}/submissions/CIK{cik}.json", as_of=as_of, raw=sub, row_count=len(df))

    # ------------------------------------------------------------------ segments (R-files route)
    async def segments(self, symbol: str | None = None, cik: str | None = None, max_filings: int = 5, **_: Any) -> Payload:
        """Segment / geographic tables parsed from the rendered R-files of recent 10-K/10-Q filings.

        companyfacts has no dimensional data, so this is the on-demand route. Output is long-form:
        accn, form, period_end, report, line_item, member, period, value.
        """
        cik = cik or await self.cik_for(symbol or "")
        sub = await self._submissions(cik)
        rec = sub.get("filings", {}).get("recent", {})
        forms, accns, dates = rec.get("form", []), rec.get("accessionNumber", []), rec.get("reportDate", [])
        picks = [(f, a, d) for f, a, d in zip(forms, accns, dates) if f in ("10-K", "10-Q", "20-F")][:max_filings]
        rows: list[dict] = []
        endpoints: list[str] = []
        for form, accn, rdate in picks:
            folder = f"{WWW}/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}"
            try:
                summary = await http.get_text(self.name, f"{folder}/FilingSummary.xml", headers=_www_headers(), timeout=60)
            except Exception:
                continue
            reports = re.findall(r"<Report[^>]*>(.*?)</Report>", summary, flags=re.S)
            for rep in reports:
                sn = re.search(r"<ShortName>(.*?)</ShortName>", rep, flags=re.S)
                fn = re.search(r"<HtmlFileName>(.*?)</HtmlFileName>", rep, flags=re.S)
                if not sn or not fn:
                    continue
                name = sn.group(1).strip()
                if "(Details)" not in name or not re.search(r"segment|geograph|disaggregat", name, flags=re.I):
                    continue
                url = f"{folder}/{fn.group(1).strip()}"
                try:
                    html = await http.get_text(self.name, url, headers=_www_headers(), timeout=60)
                    tables = pd.read_html(io.StringIO(html))
                except Exception:
                    continue
                endpoints.append(url)
                for t in tables:
                    rows.extend(_long_form_rfile(t, accn, form, rdate, name))
        if not rows:
            raise NoData(self.name, "no segment detail tables found in recent filings")
        df = pd.DataFrame(rows)
        return Payload(df, endpoints[0] if endpoints else f"{BASE}/submissions/CIK{cik}.json", row_count=len(df),
                       flags=["PROXY"], meta={"tables": len(endpoints)})

    # ------------------------------------------------------------------ Form 4 insider transactions
    async def insider_txns(self, symbol: str | None = None, cik: str | None = None, max_filings: int = 15, **_: Any) -> Payload:
        cik = cik or await self.cik_for(symbol or "")
        sub = await self._submissions(cik)
        rec = sub.get("filings", {}).get("recent", {})
        picks = [
            (a, d, p) for f, a, d, p in zip(rec.get("form", []), rec.get("accessionNumber", []), rec.get("filingDate", []), rec.get("primaryDocument", []))
            if f == "4"
        ][:max_filings]
        rows: list[dict] = []
        for accn, filed, primary in picks:
            folder = f"{WWW}/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}"
            try:
                idx = await http.get_json(self.name, f"{folder}/index.json", headers=_www_headers(), timeout=30)
                xml_name = next((i["name"] for i in idx["directory"]["item"] if i["name"].lower().endswith(".xml") and "primary_doc" not in i["name"].lower()), None)
                if not xml_name:
                    xml_name = next((i["name"] for i in idx["directory"]["item"] if i["name"].lower().endswith(".xml")), None)
                if not xml_name:
                    continue
                xml = await http.get_text(self.name, f"{folder}/{xml_name}", headers=_www_headers(), timeout=30)
            except Exception:
                continue
            rows.extend(_parse_form4(xml, accn, filed))
        if not rows:
            raise NoData(self.name, "no Form 4 transactions parsed")
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        return Payload(df, f"{BASE}/submissions/CIK{cik}.json", row_count=len(df))


def _long_form_rfile(t: pd.DataFrame, accn: str, form: str, rdate: str, report: str) -> list[dict]:
    out: list[dict] = []
    if t.shape[1] < 2:
        return out
    cols = [" | ".join(str(x) for x in c if "Unnamed" not in str(x)) if isinstance(c, tuple) else str(c) for c in t.columns]
    first = t.columns[0]
    axis: str | None = None
    member: str | None = None
    for _, r in t.iterrows():
        label = str(r[first]).strip()
        vals = [r[c] for c in t.columns[1:]]
        if all(pd.isna(v) or str(v).strip() == "" for v in vals):
            # header rows: "Product [Axis]" -> "iPhone [Member]" -> "Disaggregation of Revenue [Line Items]"
            if "[Axis]" in label:
                axis, member = label.replace("[Axis]", "").strip(), None
            elif "[Member]" in label:
                member = label.replace("[Member]", "").strip()
            elif "[Line Items]" in label or "[Abstract]" in label or "[Domain]" in label:
                pass
            else:
                member = label
            continue
        for c, v in zip(cols[1:], vals):
            if pd.isna(v):
                continue
            x = _num_cell(v)
            if x is None:
                continue
            out.append(
                {"accn": accn, "form": form, "period_end": rdate, "report": report, "line_item": label,
                 "axis": axis, "member": member, "period": c, "value": x}
            )
    return out


def _num_cell(v: Any) -> float | None:
    s = str(v).replace("$", "").replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").strip()
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _parse_form4(xml: str, accn: str, filed: str) -> list[dict]:
    out: list[dict] = []
    owner = re.search(r"<rptOwnerName>(.*?)</rptOwnerName>", xml, flags=re.S)
    title = re.search(r"<officerTitle>(.*?)</officerTitle>", xml, flags=re.S)
    is_dir = "<isDirector>1</isDirector>" in xml or "<isDirector>true</isDirector>" in xml
    for block in re.findall(r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", xml, flags=re.S):
        def g(tag: str) -> str | None:
            m = re.search(rf"<{tag}>\s*(?:<value>)?(.*?)(?:</value>)?\s*</{tag}>", block, flags=re.S)
            return m.group(1).strip() if m else None
        out.append(
            {
                "accn": accn, "filed": filed, "insider": (owner.group(1).strip() if owner else None),
                "title": (title.group(1).strip() if title else ("Director" if is_dir else None)),
                "date": g("transactionDate"), "code": g("transactionCode"),
                "shares": _num_cell(g("transactionShares") or ""), "price": _num_cell(g("transactionPricePerShare") or ""),
                "acq_disp": g("transactionAcquiredDisposedCode"),
                "shares_after": _num_cell(g("sharesOwnedFollowingTransaction") or ""),
                "security": g("securityTitle"),
            }
        )
    return out


PROVIDER = SecEdgar()

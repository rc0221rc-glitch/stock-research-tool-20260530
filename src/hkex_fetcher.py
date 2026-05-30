from __future__ import annotations

from typing import Any

from .utils import LinkResult, dedupe_links, request_json


HKEX_TYPE_MAP = {
    "annual": "ANNUAL_RPT",
    "quarterly": "INTERIM_RPT",
    "prospectus": "PROSPECTUS",
}


def fetch_hkex_filings(stock_code: str, kinds: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    code = "".join(ch for ch in str(stock_code or "") if ch.isdigit()).zfill(4)
    if not code:
        return []
    selected = kinds or ["annual"]
    links: list[LinkResult] = []
    for kind in selected:
        filing_type = HKEX_TYPE_MAP.get(kind)
        if not filing_type:
            continue
        url = f"https://www1.hkexnews.hk/app/handler/filingHandler.ashx?lang=E&stock={code}&type={filing_type}&size={limit}"
        try:
            data = request_json(url, timeout=10)
        except Exception:
            continue
        rows = data.get("data") or data.get("result") or []
        if isinstance(rows, dict):
            rows = rows.get("data", [])
        for row in rows[:limit]:
            file_link = row.get("file_link") or row.get("url") or row.get("FILE_LINK") or ""
            if not file_link:
                continue
            full_url = file_link if file_link.startswith("http") else f"https://www1.hkexnews.hk{file_link}"
            title = row.get("title") or row.get("headline") or row.get("TITLE") or f"{code} {filing_type}"
            date = row.get("date_time") or row.get("date") or row.get("DATE_TIME") or ""
            links.append(LinkResult(title=title, url=full_url, source="港交所披露易", date=date, kind=kind, is_direct_file=True))
    return dedupe_links(links)

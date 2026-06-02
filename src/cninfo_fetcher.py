from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from .utils import DEFAULT_HEADERS, LinkResult, dedupe_links


CNINFO_BASE = "https://www.cninfo.com.cn"
CNINFO_STATIC_BASE = "https://static.cninfo.com.cn"
CNINFO_HEADERS = {
    **DEFAULT_HEADERS,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Referer": "https://www.cninfo.com.cn/new/index",
    "Origin": "https://www.cninfo.com.cn",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

CATEGORY_MAP = {
    "annual": ["category_ndbg_szsh"],
    "quarterly": ["category_yjdbg_szsh", "category_bndbg_szsh", "category_sjdbg_szsh"],
}

QUARTER_TITLE_TOKENS = {
    "Q1": ["第一季度", "一季度"],
    "Q2": ["半年度", "中期", "二季度"],
    "Q3": ["第三季度", "三季度"],
    "Q4": ["年度报告", "年报"],
    "全年": ["年度报告", "年报"],
}


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(CNINFO_HEADERS)
    try:
        session.get(f"{CNINFO_BASE}/new/index", timeout=10)
    except Exception:
        pass
    return session


def _market_is_china_a(company: dict[str, Any]) -> bool:
    market = str(company.get("market", ""))
    exchange = str(company.get("exchange", ""))
    country = str(company.get("country", ""))
    code = _stock_code(company)
    if market in {"A股", "沪深"}:
        return True
    if any(token in exchange.upper() for token in ["SSE", "SZSE", "STAR"]):
        return True
    return "中国" in country and bool(code) and code[:1] in {"0", "2", "3", "6", "8", "9"}


def _stock_code(company: dict[str, Any]) -> str:
    candidates = [
        company.get("local_code"),
        company.get("ticker"),
        *(company.get("aliases") or [] if isinstance(company.get("aliases"), list) else []),
    ]
    for value in candidates:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if len(digits) == 6:
            return digits
    return ""


def _exchange_for_code(code: str) -> str:
    if code.startswith(("6", "9")):
        return "SSE"
    if code.startswith(("0", "2", "3")):
        return "SZSE"
    if code.startswith(("4", "8")):
        return "BJSE"
    return "CNINFO"


def _ticker_for_code(code: str) -> str:
    exchange = _exchange_for_code(code)
    suffix = {"SSE": ".SH", "SZSE": ".SZ", "BJSE": ".BJ"}.get(exchange, "")
    return f"{code}{suffix}" if suffix else code


CNINFO_KNOWN_ENGLISH_ALIASES = {
    "zhongji innolight": "中际旭创",
    "innolight": "中际旭创",
    "eoptolink": "新易盛",
    "tfc communication": "天孚通信",
    "tianfu communication": "天孚通信",
}

CNINFO_KNOWN_ALIASES_BY_NAME = {
    "中际旭创": ["Zhongji Innolight", "Innolight"],
    "新易盛": ["Eoptolink"],
    "天孚通信": ["TFC Communication", "Tianfu Communication"],
}


def search_cninfo_companies(query: str, limit: int = 8) -> list[dict[str, Any]]:
    original_keyword = (query or "").strip()
    keyword = original_keyword
    if not keyword:
        return []
    keyword = CNINFO_KNOWN_ENGLISH_ALIASES.get(keyword.casefold(), keyword)
    session = _session()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _top_search(session, keyword):
        code = str(row.get("code") or "").strip()
        name = str(row.get("zwjc") or row.get("secName") or "").strip()
        if not code or not name or code in seen:
            continue
        category = str(row.get("category") or "")
        if category and category != "A股":
            continue
        exchange = _exchange_for_code(code)
        ticker = _ticker_for_code(code)
        aliases = [
            name,
            code,
            ticker,
            str(row.get("pinyin") or "").strip(),
            *CNINFO_KNOWN_ALIASES_BY_NAME.get(name, []),
            original_keyword if original_keyword != keyword else "",
        ]
        results.append(
            {
                "name": name,
                "name_en": name,
                "ticker": ticker,
                "local_code": code,
                "market": "A股",
                "exchange": exchange,
                "country": "中国",
                "flag": "🇨🇳",
                "ir_url": f"{CNINFO_BASE}/new/disclosure/stock?stockCode={code}",
                "cik": "",
                "aliases": [alias for alias in aliases if alias],
                "source": "巨潮资讯公司搜索",
            }
        )
        seen.add(code)
        if len(results) >= limit:
            break
    return results


def _top_search(session: requests.Session, keyword: str) -> list[dict[str, Any]]:
    if not keyword:
        return []
    try:
        response = session.post(
            f"{CNINFO_BASE}/new/information/topSearch/query",
            data={"keyWord": keyword, "maxNum": 10},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _resolve_security(session: requests.Session, company: dict[str, Any]) -> tuple[str, str, str]:
    code = _stock_code(company)
    keywords = [code, company.get("name"), company.get("name_en")]
    for keyword in [str(item or "").strip() for item in keywords if item]:
        for row in _top_search(session, keyword):
            row_code = str(row.get("code") or "")
            org_id = str(row.get("orgId") or "")
            short_name = str(row.get("zwjc") or row.get("secName") or "")
            if code and row_code != code:
                continue
            if row_code and org_id:
                return row_code, org_id, short_name
    return code, "", str(company.get("name") or company.get("name_en") or "")


def _selected_categories(kinds: list[str] | None) -> list[str]:
    selected = set(kinds or ["annual"])
    categories: list[str] = []
    for kind in ["annual", "quarterly"]:
        if kind in selected:
            categories.extend(CATEGORY_MAP[kind])
    return categories


def _date_range(years: list[str] | None) -> str:
    numeric_years = sorted({int(year) for year in years or [] if str(year).isdigit()})
    if not numeric_years:
        end_year = datetime.now().year + 1
        start_year = end_year - 20
    else:
        start_year = min(numeric_years)
        end_year = max(numeric_years) + 1
    return f"{start_year}-01-01~{end_year}-12-31"


def _announcement_year(item: dict[str, Any]) -> str:
    title = str(item.get("announcementTitle") or item.get("shortTitle") or "")
    for index in range(len(title) - 3):
        piece = title[index : index + 4]
        if piece.isdigit() and piece.startswith("20"):
            return piece
    timestamp = item.get("announcementTime")
    if isinstance(timestamp, (int, float)):
        try:
            return datetime.fromtimestamp(timestamp / 1000).strftime("%Y")
        except Exception:
            return ""
    return ""


def _matches_year(item: dict[str, Any], years: list[str] | None) -> bool:
    selected = {str(year) for year in years or [] if str(year).isdigit()}
    if not selected:
        return True
    year = _announcement_year(item)
    return not year or year in selected


def _matches_quarter(item: dict[str, Any], quarters: list[str] | None, kind: str) -> bool:
    if kind != "quarterly":
        return True
    selected = [quarter for quarter in (quarters or []) if quarter]
    if not selected or "全年" in selected:
        return True
    title = str(item.get("announcementTitle") or item.get("shortTitle") or "")
    tokens = []
    for quarter in selected:
        tokens.extend(QUARTER_TITLE_TOKENS.get(quarter, [quarter]))
    return not tokens or any(token in title for token in tokens)


def _kind_from_title(title: str) -> str:
    if any(token in title for token in ["第一季度", "一季度", "第三季度", "三季度", "半年度", "中期"]):
        return "quarterly"
    return "annual"


def _query_announcements(
    session: requests.Session,
    code: str,
    org_id: str,
    categories: list[str],
    years: list[str] | None,
    page_size: int,
) -> list[dict[str, Any]]:
    if not code or not org_id or not categories:
        return []
    payload = {
        "stock": f"{code},{org_id}",
        "tabName": "fulltext",
        "pageSize": str(page_size),
        "pageNum": "1",
        "column": "",
        "category": ";".join(categories),
        "plate": "",
        "seDate": _date_range(years),
        "searchkey": "",
        "secid": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    try:
        response = session.post(f"{CNINFO_BASE}/new/hisAnnouncement/query", data=payload, timeout=12)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    rows = data.get("announcements") if isinstance(data, dict) else []
    return rows or []


def fetch_cninfo_filings(
    company: dict[str, Any],
    kinds: list[str] | None = None,
    years: list[str] | None = None,
    quarters: list[str] | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    if not _market_is_china_a(company):
        return []
    categories = _selected_categories(kinds)
    if not categories:
        return []
    session = _session()
    code, org_id, short_name = _resolve_security(session, company)
    if not code or not org_id:
        return []

    results: list[LinkResult] = []
    rows = _query_announcements(session, code, org_id, categories, years, page_size=max(limit, 30))
    selected_kinds = set(kinds or [])
    for item in rows:
        title = str(item.get("announcementTitle") or item.get("shortTitle") or f"{short_name} 公告")
        url_path = str(item.get("adjunctUrl") or "")
        if not url_path or not url_path.casefold().endswith(".pdf"):
            continue
        kind = _kind_from_title(title)
        if selected_kinds and kind not in selected_kinds:
            continue
        if not _matches_year(item, years):
            continue
        if not _matches_quarter(item, quarters, kind):
            continue
        direct_url = url_path if url_path.startswith("http") else f"{CNINFO_STATIC_BASE}/{url_path.lstrip('/')}"
        year = _announcement_year(item)
        results.append(
            LinkResult(
                title=title,
                url=direct_url,
                source="巨潮资讯官方公告",
                date=year,
                form=kind,
                kind=kind,
                index_url=f"{CNINFO_BASE}/new/disclosure/detail?stockCode={code}&announcementId={item.get('announcementId')}",
                is_direct_file=True,
                note=f"{code} {short_name}".strip(),
            )
        )
        if len(results) >= limit:
            break
    return dedupe_links(results)

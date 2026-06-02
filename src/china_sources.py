from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

from .utils import LinkResult, dedupe_links, request_text, run_limited, search_url


CHINA_MARKETS = {"港股", "A股", "沪深"}
CHINA_KEYWORDS = ["中国", "香港", "台股", "中芯", "腾讯", "阿里", "百度", "京东", "理想", "小鹏", "比亚迪"]
CHINA_ENGLISH_MARKERS = ["china", "hong kong", "taiwan", "shanghai", "shenzhen", "smic", "tsmc"]


def is_china_company(company: dict[str, Any]) -> bool:
    market = str(company.get("market", ""))
    country = str(company.get("country", ""))
    name = f"{company.get('name', '')} {company.get('name_en', '')} {company.get('ticker', '')} {company.get('description', '')}"
    text = f"{market} {country} {name}"
    lowered = text.casefold()
    return (
        market in CHINA_MARKETS
        or "中国" in country
        or any(keyword in text for keyword in CHINA_KEYWORDS)
        or any(marker in lowered for marker in CHINA_ENGLISH_MARKERS)
    )


def _extract_ddg_url(href: str) -> str:
    if "duckduckgo.com" not in href.casefold():
        return href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    return params.get("uddg", [""])[0]


def _duckduckgo_search(query: str, source: str, kind: str, limit: int = 6) -> list[LinkResult]:
    try:
        html = request_text(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", timeout=8)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results: list[LinkResult] = []
    for item in soup.select(".result")[:limit]:
        link = item.select_one(".result__a")
        if not link:
            continue
        url = _extract_ddg_url(link.get("href") or "")
        title = link.get_text(" ", strip=True)
        if not url or not title:
            continue
        if "duckduckgo.com/y.js" in url.casefold() or "ad_domain=" in url.casefold():
            continue
        results.append(LinkResult(title=title, url=url, source=source, kind=kind, is_direct_file=url.casefold().endswith(".pdf")))
    return results


def _sogou_wechat_link(query: str, kind: str) -> LinkResult:
    url = f"https://weixin.sogou.com/weixin?type=2&query={quote_plus(query)}"
    return LinkResult(title=f"微信文章搜索：{query}", url=url, source="微信公众号搜索", kind=kind, is_direct_file=False, note="打开后可查看公众号纪要、券商整理和会议记录。")


def _wechat_site_search_link(query: str, kind: str) -> LinkResult:
    return LinkResult(
        title=f"微信公众号站内搜索：{query}",
        url=search_url(f"site:mp.weixin.qq.com {query}"),
        source="微信公众号搜索",
        kind=kind,
        is_direct_file=False,
        note="备用入口：搜索 mp.weixin.qq.com 公开文章。",
    )


def _general_search_link(query: str, source: str, kind: str) -> LinkResult:
    return LinkResult(title=f"{source}：{query}", url=search_url(query), source=source, kind=kind, is_direct_file=False)


def _build_queries(company: dict[str, Any], kinds: list[str] | None = None, years: list[str] | None = None, quarters: list[str] | None = None) -> list[tuple[str, str, str]]:
    name = company.get("name") or company.get("name_en") or ""
    english = company.get("name_en") or ""
    ticker = company.get("ticker") or ""
    local_code = company.get("local_code") or ""
    aliases = [str(item) for item in [name, english, ticker, local_code] if item]
    base_name = " ".join(dict.fromkeys(aliases[:3]))
    selected = set(kinds or [])
    years = years or []
    quarters = [q for q in (quarters or []) if q and q != "全年"]
    date_terms = []
    if years:
        date_terms.extend(years[:6])
    if quarters:
        date_terms.extend(quarters)
    date_text = " ".join(date_terms[:4])
    queries: list[tuple[str, str, str]] = []
    if not selected or "transcript" in selected:
        for suffix in ["业绩会纪要", "业绩说明会纪要", "电话会纪要", "交流纪要", "调研纪要", "投资者交流纪要"]:
            queries.append((f"{name} {suffix} {date_text}".strip(), "中文纪要搜索", "transcript"))
        queries.extend(
            [
                (f"site:mp.weixin.qq.com {name} 业绩会纪要 {date_text}".strip(), "微信公众号文章", "transcript"),
                (f"site:mp.weixin.qq.com {name} 电话会纪要 {date_text}".strip(), "微信公众号文章", "transcript"),
                (f"site:xueqiu.com {name} 业绩会纪要 {date_text}".strip(), "雪球搜索", "transcript"),
                (f"site:eastmoney.com {name} 业绩说明会 {date_text}".strip(), "东方财富搜索", "transcript"),
            ]
        )
    if not selected or "presentation" in selected:
        queries.extend(
            [
                (f"{base_name} 业绩演示 材料 PDF {date_text}".strip(), "中文演示材料搜索", "presentation"),
                (f"{base_name} 路演材料 PDF {date_text}".strip(), "中文演示材料搜索", "presentation"),
                (f"{base_name} investor presentation pdf {date_text}".strip(), "中文演示材料搜索", "presentation"),
            ]
        )
    if not selected or selected.intersection({"annual", "quarterly"}):
        queries.extend(
            [
                (f"{name} 年报 PDF {date_text}".strip(), "中文公告搜索", "IR"),
                (f"{name} 季报 中报 PDF {date_text}".strip(), "中文公告搜索", "IR"),
                (f"{local_code} {name} 公告 PDF {date_text}".strip(), "中文公告搜索", "IR"),
            ]
        )
    return queries


def find_china_research_links(
    company: dict[str, Any],
    kinds: list[str] | None = None,
    years: list[str] | None = None,
    quarters: list[str] | None = None,
    max_results: int = 24,
) -> list[dict[str, Any]]:
    if not is_china_company(company):
        return []
    queries = _build_queries(company, kinds=kinds, years=years, quarters=quarters)
    jobs = [(_duckduckgo_search, (query, source, kind, 4), {}) for query, source, kind in queries[:10]]
    results: list[LinkResult] = []
    for group in run_limited(jobs, per_job_timeout=6, total_timeout=18, max_workers=5):
        if isinstance(group, list):
            results.extend(group)
        if len(results) >= max_results:
            break

    name = company.get("name") or company.get("name_en") or ""
    years_text = " ".join((years or [])[:3])
    if not kinds or "transcript" in kinds:
        wechat_queries = [
            f"{name} 业绩会纪要 {years_text}".strip(),
            f"{name} 电话会纪要 {years_text}".strip(),
            f"{name} 交流纪要 {years_text}".strip(),
        ]
        results.extend(_sogou_wechat_link(query, "transcript") for query in wechat_queries)
        results.extend(_wechat_site_search_link(query, "transcript") for query in wechat_queries[:2])
    if not results:
        results.append(_general_search_link(f"{name} 业绩会纪要 微信公众号", "中文投研搜索", "transcript"))
    return dedupe_links(results)[:max_results]

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

from .utils import LinkResult, dedupe_links, request_text, run_limited, search_url


TRANSCRIPT_SOURCES = [
    ("Seeking Alpha", "site:seekingalpha.com/article {query} earnings call transcript"),
    ("Motley Fool", "site:fool.com/earnings/call-transcripts {query} earnings call transcript"),
    ("Stock Analysis", "site:stockanalysis.com/stocks {query} earnings transcripts"),
    ("MarketScreener", "site:marketscreener.com {query} transcript earnings call"),
    ("AlphaSpread", "site:alphaspread.com {query} earnings call transcript"),
    ("GuruFocus", "site:gurufocus.com {query} earnings call transcript"),
    ("MarketBeat", "site:marketbeat.com {query} earnings call transcript"),
    ("Investing.com", "site:investing.com {query} earnings call transcript"),
    ("AlphaStreet", "site:alphastreet.com {query} earnings call transcript"),
    ("Morningstar", "site:morningstar.com {query} earnings transcript"),
    ("Tikr", "site:tikr.com {query} transcript earnings"),
    ("Koyfin", "site:koyfin.com {query} transcript earnings"),
    ("BamSEC", "site:bamsec.com {query} transcript"),
    ("Quartr", "site:quartr.com {query} earnings call"),
    ("EarningsCall", "site:earningscall.biz {query} transcript"),
    ("BusinessWire", "site:businesswire.com {query} earnings conference call transcript"),
    ("GlobeNewswire", "site:globenewswire.com {query} conference call transcript"),
    ("PR Newswire", "site:prnewswire.com {query} earnings conference call transcript"),
]

PRESENTATION_SOURCES = [
    ("公司官网 PDF", "site:{domain} {query} earnings presentation slides filetype:pdf"),
    ("公司官网 Events", "site:{domain} {query} events presentations investor relations"),
    ("Q4 IR", "site:q4cdn.com {query} earnings presentation filetype:pdf"),
    ("Notified IR", "site:notifications.cision.com {query} presentation filetype:pdf"),
    ("EQS IR", "site:eqs-news.com {query} presentation filetype:pdf"),
    ("Investis", "site:investis.com {query} presentation filetype:pdf"),
    ("Euroland", "site:euroland.com {query} presentation filetype:pdf"),
    ("Webcasting", "site:webcast-eqs.com {query} presentation"),
    ("Webcast Center", "site:webcast.openbriefing.com {query} presentation"),
    ("BusinessWire", "site:businesswire.com {query} investor presentation filetype:pdf"),
    ("GlobeNewswire", "site:globenewswire.com {query} presentation filetype:pdf"),
    ("PR Newswire", "site:prnewswire.com {query} presentation filetype:pdf"),
    ("SlideShare", "site:slideshare.net {query} investor presentation"),
    ("DocSend", "site:docsend.com {query} investor presentation"),
    ("SEC Exhibit", "site:sec.gov/Archives/edgar/data {query} ex-99 presentation"),
]

CHINA_PLATFORM_SOURCES = [
    ("微信公众号", "site:mp.weixin.qq.com {query} 业绩会纪要"),
    ("微信公众号", "site:mp.weixin.qq.com {query} 电话会纪要"),
    ("雪球", "site:xueqiu.com {query} 业绩会纪要"),
    ("东方财富", "site:eastmoney.com {query} 投资者关系活动记录"),
    ("同花顺公告", "site:notice.10jqka.com.cn {query} 投资者关系活动记录"),
    ("巨潮 PDF", "site:static.cninfo.com.cn {query} PDF"),
    ("华尔街见闻", "site:wallstreetcn.com {query} 电话会纪要"),
    ("格隆汇", "site:gelonghui.com {query} 业绩会"),
    ("富途牛牛", "site:futunn.com {query} 业绩会"),
    ("老虎社区", "site:laohu8.com {query} 业绩会"),
]


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return (parsed.netloc or parsed.path).replace("www.", "").strip("/")


def _extract_search_url(href: str) -> str:
    if "duckduckgo.com" in href.casefold():
        parsed = urlparse(href)
        return parse_qs(parsed.query).get("uddg", [""])[0]
    return href


def _search(query: str, source: str, kind: str, limit: int = 4) -> list[LinkResult]:
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
        url = _extract_search_url(link.get("href") or "")
        title = link.get_text(" ", strip=True)
        if not url or not title:
            continue
        lower_url = url.casefold()
        if "duckduckgo.com/y.js" in lower_url or "ad_domain=" in lower_url:
            continue
        if kind == "presentation" and not any(token in f"{title} {url}".casefold() for token in ["presentation", "slides", "deck", "results", "webcast", ".pdf"]):
            continue
        if kind == "transcript" and not any(token in f"{title} {url}".casefold() for token in ["transcript", "earnings call", "conference call", "业绩会", "电话会", "纪要", "investor relations"]):
            continue
        results.append(LinkResult(title=title, url=url, source=source, kind=kind, is_direct_file=".pdf" in lower_url))
    return results


def _platform_entry_links(query: str, kind: str) -> list[LinkResult]:
    if kind == "transcript":
        entries = [
            ("Quartr 搜索入口", f"https://quartr.com/search?query={quote_plus(query)}"),
            ("TIKR 搜索入口", f"https://app.tikr.com/search?query={quote_plus(query)}"),
            ("Koyfin 搜索入口", f"https://app.koyfin.com/search?q={quote_plus(query)}"),
            ("BamSEC 搜索入口", f"https://www.bamsec.com/search?q={quote_plus(query)}"),
        ]
    else:
        entries = [
            ("Quartr 演示材料入口", f"https://quartr.com/search?query={quote_plus(query + ' presentation')}"),
            ("SlideShare 搜索入口", f"https://www.slideshare.net/search/slideshow?searchfrom=header&q={quote_plus(query + ' investor presentation')}"),
            ("DocSend 搜索入口", f"https://www.google.com/search?q={quote_plus('site:docsend.com ' + query + ' investor presentation')}"),
        ]
    return [LinkResult(title, url, "平台入口", kind=kind, is_direct_file=False, note="该平台可能需要登录或存在访问限制。") for title, url in entries]


def discover_platform_links(
    company: dict[str, Any],
    kinds: list[str] | None = None,
    years: list[str] | None = None,
    quarters: list[str] | None = None,
    max_results: int = 28,
) -> list[dict[str, Any]]:
    selected = set(kinds or [])
    name = company.get("name") or ""
    english = company.get("name_en") or ""
    ticker = company.get("ticker") or company.get("local_code") or ""
    is_china = str(company.get("market", "")) in {"港股", "A股", "沪深"} or "中国" in str(company.get("country", ""))
    query = (name or " ".join(part for part in [english, ticker] if part)).strip() if is_china else " ".join(part for part in [english or name, ticker] if part).strip()
    if not query:
        return []
    date_text = " ".join([*(years or [])[:3], *(quarters or [])[:2]])
    query_with_date = f"{query} {date_text}".strip()
    domain = _extract_domain(company.get("ir_url", ""))

    jobs = []
    if not selected or "transcript" in selected:
        for source, template in TRANSCRIPT_SOURCES[:14]:
            jobs.append((_search, (template.format(query=query_with_date), source, "transcript", 3), {}))
    if not selected or "presentation" in selected:
        for source, template in PRESENTATION_SOURCES[:12]:
            if "{domain}" in template and not domain:
                continue
            jobs.append((_search, (template.format(query=query_with_date, domain=domain), source, "presentation", 3), {}))
    market = str(company.get("market", ""))
    country = str(company.get("country", ""))
    if market in {"港股", "A股", "沪深"} or "中国" in country or name:
        for source, template in CHINA_PLATFORM_SOURCES:
            kind = "presentation" if "PDF" in template else "transcript"
            if selected and kind not in selected and not (kind == "transcript" and "quarterly" in selected):
                continue
            jobs.append((_search, (template.format(query=f"{name or query} {date_text}".strip()), source, kind, 3), {}))

    results: list[LinkResult] = []
    for group in run_limited(jobs[:26], per_job_timeout=6, total_timeout=22, max_workers=6):
        if isinstance(group, list):
            results.extend(group)
        if len(results) >= max_results:
            break
    if not selected or "transcript" in selected:
        results.extend(_platform_entry_links(query, "transcript"))
    if not selected or "presentation" in selected:
        results.extend(_platform_entry_links(query, "presentation"))
    return dedupe_links(results)[:max_results]

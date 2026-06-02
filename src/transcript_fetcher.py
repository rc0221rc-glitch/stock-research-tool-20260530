from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .utils import DEFAULT_HEADERS, LinkResult, clean_filename, dedupe_links, hard_timeout, request_text, run_limited, search_url, url_exists
from .web_pdf import save_html_as_pdf


SESSION = requests.Session()
SESSION.headers.update(DEFAULT_HEADERS)


def _company_slug(name: str, ticker: str) -> str:
    name = (name or ticker).casefold()
    suffixes = [
        " inc.", " inc", " corp.", " corp", " corporation", " ltd.", " ltd", " limited",
        " plc", " ag", " se", " sa", " nv", " company", " group", " holdings", " holding",
        " technologies", " technology", " communications", " entertainment", " international",
        " partners", " energy", " co.", " co",
    ]
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                changed = True
    slug = re.sub(r"[^a-z0-9\s]", "", name)
    return re.sub(r"\s+", "-", slug.strip()) or ticker.casefold()


def _normalize_date(value: str) -> str:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value[:10], fmt).strftime("%Y%m%d")
        except Exception:
            continue
    return ""


def _quarter_info(date_str: str, yahoo_info: dict[str, dict[str, str]] | None = None) -> tuple[str, str]:
    yahoo = (yahoo_info or {}).get(date_str, {})
    if yahoo.get("quarter") and yahoo.get("fy"):
        return yahoo["quarter"], yahoo["fy"]
    dt = datetime.strptime(date_str, "%Y%m%d")
    q_map = {1: "4", 2: "4", 3: "4", 4: "1", 5: "1", 6: "1", 7: "2", 8: "2", 9: "2", 10: "3", 11: "3", 12: "3"}
    quarter = q_map.get(dt.month, "1")
    fiscal_year = str(dt.year - 1 if dt.month <= 3 else dt.year)
    return quarter, fiscal_year


def _motley_fool_urls(ticker: str, company_name: str, date_str: str, quarter: str, fiscal_year: str) -> list[str]:
    slug = _company_slug(company_name, ticker)
    ticker_slug = ticker.casefold().replace(".", "-")
    y, m, d = date_str[:4], date_str[4:6], date_str[6:8]
    base = f"https://www.fool.com/earnings/call-transcripts/{y}/{m}/{d}/"
    return [
        f"{base}{slug}-{ticker_slug}-q{quarter}-{fiscal_year}-earnings-call-transcript/",
        f"{base}{slug}-{ticker_slug}-q{quarter}-{fiscal_year}-earnings-transcript/",
        f"{base}{ticker_slug}-q{quarter}-{fiscal_year}-earnings-call-transcript/",
        f"{base}{ticker_slug}-q{quarter}-{fiscal_year}-earnings-transcript/",
        f"{base}{ticker_slug}-{slug}-earnings-call-transcript/",
    ]


def _get_earnings_info_uncached(ticker: str) -> tuple[list[dict[str, str]], str, str]:
    results: list[dict[str, str]] = []
    company_name = ""
    website = ""
    try:
        import yfinance as yf

        stock = yf.Ticker(ticker)
        info = stock.info or {}
        company_name = info.get("longName") or info.get("shortName") or ""
        website = info.get("website") or ""
        earnings = stock.earnings_dates
        if earnings is not None and not earnings.empty:
            for dt in earnings.index[:16]:
                date_str = dt.strftime("%Y%m%d")
                quarter, fiscal_year = _quarter_info(date_str)
                results.append({"date": date_str, "quarter": quarter, "fy": fiscal_year})
    except Exception:
        pass
    return results, company_name, website


def _get_earnings_info(ticker: str) -> tuple[list[dict[str, str]], str, str]:
    return hard_timeout(_get_earnings_info_uncached, ticker, timeout=6, default=([], "", ""))


def _candidate_dates(filing_dates: list[str] | None, ticker: str) -> tuple[list[str], dict[str, dict[str, str]], str, str]:
    yahoo_dates, yahoo_name, website = _get_earnings_info(ticker)
    yahoo_map = {item["date"]: item for item in yahoo_dates}
    dates = {_normalize_date(value) for value in (filing_dates or [])}
    dates = {value for value in dates if value}
    dates.update(item["date"] for item in yahoo_dates)
    if not dates:
        today = datetime.now()
        dates.update((today - timedelta(days=90 * index)).strftime("%Y%m%d") for index in range(8))
    return sorted(dates, reverse=True)[:16], yahoo_map, yahoo_name, website


def _motley_candidates(ticker: str, company_name: str, dates: list[str], yahoo_info: dict[str, dict[str, str]]) -> list[LinkResult]:
    candidates: list[LinkResult] = []
    checked: set[str] = set()
    for date_str in dates[:8]:
        try:
            base_dt = datetime.strptime(date_str, "%Y%m%d")
        except Exception:
            continue
        quarter, fiscal_year = _quarter_info(date_str, yahoo_info)
        found_for_date = False
        for offset in (0, -1, 1):
            if found_for_date:
                break
            shifted = (base_dt + timedelta(days=offset)).strftime("%Y%m%d")
            for url in _motley_fool_urls(ticker, company_name, shifted, quarter, fiscal_year):
                if url in checked:
                    continue
                checked.add(url)
                if url_exists(url, timeout=5, must_contain="transcript"):
                    candidates.append(
                        LinkResult(
                            title=f"{ticker.upper()} Q{quarter} FY{fiscal_year} Earnings Call Transcript",
                            url=url,
                            source="Motley Fool",
                            date=shifted,
                            kind="transcript",
                            is_direct_file=False,
                        )
                    )
                    found_for_date = True
                    break
    return candidates


def _stockanalysis_transcripts(ticker: str) -> list[LinkResult]:
    ticker_path = ticker.lower().replace(".", "-")
    archive_url = f"https://stockanalysis.com/stocks/{ticker_path}/earnings/transcripts/"
    try:
        html = request_text(archive_url, timeout=8)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results: list[LinkResult] = []
    for link in soup.select("a[href*='/transcripts/']"):
        href = link.get("href") or ""
        text = link.get_text(" ", strip=True)
        if not href or not text or href.rstrip("/").endswith("/transcripts"):
            continue
        full_url = f"https://stockanalysis.com{href}" if href.startswith("/") else href
        results.append(LinkResult(f"{ticker.upper()} {text} Transcript", full_url, "Stock Analysis", kind="transcript", is_direct_file=False))
    if not results and url_exists(archive_url, timeout=5):
        results.append(LinkResult(f"{ticker.upper()} transcript archive", archive_url, "Stock Analysis", kind="transcript", is_direct_file=False))
    return results


def _ticker_base(ticker: str) -> str:
    ticker = (ticker or "").strip().upper()
    return re.split(r"[.\s]", ticker, maxsplit=1)[0].replace("-", "")


def _slug_title(value: str) -> str:
    parsed = urlparse(value)
    value = parsed.path.strip("/").rsplit("/", 1)[-1] if parsed.scheme or parsed.netloc else value.strip("/").rsplit("/", 1)[-1]
    value = re.sub(r"[-_]+", " ", value)
    return re.sub(r"\s+", " ", value).strip().title()


def _date_from_url(url: str) -> str:
    match = re.search(r"/(20\d{2})/(\d{1,2})/(\d{1,2})/", url)
    if match:
        return f"{match.group(1)}{int(match.group(2)):02d}{int(match.group(3)):02d}"
    match = re.search(r"/reports/(20\d{2})-(\d{1,2})-(\d{1,2})-", url)
    if match:
        return f"{match.group(1)}{int(match.group(2)):02d}{int(match.group(3)):02d}"
    return ""


def _fool_quote_transcripts(ticker: str, max_results: int = 10) -> list[LinkResult]:
    base = _ticker_base(ticker).lower()
    if not base:
        return []
    results: list[LinkResult] = []
    seen: set[str] = set()
    for exchange in ["nasdaq", "nyse", "otc"]:
        quote_url = f"https://www.fool.com/quote/{exchange}/{base}/"
        try:
            response = SESSION.get(quote_url, timeout=10, allow_redirects=True)
            if response.status_code >= 400:
                continue
        except Exception:
            continue
        for match in re.finditer(r'(?:https?://www\.fool\.com)?/earnings/call-transcripts/[^"\\\s<]+', response.text):
            raw_url = match.group(0)
            url = raw_url if raw_url.startswith("http") else f"https://www.fool.com{raw_url}"
            url = url.rstrip(".,;)")
            if url in seen:
                continue
            seen.add(url)
            nearby = response.text[max(0, match.start() - 500) : match.end() + 500]
            headline = ""
            headline_match = re.search(r'headline\\?":\\?"([^"\\]+)', nearby)
            if headline_match:
                headline = headline_match.group(1)
            title = headline or _slug_title(url)
            if "transcript" not in f"{title} {url}".casefold():
                title = f"{title} Transcript"
            results.append(
                LinkResult(
                    title=title,
                    url=url,
                    source="Motley Fool",
                    date=_date_from_url(url),
                    kind="transcript",
                    is_direct_file=False,
                )
            )
            if len(results) >= max_results:
                return results
    return results


def _marketbeat_transcripts(ticker: str, max_results: int = 10) -> list[LinkResult]:
    base = _ticker_base(ticker)
    if not base:
        return []
    results: list[LinkResult] = []
    seen: set[str] = set()
    for exchange in ["NASDAQ", "NYSE", "OTCMKTS"]:
        index_url = f"https://www.marketbeat.com/stocks/{exchange}/{base}/earnings/"
        try:
            response = SESSION.get(index_url, timeout=10, allow_redirects=True)
            if response.status_code >= 400:
                continue
        except Exception:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        for link in soup.select("a[href*='/earnings/reports/']"):
            href = link.get("href") or ""
            if not href:
                continue
            url = urljoin("https://www.marketbeat.com", href).split("#", 1)[0] + "#transcript"
            if url in seen:
                continue
            seen.add(url)
            title = link.get_text(" ", strip=True)
            if not title or title.startswith("#") or "transcript" not in title.casefold():
                title = f"{base.upper()} {_slug_title(url)} Earnings Call Transcript"
            results.append(
                LinkResult(
                    title=title,
                    url=url,
                    source="MarketBeat",
                    date=_date_from_url(url),
                    kind="transcript",
                    is_direct_file=False,
                )
            )
            if len(results) >= max_results:
                return results
    return results


def _earningscall_transcripts(ticker: str, max_results: int = 12) -> list[LinkResult]:
    base = _ticker_base(ticker).lower()
    if not base:
        return []
    results: list[LinkResult] = []
    seen: set[str] = set()
    for exchange in ["nasdaq", "nyse", "otc"]:
        index_url = f"https://earningscall.biz/e/{exchange}/s/{base}/"
        try:
            response = SESSION.get(index_url, timeout=10, allow_redirects=True)
            if response.status_code >= 400 or "not found" in response.text[:20000].casefold():
                continue
        except Exception:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        selector = f"a[href*='/e/{exchange}/s/{base}/y/']"
        for link in soup.select(selector):
            href = link.get("href") or ""
            match = re.search(r"/y/(20\d{2})/q/(q[1-4])", href.casefold())
            if not match:
                continue
            url = urljoin("https://earningscall.biz", href)
            if url in seen:
                continue
            seen.add(url)
            fiscal_year, quarter = match.group(1), match.group(2).upper()
            results.append(
                LinkResult(
                    title=f"{base.upper()} {quarter} {fiscal_year} Earnings Call Transcript",
                    url=url,
                    source="EarningsCall.biz",
                    date=fiscal_year,
                    kind="transcript",
                    is_direct_file=False,
                )
            )
            if len(results) >= max_results:
                return results
    return results


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return (parsed.netloc or parsed.path).replace("www.", "").strip("/")


def _try_q4_transcripts(ir_domain: str, ticker: str) -> list[LinkResult]:
    if not ir_domain:
        return []
    try:
        response = SESSION.get(f"https://{ir_domain}/feed/Event.svc/GetEventList", timeout=8)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    results: list[LinkResult] = []
    for event in data.get("GetEventListResult", []):
        if not isinstance(event, dict):
            continue
        event_title = event.get("Title", "")
        start_date = event.get("StartDate", "")
        event_date = ""
        if start_date:
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
                try:
                    event_date = datetime.strptime(start_date[:10], fmt).strftime("%Y%m%d")
                    break
                except ValueError:
                    continue
        for attachment in event.get("Attachments", []):
            if not isinstance(attachment, dict):
                continue
            url = attachment.get("Url", "")
            title = attachment.get("Title", "")
            ext = (attachment.get("Extension") or "").upper()
            combined = f"{title} {url}".casefold()
            if not url or ext != "PDF":
                continue
            if any(keyword in combined for keyword in ["prepared remarks", "remarks", "transcript", "conference call", "earnings call"]):
                results.append(LinkResult(f"{ticker.upper()} {event_title} - {title}", url, "IR (Q4)", date=event_date, kind="transcript", is_direct_file=True))
    return results


def _extract_ddg_url(href: str) -> str:
    if "duckduckgo.com" not in href.casefold():
        return href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    return params.get("uddg", [""])[0]


def _duckduckgo_search(query: str, max_results: int = 6) -> list[LinkResult]:
    try:
        html = request_text(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}", timeout=8)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results: list[LinkResult] = []
    for item in soup.select(".result")[:max_results]:
        link = item.select_one(".result__a")
        if not link:
            continue
        real_url = _extract_ddg_url(link.get("href") or "")
        title = link.get_text(" ", strip=True)
        combined = f"{title} {real_url}".casefold()
        if not real_url:
            continue
        if any(keyword in combined for keyword in ["transcript", "earnings call", "conference call", "prepared remarks", "quarterly earnings"]):
            results.append(LinkResult(title, real_url, "网页搜索", kind="transcript", is_direct_file=real_url.casefold().endswith(".pdf")))
    return results


def _bing_search_url(query: str) -> str:
    return f"https://www.bing.com/search?q={quote_plus(query)}&setmkt=en-US&mkt=en-US&cc=US"


def _known_transcript_entry_links(ticker: str, company_name: str) -> list[LinkResult]:
    base = _ticker_base(ticker)
    if not base:
        return []
    query_name = " ".join(part for part in [company_name, base] if part).strip()
    source_queries = [
        ("Seeking Alpha", f"site:seekingalpha.com/article {query_name} earnings call transcript"),
        ("Motley Fool", f"site:fool.com/earnings/call-transcripts {query_name} earnings call transcript"),
        ("MarketBeat", f"site:marketbeat.com/earnings/reports {query_name} earnings call transcript"),
        ("EarningsCall.biz", f"site:earningscall.biz/e {query_name} transcript"),
        ("Investing.com", f"site:investing.com {query_name} earnings call transcript"),
        ("AlphaStreet", f"site:alphastreet.com {query_name} earnings call transcript"),
        ("MarketScreener", f"site:marketscreener.com {query_name} earnings call transcript"),
    ]
    entries = [
        LinkResult(
            f"Seeking Alpha {base.upper()} Transcript 页面",
            f"https://seekingalpha.com/symbol/{base.upper()}/earnings/transcripts",
            "Transcript 平台入口",
            kind="transcript",
            is_direct_file=False,
            note="可能需要登录或订阅；作为高相关平台入口保留。",
        ),
        LinkResult(
            f"MarketBeat {base.upper()} Earnings Transcript 页面",
            f"https://www.marketbeat.com/stocks/NASDAQ/{base.upper()}/earnings/",
            "Transcript 平台入口",
            kind="transcript",
            is_direct_file=False,
            note="若交易所不是 NASDAQ，可用页面内搜索或下方搜索入口。",
        ),
        LinkResult(
            f"EarningsCall.biz {base.upper()} Transcript 页面",
            f"https://earningscall.biz/e/nasdaq/s/{base.lower()}/",
            "Transcript 平台入口",
            kind="transcript",
            is_direct_file=False,
            note="若交易所不是 NASDAQ，可用 Bing 入口定位。",
        ),
    ]
    for source, query in source_queries:
        entries.append(LinkResult(f"Bing 定向搜索：{source} {base.upper()} Transcript", _bing_search_url(query), "Transcript 搜索建议", kind="transcript", is_direct_file=False))
        entries.append(LinkResult(f"Bing 中文入口：{source} {base.upper()} Transcript", search_url(query), "Transcript 搜索建议", kind="transcript", is_direct_file=False))
    return entries


def _round_robin_by_source(items: list[dict[str, Any]], preferred_sources: list[str] | None = None) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for item in items:
        source = str(item.get("source") or "")
        if source not in grouped:
            grouped[source] = []
            order.append(source)
        grouped[source].append(item)
    preferred = [source for source in (preferred_sources or []) if source in grouped]
    order = preferred + [source for source in order if source not in preferred]
    balanced: list[dict[str, Any]] = []
    while any(grouped[source] for source in order):
        for source in order:
            if grouped[source]:
                balanced.append(grouped[source].pop(0))
    return balanced


def _transcript_search_jobs(ticker: str, company_name: str, website: str) -> list[tuple[Any, tuple[Any, ...], dict[str, Any]]]:
    search_name = company_name or ticker
    jobs: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = [
        (_duckduckgo_search, (f"{search_name} {ticker} earnings call transcript", 6), {}),
        (_duckduckgo_search, (f"{search_name} quarterly earnings call transcript", 5), {}),
        (_duckduckgo_search, (f"site:fool.com {search_name} {ticker} earnings call transcript", 4), {}),
        (_duckduckgo_search, (f"site:seekingalpha.com {search_name} earnings call transcript", 4), {}),
        (_duckduckgo_search, (f"site:marketbeat.com {search_name} earnings call transcript", 4), {}),
        (_duckduckgo_search, (f"site:investing.com {search_name} earnings transcript", 4), {}),
    ]
    domain = _domain_from_url(website)
    domains = []
    if domain:
        domains.extend([f"investor.{domain}", f"ir.{domain}", f"investors.{domain}"])
    ticker_slug = ticker.lower().replace(".", "")
    domains.extend([f"investor.{ticker_slug}.com", f"ir.{ticker_slug}.com", f"investors.{ticker_slug}.com"])
    for domain in dict.fromkeys(domains):
        jobs.append((_try_q4_transcripts, (domain, ticker), {}))
    return jobs


def _claude_fallback(ticker: str, company_name: str, claude_api_key: str) -> list[LinkResult]:
    if not claude_api_key:
        return []
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=claude_api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "请给出这家上市公司最近 earnings call transcript 的公开网页搜索建议。"
                        "只返回 3 行以内，每行格式为：标题 | URL。"
                        f"公司：{company_name}，代码：{ticker}"
                    ),
                }
            ],
        )
        text = "\n".join(block.text for block in message.content if getattr(block, "type", "") == "text")
    except Exception:
        return []
    links: list[LinkResult] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        title, url = [part.strip() for part in line.split("|", 1)]
        if url.startswith("http"):
            links.append(LinkResult(title, url, "Claude 兜底", kind="transcript", is_direct_file=False))
    return links


def find_transcripts(
    ticker: str,
    company_name: str,
    filing_dates: list[str] | None = None,
    claude_api_key: str = "",
    max_results: int = 12,
) -> list[dict[str, Any]]:
    ticker = (ticker or "").strip()
    if not ticker:
        return []
    dates, yahoo_info, yahoo_name, website = _candidate_dates(filing_dates, ticker)
    company_name = (company_name or yahoo_name or ticker).strip()
    results: list[LinkResult] = []

    first_wave = [
        (_motley_candidates, (ticker, company_name, dates, yahoo_info), {}),
        (_fool_quote_transcripts, (ticker,), {}),
        (_marketbeat_transcripts, (ticker,), {}),
        (_earningscall_transcripts, (ticker,), {}),
        (_stockanalysis_transcripts, (ticker,), {}),
    ]
    for group in run_limited(first_wave, per_job_timeout=8, total_timeout=18, max_workers=5):
        if isinstance(group, list):
            results.extend(group)

    if len(dedupe_links(results)) < max_results:
        for group in run_limited(_transcript_search_jobs(ticker, company_name, website), per_job_timeout=6, total_timeout=16, max_workers=5):
            if isinstance(group, list):
                results.extend(group)

    if len(results) < 2 and claude_api_key:
        results.extend(_claude_fallback(ticker, company_name, claude_api_key))
    deduped = dedupe_links(results)
    if not deduped:
        results.extend(_known_transcript_entry_links(ticker, company_name))
    elif len(deduped) < 4:
        results.extend(_known_transcript_entry_links(ticker, company_name))
    deduped = dedupe_links(results)
    preferred_sources = ["Motley Fool", "MarketBeat", "EarningsCall.biz", "Stock Analysis", "网页搜索", "Transcript 平台入口", "Transcript 搜索建议"]
    return _round_robin_by_source(deduped, preferred_sources)[:max_results]


def _extract_transcript_text(html_content: str) -> str | None:
    soup = BeautifulSoup(html_content, "lxml")
    selectors = [
        "#transcript-panel-full",
        "div.space-y-6.text-base",
        "div.article-body",
        "div.prose",
        "div.post-content",
        "div.article-content",
        "section.article-body",
        "div.transcript-body",
        "div[itemprop='articleBody']",
        "article",
        "div.entry-content",
        "main article",
        "div.WYSIWYG",
        "div.article_wrapper",
        "#article_text",
        "#content-body",
    ]
    content = None
    for selector in selectors:
        content = soup.select_one(selector)
        if content:
            break
    if not content:
        candidates = []
        for node in soup.find_all(["div", "article", "section", "main"]):
            text = node.get_text(" ", strip=True)
            if len(text) < 2000:
                continue
            score = sum(keyword in text.casefold() for keyword in ["operator", "earnings call", "conference call", "prepared remarks", "question-and-answer", "q&a"])
            if score >= 2:
                candidates.append((score, len(text), node))
        if candidates:
            candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))
            content = candidates[0][2]
    if not content:
        return None
    paragraphs = []
    for node in content.find_all(["p", "div", "section"]):
        text = node.get_text(" ", strip=True)
        if len(text) <= 30:
            continue
        first = text.casefold()[:80]
        if any(skip in first for skip in ["cookie", "advertisement", "subscribe", "sign up", "login", "menu", "share this article"]):
            continue
        paragraphs.append(text)
    if not paragraphs:
        text = content.get_text("\n\n", strip=True)
        if len(text) > 500:
            paragraphs = [text]
    return "\n\n".join(paragraphs) if paragraphs else None


def download_transcript_items(items: list[dict[str, Any]], target_dir: str | Path, ticker: str = "") -> list[Path]:
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for index, item in enumerate(items, start=1):
        url = item.get("url", "")
        if not url or item.get("source") == "兜底链接":
            continue
        title = item.get("title") or f"transcript_{index}"
        prefix = clean_filename(f"{ticker}_{item.get('source', 'web')}_{title}", "transcript")[:100]
        try:
            response = SESSION.get(url, timeout=18, allow_redirects=True)
            response.raise_for_status()
        except Exception:
            continue
        content_type = response.headers.get("Content-Type", "")
        is_pdf = ".pdf" in url.casefold() or "pdf" in content_type.casefold()
        if is_pdf:
            path = target / f"{prefix}.pdf"
            path.write_bytes(response.content)
            saved.append(path)
            continue
        try:
            path = target / f"{prefix}.pdf"
            save_html_as_pdf(response.text, path, source_url=response.url or url, title=title)
        except Exception:
            text = _extract_transcript_text(response.text)
            if text and len(text) > 500:
                path = target / f"{prefix}.txt"
                path.write_text(
                    f"Title: {title}\nSource: {item.get('source', '')}\nURL: {url}\n{'=' * 60}\n\n{text}",
                    encoding="utf-8",
                )
            else:
                path = target / f"{prefix}.html"
                path.write_text(response.text, encoding="utf-8", errors="ignore")
        saved.append(path)
        time.sleep(0.2)
    return saved


def download_transcripts(*args: Any, **kwargs: Any) -> list[Any]:
    if args and isinstance(args[0], list):
        return [str(path) for path in download_transcript_items(args[0], args[1], kwargs.get("ticker", ""))]
    ticker = args[0] if args else kwargs.get("ticker", "")
    filing_dates = args[1] if len(args) > 1 else kwargs.get("filing_dates", [])
    output_dir = args[2] if len(args) > 2 else kwargs.get("output_dir", "downloads")
    company_name = kwargs.get("company_name", "")
    transcripts = find_transcripts(ticker, company_name, filing_dates)
    return download_transcript_items(transcripts, output_dir, ticker)

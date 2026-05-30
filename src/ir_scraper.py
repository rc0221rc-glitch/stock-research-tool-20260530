from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .utils import DEFAULT_HEADERS, LinkResult, clean_filename, dedupe_links, hard_timeout, request_text, run_limited, search_url


SESSION = requests.Session()
SESSION.headers.update(DEFAULT_HEADERS)

REPORT_KEYWORDS = ["annual report", "interim report", "quarterly report", "financial report", "results"]
PRESENTATION_KEYWORDS = [
    "presentation",
    "slides",
    "deck",
    "earnings presentation",
    "investor presentation",
    "webcast slides",
    "quarterly results",
    "financial results",
    "supplement",
]
SKIP_PRESENTATION_KEYWORDS = [
    "10-k",
    "10k",
    "10-q",
    "10q",
    "20-f",
    "20f",
    "annual-report-on-form",
    "as-filed",
    "proxy",
    "sustainability",
    "esg",
]


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return (parsed.netloc or parsed.path).replace("www.", "").strip("/")


def _get_yahoo_website_uncached(ticker: str) -> tuple[str, str]:
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info or {}
        return info.get("longName") or info.get("shortName") or "", info.get("website") or ""
    except Exception:
        return "", ""


def _get_yahoo_website(ticker: str) -> tuple[str, str]:
    return hard_timeout(_get_yahoo_website_uncached, ticker, timeout=6, default=("", ""))


def _parse_date(value: str) -> tuple[str, datetime | None]:
    if not value:
        return "", None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%Y%m%d"):
        try:
            dt = datetime.strptime(value[:10], fmt)
            return dt.strftime("%Y%m%d"), dt
        except ValueError:
            continue
    return "", None


def _target_date_objects(target_dates: list[str] | None) -> list[datetime]:
    dates: list[datetime] = []
    for value in target_dates or []:
        _, dt = _parse_date(value)
        if dt:
            dates.append(dt)
    return dates


def _date_matches(event_dt: datetime | None, target_dates: list[datetime], tolerance_days: int = 5) -> bool:
    if not target_dates or not event_dt:
        return True
    return any(abs((event_dt - target).days) <= tolerance_days for target in target_dates)


def _is_presentation_candidate(title: str, url: str) -> bool:
    combined = f"{title} {url}".casefold()
    if any(skip in combined for skip in SKIP_PRESENTATION_KEYWORDS):
        return False
    return any(keyword in combined for keyword in PRESENTATION_KEYWORDS)


def _is_report_candidate(title: str, url: str) -> bool:
    combined = f"{title} {url}".casefold()
    return any(keyword in combined for keyword in REPORT_KEYWORDS)


def _url_is_pdf(url: str, timeout: float = 5) -> bool:
    try:
        response = SESSION.head(url, timeout=timeout, allow_redirects=True)
        if response.status_code == 405:
            response = SESSION.get(url, timeout=timeout, stream=True, allow_redirects=True)
        return response.status_code < 400 and "pdf" in response.headers.get("Content-Type", "").casefold()
    except Exception:
        return False


def _known_official_pdfs(ticker: str, company_name: str, kinds: list[str] | None = None) -> list[LinkResult]:
    combined_name = f"{ticker} {company_name}".casefold()
    if not any(token in combined_name for token in ["infineon", "ifnny", "ifx"]):
        return []
    years = [datetime.now().year, datetime.now().year - 1, datetime.now().year - 2]
    candidates: list[tuple[str, str, str]] = []
    if not kinds or any(kind in kinds for kind in ["annual", "quarterly", "IR"]):
        for year in years:
            candidates.append(
                (
                    f"Infineon {year} Annual Report",
                    f"https://www.infineon.com/assets/row/public/documents/corporate/investors/annual-reports/{year}/{year}-annual-report-v01-00-en.pdf",
                    "IR 官网",
                )
            )
    if not kinds or "presentation" in kinds:
        fiscal_years = [str(year)[-2:] for year in years]
        quarter_dates = [("q1", "02-04"), ("q2", "05-08"), ("q3", "08-05"), ("q4", "11-12")]
        for year, fy in zip(years, fiscal_years):
            for quarter, month_day in quarter_dates:
                candidates.extend(
                    [
                        (
                            f"Infineon {quarter.upper()} FY{fy} Investor Presentation",
                            f"https://www.infineon.com/row/public/documents/corporate/investors/presentations/{year}/{year}-{month_day}-{quarter}-fy{fy}-investor-presentation-v01-00-en.pdf",
                            "IR 官网 Presentation",
                        ),
                        (
                            f"Infineon {quarter.upper()} FY{fy} Investor Presentation",
                            f"https://www.infineon.com/assets/row/public/documents/corporate/investors/presentations/{year}/{year}-{month_day}-{quarter}-fy{fy}-investor-presentation-v01-00-en.pdf",
                            "IR 官网 Presentation",
                        ),
                    ]
                )
    results: list[LinkResult] = []
    for title, url, source in candidates:
        if _url_is_pdf(url):
            results.append(LinkResult(title, url, source, kind="presentation" if "Presentation" in title else "IR", is_direct_file=True))
        if len(results) >= 8:
            break
    return results


def _try_q4_events(ir_domain: str, ticker: str, target_dates: list[str] | None = None) -> list[LinkResult]:
    if not ir_domain:
        return []
    try:
        response = SESSION.get(f"https://{ir_domain}/feed/Event.svc/GetEventList", timeout=8)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    targets = _target_date_objects(target_dates)
    results: list[LinkResult] = []
    for event in data.get("GetEventListResult", []):
        if not isinstance(event, dict):
            continue
        event_title = event.get("Title", "")
        event_date, event_dt = _parse_date(event.get("StartDate", ""))
        if not _date_matches(event_dt, targets):
            continue
        attachments = event.get("Attachments", []) or []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            url = attachment.get("Url", "")
            title = attachment.get("Title", "")
            ext = (attachment.get("Extension") or "").upper()
            attachment_type = attachment.get("Type", "")
            if not url or ext != "PDF":
                continue
            combined = f"{title} {url} {attachment_type}".casefold()
            is_transcript = any(keyword in combined for keyword in ["prepared remarks", "remarks", "transcript", "conference call"])
            is_presentation = attachment_type == "Presentation" or _is_presentation_candidate(title, url)
            if is_presentation or is_transcript:
                results.append(
                    LinkResult(
                        title=f"{ticker.upper()} {event_title} - {title}",
                        url=url,
                        source="IR (Q4 Events)",
                        date=event_date,
                        kind="transcript" if is_transcript else "presentation",
                        is_direct_file=True,
                    )
                )
        document_path = event.get("DocumentPath", "")
        if document_path and document_path.casefold().endswith(".pdf") and _is_presentation_candidate(event_title, document_path):
            results.append(LinkResult(f"{ticker.upper()} {event_title}", document_path, "IR (Q4 Events)", date=event_date, kind="presentation", is_direct_file=True))
    return results


def _common_ir_domains(ticker: str, company_name: str = "", ir_url: str = "") -> list[str]:
    domains: list[str] = []
    if ir_url:
        domain = _extract_domain(ir_url)
        if domain:
            domains.extend([domain, f"investor.{domain}", f"ir.{domain}", f"investors.{domain}"])
    yahoo_name, yahoo_website = _get_yahoo_website(ticker)
    website_domain = _extract_domain(yahoo_website)
    if website_domain:
        domains.extend([f"investor.{website_domain}", f"ir.{website_domain}", f"investors.{website_domain}"])
    ticker_slug = (ticker or "").lower().replace(".", "")
    if ticker_slug:
        domains.extend([f"investor.{ticker_slug}.com", f"ir.{ticker_slug}.com", f"investors.{ticker_slug}.com"])
    name = company_name or yahoo_name
    if name:
        name_slug = re.sub(r"[^a-z0-9]", "", name.casefold())[:24]
        if name_slug:
            domains.extend([f"investor.{name_slug}.com", f"ir.{name_slug}.com"])
    return list(dict.fromkeys(domain for domain in domains if domain))


def _common_ir_pages(ticker: str, company_name: str = "", ir_url: str = "") -> list[str]:
    pages: list[str] = []
    if ir_url:
        pages.append(ir_url)
    _, yahoo_website = _get_yahoo_website(ticker)
    roots = []
    for raw_url in [ir_url, yahoo_website]:
        domain = _extract_domain(raw_url)
        if domain:
            roots.append(f"https://{domain}")
    for domain in _common_ir_domains(ticker, company_name, ir_url):
        roots.append(f"https://{domain}")
    suffixes = [
        "",
        "/investors",
        "/investor-relations",
        "/investor",
        "/ir",
        "/financials",
        "/financial-reports",
        "/quarterly-results",
        "/events-and-presentations",
        "/presentations",
        "/news-events/events-presentations",
    ]
    for root in roots:
        for suffix in suffixes:
            pages.append(urljoin(root.rstrip("/") + "/", suffix.lstrip("/")))
    return list(dict.fromkeys(page for page in pages if page.startswith("http")))


def _extract_pdf_links(base_url: str, limit: int = 16) -> list[LinkResult]:
    try:
        html = request_text(base_url, timeout=8)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    links: list[LinkResult] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        text = anchor.get_text(" ", strip=True)
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if not full_url.startswith("http"):
            continue
        if ".pdf" not in urlparse(full_url).path.casefold():
            continue
        combined = f"{text} {full_url}".casefold()
        if not any(keyword in combined for keyword in [*REPORT_KEYWORDS, *PRESENTATION_KEYWORDS]):
            continue
        is_pdf = ".pdf" in urlparse(full_url).path.casefold()
        if _is_presentation_candidate(text, full_url):
            kind = "presentation"
            source = "IR 官网 Presentation"
        elif _is_report_candidate(text, full_url):
            kind = "IR"
            source = "IR 官网"
        else:
            kind = "IR"
            source = "IR 官网"
        links.append(LinkResult((text or full_url.rsplit("/", 1)[-1])[:180], full_url, source, kind=kind, is_direct_file=is_pdf))
        if len(links) >= limit:
            break
    return links


def _extract_ddg_url(href: str) -> str:
    if "duckduckgo.com" not in href.casefold():
        return href
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    return params.get("uddg", [""])[0]


def _duckduckgo_pdf_search(query: str, kind: str = "presentation", max_results: int = 6) -> list[LinkResult]:
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
        if not real_url:
            continue
        host = urlparse(real_url).netloc.casefold()
        if kind == "presentation" and any(blocked in host for blocked in ["myapplestock", "wallstreetzen", "macrotrends", "companiesmarketcap"]):
            continue
        if kind == "presentation" and not _is_presentation_candidate(title, real_url):
            continue
        if kind != "presentation" and not (_is_report_candidate(title, real_url) or real_url.casefold().endswith(".pdf")):
            continue
        results.append(LinkResult(title, real_url, "网页搜索", kind=kind, is_direct_file=".pdf" in real_url.casefold()))
    return results


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
                        "请给出这家公司投资者关系页面、年度报告或 earnings presentation 的公开链接建议。"
                        "只返回 4 行以内，每行格式为：标题 | URL。"
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
            links.append(LinkResult(title, url, "Claude 兜底", kind="IR", is_direct_file=".pdf" in url.casefold()))
    return links


def find_presentations(
    ticker: str,
    company_name: str,
    target_dates: list[str] | None = None,
    claude_api_key: str = "",
    ir_url: str = "",
    max_results: int = 12,
) -> list[dict[str, Any]]:
    ticker = (ticker or "").strip()
    if not ticker and not company_name:
        return []
    all_results: list[LinkResult] = []
    all_results.extend(_known_official_pdfs(ticker, company_name, kinds=["presentation"]))
    q4_jobs = [(_try_q4_events, (domain, ticker, target_dates), {}) for domain in _common_ir_domains(ticker, company_name, ir_url)[:8]]
    page_jobs = [(_extract_pdf_links, (page, 10), {}) for page in _common_ir_pages(ticker, company_name, ir_url)[:12]]
    search_jobs = [
        (_duckduckgo_pdf_search, (f"{company_name} {ticker} earnings presentation slides filetype:pdf", "presentation", 6), {}),
        (_duckduckgo_pdf_search, (f"{company_name} {ticker} quarterly results presentation PDF", "presentation", 6), {}),
        (_duckduckgo_pdf_search, (f"{company_name} {ticker} investor presentation earnings deck", "presentation", 5), {}),
    ]
    domain = _extract_domain(ir_url)
    if domain:
        search_jobs.extend(
            [
                (_duckduckgo_pdf_search, (f"site:{domain} earnings presentation slides filetype:pdf", "presentation", 6), {}),
                (_duckduckgo_pdf_search, (f"site:{domain} quarterly results presentation PDF", "presentation", 6), {}),
            ]
        )
    for group in run_limited([*q4_jobs, *page_jobs, *search_jobs], per_job_timeout=6, total_timeout=18, max_workers=6):
        if isinstance(group, list):
            all_results.extend(group)
        if len(all_results) >= max_results:
            break
    filtered = [item for item in all_results if item.kind == "presentation"]
    if len(filtered) < 2 and claude_api_key:
        filtered.extend(_claude_fallback(ticker, company_name, claude_api_key))
    if not filtered:
        filtered.append(LinkResult("未找到官网 Presentation PDF，打开搜索建议", search_url(f"{company_name} {ticker} earnings presentation slides filetype:pdf"), "搜索建议", kind="presentation", is_direct_file=False, note="IR 渠道未抓到具体 PDF 文件。"))
    return dedupe_links(filtered)[:max_results]


def find_ir_documents(company: dict[str, Any], kinds: list[str] | None = None, claude_api_key: str = "", max_results: int = 12) -> list[dict[str, Any]]:
    kinds = kinds or ["annual"]
    company_name = company.get("name_en") or company.get("name") or company.get("ticker") or ""
    ticker = company.get("ticker") or company.get("local_code") or ""
    ir_url = company.get("ir_url", "")
    results: list[LinkResult] = []
    presentation_results: list[dict[str, Any]] = []
    results.extend(_known_official_pdfs(ticker, company_name, kinds=kinds))
    if "presentation" in kinds:
        presentation_results = find_presentations(ticker, company_name, target_dates=None, claude_api_key=claude_api_key, ir_url=ir_url, max_results=max_results)
        if set(kinds) == {"presentation"}:
            return presentation_results
    jobs = [(_extract_pdf_links, (page, 10), {}) for page in _common_ir_pages(ticker, company_name, ir_url)[:10]]
    jobs.extend(
        [
            (_duckduckgo_pdf_search, (f"{company_name} {ticker} annual report filetype:pdf", "IR", 5), {}),
            (_duckduckgo_pdf_search, (f"{company_name} {ticker} interim report filetype:pdf", "IR", 5), {}),
        ]
    )
    for group in run_limited(jobs, per_job_timeout=6, total_timeout=16, max_workers=5):
        if isinstance(group, list):
            results.extend(group)
        if len(results) >= max_results:
            break
    if len(results) < 2 and claude_api_key:
        results.extend(_claude_fallback(ticker, company_name, claude_api_key))
    if not results:
        results.append(LinkResult("未找到官网报告 PDF，打开搜索建议", search_url(f"{company_name} {ticker} annual report filetype:pdf"), "搜索建议", kind="搜索", is_direct_file=False, note="IR 渠道未抓到具体 PDF 文件。"))
    return dedupe_links([*presentation_results, *results])[:max_results]


def download_presentations(items: list[dict[str, Any]], target_dir: str | Path, ticker: str = "") -> list[Path]:
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for index, item in enumerate(items, start=1):
        url = item.get("url", "")
        if not url or item.get("source") == "兜底链接":
            continue
        try:
            response = SESSION.get(url, timeout=18, allow_redirects=True)
            response.raise_for_status()
        except Exception:
            continue
        content_type = response.headers.get("Content-Type", "")
        is_pdf = ".pdf" in url.casefold() or "pdf" in content_type.casefold()
        title = clean_filename(f"{ticker}_{item.get('source', 'IR')}_{item.get('title', 'presentation')}", "presentation")[:110]
        path = target / f"{title}{'.pdf' if is_pdf else '.html'}"
        if is_pdf:
            path.write_bytes(response.content)
        else:
            path.write_text(response.text, encoding="utf-8", errors="ignore")
        saved.append(path)
        time.sleep(0.2)
    return saved

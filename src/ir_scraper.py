from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup

from .utils import LinkResult, dedupe_links, request_text, run_limited, search_url


PDF_KEYWORDS = [
    "annual report",
    "interim report",
    "quarterly",
    "results",
    "presentation",
    "investor presentation",
    "earnings",
    "financial",
    "report",
]


def _extract_pdf_links(base_url: str, limit: int = 12) -> list[LinkResult]:
    if not base_url:
        return []
    try:
        html = request_text(base_url, timeout=8)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    links: list[LinkResult] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        text = anchor.get_text(" ", strip=True)
        combined = f"{text} {href}".casefold()
        if ".pdf" not in combined and not any(keyword in combined for keyword in PDF_KEYWORDS):
            continue
        url = urljoin(base_url, href)
        if not urlparse(url).scheme.startswith("http"):
            continue
        title = text or url.split("/")[-1]
        is_pdf = ".pdf" in urlparse(url).path.casefold()
        kind = "presentation" if any(word in combined for word in ["presentation", "slides", "deck", "earnings"]) else "IR"
        links.append(LinkResult(title[:180], url, "IR 官网", kind=kind, is_direct_file=is_pdf))
        if len(links) >= limit:
            break
    return links


def _try_common_ir_paths(ir_url: str) -> list[str]:
    if not ir_url:
        return []
    parsed = urlparse(ir_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    paths = [
        ir_url,
        urljoin(root, "/investors"),
        urljoin(root, "/investor-relations"),
        urljoin(root, "/en/investors"),
        urljoin(root, "/ir"),
        urljoin(root, "/financials"),
        urljoin(root, "/events-and-presentations"),
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _duckduckgo_pdf_search(query: str, max_results: int = 5) -> list[LinkResult]:
    try:
        html = request_text(f"https://duckduckgo.com/html/?q={quote_plus(query)}", timeout=6)
    except Exception:
        return []
    soup = BeautifulSoup(html, "lxml")
    results: list[LinkResult] = []
    for item in soup.select(".result")[:max_results]:
        link = item.select_one(".result__a")
        if not link:
            continue
        href = link.get("href") or ""
        title = link.get_text(" ", strip=True)
        if href:
            results.append(LinkResult(title, href, "网页搜索", kind="presentation" if "presentation" in query else "IR", is_direct_file=".pdf" in href.casefold()))
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


def find_ir_documents(company: dict[str, Any], kinds: list[str] | None = None, claude_api_key: str = "", max_results: int = 12) -> list[dict[str, Any]]:
    company_name = company.get("name_en") or company.get("name") or company.get("ticker") or ""
    ticker = company.get("ticker") or company.get("local_code") or ""
    ir_url = company.get("ir_url", "")
    paths = _try_common_ir_paths(ir_url)
    jobs = [(_extract_pdf_links, (path, 8), {}) for path in paths[:5]]
    jobs.extend(
        [
            (_duckduckgo_pdf_search, (f"{company_name} {ticker} annual report filetype:pdf", 4), {}),
            (_duckduckgo_pdf_search, (f"{company_name} {ticker} earnings presentation filetype:pdf", 4), {}),
        ]
    )
    links: list[LinkResult] = []
    for group in run_limited(jobs, per_job_timeout=6, total_timeout=20, max_workers=4):
        if isinstance(group, list):
            links.extend(group)
        if len(links) >= max_results:
            break
    if len(links) < 2 and claude_api_key:
        links.extend(_claude_fallback(ticker, company_name, claude_api_key))
    if not links and ir_url:
        links.append(LinkResult("官方 IR 网站", ir_url, "兜底链接", kind="IR", is_direct_file=False))
    if not links:
        links.append(LinkResult("Google PDF 搜索", search_url(f"{company_name} {ticker} annual report presentation filetype:pdf"), "兜底链接", kind="搜索", is_direct_file=False))
    return dedupe_links(links)[:max_results]


def find_presentations(ticker: str, company_name: str, target_dates: list[str] | None = None, claude_api_key: str = "", ir_url: str = "") -> list[dict[str, Any]]:
    company = {"ticker": ticker, "name_en": company_name, "ir_url": ir_url}
    links = find_ir_documents(company, kinds=["presentation"], claude_api_key=claude_api_key, max_results=10)
    filtered = [item for item in links if re.search(r"presentation|slides|deck|earnings|results", f"{item.get('title','')} {item.get('url','')}", re.I)]
    if filtered:
        return filtered
    return links


def download_presentations(items: list[dict[str, Any]], target_dir: str) -> list[str]:
    import os
    import requests

    os.makedirs(target_dir, exist_ok=True)
    saved: list[str] = []
    for index, item in enumerate(items, start=1):
        url = item.get("url", "")
        if ".pdf" not in url.casefold():
            continue
        try:
            response = requests.get(url, timeout=12, headers={"User-Agent": "GlobalFilingResearchTool/1.0 research@example.com"})
            response.raise_for_status()
        except Exception:
            continue
        path = os.path.join(target_dir, f"presentation_{index}.pdf")
        with open(path, "wb") as file:
            file.write(response.content)
        saved.append(path)
    return saved

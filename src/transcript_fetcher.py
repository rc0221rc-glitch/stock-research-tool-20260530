from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from .utils import LinkResult, dedupe_links, request_text, run_limited, search_url, url_exists


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _candidate_dates(filing_dates: list[str] | None) -> list[str]:
    dates: list[str] = []
    for value in filing_dates or []:
        try:
            base = datetime.strptime(value[:10], "%Y-%m-%d")
        except Exception:
            continue
        for delta in [-1, 0, 1]:
            dates.append((base + timedelta(days=delta)).strftime("%Y-%m-%d"))
    return dates[:9]


def _motley_candidates(ticker: str, company_name: str, dates: list[str]) -> list[LinkResult]:
    ticker_slug = _slug(ticker)
    company_slug = _slug(company_name)
    templates = [
        "https://www.fool.com/earnings/call-transcripts/{date}/{ticker}-{company}-earnings-call-transcript/",
        "https://www.fool.com/earnings/call-transcripts/{date}/{ticker}-q{quarter}-earnings-call-transcript/",
    ]
    quarters = ["1", "2", "3", "4"]
    candidates: list[LinkResult] = []
    for date in dates[:6]:
        for template in templates:
            if "{quarter}" in template:
                for quarter in quarters:
                    url = template.format(date=date, ticker=ticker_slug, company=company_slug, quarter=quarter)
                    if url_exists(url, timeout=4, must_contain="transcript"):
                        candidates.append(LinkResult(f"Motley Fool Transcript {date}", url, "Motley Fool", date=date, kind="transcript", is_direct_file=False))
            else:
                url = template.format(date=date, ticker=ticker_slug, company=company_slug, quarter="")
                if url_exists(url, timeout=4, must_contain="transcript"):
                    candidates.append(LinkResult(f"Motley Fool Transcript {date}", url, "Motley Fool", date=date, kind="transcript", is_direct_file=False))
    return candidates


def _duckduckgo_search(query: str, max_results: int = 5) -> list[LinkResult]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    try:
        html = request_text(url, timeout=6)
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
        if not href or not title:
            continue
        results.append(LinkResult(title, href, "网页搜索", kind="transcript", is_direct_file=False))
    return results


def _stockanalysis_search(ticker: str) -> list[LinkResult]:
    ticker = ticker.upper().replace(".", "-")
    archive = f"https://stockanalysis.com/stocks/{ticker.lower()}/earnings/transcripts/"
    if url_exists(archive, timeout=5):
        return [LinkResult(f"{ticker} transcript archive", archive, "Stock Analysis", kind="transcript", is_direct_file=False)]
    return []


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
    max_results: int = 8,
) -> list[dict[str, Any]]:
    ticker = (ticker or "").strip()
    company_name = (company_name or ticker).strip()
    if not ticker and not company_name:
        return []

    dates = _candidate_dates(filing_dates)
    jobs = [
        (_motley_candidates, (ticker, company_name, dates), {}),
        (_stockanalysis_search, (ticker,), {}),
        (_duckduckgo_search, (f"{ticker} {company_name} earnings call transcript", 5), {}),
        (_duckduckgo_search, (f"site:fool.com {ticker} earnings call transcript", 3), {}),
        (_duckduckgo_search, (f"site:seekingalpha.com {company_name} earnings call transcript", 3), {}),
    ]
    results: list[LinkResult] = []
    search_results = run_limited(jobs, per_job_timeout=6, total_timeout=20, max_workers=4)
    for group in search_results:
        if isinstance(group, list):
            results.extend(group)
        if len(results) >= max_results:
            break
    if len(results) < 2 and claude_api_key:
        results.extend(_claude_fallback(ticker, company_name, claude_api_key))
    if not results:
        results.append(LinkResult("Transcript 网页搜索", search_url(f"{ticker} {company_name} earnings call transcript"), "兜底链接", kind="transcript", is_direct_file=False, note="自动发现失败，可用搜索链接继续查找。"))
    return dedupe_links(results)[:max_results]


def download_transcripts(items: list[dict[str, Any]], target_dir: str) -> list[str]:
    import os
    import requests

    os.makedirs(target_dir, exist_ok=True)
    saved: list[str] = []
    for index, item in enumerate(items, start=1):
        url = item.get("url", "")
        if not url:
            continue
        try:
            response = requests.get(url, timeout=10, headers={"User-Agent": "GlobalFilingResearchTool/1.0 research@example.com"})
            response.raise_for_status()
        except Exception:
            continue
        path = os.path.join(target_dir, f"transcript_{index}.html")
        with open(path, "w", encoding="utf-8") as file:
            file.write(response.text)
        saved.append(path)
    return saved

from __future__ import annotations

import concurrent.futures
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable
from urllib.parse import quote_plus, urlparse

import requests


DEFAULT_USER_AGENT = "GlobalFilingResearchTool/1.0 research@example.com"
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class LinkResult:
    title: str
    url: str
    source: str
    date: str = ""
    form: str = ""
    kind: str = ""
    index_url: str = ""
    is_direct_file: bool = True
    note: str = ""


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.casefold().strip()
    text = re.sub(r"[\s\-_./]+", "", text)
    return text


def clean_filename(value: str, default: str = "download") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value or "")
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned[:120] or default


def clean_sheet_name(value: str, fallback: str = "Sheet") -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]+", " ", value or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned or fallback)[:31]


def dedupe_links(items: Iterable[dict[str, Any] | LinkResult]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        data = item.__dict__.copy() if isinstance(item, LinkResult) else dict(item)
        url = data.get("url", "")
        if not url:
            continue
        key = canonical_url(url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(data)
    return deduped


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/+", "/", parsed.path.rstrip("/"))
    return f"{parsed.netloc.casefold()}{path}?{parsed.query}".rstrip("?")


def request_json(url: str, timeout: float = 10, **kwargs: Any) -> Any:
    headers = dict(DEFAULT_HEADERS)
    headers.update(kwargs.pop("headers", {}) or {})
    response = requests.get(url, headers=headers, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response.json()


def request_text(url: str, timeout: float = 10, **kwargs: Any) -> str:
    headers = dict(DEFAULT_HEADERS)
    headers.update(kwargs.pop("headers", {}) or {})
    response = requests.get(url, headers=headers, timeout=timeout, **kwargs)
    response.raise_for_status()
    if not response.encoding:
        response.encoding = response.apparent_encoding
    return response.text


def url_exists(url: str, timeout: float = 5, must_contain: str | None = None) -> bool:
    try:
        headers = dict(DEFAULT_HEADERS)
        response = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if response.status_code >= 400 or response.status_code == 405:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
        final_url = response.url.casefold()
        if must_contain and must_contain.casefold() not in final_url:
            return False
        return response.status_code < 400
    except Exception:
        return False


def hard_timeout(callable_: Callable[..., Any], *args: Any, timeout: float = 6, default: Any = None, **kwargs: Any) -> Any:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(callable_, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except Exception:
            future.cancel()
            return default


def run_limited(
    jobs: Iterable[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]],
    per_job_timeout: float = 6,
    total_timeout: float = 20,
    max_workers: int = 4,
) -> list[Any]:
    start = time.monotonic()
    results: list[Any] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(func, *args, **kwargs) for func, args, kwargs in jobs]
        for future in concurrent.futures.as_completed(futures, timeout=total_timeout):
            remaining = max(0.1, min(per_job_timeout, total_timeout - (time.monotonic() - start)))
            if remaining <= 0:
                break
            try:
                results.append(future.result(timeout=remaining))
            except Exception:
                results.append(None)
            if time.monotonic() - start >= total_timeout:
                break
        for future in futures:
            if not future.done():
                future.cancel()
    return results


def search_url(query: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(query)}"


def fallback_links(company: dict[str, Any], kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
    name = company.get("name") or company.get("name_en") or company.get("ticker") or "company"
    ticker = company.get("ticker") or company.get("local_code") or ""
    ir_url = company.get("ir_url", "")
    market = company.get("market", "")
    selected = set(kinds or [])
    suffix = " annual report investor relations filetype:pdf"
    links: list[LinkResult] = []
    if ir_url:
        links.append(LinkResult("官方 IR 网站", ir_url, "兜底链接", kind="IR", is_direct_file=False, note="请在官方投资者关系页面继续筛选。"))
    if market in {"港股", "HK"} and company.get("local_code"):
        code = str(company["local_code"]).zfill(4)
        links.append(
            LinkResult(
                "披露易公告搜索",
                f"https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&stockcode={code}",
                "兜底链接",
                kind="HKEX",
                is_direct_file=False,
            )
        )
    if market in {"A股", "沪深"}:
        links.append(LinkResult("巨潮资讯搜索", f"https://www.cninfo.com.cn/new/fulltextSearch?notautosubmit=&keyWord={quote_plus(name)}", "兜底链接", kind="CNINFO", is_direct_file=False))
    if "台股" in market:
        links.append(LinkResult("台湾公开资讯观测站 MOPS", "https://mops.twse.com.tw/mops/web/index", "兜底链接", kind="MOPS", is_direct_file=False))
    if "韩股" in market:
        links.append(LinkResult("韩国 DART", "https://dart.fss.or.kr/", "兜底链接", kind="DART", is_direct_file=False))
    if not selected or selected.intersection({"annual", "quarterly", "prospectus", "presentation", "transcript"}):
        links.append(LinkResult("Google PDF 搜索", search_url(f"{name} {ticker} {suffix}"), "兜底链接", kind="搜索", is_direct_file=False))
    return [item.__dict__ for item in links]

from __future__ import annotations

import concurrent.futures
import html
import mimetypes
import queue
import re
import threading
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
    if parsed.netloc.casefold().endswith("infineon.com"):
        path = path.replace("/assets/row/public/", "/row/public/")
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
    request_error: Exception | None = None
    try:
        response = requests.get(url, headers=headers, timeout=timeout, **kwargs)
        response.raise_for_status()
        if not response.encoding:
            response.encoding = response.apparent_encoding
        text = response.text
        if _should_retry_with_scrapling(text, response.url):
            try:
                scrapling_text = _request_text_with_scrapling(url, timeout=timeout, headers=headers, **kwargs)
                if len(scrapling_text.strip()) > len(text.strip()):
                    return scrapling_text
            except Exception:
                return text
        return text
    except Exception as exc:
        request_error = exc
    try:
        return _request_text_with_scrapling(url, timeout=timeout, headers=headers, **kwargs)
    except Exception:
        if request_error:
            raise request_error
        raise


def _request_text_with_scrapling(url: str, timeout: float = 10, **kwargs: Any) -> str:
    from .scrapling_fetcher import fetch_text_with_scrapling

    return fetch_text_with_scrapling(url, timeout=timeout, **kwargs)


def _should_retry_with_scrapling(text: str, url: str) -> bool:
    sample = " ".join((text or "").casefold().split())[:2000]
    if len(sample) < 400:
        return True
    blocked_tokens = [
        "enable javascript",
        "checking your browser",
        "access denied",
        "temporarily blocked",
        "unusual traffic",
        "captcha",
        "robot check",
        "verify you are human",
    ]
    return any(token in sample for token in blocked_tokens)


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
    result_queue: queue.Queue[Any] = queue.Queue(maxsize=1)

    def runner() -> None:
        try:
            result_queue.put(("ok", callable_(*args, **kwargs)), block=False)
        except Exception as exc:
            result_queue.put(("error", exc), block=False)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    try:
        status, value = result_queue.get(timeout=timeout)
        if status == "ok":
            return value
        return default
    except queue.Empty:
        return default


def run_limited(
    jobs: Iterable[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]],
    per_job_timeout: float = 6,
    total_timeout: float = 20,
    max_workers: int = 4,
) -> list[Any]:
    start = time.monotonic()
    jobs = list(jobs)
    results: list[Any] = []
    result_queue: queue.Queue[Any] = queue.Queue()
    semaphore = threading.BoundedSemaphore(max(1, max_workers))

    def runner(index: int, func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        acquired = semaphore.acquire(timeout=max(0.1, total_timeout))
        if not acquired:
            return
        try:
            result_queue.put((index, func(*args, **kwargs)))
        except Exception:
            result_queue.put((index, None))
        finally:
            semaphore.release()

    threads = [
        threading.Thread(target=runner, args=(index, func, args, kwargs), daemon=True)
        for index, (func, args, kwargs) in enumerate(jobs)
    ]
    for thread in threads:
        thread.start()

    completed: set[int] = set()
    while len(completed) < len(jobs) and time.monotonic() - start < total_timeout:
        remaining = max(0.1, total_timeout - (time.monotonic() - start))
        try:
            index, value = result_queue.get(timeout=min(0.25, remaining))
        except queue.Empty:
            continue
        if index in completed:
            continue
        completed.add(index)
        results.append(value)
    return results


def extension_from_response(url: str, content_type: str = "") -> str:
    parsed_ext = re.sub(r"[^a-zA-Z0-9.]", "", urlparse(url).path.rsplit("/", 1)[-1].rsplit(".", 1)[-1]) if "." in urlparse(url).path else ""
    if parsed_ext and len(parsed_ext) <= 5:
        return f".{parsed_ext.lower()}"
    if content_type:
        content_type = content_type.split(";", 1)[0].strip().lower()
        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            return guessed
        if "html" in content_type:
            return ".html"
        if "pdf" in content_type:
            return ".pdf"
    return ".html"


def html_link_manifest(items: Iterable[dict[str, Any]], title: str = "Links") -> str:
    rows = []
    for item in items:
        item_title = html.escape(str(item.get("title") or item.get("url") or "Untitled"))
        url = html.escape(str(item.get("url") or ""))
        source = html.escape(str(item.get("source") or ""))
        date = html.escape(str(item.get("date") or ""))
        kind = html.escape(str(item.get("kind") or item.get("form") or ""))
        note = html.escape(str(item.get("note") or ""))
        rows.append(
            "<tr>"
            f"<td>{source}</td><td>{kind}</td><td>{date}</td>"
            f"<td><a href=\"{url}\">{item_title}</a></td><td>{note}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:Arial,sans-serif;margin:24px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px}"
        "th{background:#f2f6fb;text-align:left}</style></head><body>"
        f"<h1>{html.escape(title)}</h1><table>"
        "<thead><tr><th>Source</th><th>Type</th><th>Date</th><th>Title</th><th>Note</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
    )


def search_url(query: str) -> str:
    return f"https://cn.bing.com/search?q={quote_plus(query)}&setlang=zh-CN&cc=CN"


def fallback_links(company: dict[str, Any], kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
    name = company.get("name") or company.get("name_en") or company.get("ticker") or "company"
    ticker = company.get("ticker") or company.get("local_code") or ""
    ir_url = company.get("ir_url", "")
    market = company.get("market", "")
    selected = set(kinds or [])
    suffix = " annual report investor relations filetype:pdf"
    links: list[LinkResult] = []
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
        links.append(LinkResult("Bing PDF 搜索", search_url(f"{name} {ticker} {suffix}"), "兜底链接", kind="搜索", is_direct_file=False))
    return [item.__dict__ for item in links]

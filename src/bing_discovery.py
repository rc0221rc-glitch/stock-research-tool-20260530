from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .utils import DEFAULT_HEADERS, LinkResult, dedupe_links, request_text, run_limited


FILE_TERMS = {
    "annual": ["annual report filetype:pdf", "年度报告 PDF", "年报 PDF", "form 20-F pdf", "10-K pdf"],
    "quarterly": ["quarterly results pdf", "quarterly report pdf", "interim report pdf", "季报 PDF", "中报 PDF", "季度报告 PDF"],
    "transcript": ["earnings call transcript", "conference call transcript", "业绩会纪要", "电话会纪要", "业绩说明会纪要", "交流纪要", "专家交流纪要", "专家电话会纪要", "产业链专家交流", "渠道调研纪要"],
    "presentation": ["earnings presentation filetype:pdf", "investor presentation filetype:pdf", "results presentation filetype:pdf", "业绩演示材料 PDF", "业绩发布材料 PDF", "投资者演示 PDF"],
    "prospectus": ["prospectus pdf", "招股说明书 PDF"],
    "proxy": ["proxy statement", "DEF 14A pdf"],
}

DOCUMENT_TOKENS = {
    "annual": ["annual", "report", "20-f", "10-k", "年度报告", "年报", ".pdf"],
    "quarterly": ["quarter", "interim", "results", "report", "季报", "中报", "季度", "业绩", ".pdf"],
    "transcript": ["transcript", "conference call", "earnings call", "prepared remarks", "电话会", "业绩会", "纪要", "交流", "专家", "调研", "渠道"],
    "presentation": ["presentation", "slides", "deck", "results", "investor", "业绩", "演示", "材料", ".pdf"],
    "prospectus": ["prospectus", "招股说明书", ".pdf"],
    "proxy": ["proxy", "def 14a", ".pdf"],
}

BLOCKED_DOMAINS = {
    "bing.com",
    "microsoft.com",
    "youtube.com",
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "pinterest.com",
}

PDF_KINDS = {"annual", "quarterly", "presentation", "prospectus", "proxy"}
BING_ENDPOINTS = [
    ("https://www.bing.com/search", "en-US", "US"),
    ("https://cn.bing.com/search", "zh-CN", "CN"),
    ("https://www2.bing.com/search", "en-US", "US"),
]


@dataclass(frozen=True)
class QueryJob:
    query: str
    kind: str
    year: str = ""
    quarter: str = ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            deduped.append(cleaned)
    return deduped


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _localized_file_terms(kind: str, china_company: bool) -> list[str]:
    terms = FILE_TERMS.get(kind, [])
    if not china_company:
        return terms
    cjk_terms = [term for term in terms if _contains_cjk(term)]
    other_terms = [term for term in terms if term not in cjk_terms]
    return [*cjk_terms, *other_terms]


def _company_terms(company: dict[str, Any]) -> list[str]:
    aliases = company.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []
    raw_terms = [
        company.get("name"),
        company.get("name_en"),
        *aliases,
        company.get("ticker"),
        company.get("local_code"),
    ]
    return _dedupe([str(value) for value in raw_terms if value])


def _is_china_company(company: dict[str, Any]) -> bool:
    text = " ".join(
        str(company.get(key, ""))
        for key in ["name", "name_en", "market", "country", "exchange"]
    )
    return any(token in text for token in ["中国", "港股", "A股", "沪深", "台股", "台湾"])


def _quarter_phrases(quarters: list[str] | None, china_company: bool) -> list[tuple[str, str]]:
    selected = _dedupe([str(quarter) for quarter in (quarters or []) if quarter])
    if not selected:
        return [("", "")]

    phrases: list[tuple[str, str]] = []
    if "全年" in selected:
        phrases.append(("", "全年"))

    aliases = {
        "Q1": ["Q1", "一季度"] if china_company else ["Q1", "first quarter"],
        "Q2": ["Q2", "二季度", "中期"] if china_company else ["Q2", "second quarter"],
        "Q3": ["Q3", "三季度"] if china_company else ["Q3", "third quarter"],
        "Q4": ["Q4", "四季度", "全年"] if china_company else ["Q4", "fourth quarter"],
    }
    for quarter in selected:
        if quarter in aliases:
            for phrase in aliases[quarter][:2]:
                phrases.append((phrase, quarter))
    return _dedupe_quarter_phrases(phrases) or [("", "")]


def _dedupe_quarter_phrases(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[tuple[str, str]] = []
    for phrase, quarter in values:
        key = (phrase.casefold(), quarter.casefold())
        if key not in seen:
            seen.add(key)
            deduped.append((phrase, quarter))
    return deduped


def _date_phrases(kind: str, years: list[str] | None, quarters: list[str] | None, china_company: bool) -> list[tuple[str, str, str]]:
    selected_years = _dedupe([str(year) for year in (years or []) if year]) or [""]
    quarter_phrases = _quarter_phrases(quarters, china_company)

    if kind in {"annual", "prospectus", "proxy"}:
        return [(year, year, "") for year in selected_years]

    phrases: list[tuple[str, str, str]] = []
    for year in selected_years:
        for quarter_phrase, quarter in quarter_phrases:
            if not quarter_phrase:
                phrases.append((year, year, quarter))
                continue
            if china_company and any("\u4e00" <= char <= "\u9fff" for char in quarter_phrase):
                phrases.append((f"{year} {quarter_phrase}".strip(), year, quarter))
            else:
                phrases.append((f"{quarter_phrase} {year}".strip(), year, quarter))
    return _dedupe_date_phrases(phrases) or [("", "", "")]


def _dedupe_date_phrases(values: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str, str]] = []
    for phrase, year, quarter in values:
        key = f"{phrase}|{year}|{quarter}".casefold()
        if key not in seen:
            seen.add(key)
            deduped.append((phrase, year, quarter))
    return deduped


def _official_domain(company: dict[str, Any]) -> str:
    ir_url = str(company.get("ir_url") or "")
    parsed = urlparse(ir_url if "://" in ir_url else f"https://{ir_url}")
    return parsed.netloc.casefold().replace("www.", "")


def _query_jobs(
    company: dict[str, Any],
    kinds: list[str],
    years: list[str] | None,
    quarters: list[str] | None,
    max_queries: int,
) -> list[QueryJob]:
    company_terms = _company_terms(company)
    if not company_terms:
        return []

    china_company = _is_china_company(company)
    official_domain = _official_domain(company)
    if china_company:
        cjk_terms = [term for term in company_terms if _contains_cjk(term)]
        non_cjk_terms = [term for term in company_terms if term not in cjk_terms]
        primary_company_terms = [*cjk_terms[:2], *non_cjk_terms[:3]][:4]
    else:
        aliases = company.get("aliases") if isinstance(company.get("aliases"), list) else []
        primary_company_terms = _dedupe(
            [
                str(company.get("name_en") or ""),
                *[str(alias) for alias in aliases if alias],
                str(company.get("ticker") or ""),
                str(company.get("local_code") or ""),
                str(company.get("name") or ""),
            ]
        )[:3]
    primary_company_terms = primary_company_terms or company_terms[:2]
    cjk_company_terms = [term for term in primary_company_terms if _contains_cjk(term)] or primary_company_terms[:2]
    per_kind_limit = max(8, max_queries // max(1, len(kinds)))
    jobs: list[QueryJob] = []

    def add(candidates: list[QueryJob], query: str, kind: str, year: str = "", quarter: str = "") -> None:
        query = " ".join(query.split())
        if not query:
            return
        job = QueryJob(query=query, kind=kind, year=year, quarter=quarter)
        if job not in candidates:
            candidates.append(job)

    for kind in kinds:
        file_terms = _localized_file_terms(kind, china_company)
        if not file_terms:
            continue
        date_terms = _date_phrases(kind, years, quarters, china_company)
        candidates: list[QueryJob] = []

        if china_company and kind == "transcript":
            for date_text, year, quarter in date_terms[:6]:
                for company_term in cjk_company_terms[:2]:
                    for suffix in ["业绩会纪要", "电话会纪要", "业绩说明会纪要", "交流纪要", "专家交流纪要", "专家电话会纪要", "行业专家交流", "产业链专家交流", "渠道调研纪要", "草根调研纪要"]:
                        add(candidates, " ".join(part for part in [company_term, date_text, suffix] if part), kind, year, quarter)
                        add(candidates, " ".join(part for part in ["site:mp.weixin.qq.com", company_term, date_text, suffix] if part), kind, year, quarter)

        if china_company and kind == "presentation":
            for date_text, year, quarter in date_terms[:6]:
                for company_term in cjk_company_terms[:2]:
                    for suffix in ["业绩演示材料 PDF", "业绩发布材料 PDF", "路演材料 PDF"]:
                        add(candidates, " ".join(part for part in [company_term, date_text, suffix] if part), kind, year, quarter)

        for date_text, year, quarter in date_terms:
            for company_term in primary_company_terms[:2]:
                add(candidates, " ".join(part for part in [company_term, date_text, file_terms[0]] if part), kind, year, quarter)

        for date_text, year, quarter in date_terms[:8]:
            for file_term in file_terms[1:3]:
                add(candidates, " ".join(part for part in [primary_company_terms[0], date_text, file_term] if part), kind, year, quarter)

        if official_domain and kind in PDF_KINDS:
            for date_text, year, quarter in date_terms[:8]:
                query = " ".join(part for part in [f"site:{official_domain}", primary_company_terms[0], date_text, file_terms[0]] if part)
                add(candidates, query, kind, year, quarter)

        jobs.extend(candidates[:per_kind_limit])
        if len(jobs) >= max_queries:
            return jobs[:max_queries]

    return jobs


def _build_bing_url(endpoint: str, query: str, limit: int, language: str, country: str) -> str:
    params = [
        f"q={quote_plus(query)}",
        f"count={limit}",
        f"setlang={language}",
        f"cc={country}",
    ]
    if language.startswith("en"):
        params.append("ensearch=1")
    return f"{endpoint}?{'&'.join(params)}"


def _unwrap_bing_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if "bing.com" not in parsed.netloc.casefold():
        return url

    params = parse_qs(parsed.query)
    encoded = (params.get("u") or [""])[0]
    if not encoded:
        return url
    encoded = unquote(encoded)
    if encoded.startswith(("http://", "https://")):
        return encoded
    if encoded.startswith("a1"):
        encoded = encoded[2:]
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="ignore")
    except Exception:
        return url
    return decoded if decoded.startswith(("http://", "https://")) else url


def _domain_matches(host: str, domain: str) -> bool:
    if not host or not domain:
        return False
    host = host.casefold().replace("www.", "")
    domain = domain.casefold().replace("www.", "")
    return host == domain or host.endswith(f".{domain}") or domain.endswith(f".{host}")


def _company_needles(company: dict[str, Any]) -> list[str]:
    return [term.casefold() for term in _company_terms(company) if len(term) >= 2]


def _is_good_result(title: str, url: str, company: dict[str, Any], kind: str, year: str = "") -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.casefold().replace("www.", "")
    if not host or any(host == blocked or host.endswith(f".{blocked}") for blocked in BLOCKED_DOMAINS):
        return False

    combined = f"{title} {url}".casefold()
    needles = _company_needles(company)
    official_domain = _official_domain(company)
    official_match = _domain_matches(host, official_domain)
    if not official_match and needles and not any(needle in combined for needle in needles):
        return False

    if year and year not in combined and kind in PDF_KINDS:
        return False

    tokens = DOCUMENT_TOKENS.get(kind, [])
    if tokens and not any(token.casefold() in combined for token in tokens):
        return False

    if kind in PDF_KINDS:
        looks_specific = any(token in combined for token in [".pdf", year, "download", "report", "presentation", "results", "公告", "报告", "材料"])
        if not looks_specific:
            return False
    return True


def _link_result(title: str, url: str, job: QueryJob) -> LinkResult:
    return LinkResult(
        title=title,
        url=url,
        source="Bing 定向搜索",
        date=job.year,
        form=job.quarter,
        kind=job.kind,
        is_direct_file=".pdf" in url.casefold(),
        note=f"查询：{job.query}",
    )


def _parse_bing_results(html: str, job: QueryJob, company: dict[str, Any], limit: int) -> list[LinkResult]:
    soup = BeautifulSoup(html, "lxml")
    if not soup.select("li.b_algo"):
        return []

    results: list[LinkResult] = []
    for item in soup.select("li.b_algo")[:limit]:
        link = item.select_one("h2 a[href]")
        if not link:
            continue
        raw_url = link.get("href") or ""
        url = _unwrap_bing_url(urljoin("https://www.bing.com", raw_url))
        title = link.get_text(" ", strip=True)
        if not url.startswith("http"):
            continue
        if not _is_good_result(title, url, company, job.kind, job.year):
            continue
        results.append(_link_result(title, url, job))
    return results


def _parse_bing_rss(xml_text: str, job: QueryJob, company: dict[str, Any], limit: int) -> list[LinkResult]:
    soup = BeautifulSoup(xml_text, "xml")
    results: list[LinkResult] = []
    for item in soup.find_all("item")[:limit]:
        title = item.title.get_text(" ", strip=True) if item.title else ""
        url = item.link.get_text(" ", strip=True) if item.link else ""
        url = _unwrap_bing_url(url)
        if not title or not url.startswith("http"):
            continue
        if not _is_good_result(title, url, company, job.kind, job.year):
            continue
        results.append(_link_result(title, url, job))
    return results


def _result_score(result: LinkResult, company: dict[str, Any]) -> int:
    url = result.url.casefold()
    title = result.title.casefold()
    host = urlparse(result.url).netloc.casefold().replace("www.", "")
    score = 0
    if result.is_direct_file:
        score += 40
    if _domain_matches(host, _official_domain(company)):
        score += 25
    if any(domain in host for domain in ["sec.gov", "hkexnews.hk", "cninfo.com.cn", "static.cninfo.com.cn"]):
        score += 18
    if str(result.date or "") and str(result.date) in f"{title} {url}":
        score += 8
    if result.kind == "transcript" and any(token in f"{title} {url}" for token in ["transcript", "纪要", "电话会", "专家", "调研"]):
        score += 8
    if result.kind == "presentation" and any(token in f"{title} {url}" for token in ["presentation", "slides", "演示", "材料", ".pdf"]):
        score += 8
    return score


def _bing_search(job: QueryJob, company: dict[str, Any], limit: int = 5) -> list[LinkResult]:
    headers = {
        **DEFAULT_HEADERS,
        "User-Agent": "Mozilla/5.0 (compatible; GlobalFilingResearchTool/1.0; +https://github.com/rc0221rc-glitch/stock-research-tool-20260530)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for endpoint, language, country in BING_ENDPOINTS:
        try:
            html = request_text(
                _build_bing_url(endpoint, job.query, limit, language, country),
                timeout=8,
                headers={**headers, "Accept-Language": f"{language},{language.split('-')[0]};q=0.9,en;q=0.8"},
            )
        except Exception:
            continue
        results = _parse_bing_results(html, job, company, limit)
        if results:
            return results

    for endpoint, language, country in BING_ENDPOINTS[:2]:
        try:
            rss = request_text(
                f"{_build_bing_url(endpoint, job.query, limit, language, country)}&format=rss",
                timeout=8,
                headers={**headers, "Accept": "application/rss+xml,application/xml,text/xml,*/*"},
            )
        except Exception:
            continue
        results = _parse_bing_rss(rss, job, company, limit)
        if results:
            return results
    return []


def _search_suggestion(job: QueryJob) -> LinkResult:
    return LinkResult(
        title=f"Bing 定向搜索：{job.query}",
        url=f"https://www.bing.com/search?q={quote_plus(job.query)}",
        source="Bing 定向搜索",
        date=job.year,
        form=job.quarter,
        kind="搜索",
        is_direct_file=False,
        note="自动解析结果较少，可打开 Bing 继续人工筛选。",
    )


def _balanced_suggestion_jobs(jobs: list[QueryJob], limit: int) -> list[QueryJob]:
    if limit <= 0:
        return []
    buckets: dict[str, list[QueryJob]] = {}
    for job in jobs:
        buckets.setdefault(job.kind, []).append(job)

    selected: list[QueryJob] = []
    while len(selected) < limit and any(buckets.values()):
        for kind in list(buckets):
            if not buckets[kind]:
                continue
            candidate = buckets[kind].pop(0)
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) >= limit:
                break
    return selected


def find_bing_targeted_links(
    company: dict[str, Any],
    kinds: list[str] | None = None,
    years: list[str] | None = None,
    quarters: list[str] | None = None,
    max_results: int = 30,
    max_queries: int = 90,
    max_search_attempts: int = 24,
) -> list[dict[str, Any]]:
    selected_kinds = [kind for kind in (kinds or ["annual", "quarterly", "transcript", "presentation"]) if kind in FILE_TERMS]
    jobs = _query_jobs(company, selected_kinds, years, quarters, max_queries=max_queries)
    if not jobs:
        return []

    searchable_jobs = _balanced_suggestion_jobs(jobs, min(len(jobs), max_search_attempts))
    search_jobs = [(_bing_search, (job, company, 5), {}) for job in searchable_jobs]
    results: list[LinkResult] = []
    for group in run_limited(search_jobs, per_job_timeout=7, total_timeout=28, max_workers=8):
        if isinstance(group, list):
            results.extend(group)
        if len(results) >= max_results * 2:
            break

    results = sorted(dedupe_links(results), key=lambda item: _result_score(LinkResult(**item), company), reverse=True)
    suggestion_limit = min(max_results, 12)
    if len(results) < suggestion_limit:
        existing = {item.get("url") for item in results}
        for suggestion in [_search_suggestion(job) for job in _balanced_suggestion_jobs(jobs, suggestion_limit)]:
            if suggestion.url not in existing:
                results.append(suggestion.__dict__)
            if len(results) >= suggestion_limit:
                break
    return results[:max_results]

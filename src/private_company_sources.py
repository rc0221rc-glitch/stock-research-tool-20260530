from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

from bs4 import BeautifulSoup

from .utils import LinkResult, dedupe_links, request_text, run_limited


PRIVATE_SOURCE_QUERIES: dict[str, list[tuple[str, str, str]]] = {
    "OPENAI": [
        ("Official OpenAI", "site:openai.com OpenAI revenue API pricing enterprise customers compute partnership", "company"),
        ("Microsoft IR", "site:microsoft.com/en-us/Investor OpenAI Azure AI capex partnership", "partner"),
        ("Reuters", "site:reuters.com OpenAI revenue ARR funding users API pricing compute", "media"),
        ("The Information", "site:theinformation.com OpenAI revenue ARR funding compute", "media"),
        ("Semafor", "site:semafor.com OpenAI revenue funding users", "media"),
        ("CNBC", "site:cnbc.com OpenAI revenue funding users", "media"),
        ("OpenAI Careers", "site:openai.com/careers OpenAI infrastructure compute training cluster", "hiring"),
        ("OpenAI Blog Pricing", "site:openai.com pricing API model", "pricing"),
    ],
    "ANTHROPIC": [
        ("Official Anthropic", "site:anthropic.com Anthropic Claude API pricing enterprise compute partnership", "company"),
        ("Amazon IR", "site:ir.aboutamazon.com Anthropic AWS investment partnership", "partner"),
        ("Google Blog", "site:cloud.google.com Anthropic Google Cloud partnership TPU", "partner"),
        ("Reuters", "site:reuters.com Anthropic revenue ARR funding API pricing compute", "media"),
        ("CNBC", "site:cnbc.com Anthropic funding revenue Amazon Google", "media"),
        ("Anthropic Careers", "site:anthropic.com/careers infrastructure compute cluster", "hiring"),
        ("Anthropic Pricing", "site:anthropic.com pricing Claude API", "pricing"),
    ],
    "XAI": [
        ("Official xAI", "site:x.ai Grok API pricing funding compute Colossus", "company"),
        ("Reuters", "site:reuters.com xAI funding valuation Grok compute Colossus", "media"),
        ("CNBC", "site:cnbc.com xAI funding valuation Grok", "media"),
        ("The Information", "site:theinformation.com xAI revenue funding compute", "media"),
        ("xAI Careers", "site:x.ai/careers infrastructure compute data center", "hiring"),
        ("Supermicro xAI", "site:supermicro.com xAI Colossus GPU", "supplier"),
        ("NVIDIA xAI", "site:nvidia.com xAI Grok GPU", "supplier"),
    ],
}

PRIVATE_SEED_LINKS: dict[str, list[LinkResult]] = {
    "OPENAI": [
        LinkResult("OpenAI API pricing", "https://openai.com/api/pricing/", "Official OpenAI", kind="private_company", is_direct_file=False, note="private_company_signal:pricing"),
        LinkResult("OpenAI for business", "https://openai.com/business/", "Official OpenAI", kind="private_company", is_direct_file=False, note="private_company_signal:enterprise_customers"),
        LinkResult("Microsoft investor relations", "https://www.microsoft.com/en-us/Investor/", "Microsoft IR", kind="private_company", is_direct_file=False, note="private_company_signal:partner_disclosure"),
        LinkResult("OpenAI careers", "https://openai.com/careers/", "Official OpenAI", kind="private_company", is_direct_file=False, note="private_company_signal:hiring_compute"),
    ],
    "ANTHROPIC": [
        LinkResult("Anthropic Claude pricing", "https://www.anthropic.com/pricing", "Official Anthropic", kind="private_company", is_direct_file=False, note="private_company_signal:pricing"),
        LinkResult("Anthropic enterprise", "https://www.anthropic.com/enterprise", "Official Anthropic", kind="private_company", is_direct_file=False, note="private_company_signal:enterprise_customers"),
        LinkResult("Amazon investor relations", "https://ir.aboutamazon.com/", "Amazon IR", kind="private_company", is_direct_file=False, note="private_company_signal:partner_disclosure"),
        LinkResult("Anthropic careers", "https://www.anthropic.com/careers", "Official Anthropic", kind="private_company", is_direct_file=False, note="private_company_signal:hiring_compute"),
    ],
    "XAI": [
        LinkResult("xAI Grok", "https://x.ai/grok", "Official xAI", kind="private_company", is_direct_file=False, note="private_company_signal:product_users"),
        LinkResult("xAI API", "https://x.ai/api", "Official xAI", kind="private_company", is_direct_file=False, note="private_company_signal:api_pricing"),
        LinkResult("xAI careers", "https://x.ai/careers", "Official xAI", kind="private_company", is_direct_file=False, note="private_company_signal:hiring_compute"),
        LinkResult("NVIDIA news", "https://nvidianews.nvidia.com/", "NVIDIA News", kind="private_company", is_direct_file=False, note="private_company_signal:supplier_disclosure"),
    ],
}


def find_private_company_evidence(company: dict[str, Any], max_results: int = 10) -> list[dict[str, Any]]:
    ticker = str(company.get("ticker") or company.get("name") or "").upper()
    name = str(company.get("name") or ticker)
    templates = PRIVATE_SOURCE_QUERIES.get(ticker) or _generic_private_queries(name)
    jobs = [(_search, (query, source, kind, 3), {}) for source, query, kind in templates]
    results: list[LinkResult] = []
    for group in run_limited(jobs, per_job_timeout=7, total_timeout=24, max_workers=6):
        if isinstance(group, list):
            results.extend(group)
        if len(results) >= max_results:
            break
    results = [*(PRIVATE_SEED_LINKS.get(ticker) or []), *results]
    return dedupe_links(results)[:max_results]


def _generic_private_queries(name: str) -> list[tuple[str, str, str]]:
    return [
        ("Official", f"site:{_domain_guess(name)} {name} revenue funding API pricing compute", "company"),
        ("Reuters", f"site:reuters.com {name} revenue funding valuation users compute", "media"),
        ("CNBC", f"site:cnbc.com {name} funding revenue valuation", "media"),
        ("Careers", f"{name} careers infrastructure compute cluster", "hiring"),
    ]


def _domain_guess(name: str) -> str:
    return "".join(char for char in name.lower() if char.isalnum()) + ".com"


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
        lower = f"{title} {url}".casefold()
        if any(blocked in lower for blocked in ["youtube.com", "reddit.com", "linkedin.com", "facebook.com"]):
            continue
        if not any(token in lower for token in ["fund", "revenue", "arr", "api", "pricing", "compute", "gpu", "cloud", "career", "partnership", "investment", "valuation", "user", "customer", "colossus", "aws", "azure", "tpu", "claude", "grok", "openai", "anthropic"]):
            continue
        results.append(
            LinkResult(
                title=title,
                url=url,
                source=source,
                kind="private_company",
                is_direct_file=".pdf" in url.casefold(),
                note=f"private_company_signal:{kind}",
            )
        )
    return results


def _extract_search_url(href: str) -> str:
    if "duckduckgo.com" in href.casefold():
        parsed = urlparse(href)
        return parse_qs(parsed.query).get("uddg", [""])[0]
    return href

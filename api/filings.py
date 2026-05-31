from __future__ import annotations

import importlib
from http.server import BaseHTTPRequestHandler

from ._common import anthropic_key, error_response, handle_options, json_response, read_json_body, runtime_note


MODULE_NAMES = {
    "sec": "src.filing_fetcher_us",
    "hkex": "src.hkex_fetcher",
    "cninfo": "src.cninfo_fetcher",
    "ir": "src.ir_scraper",
    "transcript": "src.transcript_fetcher",
    "china": "src.china_sources",
    "bing": "src.bing_discovery",
    "platforms": "src.platform_discovery",
    "utils": "src.utils",
}


def load_modules() -> dict[str, object]:
    modules: dict[str, object] = {}
    for name, module_path in MODULE_NAMES.items():
        try:
            modules[name] = importlib.import_module(module_path)
        except Exception:
            pass
    return modules


def filter_results_by_years(items: list[dict], years: list[str]) -> list[dict]:
    if not years:
        return items
    selected = set(years)
    strict_sources = {"SEC EDGAR", "SEC EDGAR 附件", "巨潮资讯官方公告", "港交所披露易", "IR 官网", "IR 官网 Presentation", "IR (Q4 Events)"}
    filtered = []
    for item in items:
        source = str(item.get("source", ""))
        if source not in strict_sources:
            filtered.append(item)
            continue
        text = " ".join(str(item.get(field, "")) for field in ["date", "title", "url"])
        if any(year in text for year in selected):
            filtered.append(item)
    return filtered or items


def collect_filings(company: dict, kinds: list[str], years: list[str], quarters: list[str]) -> list[dict]:
    modules = load_modules()
    results: list[dict] = []
    sec = modules.get("sec")
    cninfo = modules.get("cninfo")
    ir = modules.get("ir")
    transcript = modules.get("transcript")
    china = modules.get("china")
    bing = modules.get("bing")
    platforms = modules.get("platforms")
    utils = modules.get("utils")
    key = anthropic_key()
    sec_kinds = [kind for kind in kinds if kind in {"annual", "quarterly", "prospectus", "presentation", "proxy"}]
    if sec and company.get("cik") and sec_kinds:
        try:
            results.extend(sec.fetch_sec_filings_for_years(company["cik"], kinds=sec_kinds, years=years, limit_per_year=12, include_exhibits=("presentation" in kinds)))
        except Exception:
            pass
    if cninfo and any(kind in kinds for kind in ["annual", "quarterly"]):
        try:
            results.extend(cninfo.fetch_cninfo_filings(company, kinds=kinds, years=years, quarters=quarters, limit=30))
        except Exception:
            pass
    if ir and any(kind in kinds for kind in ["annual", "quarterly", "presentation"]):
        try:
            results.extend(ir.find_ir_documents(company, kinds=kinds, claude_api_key=key, max_results=8))
        except Exception:
            pass
    filing_dates = [item.get("date", "") for item in results if item.get("date")]
    if transcript and "transcript" in kinds:
        try:
            results.extend(transcript.find_transcripts(company.get("ticker") or company.get("local_code") or "", company.get("name_en") or company.get("name") or "", filing_dates=filing_dates, max_results=10))
        except Exception:
            pass
    if china and any(kind in kinds for kind in ["annual", "quarterly", "transcript", "presentation"]):
        try:
            results.extend(china.find_china_research_links(company, kinds=kinds, years=years, quarters=quarters, max_results=16))
        except Exception:
            pass
    if bing and any(kind in kinds for kind in ["annual", "quarterly", "transcript", "presentation", "prospectus", "proxy"]):
        try:
            results.extend(bing.find_bing_targeted_links(company, kinds=kinds, years=years, quarters=quarters, max_results=20, max_search_attempts=8))
        except Exception:
            pass
    if platforms and any(kind in kinds for kind in ["transcript", "presentation"]):
        try:
            results.extend(platforms.discover_platform_links(company, kinds=kinds, years=years, quarters=quarters, max_results=16))
        except Exception:
            pass
    if utils:
        if not results:
            return utils.fallback_links(company, kinds)
        results = utils.dedupe_links(results)
    return filter_results_by_years(results, years)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        handle_options(self)

    def do_POST(self) -> None:
        if handle_options(self):
            return
        try:
            body = read_json_body(self)
            company = body.get("company") or {}
            kinds = body.get("kinds") or ["annual"]
            years = body.get("years") or []
            quarters = body.get("quarters") or []
            if not company:
                error_response(self, "Missing company", status=400)
                return
            results = collect_filings(company, kinds, years, quarters)
            json_response(self, {"results": results, "note": runtime_note()})
        except Exception as exc:
            error_response(self, str(exc))

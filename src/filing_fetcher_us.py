from __future__ import annotations

import re
import time
from typing import Any

from .utils import LinkResult, dedupe_links, request_json


FORM_MAP = {
    "annual": {"10-K", "10-K/A", "20-F", "20-F/A", "40-F"},
    "quarterly": {"10-Q", "10-Q/A", "6-K", "6-K/A"},
    "prospectus": {"S-1", "S-1/A", "F-1", "F-1/A", "424B4", "424B5", "FWP"},
    "presentation": {"8-K", "6-K"},
    "proxy": {"DEF 14A", "DEFA14A", "PRE 14A"},
}


def normalize_cik(cik: str | int) -> str:
    return str(cik).strip().lstrip("0").zfill(10)


def _archive_urls(cik: str, accession: str, primary_document: str) -> tuple[str, str]:
    cik_int = str(int(cik))
    accession_clean = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}"
    return f"{base}/{primary_document}", f"{base}/{accession}-index.html"


def _matches_year(filing_date: str, year: str | int | None, tolerance: int = 1) -> bool:
    if not year or str(year) in {"最新", "不限", "全部", "latest"}:
        return True
    try:
        filing_year = int(filing_date[:4])
        target_year = int(year)
    except Exception:
        return True
    return abs(filing_year - target_year) <= tolerance


def fetch_sec_filings(
    cik: str | int,
    kinds: list[str] | None = None,
    year: str | int | None = None,
    limit: int = 40,
    include_exhibits: bool = False,
) -> list[dict[str, Any]]:
    if not cik:
        return []
    selected_kinds = kinds or ["annual"]
    wanted_forms = set().union(*(FORM_MAP.get(kind, set()) for kind in selected_kinds))
    if not wanted_forms:
        wanted_forms = FORM_MAP["annual"]
    normalized_cik = normalize_cik(cik)
    try:
        data = request_json(f"https://data.sec.gov/submissions/CIK{normalized_cik}.json", timeout=12)
    except Exception:
        return []

    filing_sets = [data.get("filings", {}).get("recent", {})]
    need_older = bool(year and str(year) not in {"最新", "不限", "全部", "latest"})
    results: list[LinkResult] = []
    for filing_set in filing_sets:
        forms = filing_set.get("form", [])
        dates = filing_set.get("filingDate", [])
        accessions = filing_set.get("accessionNumber", [])
        documents = filing_set.get("primaryDocument", [])
        descriptions = filing_set.get("primaryDocDescription", [""] * len(forms))
        for form, filing_date, accession, document, description in zip(forms, dates, accessions, documents, descriptions):
            if form not in wanted_forms:
                continue
            if not _matches_year(filing_date, year):
                continue
            primary_url, index_url = _archive_urls(normalized_cik, accession, document)
            kind = next((key for key, values in FORM_MAP.items() if form in values), "filing")
            title = f"{form} {filing_date} {description or document}".strip()
            results.append(
                LinkResult(
                    title=title,
                    url=primary_url,
                    source="SEC EDGAR",
                    date=filing_date,
                    form=form,
                    kind=kind,
                    index_url=index_url,
                    is_direct_file=True,
                )
            )
            if len(results) >= limit:
                break
            time.sleep(0.03)
        if len(results) >= limit:
            break
    if need_older and len(results) < limit:
        for filing_set in _fetch_older_filing_sets(data):
            forms = filing_set.get("form", [])
            dates = filing_set.get("filingDate", [])
            accessions = filing_set.get("accessionNumber", [])
            documents = filing_set.get("primaryDocument", [])
            descriptions = filing_set.get("primaryDocDescription", [""] * len(forms))
            for form, filing_date, accession, document, description in zip(forms, dates, accessions, documents, descriptions):
                if form not in wanted_forms or not _matches_year(filing_date, year):
                    continue
                primary_url, index_url = _archive_urls(normalized_cik, accession, document)
                kind = next((key for key, values in FORM_MAP.items() if form in values), "filing")
                results.append(
                    LinkResult(
                        title=f"{form} {filing_date} {description or document}".strip(),
                        url=primary_url,
                        source="SEC EDGAR",
                        date=filing_date,
                        form=form,
                        kind=kind,
                        index_url=index_url,
                        is_direct_file=True,
                    )
                )
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

    if include_exhibits and "presentation" in selected_kinds:
        results.extend(fetch_sec_exhibit_links(normalized_cik, selected_kinds, year=year, limit=10))
    return dedupe_links(results)


def _fetch_older_filing_sets(submissions: dict[str, Any]) -> list[dict[str, list[Any]]]:
    older_sets: list[dict[str, list[Any]]] = []
    for file_info in submissions.get("filings", {}).get("files", [])[:8]:
        name = file_info.get("name", "")
        if not name:
            continue
        try:
            data = request_json(f"https://data.sec.gov/submissions/{name}", timeout=10)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("form"):
            older_sets.append(data)
        time.sleep(0.05)
    return older_sets


def fetch_sec_exhibit_links(cik: str | int, kinds: list[str] | None = None, year: str | int | None = None, limit: int = 10) -> list[dict[str, Any]]:
    filings = fetch_sec_filings(cik, kinds=["presentation"], year=year, limit=20, include_exhibits=False)
    results: list[LinkResult] = []

    for filing in filings:
        index_url = filing.get("index_url", "")
        url = filing.get("url", "")
        if not index_url or not url:
            continue
        base_url = url.rsplit("/", 1)[0]
        json_url = f"{base_url}/index.json"
        try:
            data = request_json(json_url, timeout=8)
        except Exception:
            continue
        for item in data.get("directory", {}).get("item", []):
            filename = item.get("name", "")
            dtype = item.get("type", "")
            combined = f"{filename} {dtype}".casefold()
            if not filename:
                continue
            if any(skip in combined for skip in ["-index", ".xsd", ".xml", ".jpg", ".png", ".gif", "xbrl"]):
                continue
            is_likely_exhibit = dtype.upper().startswith("EX-") or re.search(r"ex(?:99|10|hibit)", combined)
            is_likely_presentation = any(token in combined for token in ["presentation", "slides", "deck", "investor", "earnings", "ex99", "ex-99"])
            if not (is_likely_exhibit and is_likely_presentation):
                continue
            exhibit_url = f"{base_url}/{filename}"
            results.append(
                LinkResult(
                    title=f"{filing.get('form', 'SEC')} 附件 {dtype or filename}",
                    url=exhibit_url,
                    source="SEC EDGAR 附件",
                    date=filing.get("date", ""),
                    form=f"{filing.get('form', '')} exhibit",
                    kind="presentation",
                    index_url=index_url,
                    is_direct_file=True,
                )
            )
            if len(results) >= limit:
                return dedupe_links(results)
    return dedupe_links(results)

from __future__ import annotations

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

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    documents = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])
    results: list[LinkResult] = []
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
        time.sleep(0.05)

    if include_exhibits and "presentation" in selected_kinds:
        results.extend(fetch_sec_exhibit_links(normalized_cik, selected_kinds, year=year, limit=10))
    return dedupe_links(results)


def fetch_sec_exhibit_links(cik: str | int, kinds: list[str] | None = None, year: str | int | None = None, limit: int = 10) -> list[dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return []
    filings = fetch_sec_filings(cik, kinds=["presentation"], year=year, limit=20, include_exhibits=False)
    results: list[LinkResult] = []
    import requests

    for filing in filings:
        index_url = filing.get("index_url")
        if not index_url:
            continue
        try:
            response = requests.get(index_url, timeout=8, headers={"User-Agent": "GlobalFilingResearchTool/1.0 research@example.com"})
            response.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        table = soup.find("table", class_="tableFile")
        if not table:
            continue
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            if len(cells) < 4:
                continue
            description = " ".join(cells).casefold()
            if not any(token in description for token in ["presentation", "slides", "investor", "earnings"]):
                continue
            link = row.find("a")
            if not link or not link.get("href"):
                continue
            url = "https://www.sec.gov" + link["href"] if link["href"].startswith("/") else link["href"]
            results.append(
                LinkResult(
                    title=f"8-K 附件 {cells[1] or cells[2]}",
                    url=url,
                    source="SEC EDGAR 附件",
                    date=filing.get("date", ""),
                    form="8-K exhibit",
                    kind="presentation",
                    index_url=index_url,
                    is_direct_file=True,
                )
            )
            if len(results) >= limit:
                return dedupe_links(results)
    return dedupe_links(results)

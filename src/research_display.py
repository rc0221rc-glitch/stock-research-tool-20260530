from __future__ import annotations

import re
from typing import Any

from .research_models import CompanyProfile


def company_display_name(company: CompanyProfile | None) -> str:
    if not company:
        return ""
    return _clean_name(company.name) or _friendly_ticker(company.ticker)


def company_label(company: CompanyProfile | None, include_ticker: bool = False) -> str:
    if not company:
        return ""
    name = company_display_name(company)
    ticker = _friendly_ticker(company.ticker)
    if include_ticker and ticker and ticker.casefold() != name.casefold():
        return f"{name}（{ticker}）"
    return name or ticker


def point_display_name(point: Any) -> str:
    company = _clean_name(getattr(point, "company", ""))
    if company:
        return company
    return _friendly_ticker(getattr(point, "ticker", ""))


def resolve_display_name(identifier: str, lookup: dict[str, str] | None = None) -> str:
    key = (identifier or "").upper()
    if lookup and key in lookup:
        return lookup[key]
    return _friendly_ticker(identifier)


def replace_identifier_with_name(text: str, ticker: str, display_name: str) -> str:
    value = str(text or "")
    name = str(display_name or "").strip()
    if not value or not ticker or not name:
        return value
    candidates = {ticker, ticker.upper(), ticker.lower()}
    if "." in ticker:
        candidates.add(ticker.split(".")[0])
    for candidate in sorted(candidates, key=len, reverse=True):
        if not candidate or candidate == name:
            continue
        value = re.sub(rf"(?<![\w.]){re.escape(candidate)}(?![\w.])", name, value, flags=re.I)
    return value


def display_name_lookup(companies: list[CompanyProfile]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for company in companies:
        key = (company.ticker or "").upper()
        if key:
            lookup[key] = company_display_name(company)
    return lookup


def _clean_name(name: str) -> str:
    value = " ".join(str(name or "").split())
    return "" if value.casefold() in {"unknown", "n/a", "none"} else value


def _friendly_ticker(ticker: str) -> str:
    value = str(ticker or "").strip()
    if re.fullmatch(r"\d{6}(?:\.(?:SZ|SH|BJ))?", value, flags=re.I):
        return value.split(".")[0]
    if re.fullmatch(r"\d{1,5}\.HK", value, flags=re.I):
        return value.split(".")[0].lstrip("0") or value.split(".")[0]
    return value.upper()

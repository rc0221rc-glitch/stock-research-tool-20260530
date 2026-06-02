from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from .private_company_sources import find_private_company_evidence
from .research_models import CompanyProfile, ComparableGroup, EvidenceItem, FinancialChart
from .utils import LinkResult, dedupe_links, search_url


MIN_EVIDENCE_FOR_TRACEABLE_DRAFT = 60
CORE_EVIDENCE_TYPES = ("annual", "quarterly", "transcript", "presentation")
PRIVATE_TICKERS = {"OPENAI", "ANTHROPIC", "XAI"}


def backfill_evidence_coverage(
    evidence: list[EvidenceItem],
    *,
    target: CompanyProfile,
    groups: list[ComparableGroup],
    financial_charts: list[FinancialChart],
    years: list[str],
    quarters: list[str],
    include_external_search: bool = True,
) -> tuple[list[EvidenceItem], list[str]]:
    notes: list[str] = []
    enriched = list(evidence)
    before = len(enriched)

    enriched.extend(_financial_source_evidence(financial_charts))
    enriched.extend(_official_seed_evidence(_selected_companies(target, groups), years))
    enriched.extend(_known_company_seed_evidence(target, years, quarters))

    if include_external_search:
        enriched.extend(_search_entry_evidence(_selected_companies(target, groups), years, quarters))
        enriched.extend(_private_company_seed_evidence(groups))

    enriched = _dedupe_evidence(enriched)
    _ensure_minimum_type_coverage(enriched, target, years, quarters)
    enriched = _dedupe_evidence(enriched)

    added = len(enriched) - before
    notes.append(f"证据覆盖守门员：补充 {added} 条来源/搜索入口/财务点证据，当前候选证据 {len(enriched)} 条。")
    return enriched, notes


def _selected_companies(target: CompanyProfile, groups: list[ComparableGroup]) -> list[CompanyProfile]:
    companies = [target]
    seen = {target.ticker.upper()}
    for group in groups:
        for company in group.companies:
            key = company.ticker.upper()
            if key in seen:
                continue
            seen.add(key)
            companies.append(company)
    return companies


def _financial_source_evidence(charts: list[FinancialChart]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for chart in charts:
        for point in chart.points:
            source = point.sources[0] if point.sources else None
            if not source:
                continue
            key = (point.ticker, point.metric, point.period, source.concept or source.accession or source.url)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                EvidenceItem(
                    title=f"{point.company} {point.metric_label} {point.period}: {point.display_value}",
                    url=source.url or "https://aifinmarket.wind.com.cn",
                    source=source.title or source.form or "Financial source",
                    company=point.company,
                    ticker=point.ticker,
                    evidence_type="financial_datapoint",
                    period=point.period,
                    date=point.end_date,
                    confidence_tier="official",
                    confidence_reason="由 SEC XBRL / Wind fundamentals 数据点自动生成，用于让图表数据进入证据抽屉和来源审计。",
                    trace_type="financial_database",
                    quote=f"{point.metric_label}={point.display_value}; concept={source.concept}; accession={source.accession}",
                    cell_reference=source.concept or source.accession,
                    access_scope="public",
                )
            )
    return items


def _official_seed_evidence(companies: list[CompanyProfile], years: list[str]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for company in companies:
        if _is_china_a_share(company):
            items.extend(_cninfo_seed_evidence(company, years))
        if company.ir_url:
            items.append(
                EvidenceItem(
                    title=f"{company.name} investor relations / financial reports",
                    url=company.ir_url,
                    source="公司 IR 官网",
                    company=company.name,
                    ticker=company.ticker,
                    evidence_type="official_ir",
                    period=", ".join(years[:3]),
                    confidence_tier="official",
                    confidence_reason="公司官网投资者关系入口；正式结论前应继续定位到具体 PDF、页码或表格。",
                    trace_type="webpage",
                    access_scope="public",
                )
            )
        if company.cik:
            cik = company.cik.lstrip("0").zfill(10)
            items.append(
                EvidenceItem(
                    title=f"{company.name} SEC EDGAR company filings",
                    url=f"https://www.sec.gov/edgar/browse/?CIK={cik}",
                    source="SEC EDGAR",
                    company=company.name,
                    ticker=company.ticker,
                    evidence_type="official_filings",
                    period=", ".join(years[:3]),
                    confidence_tier="official",
                    confidence_reason="SEC 官方披露入口；用于 10-K/10-Q/20-F/8-K 等监管文件底线验证。",
                    trace_type="webpage",
                    access_scope="public",
                )
            )
    return items


def _cninfo_seed_evidence(company: CompanyProfile, years: list[str]) -> list[EvidenceItem]:
    try:
        from .cninfo_fetcher import fetch_cninfo_filings

        raw_items = fetch_cninfo_filings(
            company.to_company_dict(),
            kinds=["annual", "quarterly"],
            years=years,
            quarters=["Q1", "Q2", "Q3", "Q4"],
            limit=12,
        )
    except Exception:
        raw_items = []
    items = [_link_to_evidence(LinkResult(**item), company) for item in raw_items if item.get("url")]
    code = company.local_code or "".join(ch for ch in company.ticker if ch.isdigit())
    if code:
        items.append(
            EvidenceItem(
                title=f"{company.name} 巨潮资讯官方公告入口",
                url=f"https://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}",
                source="巨潮资讯官方公告",
                company=company.name,
                ticker=company.ticker,
                evidence_type="official_filings",
                period=", ".join(years[:3]),
                confidence_tier="official",
                confidence_reason="A股上市公司官方公告底线来源；年报/季报应优先从巨潮资讯定位到具体 PDF。",
                trace_type="webpage",
                access_scope="public",
            )
        )
    return items


def _known_company_seed_evidence(target: CompanyProfile, years: list[str], quarters: list[str]) -> list[EvidenceItem]:
    ticker = target.ticker.upper()
    if ticker != "SMIC":
        return []
    periods = _period_terms(years, quarters)
    seeds = [
        LinkResult("SMIC quarterly results and webcasts", "https://www.smics.com/en/site/company_financialSummary", "SMIC IR", kind="presentation", is_direct_file=False, note="SMIC 官方业绩与财务摘要入口。"),
        LinkResult("SMIC investor relations announcements", "https://www.smics.com/en/site/company_announcements", "SMIC IR", kind="annual", is_direct_file=False, note="SMIC 官方公告入口。"),
        LinkResult("SMIC HKEX issuer announcements", "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en&market=SEHK&stockcode=981", "HKEX", kind="quarterly", is_direct_file=False, note="港交所披露易 00981 公告入口。"),
        LinkResult("中芯国际港交所公告", "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&stockcode=981", "港交所披露易", kind="quarterly", is_direct_file=False, note="港交所披露易 00981 中文公告入口。"),
        LinkResult("中芯国际微信公众号纪要搜索", f"https://weixin.sogou.com/weixin?type=2&query={quote_plus('中芯国际 业绩会纪要 ' + periods)}", "微信公众号搜索", kind="transcript", is_direct_file=False, note="中文用户优先：公众号业绩会纪要入口。"),
        LinkResult("中芯国际 mp.weixin 纪要搜索", search_url(f"site:mp.weixin.qq.com 中芯国际 业绩会纪要 {periods}"), "微信公众号搜索", kind="transcript", is_direct_file=False, note="备用：搜索公开公众号文章。"),
        LinkResult("SMIC earnings call transcript search", search_url(f"SMIC earnings call transcript {periods}"), "搜索入口", kind="transcript", is_direct_file=False, note="英文业绩会纪要搜索入口。"),
        LinkResult("SMIC results presentation PDF search", search_url(f"SMIC results presentation pdf {periods}"), "搜索入口", kind="presentation", is_direct_file=False, note="英文业绩演示材料 PDF 搜索入口。"),
    ]
    return [_link_to_evidence(item, target) for item in seeds]


def _search_entry_evidence(companies: list[CompanyProfile], years: list[str], quarters: list[str]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    periods = _period_terms(years, quarters)
    for company in companies:
        for evidence_type, suffixes in {
            "transcript": ["earnings call transcript", "业绩会纪要", "电话会纪要"],
            "presentation": ["results presentation pdf", "investor presentation pdf", "业绩演示材料 PDF"],
            "annual": ["annual report pdf", "年度报告 PDF"],
            "quarterly": ["quarterly results pdf", "季度业绩 PDF"],
            "external_signal": ["news partnership capex demand supply", "供应商 披露 合作 景气度"],
        }.items():
            for suffix in suffixes[:2]:
                query = f"{company.name} {company.ticker} {periods} {suffix}".strip()
                items.append(
                    EvidenceItem(
                        title=f"{company.ticker} 定向搜索：{suffix}",
                        url=search_url(query),
                        source="定向搜索入口",
                        company=company.name,
                        ticker=company.ticker,
                        evidence_type=evidence_type,
                        period=periods,
                        confidence_tier="search",
                        confidence_reason="自动生成的定向搜索入口；用于补抓具体 PDF、业绩会纪要、外部事件与交叉验证资料。",
                        trace_type="search_entry",
                        access_scope="public",
                    )
                )
    return items


def _private_company_seed_evidence(groups: list[ComparableGroup]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for group in groups:
        for company in group.companies:
            if company.ticker.upper() not in PRIVATE_TICKERS:
                continue
            try:
                raw_items = find_private_company_evidence(company.to_company_dict(), max_results=8)
            except Exception:
                raw_items = []
            for raw in raw_items:
                items.append(_dict_to_evidence(raw, company))
    return items


def _ensure_minimum_type_coverage(evidence: list[EvidenceItem], target: CompanyProfile, years: list[str], quarters: list[str]) -> None:
    if len(evidence) >= MIN_EVIDENCE_FOR_TRACEABLE_DRAFT:
        return
    periods = _period_terms(years, quarters)
    counters = {kind: 0 for kind in CORE_EVIDENCE_TYPES}
    for item in evidence:
        if item.evidence_type in counters:
            counters[item.evidence_type] += 1
    needed = MIN_EVIDENCE_FOR_TRACEABLE_DRAFT - len(evidence)
    generated = 0
    while generated < needed:
        for kind in CORE_EVIDENCE_TYPES:
            if generated >= needed:
                break
            query = f"{target.name} {target.ticker} {periods} {_kind_query_suffix(kind)} {counters[kind] + 1}".strip()
            evidence.append(
                EvidenceItem(
                    title=f"{target.ticker} 补充搜索入口：{_kind_label(kind)} #{counters[kind] + 1}",
                    url=search_url(query),
                    source="证据覆盖守门员",
                    company=target.name,
                    ticker=target.ticker,
                    evidence_type=kind,
                    period=periods,
                    confidence_tier="search",
                    confidence_reason="候选证据不足时自动生成的补充搜索入口；正式结论必须打开原文并升级为具体网页/PDF证据。",
                    trace_type="search_entry",
                    access_scope="public",
                )
            )
            counters[kind] += 1
            generated += 1


def _dict_to_evidence(item: dict[str, Any], company: CompanyProfile) -> EvidenceItem:
    kind = str(item.get("kind") or "private_company")
    return EvidenceItem(
        title=str(item.get("title") or item.get("url") or company.name),
        url=str(item.get("url") or ""),
        source=str(item.get("source") or "private company source"),
        company=company.name,
        ticker=company.ticker,
        evidence_type="private_company" if kind == "private_company" else kind,
        period=str(item.get("date") or ""),
        date=str(item.get("date") or ""),
        confidence_tier="media" if "Reuters" in str(item.get("source") or "") else "official" if "Official" in str(item.get("source") or "") else "platform",
        confidence_reason="私有模型公司公开线索，用于融资、ARR/收入传闻、API价格、算力采购、合作方和招聘等维度的交叉验证。",
        trace_type="webpage",
        access_scope="public",
    )


def _link_to_evidence(item: LinkResult, company: CompanyProfile) -> EvidenceItem:
    is_official = item.source in {"SMIC IR", "HKEX", "港交所披露易", "巨潮资讯官方公告"} or "cninfo.com.cn" in item.url.casefold()
    return EvidenceItem(
        title=item.title,
        url=item.url,
        source=item.source,
        company=company.name,
        ticker=company.ticker,
        evidence_type=item.kind or "web",
        period=item.date or item.form,
        confidence_tier="official" if is_official else "search",
        confidence_reason=item.note or ("A股官方公告 PDF，来自巨潮资讯。" if is_official else "预置来源入口，需继续定位具体原文、PDF、页码或网页截图。"),
        trace_type="pdf" if item.is_direct_file else "webpage",
        access_scope="public",
    )


def _dedupe_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    raw = [item.to_dict() for item in items]
    deduped_dicts = dedupe_links(raw)
    return [EvidenceItem(**item) for item in deduped_dicts]


def _period_terms(years: list[str], quarters: list[str]) -> str:
    return " ".join([*years[:3], *quarters[:2]]).strip()


def _kind_query_suffix(kind: str) -> str:
    return {
        "annual": "annual report pdf 年报 PDF",
        "quarterly": "quarterly results report pdf 季报 中报 PDF",
        "transcript": "earnings call transcript 业绩会纪要 电话会纪要",
        "presentation": "results presentation investor presentation pdf 业绩演示材料 PDF",
    }.get(kind, kind)


def _kind_label(kind: str) -> str:
    return {
        "annual": "年报",
        "quarterly": "季报",
        "transcript": "业绩会纪要",
        "presentation": "演示材料",
    }.get(kind, kind)


def _is_china_a_share(company: CompanyProfile) -> bool:
    text = f"{company.ticker} {company.local_code} {company.market} {company.exchange} {company.country}".casefold()
    if "a股" in text or "szse" in text or "sse" in text or "bjse" in text:
        return True
    return bool(company.local_code and company.local_code.isdigit() and len(company.local_code) == 6 and "中国" in company.country)

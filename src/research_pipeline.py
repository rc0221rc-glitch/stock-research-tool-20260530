from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .research_financials import build_financial_charts
from .research_llm import generate_deepseek_research_signals, missing_deepseek_key_record, resolve_deepseek_api_key
from .research_models import AuditFinding, CompanyProfile, EvidenceItem, FinancialChart, ResearchDraft, ResearchSignal, SignalScore
from .research_universe import get_company_profile, recommend_comparable_groups
from .research_validation import validate_research_draft
from .utils import dedupe_links, run_limited


CORE_KINDS = ["annual", "quarterly", "transcript", "presentation"]
QUARTER_OPTIONS = ["Q1", "Q2", "Q3", "Q4"]


def recent_years_for_quarters(quarter_count: int, current_year: int | None = None) -> list[str]:
    current_year = current_year or datetime.now().year
    year_count = max(1, min(4, (quarter_count + 3) // 4 + 1))
    return [str(current_year - offset) for offset in range(year_count)]


def collect_research_draft(
    target_query: str,
    quarter_count: int = 4,
    comparable_groups: list[Any] | None = None,
    claude_api_key: str = "",
    deepseek_api_key: str = "",
    require_llm: bool = False,
    include_external_search: bool = True,
    max_companies: int = 12,
) -> ResearchDraft:
    target = get_company_profile(target_query)
    groups = comparable_groups or recommend_comparable_groups(target.ticker or target.name)
    companies = _selected_companies(target, groups, max_companies=max_companies)
    years = recent_years_for_quarters(quarter_count)
    quarters = QUARTER_OPTIONS

    jobs = []
    for company in companies:
        jobs.extend(_company_source_jobs(company, years, quarters, claude_api_key, include_external_search))
    evidence: list[EvidenceItem] = []
    run_notes: list[str] = []
    for result in run_limited(jobs, per_job_timeout=18, total_timeout=80, max_workers=8):
        if isinstance(result, tuple):
            items, notes = result
            evidence.extend(items)
            run_notes.extend(notes)

    evidence = _dedupe_evidence(evidence)
    financial_charts, financial_notes = build_financial_charts(companies, quarter_count=quarter_count)
    run_notes.extend(financial_notes)
    audit_findings = audit_evidence(evidence, target, groups, financial_charts)
    fallback_signals = build_signal_draft(evidence, target, groups, financial_charts)
    signals = fallback_signals
    next_fetch_plan = build_next_fetch_plan(evidence, signals, groups, financial_charts)
    model_runs = []
    deepseek_api_key = resolve_deepseek_api_key(deepseek_api_key)
    if deepseek_api_key:
        llm_signals, llm_plan, model_run = generate_deepseek_research_signals(
            api_key=deepseek_api_key,
            target_name=target.name,
            quarter_count=quarter_count,
            comparable_groups=groups,
            evidence=evidence,
            financial_charts=financial_charts,
            fallback_signals=fallback_signals,
        )
        model_runs.append(model_run)
        if model_run.status == "success":
            signals = llm_signals
            if llm_plan:
                next_fetch_plan = llm_plan
    elif require_llm:
        model_runs.append(missing_deepseek_key_record())
    draft = ResearchDraft(
        target=target,
        quarter_count=quarter_count,
        comparable_groups=groups,
        evidence=evidence,
        signals=signals,
        audit_findings=audit_findings,
        next_fetch_plan=next_fetch_plan,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        financial_charts=financial_charts,
        model_runs=model_runs,
        run_notes=run_notes,
    )
    draft.validation_report = validate_research_draft(draft)
    if any(run.status == "success" for run in model_runs):
        draft.report_label = "DeepSeek 已参与分析的内测研究草稿：仍需完成截图溯源、权限、队列等最终交付验收"
    else:
        draft.report_label = "可内测研究草稿：未成功调用大模型，未达到专业最终交付标准"
    return draft


def audit_evidence(evidence: list[EvidenceItem], target: CompanyProfile, groups: list[Any], financial_charts: list[FinancialChart] | None = None) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    by_company: dict[str, list[int]] = defaultdict(list)
    by_type: Counter[str] = Counter()
    for index, item in enumerate(evidence):
        by_company[(item.ticker or item.company).upper()].append(index)
        by_type[item.evidence_type or "unknown"] += 1

    target_key = target.ticker.upper()
    target_items = by_company.get(target_key, [])
    findings.append(
        AuditFinding(
            topic="目标公司证据覆盖",
            status="pass" if len(target_items) >= 3 else "warning",
            finding=f"已为 {target.name} 收集 {len(target_items)} 条候选证据；正式报告前至少需要覆盖官方披露、业绩会/PPT、外部交叉验证三类。",
            severity="info" if len(target_items) >= 3 else "warning",
            related_evidence_ids=target_items[:8],
        )
    )

    chart_count = len(financial_charts or [])
    point_count = sum(len(chart.points) for chart in (financial_charts or []))
    findings.append(
        AuditFinding(
            topic="真实财务图表覆盖",
            status="pass" if chart_count else "warning",
            finding=f"已生成 {chart_count} 个真实财务图表，包含 {point_count} 个 SEC XBRL 数据点；每个数据点都保留 SEC accession 来源链接。",
            severity="info" if chart_count else "warning",
            related_evidence_ids=[],
        )
    )

    official_ids = [index for index, item in enumerate(evidence) if item.confidence_tier == "official"]
    findings.append(
        AuditFinding(
            topic="官方来源底线",
            status="pass" if official_ids else "warning",
            finding=f"官方或监管来源候选证据 {len(official_ids)} 条。年报 / 季报 / 20-F / 10-Q 类判断必须优先引用这些来源。",
            severity="info" if official_ids else "warning",
            related_evidence_ids=official_ids[:8],
        )
    )

    transcript_ids = [index for index, item in enumerate(evidence) if item.evidence_type == "transcript"]
    presentation_ids = [index for index, item in enumerate(evidence) if item.evidence_type == "presentation"]
    findings.append(
        AuditFinding(
            topic="管理层表述与演示材料",
            status="pass" if transcript_ids or presentation_ids else "warning",
            finding=f"Transcript 候选 {len(transcript_ids)} 条，Presentation 候选 {len(presentation_ids)} 条；后续 AI 应重点比对措辞变化和经营分部口径。",
            severity="info" if transcript_ids or presentation_ids else "warning",
            related_evidence_ids=[*transcript_ids[:4], *presentation_ids[:4]],
        )
    )

    company_count = len(by_company)
    expected = 1 + sum(len(group.companies) for group in groups)
    findings.append(
        AuditFinding(
            topic="横向可比覆盖",
            status="pass" if company_count >= min(expected, 5) else "warning",
            finding=f"已覆盖 {company_count} 家公司 / 私有玩家，目标覆盖 {expected} 个研究对象；覆盖不足的对象会进入下一轮抓取计划。",
            severity="info" if company_count >= min(expected, 5) else "warning",
            related_evidence_ids=[],
        )
    )

    source_count = len({item.source for item in evidence if item.source})
    findings.append(
        AuditFinding(
            topic="交叉验证独立性",
            status="pass" if source_count >= 3 else "warning",
            finding=f"当前有 {source_count} 个来源名称。证据强结论要求至少 3 个独立可信来源交叉验证；不足时仅能进入待验证线索。",
            severity="info" if source_count >= 3 else "warning",
            related_evidence_ids=[],
        )
    )

    return findings


def build_signal_draft(evidence: list[EvidenceItem], target: CompanyProfile, groups: list[Any], financial_charts: list[FinancialChart] | None = None) -> list[ResearchSignal]:
    by_type = Counter(item.evidence_type or "unknown" for item in evidence)
    by_tier = Counter(item.confidence_tier for item in evidence)
    target_ids = [index for index, item in enumerate(evidence) if (item.ticker or "").upper() == target.ticker.upper()]
    transcript_ids = [index for index, item in enumerate(evidence) if item.evidence_type == "transcript"]
    presentation_ids = [index for index, item in enumerate(evidence) if item.evidence_type == "presentation"]
    official_ids = [index for index, item in enumerate(evidence) if item.confidence_tier == "official"]
    external_ids = [index for index, item in enumerate(evidence) if item.confidence_tier in {"media", "platform", "search"}]
    charts = financial_charts or []

    signals = [
        ResearchSignal(
            title="真实财务数据已进入图表层，但仍需 AI 继续挑选“最值得呈现”的异常维度",
            conclusion=f"本轮已基于 SEC XBRL 生成 {len(charts)} 个财务图表。它们覆盖收入、利润率/R&D 强度和可比公司横向对比；下一步应在这些真实数据上做纵向边际变化与横向背离扫描，而不是停留在证据目录。",
            signal_type="亮点：财务数据信号",
            status="evidence_backed" if charts else "data_gap",
            score=SignalScore(5, 5 if charts else 1, 4, 5, 4, 5),
            evidence_ids=official_ids[:6],
            chart_hint="真实财务趋势图 + 可比公司横向柱状图",
            chart_reason="折线/柱状组合可以同时呈现目标公司自身过去季度变化，以及与可比公司的同截面差异。",
            reasoning_summary="没有真实财务数据图表时，HTML 只能算研究流程草稿；有了 XBRL 数据后，才开始接近投资人可阅读交付物。",
            reasoning_chain=[
                "从 SEC companyfacts 拉取季度 XBRL 概念数据。",
                "对 revenue、gross profit、operating income、net income、R&D 等指标按季度归一。",
                "派生 gross margin、operating margin、R&D/revenue，并生成目标公司趋势和可比公司横向图。",
            ],
            next_validation_actions=[
                "把 SEC accession 升级为具体 filing 页面、表格位置和截图。",
                "继续补充非 SEC 公司，如 TSM、SK Hynix、Samsung 的 IR 表格数据。",
            ],
        ),
        ResearchSignal(
            title="AI 产业链景气度需要用“芯片—制造—云—基础设施”闭环验证",
            conclusion="当前草稿已建立多组可比与交叉验证对象；最终结论不应只看目标公司单季指标，而应同时验证上游供给约束、下游 CSP 资本开支和服务器/网络/电力散热交付。",
            signal_type="研究框架信号",
            status="evidence_backed" if len(groups) >= 3 and len(evidence) >= 8 else "needs_validation",
            score=SignalScore(5, min(5, 1 + len(groups)), 4, 5, 4, 4),
            evidence_ids=target_ids[:3] + official_ids[:3],
            chart_hint="产业链证据覆盖矩阵",
            chart_reason="矩阵最适合展示每个产业链环节是否已有官方披露、Transcript、Presentation 和外部交叉验证。",
            reasoning_summary="先确认哪些环节已有证据，再决定哪些指标值得深挖，避免预设指标导致遗漏真正关键变化。",
            reasoning_chain=[
                "将目标公司放入核心业务可比组、上游验证组、下游需求组和基础设施组。",
                "统计每组证据类型覆盖情况，识别缺口。",
                "只有跨组证据相互支持时，才把结论升级为强证据信号。",
            ],
            next_validation_actions=[
                "为覆盖不足的可比组补抓最近 4 个季度 transcript 与 presentation。",
                "抽取收入、毛利率、库存、CapEx、订单/backlog 与管理层措辞变化。",
            ],
        ),
        ResearchSignal(
            title="管理层措辞变化将是第一版深挖重点",
            conclusion=f"已发现 {by_type.get('transcript', 0)} 条 transcript 与 {by_type.get('presentation', 0)} 条 presentation 候选；这些材料最适合识别需求、供给、价格、客户结构和风险措辞的边际变化。",
            signal_type="高潜力待验证线索",
            status="needs_validation" if transcript_ids or presentation_ids else "data_gap",
            score=SignalScore(5, 3 if transcript_ids or presentation_ids else 1, 5, 5, 5, 4),
            evidence_ids=[*transcript_ids[:4], *presentation_ids[:4]],
            chart_hint="季度措辞热度折线 + 关键词证据抽屉",
            chart_reason="折线适合展示同一关键词簇在连续季度中的出现强度变化，点击点位可打开原文和截图。",
            reasoning_summary="AI 产业链拐点往往先出现在订单、供给、客户和价格的语气变化里，而不是只出现在财务表。",
            reasoning_chain=[
                "按季度切分管理层问答和 prepared remarks。",
                "抽取需求、供给、价格、库存、客户、竞争、CapEx 等关键词簇。",
                "与可比公司同季度措辞变化横向比较，找出目标公司的独特变化。",
            ],
            next_validation_actions=[
                "下载候选网页/PDF并转为可引用文本。",
                "生成每条措辞变化的原文引用和 PDF / 网页截图。",
            ],
        ),
        ResearchSignal(
            title="官方披露是财务与经营数据的底座",
            conclusion=f"当前草稿识别到 {by_tier.get('official', 0)} 条官方/监管候选证据。最终 HTML 中所有财务数据、比率和分部数据都应回链到官方文件页码或表格单元格。",
            signal_type="证据质量信号",
            status="evidence_backed" if official_ids else "data_gap",
            score=SignalScore(5, min(5, by_tier.get("official", 0)), 3, 5, 3, 5),
            evidence_ids=official_ids[:8],
            chart_hint="财务指标纵向折线 + 可比公司横向柱状图",
            chart_reason="折线适合显示目标公司连续季度边际变化，柱状图适合同一季度可比公司横向差异。",
            reasoning_summary="先把官方表格数据结构化，再让 AI 挑选显著优于/弱于自身历史与可比公司的维度。",
            reasoning_chain=[
                "对年报、季报、20-F、10-K、10-Q 提取表格。",
                "统一期间、币种、会计口径和分部口径。",
                "对所有候选指标做纵向和横向异常扫描。",
            ],
            next_validation_actions=[
                "对官方 PDF 执行表格抽取并记录表格页码。",
                "把每个图表数据点绑定到文件、页码和单元格来源。",
            ],
        ),
        ResearchSignal(
            title="外部公开信息可作为事件与私有玩家交叉验证",
            conclusion=f"当前草稿包含 {len(external_ids)} 条搜索/平台/媒体类候选证据。它们适合发现融资、ARR/收入传闻、API 价格、招聘、合作、供应商披露和突发事件，但正式强结论需要三方交叉验证。",
            signal_type="高潜力待验证线索",
            status="needs_validation" if external_ids else "data_gap",
            score=SignalScore(4, 2 + min(3, len(external_ids) // 3), 5, 4, 5, 3),
            evidence_ids=external_ids[:8],
            chart_hint="事件时间线 + 置信度标签",
            chart_reason="事件时间线最适合展示新闻、融资、合作、价格和人事事件如何与经营数据变化相互印证。",
            reasoning_summary="非财务事件可能是研究 alpha 的来源，但必须清楚标注公开可验证程度。",
            reasoning_chain=[
                "收集主流媒体、行业平台、公司公告和供应商披露。",
                "同一事件至少寻找三个独立来源或一个高权威源加两个弱源。",
                "把无法充分验证但有价值的内容放入高潜力待验证区域。",
            ],
            next_validation_actions=[
                "对私有模型公司补充融资、ARR、API 价格、用户增长和算力采购证据。",
                "对网页证据生成截图并保存原始链接。",
            ],
        ),
    ]
    return signals[:5]


def build_next_fetch_plan(evidence: list[EvidenceItem], signals: list[ResearchSignal], groups: list[Any], financial_charts: list[FinancialChart] | None = None) -> list[str]:
    plan = [
        "对已生成的 SEC XBRL 财务图表做异常扫描：同比/环比、利润率背离、R&D 强度、经营杠杆和可比公司横向排名。",
        "补抓每家核心可比公司最近 4 个季度的 earnings call transcript 与 presentation。",
        "对官方 PDF 执行表格抽取，建立指标-期间-来源页码-单元格映射。",
        "对管理层文字做季度切片，比较需求、供给、价格、库存、客户、CapEx、竞争等关键词簇。",
        "对 OpenAI / Anthropic / xAI 等私有玩家补抓融资估值、收入传闻、API 价格、模型能力和算力采购证据。",
    ]
    if any(signal.status != "evidence_backed" for signal in signals):
        plan.append("对待验证线索自动追加最多 3 轮搜索，并把冲突来源写入证据审计附录。")
    return plan


def _selected_companies(target: CompanyProfile, groups: list[Any], max_companies: int) -> list[CompanyProfile]:
    companies: list[CompanyProfile] = [target]
    seen = {target.ticker.upper()}
    for group in groups:
        for company in group.companies:
            key = company.ticker.upper()
            if key in seen:
                continue
            seen.add(key)
            companies.append(company)
            if len(companies) >= max_companies:
                return companies
    return companies


def _company_source_jobs(
    company: CompanyProfile,
    years: list[str],
    quarters: list[str],
    claude_api_key: str,
    include_external_search: bool,
) -> list[tuple[Any, tuple[Any, ...], dict[str, Any]]]:
    jobs: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []
    if company.is_public:
        if company.cik:
            jobs.append((_collect_sec_evidence, (company, years), {}))
        jobs.append((_collect_ir_evidence, (company, claude_api_key), {}))
        jobs.append((_collect_transcript_evidence, (company, claude_api_key), {}))
    if include_external_search:
        jobs.append((_collect_bing_evidence, (company, years, quarters), {}))
        jobs.append((_collect_platform_evidence, (company, years, quarters), {}))
        if _is_china_related(company):
            jobs.append((_collect_china_evidence, (company, years, quarters), {}))
    return jobs


def _collect_sec_evidence(company: CompanyProfile, years: list[str]) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .filing_fetcher_us import fetch_sec_filings_for_years

        raw_items = fetch_sec_filings_for_years(
            company.cik,
            kinds=["annual", "quarterly", "presentation"],
            years=years,
            limit_per_year=8,
            include_exhibits=True,
        )
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:16]], []
    except Exception as exc:
        return [], [f"{company.ticker}: SEC 抓取失败：{exc}"]


def _collect_ir_evidence(company: CompanyProfile, claude_api_key: str) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .ir_scraper import find_ir_documents

        raw_items = find_ir_documents(company.to_company_dict(), kinds=["annual", "quarterly", "presentation"], claude_api_key=claude_api_key, max_results=8)
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:12]], []
    except Exception as exc:
        return [], [f"{company.ticker}: IR 抓取失败：{exc}"]


def _collect_transcript_evidence(company: CompanyProfile, claude_api_key: str) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .transcript_fetcher import find_transcripts

        raw_items = find_transcripts(company.ticker, company.name, claude_api_key=claude_api_key, max_results=8)
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:12]], []
    except Exception as exc:
        return [], [f"{company.ticker}: Transcript 抓取失败：{exc}"]


def _collect_bing_evidence(company: CompanyProfile, years: list[str], quarters: list[str]) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .bing_discovery import find_bing_targeted_links

        raw_items = find_bing_targeted_links(
            company.to_company_dict(),
            kinds=CORE_KINDS,
            years=years,
            quarters=quarters,
            max_results=12,
            max_queries=32,
            max_search_attempts=10,
        )
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:12]], []
    except Exception as exc:
        return [], [f"{company.ticker}: Bing 定向搜索失败：{exc}"]


def _collect_platform_evidence(company: CompanyProfile, years: list[str], quarters: list[str]) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .platform_discovery import discover_platform_links

        raw_items = discover_platform_links(company.to_company_dict(), kinds=CORE_KINDS, years=years, quarters=quarters, max_results=8)
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:8]], []
    except Exception as exc:
        return [], [f"{company.ticker}: 平台搜索失败：{exc}"]


def _collect_china_evidence(company: CompanyProfile, years: list[str], quarters: list[str]) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .china_sources import find_china_research_links

        raw_items = find_china_research_links(company.to_company_dict(), kinds=CORE_KINDS, years=years, quarters=quarters, max_results=8)
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:8]], []
    except Exception as exc:
        return [], [f"{company.ticker}: 中文来源搜索失败：{exc}"]


def _to_evidence_item(item: dict[str, Any], company: CompanyProfile) -> EvidenceItem:
    source = str(item.get("source") or "")
    kind = str(item.get("kind") or item.get("form") or "").lower()
    url = str(item.get("url") or "")
    title = str(item.get("title") or url or "Untitled")
    confidence_tier, reason = _confidence_for_item(source, url)
    evidence_type = _kind_for_item(kind, title, url)
    return EvidenceItem(
        title=title,
        url=url,
        source=source or "unknown",
        company=company.name,
        ticker=company.ticker,
        evidence_type=evidence_type,
        period=str(item.get("quarter") or item.get("year") or ""),
        date=str(item.get("date") or ""),
        confidence_tier=confidence_tier,
        confidence_reason=reason,
        trace_type="pdf" if ".pdf" in url.lower() or item.get("is_direct_file") else "webpage",
        quote="",
        access_scope="public" if not item.get("is_user_provided") else "authorized",
    )


def _confidence_for_item(source: str, url: str) -> tuple[str, str]:
    text = f"{source} {url}".casefold()
    if "sec" in text or "edgar" in text or "cninfo" in text or "hkex" in text:
        return "official", "监管披露或官方公告平台，优先作为财务与公告事实来源。"
    if any(token in text for token in ["investor", "ir.", "investors.", "annualreports", "tsmc.com", "nvidia.com"]):
        return "official", "公司官网或投资者关系域名，适合作为公司原始披露来源。"
    if any(token in text for token in ["motley", "marketbeat", "stock analysis", "earningscall", "seekingalpha"]):
        return "platform", "第三方业绩会/投研平台，需要与官方材料或其他平台交叉验证。"
    if any(token in text for token in ["bloomberg", "reuters", "wsj", "financial times", "nikkei", "the information"]):
        return "media", "主流财经或行业媒体，可用于事件和外部验证。"
    if "search" in text or "bing" in text or "duckduckgo" in text:
        return "search", "搜索入口或搜索结果，需要打开原文后再升级置信度。"
    return "medium", "普通公开网页，正式结论前需要交叉验证。"


def _kind_for_item(kind: str, title: str, url: str) -> str:
    text = f"{kind} {title} {url}".casefold()
    if "transcript" in text or "call" in text or "纪要" in text:
        return "transcript"
    if "presentation" in text or "slide" in text or "deck" in text or "演示" in text:
        return "presentation"
    if "10-k" in text or "20-f" in text or "annual" in text or "年报" in text:
        return "annual"
    if "10-q" in text or "quarter" in text or "interim" in text or "季报" in text:
        return "quarterly"
    if any(token in text for token in ["valuation", "arr", "api", "pricing", "partnership", "hiring", "funding"]):
        return "external_signal"
    return kind or "web"


def _dedupe_evidence(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[str] = set()
    deduped: list[EvidenceItem] = []
    for item in items:
        key = item.url.casefold().strip().rstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _is_china_related(company: CompanyProfile) -> bool:
    text = f"{company.name} {company.market} {company.description}".casefold()
    return any(token in text for token in ["china", "hong kong", "taiwan", "中", "港", "台", "smic", "tsmc"])

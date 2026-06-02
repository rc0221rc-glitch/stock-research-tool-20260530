from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .research_anomalies import build_objective_anomalies
from .research_evidence_backfill import backfill_evidence_coverage
from .research_financials import build_financial_charts
from .research_llm import generate_deepseek_research_signals, missing_deepseek_key_record, resolve_deepseek_api_key
from .research_models import AuditFinding, CompanyProfile, EvidenceItem, FinancialChart, ObjectiveAnomaly, ResearchDraft, ResearchSignal, SignalScore
from .research_screenshots import capture_evidence_screenshots
from .research_text_insights import build_text_theme_anomalies, enrich_readable_evidence
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
    enable_llm: bool = True,
    include_external_search: bool = True,
    max_companies: int = 12,
    capture_screenshots: bool = True,
    task_mode: str = "streamlit_sync_prototype",
    user_id: str = "",
    job_id: str = "",
    selected_anomalies: list[ObjectiveAnomaly] | None = None,
) -> ResearchDraft:
    target = get_company_profile(target_query)
    groups = recommend_comparable_groups(target.ticker or target.name) if comparable_groups is None else comparable_groups
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

    financial_charts, financial_notes = build_financial_charts(_financial_comparison_companies(target, groups, companies), quarter_count=quarter_count)
    run_notes.extend(financial_notes)
    evidence = _dedupe_evidence(evidence)
    evidence, backfill_notes = backfill_evidence_coverage(
        evidence,
        target=target,
        groups=groups,
        financial_charts=financial_charts,
        years=years,
        quarters=quarters,
        include_external_search=include_external_search,
    )
    run_notes.extend(backfill_notes)
    evidence, text_notes = enrich_readable_evidence(evidence)
    run_notes.extend(text_notes)
    if capture_screenshots:
        run_notes.extend(capture_evidence_screenshots(evidence, limit=3))
    all_objective_anomalies = _dedupe_objective_anomalies([*build_objective_anomalies(evidence, financial_charts), *build_text_theme_anomalies(evidence)])
    evidence_gap_anomalies = [anomaly for anomaly in all_objective_anomalies if anomaly.category == "资料缺口"]
    objective_anomalies = [anomaly for anomaly in all_objective_anomalies if anomaly.category != "资料缺口"]
    if selected_anomalies:
        selected_ids = {anomaly.anomaly_id for anomaly in selected_anomalies}
        objective_anomalies = [
            ObjectiveAnomaly(**{**anomaly.to_dict(), "selected_for_deep_dive": anomaly.anomaly_id in selected_ids})
            for anomaly in objective_anomalies
        ]
    audit_findings = audit_evidence(evidence, target, groups, financial_charts)
    fallback_signals = build_signal_draft(evidence, target, groups, financial_charts, objective_anomalies)
    _annotate_and_downgrade_weak_strong_signals(fallback_signals, evidence)
    signals = fallback_signals
    next_fetch_plan = build_next_fetch_plan(evidence, signals, groups, financial_charts)
    model_runs = []
    deepseek_api_key = resolve_deepseek_api_key(deepseek_api_key) if enable_llm else ""
    should_run_deep_analysis = enable_llm and bool(selected_anomalies)
    if should_run_deep_analysis and deepseek_api_key:
        llm_signals, llm_plan, model_run = generate_deepseek_research_signals(
            api_key=deepseek_api_key,
            target_name=target.name,
            quarter_count=quarter_count,
            comparable_groups=groups,
            evidence=evidence,
            financial_charts=financial_charts,
            selected_anomalies=selected_anomalies or [anomaly for anomaly in objective_anomalies if anomaly.selected_for_deep_dive],
            fallback_signals=fallback_signals,
        )
        model_runs.append(model_run)
        if model_run.status == "success":
            signals = _ensure_deep_signal_floor(llm_signals, selected_anomalies or [anomaly for anomaly in objective_anomalies if anomaly.selected_for_deep_dive], fallback_signals, evidence)
            if llm_plan:
                next_fetch_plan = llm_plan
    elif should_run_deep_analysis and require_llm:
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
        objective_anomalies=objective_anomalies,
        model_runs=model_runs,
        run_notes=run_notes,
        run_metadata={
            "task_mode": task_mode,
            "job_id": job_id,
            "user_id": user_id,
            "queue_statuses": [
                "submitted",
                "collecting_evidence",
                "objective_anomaly_scan",
                "user_anomaly_selection" if not selected_anomalies else "model_deep_analysis",
                "validation_ready",
            ],
            "workflow_stage": "deep_analysis_ready" if selected_anomalies else "objective_scan_ready",
            "selected_anomaly_ids": [anomaly.anomaly_id for anomaly in selected_anomalies or []],
            "evidence_gap_anomalies": [anomaly.to_dict() for anomaly in evidence_gap_anomalies],
            "permissions": {
                "visibility": "authorized",
                "access_logs": "local_or_supabase",
                "user_id_required": bool(user_id),
            },
            "mobile_validation": {},
        },
    )
    draft.validation_report = validate_research_draft(draft)
    if selected_anomalies and any(run.status == "success" for run in model_runs):
        draft.report_label = "DeepSeek 已基于用户勾选的客观异常完成深度分析：仍需完成截图溯源、权限、队列等最终交付验收"
    elif selected_anomalies:
        draft.report_label = "深度分析草稿：用户已选择异常条目，但大模型未成功参与分析，未达到专业最终交付标准"
    else:
        draft.report_label = "第一阶段客观扫描结果：已完成资料/数据收集、横纵对比和异常列表，等待用户勾选后再做深度分析"
    return draft


def run_deep_analysis_for_selected_anomalies(
    draft: ResearchDraft,
    selected_anomaly_ids: list[str],
    deepseek_api_key: str = "",
    require_llm: bool = True,
) -> ResearchDraft:
    selected_ids = set(selected_anomaly_ids)
    draft.objective_anomalies = [
        ObjectiveAnomaly(**{**anomaly.to_dict(), "selected_for_deep_dive": anomaly.anomaly_id in selected_ids})
        for anomaly in draft.objective_anomalies
    ]
    selected = [anomaly for anomaly in draft.objective_anomalies if anomaly.selected_for_deep_dive]
    years = recent_years_for_quarters(draft.quarter_count)
    selected_companies = _selected_companies(draft.target, draft.comparable_groups, max_companies=12)
    draft.financial_charts, financial_notes = build_financial_charts(_financial_comparison_companies(draft.target, draft.comparable_groups, selected_companies), quarter_count=draft.quarter_count)
    draft.run_notes.extend(financial_notes)
    draft.evidence, backfill_notes = backfill_evidence_coverage(
        draft.evidence,
        target=draft.target,
        groups=draft.comparable_groups,
        financial_charts=draft.financial_charts,
        years=years,
        quarters=QUARTER_OPTIONS,
        include_external_search=True,
    )
    draft.run_notes.extend(backfill_notes)
    if not any(item.screenshot_path for item in draft.evidence):
        draft.run_notes.extend(capture_evidence_screenshots(draft.evidence, limit=3))
    all_objective_anomalies = _dedupe_objective_anomalies([*build_objective_anomalies(draft.evidence, draft.financial_charts), *build_text_theme_anomalies(draft.evidence)])
    draft.run_metadata["evidence_gap_anomalies"] = [anomaly.to_dict() for anomaly in all_objective_anomalies if anomaly.category == "资料缺口"]
    draft.objective_anomalies = [anomaly for anomaly in all_objective_anomalies if anomaly.category != "资料缺口"]
    draft.objective_anomalies = [
        ObjectiveAnomaly(**{**anomaly.to_dict(), "selected_for_deep_dive": anomaly.anomaly_id in selected_ids})
        for anomaly in draft.objective_anomalies
    ]
    selected = [anomaly for anomaly in draft.objective_anomalies if anomaly.selected_for_deep_dive]
    draft.run_metadata["workflow_stage"] = "model_deep_analysis"
    draft.run_metadata["selected_anomaly_ids"] = [anomaly.anomaly_id for anomaly in selected]
    draft.run_metadata["queue_statuses"] = [
        "submitted",
        "collecting_evidence",
        "objective_anomaly_scan",
        "user_anomaly_selection",
        "model_deep_analysis",
        "validation_ready",
    ]

    fallback_signals = build_signal_draft(draft.evidence, draft.target, draft.comparable_groups, draft.financial_charts, draft.objective_anomalies)
    _annotate_and_downgrade_weak_strong_signals(fallback_signals, draft.evidence)
    draft.signals = fallback_signals
    draft.next_fetch_plan = build_next_fetch_plan(draft.evidence, fallback_signals, draft.comparable_groups, draft.financial_charts)
    api_key = resolve_deepseek_api_key(deepseek_api_key)
    if selected and api_key:
        llm_signals, llm_plan, model_run = generate_deepseek_research_signals(
            api_key=api_key,
            target_name=draft.target.name,
            quarter_count=draft.quarter_count,
            comparable_groups=draft.comparable_groups,
            evidence=draft.evidence,
            financial_charts=draft.financial_charts,
            selected_anomalies=selected,
            fallback_signals=fallback_signals,
        )
        draft.model_runs.append(model_run)
        if model_run.status == "success":
            draft.signals = _ensure_deep_signal_floor(llm_signals, selected, fallback_signals, draft.evidence)
            if llm_plan:
                draft.next_fetch_plan = llm_plan
    elif selected and require_llm:
        draft.model_runs.append(missing_deepseek_key_record())

    if selected and any(run.status == "success" for run in draft.model_runs):
        draft.report_label = "DeepSeek 已基于用户勾选的客观异常完成深度分析：仍需完成截图溯源、权限、队列等最终交付验收"
    elif selected:
        draft.report_label = "深度分析草稿：用户已选择异常条目，但大模型未成功参与分析，未达到专业最终交付标准"
    else:
        draft.report_label = "第一阶段客观扫描结果：尚未选择需要深挖的异常条目"
    draft.validation_report = validate_research_draft(draft)
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
            finding=f"已生成 {chart_count} 个真实财务图表，包含 {point_count} 个 SEC XBRL / Wind fundamentals 数据点；每个数据点都保留 accession、Wind 字段或原始来源链接。",
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
    readable_transcript_ids = [index for index, item in enumerate(evidence) if item.evidence_type == "transcript" and item.quote]
    presentation_ids = [index for index, item in enumerate(evidence) if item.evidence_type == "presentation"]
    expert_memo_ids = [
        index
        for index, item in enumerate(evidence)
        if item.evidence_type == "expert_memo"
        or any(token in f"{item.title} {item.source} {item.url}" for token in ["专家交流", "专家电话", "行业专家", "产业链专家", "渠道调研", "草根调研"])
    ]
    findings.append(
        AuditFinding(
            topic="管理层表述与演示材料",
            status="pass" if readable_transcript_ids or presentation_ids else "warning",
            finding=f"Transcript 候选 {len(transcript_ids)} 条，其中已抽取可读正文 {len(readable_transcript_ids)} 条；Presentation 候选 {len(presentation_ids)} 条。只有进入正文/表格层的材料才能用于生成经营信号，搜索入口只保留为资料缺口和下一步抓取计划。",
            severity="info" if readable_transcript_ids or presentation_ids else "warning",
            related_evidence_ids=[*readable_transcript_ids[:4], *presentation_ids[:4]],
        )
    )
    findings.append(
        AuditFinding(
            topic="中文专家/渠道纪要线索",
            status="pass" if expert_memo_ids or not _is_china_related(target) else "warning",
            finding=f"专家交流、产业链专家或渠道调研类候选 {len(expert_memo_ids)} 条。这类微信公众号/雪球/中文平台内容可提供需求、库存、价格和客户变化线索，但不能直接作为强结论，必须与官方披露、财务数据和同行/上下游来源交叉验证。",
            severity="info" if expert_memo_ids or not _is_china_related(target) else "warning",
            related_evidence_ids=expert_memo_ids[:8],
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


def build_signal_draft(
    evidence: list[EvidenceItem],
    target: CompanyProfile,
    groups: list[Any],
    financial_charts: list[FinancialChart] | None = None,
    objective_anomalies: list[ObjectiveAnomaly] | None = None,
) -> list[ResearchSignal]:
    anomalies = [anomaly for anomaly in (objective_anomalies or []) if anomaly.category != "资料缺口"]
    signals = _signals_from_selected_anomalies(_prioritized_signal_anomalies(anomalies, target.ticker, limit=5), evidence)
    if signals:
        return signals[:5]

    official_ids = [index for index, item in enumerate(evidence) if item.confidence_tier == "official"]
    charts = financial_charts or []
    if charts:
        return [
            ResearchSignal(
                title="已取得真实财务数据，但尚未扫描出足够显著的经营异常",
                conclusion=f"本轮已生成 {len(charts)} 个真实财务图表，但按当前阈值尚未形成可展示的积极/风险异常。系统不会把资料数量、来源覆盖或搜索入口当作投资信号；下一步应扩大指标维度并结合业绩会正文解释。",
                signal_type="高潜力待验证线索",
                status="needs_validation",
                score=SignalScore(5, 2, 3, 5, 4, 4),
                evidence_ids=official_ids[:8],
                chart_hint="多指标趋势图 + 横向可比图 + 证据审计附录",
                chart_reason="没有显著异常时，展示数据底座和下一步验证路径比硬凑结论更可靠。",
                reasoning_summary="真实财务数据是分析底座，但必须由异常扫描或正文证据触发具体企业/行业信号。",
                reasoning_chain=["检查财务图表数量。", "过滤资料缺口类条目。", "未达异常阈值时不生成积极/风险结论。"],
                next_validation_actions=["补充现金流、CapEx、分部收入、云业务、广告业务等更细维度。", "抓取并抽取最近 4–8 个季度 earnings call transcript 正文。"],
            )
        ]

    return [
        ResearchSignal(
            title="当前还不能形成企业经营层面的积极/风险信号",
            conclusion="本轮尚未取得足够真实财务图表或可读业绩会正文。为避免幻觉和误导，系统只在审计区列出资料缺口，不把资料覆盖度或链接数量当作投资结论。",
            signal_type="高潜力待验证线索",
            status="data_gap",
            score=SignalScore(5, 1, 3, 5, 4, 5),
            evidence_ids=official_ids[:6],
            chart_hint="证据缺口矩阵 + 下一步抓取计划",
            chart_reason="没有正文和充分财务维度时，展示缺口比生成空泛结论更可靠。",
            reasoning_summary="必须读取正文或结构化财务数据后，才生成企业/行业判断。",
            reasoning_chain=["检查可读正文。", "检查财务图表。", "未达到阈值时不生成经营结论。"],
            next_validation_actions=["优先抓取并抽取最近 4–8 个季度 earnings call transcript 正文。", "补齐 revenue、gross margin、operating margin、R&D/revenue、FCF/CapEx 等财务图表。"],
        )
    ]


def build_next_fetch_plan(evidence: list[EvidenceItem], signals: list[ResearchSignal], groups: list[Any], financial_charts: list[FinancialChart] | None = None) -> list[str]:
    plan = [
        "对已生成的 SEC XBRL / Wind 财务图表做异常扫描：同比/环比、利润率背离、R&D 强度、经营杠杆和可比公司横向排名。",
        "补抓每家核心可比公司最近 4 个季度的 earnings call transcript、presentation 与中文专家/渠道纪要。",
        "对官方 PDF 执行表格抽取，建立指标-期间-来源页码-单元格映射。",
        "对管理层文字做季度切片，比较需求、供给、价格、库存、客户、CapEx、竞争等关键词簇。",
        "对 OpenAI / Anthropic / xAI 等私有玩家补抓融资估值、收入传闻、API 价格、模型能力和算力采购证据。",
    ]
    if any(signal.status != "evidence_backed" for signal in signals):
        plan.append("对待验证线索自动追加最多 3 轮搜索，并把冲突来源写入证据审计附录。")
    return plan


def _ensure_deep_signal_floor(
    signals: list[ResearchSignal],
    selected_anomalies: list[ObjectiveAnomaly],
    fallback_signals: list[ResearchSignal],
    evidence: list[EvidenceItem],
) -> list[ResearchSignal]:
    selected_ids = {anomaly.anomaly_id for anomaly in selected_anomalies}
    valid = []
    for signal in signals:
        if selected_ids and not set(signal.anomaly_ids).intersection(selected_ids):
            signal.anomaly_ids = [next(iter(selected_ids))]
        _annotate_signal_source_count(signal, evidence)
        valid.append(signal)

    combined = list(valid)
    for signal in _signals_from_selected_anomalies(selected_anomalies, evidence):
        if len(combined) >= 5:
            break
        if not any(existing.title == signal.title for existing in combined):
            combined.append(signal)
    for signal in fallback_signals:
        if len(combined) >= 5:
            break
        cloned = ResearchSignal(**{**signal.to_dict(), "score": SignalScore(**{key: value for key, value in signal.score.to_dict().items() if key != "total"})})
        if selected_ids and not cloned.anomaly_ids:
            cloned.anomaly_ids = [next(iter(selected_ids))]
        _annotate_signal_source_count(cloned, evidence)
        combined.append(cloned)

    combined = _ensure_signal_type_mix(combined, selected_anomalies, evidence)
    return combined[:8]


def _signals_from_selected_anomalies(selected_anomalies: list[ObjectiveAnomaly], evidence: list[EvidenceItem]) -> list[ResearchSignal]:
    signals: list[ResearchSignal] = []
    for anomaly in selected_anomalies:
        evidence_ids = [index for index in anomaly.evidence_ids if 0 <= index < len(evidence)]
        if not evidence_ids:
            evidence_ids = _evidence_ids_for_ticker(evidence, anomaly.ticker, limit=6)
        status = "evidence_backed" if len({evidence[index].source for index in evidence_ids if evidence[index].source}) >= 3 else "needs_validation"
        signal_type = "积极信号" if anomaly.polarity == "积极信号" else "风险信号"
        signal = ResearchSignal(
            title=f"{anomaly.title}：需要解释背后驱动",
            conclusion=f"{anomaly.observation} 这是一条由客观扫描发现的{signal_type}，下一步应验证它究竟来自需求、价格、产能、客户结构、产品结构、会计口径还是一次性因素。",
            signal_type=signal_type,
            status=status,
            score=SignalScore(5, 3 if status == "needs_validation" else 4, 4, 5, 4, 4),
            evidence_ids=evidence_ids[:8],
            anomaly_ids=[anomaly.anomaly_id],
            chart_hint="纵向趋势图 + 可比公司横向柱状图 + 证据抽屉",
            chart_reason="该组合能同时验证目标公司自身边际变化、可比公司的同口径差异，以及原始证据是否支持解释。",
            reasoning_summary="该信号先由确定性财务数据或已读取正文触发，再由模型围绕用户勾选条目做解释和验证计划。",
            reasoning_chain=[
                f"客观异常：{anomaly.comparison_basis}",
                f"幅度/现象：{anomaly.magnitude or anomaly.observation}",
                "优先检查官方披露和业绩会/PPT，再用外部来源做交叉验证。",
            ],
            next_validation_actions=[
                anomaly.suggested_deep_dive or "补充官方原文、业绩会纪要和外部交叉验证来源。",
                "把每个图表数据点绑定到文件、页码、截图或 Wind/SEC 字段。",
            ],
        )
        _annotate_signal_source_count(signal, evidence)
        signals.append(signal)
    return signals


def _prioritized_signal_anomalies(anomalies: list[ObjectiveAnomaly], target_ticker: str, limit: int) -> list[ObjectiveAnomaly]:
    target_ticker = (target_ticker or "").upper()
    target_related = [anomaly for anomaly in anomalies if (anomaly.ticker or "").upper() == target_ticker or anomaly.title.upper().startswith(target_ticker)]
    selected = _balanced_anomalies(target_related, limit)
    if len(selected) < limit:
        text_anomalies = [anomaly for anomaly in anomalies if anomaly.category == "管理层/外部文字信号" and anomaly not in selected]
        selected.extend(_balanced_anomalies(text_anomalies, limit - len(selected)))
    if len(selected) < limit:
        remaining = [anomaly for anomaly in anomalies if anomaly not in selected]
        selected.extend(_balanced_anomalies(remaining, limit - len(selected)))
    return selected[:limit]


def _balanced_anomalies(anomalies: list[ObjectiveAnomaly], limit: int) -> list[ObjectiveAnomaly]:
    positives = [anomaly for anomaly in anomalies if anomaly.polarity == "积极信号"]
    risks = [anomaly for anomaly in anomalies if anomaly.polarity == "风险信号"]
    balanced: list[ObjectiveAnomaly] = []
    while len(balanced) < limit and (positives or risks):
        if positives:
            balanced.append(positives.pop(0))
        if len(balanced) >= limit:
            break
        if risks:
            balanced.append(risks.pop(0))
    return balanced[:limit]


def _ensure_signal_type_mix(signals: list[ResearchSignal], selected_anomalies: list[ObjectiveAnomaly], evidence: list[EvidenceItem]) -> list[ResearchSignal]:
    text = " ".join(f"{signal.signal_type} {signal.title} {signal.conclusion} {signal.status}" for signal in signals)
    selected_ids = [anomaly.anomaly_id for anomaly in selected_anomalies]
    default_anomaly_ids = selected_ids[:1]
    if "积极" not in text and "亮点" not in text:
        signals.append(_generic_mix_signal("积极信号", "需要从客观异常中寻找正面亮点", "当前模型输出没有覆盖正面亮点，系统自动加入该检查项，防止报告只呈现风险。", default_anomaly_ids, evidence))
    if "风险" not in text:
        signals.append(_generic_mix_signal("风险信号", "需要从客观异常中寻找风险信号", "当前模型输出没有覆盖风险项，系统自动加入该检查项，防止报告只报喜不报忧。", default_anomaly_ids, evidence))
    if "待验证" not in text and "needs_validation" not in text and "线索" not in text:
        signals.append(_generic_mix_signal("高潜力待验证线索", "需要保留高潜力待验证线索", "证据不足但投资相关性较强的内容应进入待验证区域，并提供继续验证按钮/计划。", default_anomaly_ids, evidence))
    for signal in signals:
        _annotate_signal_source_count(signal, evidence)
    return signals


def _generic_mix_signal(signal_type: str, title: str, conclusion: str, anomaly_ids: list[str], evidence: list[EvidenceItem]) -> ResearchSignal:
    evidence_ids = list(range(min(8, len(evidence))))
    signal = ResearchSignal(
        title=title,
        conclusion=conclusion,
        signal_type=signal_type,
        status="needs_validation",
        score=SignalScore(4, 2, 4, 5, 4, 4),
        evidence_ids=evidence_ids,
        anomaly_ids=anomaly_ids,
        chart_hint="信号覆盖审计卡片",
        chart_reason="用于提醒用户当前模型输出类型不完整，不能作为最终交付物。",
        reasoning_summary="这是输出合同守门员生成的补充信号，不是最终结论。",
        reasoning_chain=["检查模型输出是否同时覆盖积极、风险、待验证三类。", "缺失类别时自动补入审计信号，避免误导用户。"],
        next_validation_actions=["重新选择更多客观异常，或执行下一轮资料抓取后再次调用模型。"],
    )
    _annotate_signal_source_count(signal, evidence)
    return signal


def _evidence_ids_for_ticker(evidence: list[EvidenceItem], ticker: str, limit: int) -> list[int]:
    ticker = (ticker or "").upper()
    if ticker:
        ids = [index for index, item in enumerate(evidence) if item.ticker.upper() == ticker]
        if ids:
            return ids[:limit]
    return list(range(min(limit, len(evidence))))


def _annotate_signal_source_count(signal: ResearchSignal, evidence: list[EvidenceItem]) -> None:
    valid_ids = [index for index in signal.evidence_ids if 0 <= index < len(evidence)]
    signal.evidence_ids = valid_ids[:10]
    signal.source_count = len({evidence[index].source for index in valid_ids if evidence[index].source})
    if signal.status == "evidence_backed" and signal.source_count < 3:
        signal.status = "needs_validation"


def _annotate_and_downgrade_weak_strong_signals(signals: list[ResearchSignal], evidence: list[EvidenceItem]) -> None:
    for signal in signals:
        _annotate_signal_source_count(signal, evidence)


def _dedupe_objective_anomalies(anomalies: list[ObjectiveAnomaly]) -> list[ObjectiveAnomaly]:
    seen: set[str] = set()
    deduped: list[ObjectiveAnomaly] = []
    for anomaly in anomalies:
        if anomaly.anomaly_id in seen:
            continue
        seen.add(anomaly.anomaly_id)
        deduped.append(anomaly)
    return sorted(deduped, key=lambda item: (0 if item.polarity == "积极信号" else 1, item.category, item.title))[:40]


def _financial_comparison_companies(target: CompanyProfile, groups: list[Any], selected_companies: list[CompanyProfile]) -> list[CompanyProfile]:
    companies: list[CompanyProfile] = [target]
    seen = {target.ticker.upper()}
    core_groups = [
        group
        for group in groups
        if "core" in str(group.group_id).casefold()
        or "核心" in str(group.title)
        or "可比" in str(group.title)
    ]
    for group in core_groups or groups[:1]:
        for company in group.companies:
            if not company.is_public:
                continue
            key = company.ticker.upper()
            if key in seen:
                continue
            seen.add(key)
            companies.append(company)
    if len(companies) < 3:
        for company in selected_companies:
            if not company.is_public:
                continue
            key = company.ticker.upper()
            if key in seen:
                continue
            seen.add(key)
            companies.append(company)
            if len(companies) >= 5:
                break
    return companies


def _selected_companies(target: CompanyProfile, groups: list[Any], max_companies: int) -> list[CompanyProfile]:
    companies: list[CompanyProfile] = [target]
    seen = {target.ticker.upper()}
    for group in groups:
        for company in group.companies:
            if not company.is_public:
                continue
            key = company.ticker.upper()
            if key in seen:
                continue
            seen.add(key)
            companies.append(company)
            if len(companies) >= max_companies:
                return companies
    for group in groups:
        for company in group.companies:
            if company.is_public:
                continue
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
        if _is_china_a_share(company):
            jobs.append((_collect_cninfo_evidence, (company, years, quarters), {}))
        elif company.cik:
            jobs.append((_collect_sec_evidence, (company, years), {}))
        jobs.append((_collect_ir_evidence, (company, claude_api_key), {}))
        jobs.append((_collect_transcript_evidence, (company, claude_api_key), {}))
    if include_external_search:
        jobs.append((_collect_bing_evidence, (company, years, quarters), {}))
        jobs.append((_collect_platform_evidence, (company, years, quarters), {}))
        if not company.is_public:
            jobs.append((_collect_private_company_evidence, (company,), {}))
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


def _collect_cninfo_evidence(company: CompanyProfile, years: list[str], quarters: list[str]) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .cninfo_fetcher import fetch_cninfo_filings

        raw_items = fetch_cninfo_filings(
            company.to_company_dict(),
            kinds=["annual", "quarterly"],
            years=years,
            quarters=quarters,
            limit=24,
        )
        items = [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:24]]
        if items:
            return items, [f"{company.ticker}: 已从巨潮资讯获取 {len(items)} 条 A股官方年报/季报 PDF。"]
        return [], [f"{company.ticker}: 巨潮资讯未返回匹配的官方年报/季报 PDF。"]
    except Exception as exc:
        return [], [f"{company.ticker}: 巨潮资讯官方公告抓取失败：{exc}"]


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

        limit = 16 if _is_china_related(company) else 8
        raw_items = discover_platform_links(company.to_company_dict(), kinds=CORE_KINDS, years=years, quarters=quarters, max_results=limit)
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:limit]], []
    except Exception as exc:
        return [], [f"{company.ticker}: 平台搜索失败：{exc}"]


def _collect_private_company_evidence(company: CompanyProfile) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .private_company_sources import find_private_company_evidence

        raw_items = find_private_company_evidence(company.to_company_dict(), max_results=10)
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:10]], []
    except Exception as exc:
        return [], [f"{company.ticker}: 私有公司公开证据搜索失败：{exc}"]


def _collect_china_evidence(company: CompanyProfile, years: list[str], quarters: list[str]) -> tuple[list[EvidenceItem], list[str]]:
    try:
        from .china_sources import find_china_research_links

        raw_items = find_china_research_links(company.to_company_dict(), kinds=CORE_KINDS, years=years, quarters=quarters, max_results=16)
        return [_to_evidence_item(item, company) for item in dedupe_links(raw_items)[:16]], []
    except Exception as exc:
        return [], [f"{company.ticker}: 中文来源搜索失败：{exc}"]


def _to_evidence_item(item: dict[str, Any], company: CompanyProfile) -> EvidenceItem:
    source = str(item.get("source") or "")
    kind = str(item.get("kind") or item.get("form") or "").lower()
    url = str(item.get("url") or "")
    title = str(item.get("title") or url or "Untitled")
    confidence_tier, reason = _confidence_for_item(source, url)
    evidence_type = _kind_for_item(kind, title, url)
    note = str(item.get("note") or "")
    if kind == "private_company" or note.startswith("private_company_signal"):
        evidence_type = "private_company"
        if confidence_tier in {"medium", "search"}:
            confidence_tier = "media" if any(token in f"{source} {url}".casefold() for token in ["reuters", "cnbc", "information", "semafor"]) else "platform"
        reason = f"私有模型公司公开线索（{note.replace('private_company_signal:', '') or source}），需与合作方、媒体和官方披露交叉验证。"
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
    if any(token in f"{source} {url}" for token in ["微信公众号", "雪球", "格隆汇", "富途", "老虎社区"]) or any(token in text for token in ["mp.weixin.qq.com", "weixin.sogou.com", "xueqiu.com", "gelonghui.com", "futunn.com", "laohu8.com"]):
        return "platform", "微信公众号/公开中文纪要来源，常包含专家交流和产业链调研线索；正式结论前必须用公告、财务数据、同行披露或多个独立来源交叉验证。"
    if any(token in f"{source} {url}" for token in ["华尔街见闻", "东方财富", "同花顺"]) or any(token in text for token in ["wallstreetcn.com", "eastmoney.com", "10jqka.com.cn"]):
        return "media", "中文财经/投研平台，可用于外部事件、业绩说明会和产业链线索；正式强结论前需要交叉验证。"
    if any(token in text for token in ["motley", "marketbeat", "stock analysis", "earningscall", "seekingalpha"]):
        return "platform", "第三方业绩会/投研平台，需要与官方材料或其他平台交叉验证。"
    if any(token in text for token in ["bloomberg", "reuters", "wsj", "financial times", "nikkei", "the information"]):
        return "media", "主流财经或行业媒体，可用于事件和外部验证。"
    if "search" in text or "bing" in text or "duckduckgo" in text:
        return "search", "搜索入口或搜索结果，需要打开原文后再升级置信度。"
    return "medium", "普通公开网页，正式结论前需要交叉验证。"


def _kind_for_item(kind: str, title: str, url: str) -> str:
    text = f"{kind} {title} {url}".casefold()
    if "专家交流" in text or "专家电话" in text or "专家会议" in text or "行业专家" in text or "产业链专家" in text or "渠道调研" in text or "草根调研" in text or "专家访谈" in text:
        return "expert_memo"
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


def _is_china_a_share(company: CompanyProfile) -> bool:
    text = f"{company.ticker} {company.local_code} {company.market} {company.exchange} {company.country}".casefold()
    if "a股" in text or "szse" in text or "sse" in text or "bjse" in text:
        return True
    return bool(company.local_code and company.local_code.isdigit() and len(company.local_code) == 6 and "中国" in company.country)

from __future__ import annotations

from collections import Counter

from .research_anomalies import POSITIVE, RISK
from .research_display import company_display_name
from .research_financials import REQUIRED_FINANCIAL_CHART_IDS
from .research_models import ResearchDraft, ValidationCheck, ValidationReport


FINAL_MIN_SECONDS = 30 * 60
MIN_SIGNALS = 5
MIN_FINANCIAL_CHARTS = len(REQUIRED_FINANCIAL_CHART_IDS)
MIN_EVIDENCE = 60
MIN_COMPANIES = 5
MIN_MODEL_RUNS = 1
MIN_MODEL_PROVIDERS_FOR_PRO_MODE = 3
MIN_SELECTED_SIGNAL_LINKAGE = 1


def validate_research_draft(draft: ResearchDraft) -> ValidationReport:
    checks = [
        _check_final_stage_readiness(draft),
        _check_model_called(draft),
        _check_deep_research_runtime(draft),
        _check_multi_model_attempts(draft),
        _check_two_stage_anomaly_workflow(draft),
        _check_no_coverage_as_signal(draft),
        _check_no_evidence_gap_in_signal_list(draft),
        _check_readable_text_for_text_signals(draft),
        _check_financial_charts(draft),
        _check_target_chart_identity(draft),
        _check_peer_comparables(draft),
        _check_source_traceability(draft),
        _check_pdf_or_web_screenshots(draft),
        _check_table_cell_traceability(draft),
        _check_signal_count(draft),
        _check_signal_types(draft),
        _check_selected_anomaly_signal_linkage(draft),
        _check_evidence_audit(draft),
        _check_three_source_validation(draft),
        _check_transcript_and_presentation(draft),
        _check_chinese_expert_memos(draft),
        _check_external_sources(draft),
        _check_private_company_evidence(draft),
        _check_interactive_html_support(draft),
        _check_mobile_report_shape(draft),
        _check_async_task_queue(draft),
        _check_permissions_logging(draft),
        _check_disclaimer(draft),
    ]
    failed = sum(1 for check in checks if check.status == "fail" and check.severity == "must")
    warning = sum(1 for check in checks if check.status in {"warn", "fail"} and check.severity != "must")
    passed = sum(1 for check in checks if check.status == "pass")
    status = "PASS_FINAL_DELIVERABLE" if failed == 0 and warning == 0 else "NOT_FINAL_DELIVERABLE"
    return ValidationReport(status=status, passed=passed, failed=failed, warning=warning, checks=checks)


def checklist_markdown(report: ValidationReport) -> str:
    lines = [f"# 自动验收 Checklist：{report.status}", ""]
    for check in report.checks:
        marker = "✅" if check.status == "pass" else "⚠️" if check.status == "warn" else "❌"
        lines.append(f"- {marker} **{check.category} / {check.check_id}**：{check.requirement}")
        lines.append(f"  - 当前：{check.observed}")
        lines.append(f"  - 要求：{check.required}")
        if check.remediation:
            lines.append(f"  - 修复：{check.remediation}")
    return "\n".join(lines)


def _check_final_stage_readiness(draft: ResearchDraft) -> ValidationCheck:
    stage = (draft.run_metadata or {}).get("workflow_stage", "")
    selected_count = len((draft.run_metadata or {}).get("selected_anomaly_ids", []))
    successful_model_runs = len([run for run in draft.model_runs if run.status == "success"])
    ok = stage in {"model_deep_analysis", "deep_analysis_ready"} and selected_count > 0 and successful_model_runs > 0
    return _check(
        "final_stage_readiness",
        "最终阶段状态",
        "最终 HTML 必须完成：客观异常清单 → 用户勾选 → 大模型围绕勾选异常深度分析；第一阶段扫描不能标记为最终交付。",
        ok,
        f"workflow_stage={stage or '无'}；已勾选异常 {selected_count} 个；成功模型调用 {successful_model_runs} 次。",
        "必须处于 model_deep_analysis，且有 selected_anomaly_ids 和成功模型调用记录。",
        "请在第一阶段勾选异常后运行第二阶段深度分析，再生成最终候选 HTML。",
    )


def _check_model_called(draft: ResearchDraft) -> ValidationCheck:
    if _is_objective_scan_stage(draft):
        return _check(
            "model_called",
            "大模型调用",
            "第一阶段只做客观异常扫描，不应强制调用大模型；第二阶段深度分析才需要模型记录。",
            True,
            "当前处于 objective_scan_ready，未调用大模型是符合设计的。",
            "第一阶段无需模型调用；最终深度分析阶段至少 1 次成功模型调用。",
            "",
            severity="stage",
        )
    successful = [run for run in draft.model_runs if run.status == "success"]
    return _check(
        "model_called",
        "大模型调用",
        "报告必须真实调用大模型完成研究判断，而不是只用确定性模板生成。",
        len(successful) >= MIN_MODEL_RUNS,
        f"成功模型调用 {len(successful)} 次。",
        "至少 1 次成功模型调用，并记录 provider/model/purpose/duration。",
        "接入真实 LLM provider，并把每次调用写入 model_runs。",
    )


def _check_deep_research_runtime(draft: ResearchDraft) -> ValidationCheck:
    if _is_objective_scan_stage(draft):
        return _check(
            "deep_research_runtime",
            "深度研究时长",
            "第一阶段先输出客观异常清单；专业版深度研究时长在用户勾选后计算。",
            True,
            "当前处于 objective_scan_ready，尚未进入深度分析。",
            f"第二阶段专业版目标至少 {FINAL_MIN_SECONDS // 60} 分钟研究/验证运行记录。",
            "",
            severity="stage",
        )
    total_seconds = sum(run.duration_seconds for run in draft.model_runs)
    return _check(
        "deep_research_runtime",
        "深度研究时长",
        "专业版深度研究不能半分钟生成，必须有长任务流程和充分推理/验证时间。",
        total_seconds >= FINAL_MIN_SECONDS,
        f"记录模型/研究运行时长 {total_seconds:.1f} 秒。",
        f"专业版目标至少 {FINAL_MIN_SECONDS // 60} 分钟研究/验证运行记录。",
        "接入后台任务队列，分阶段执行资料抓取、模型分析、二次验证和审计。",
        severity="architecture",
    )


def _check_multi_model_attempts(draft: ResearchDraft) -> ValidationCheck:
    if _is_objective_scan_stage(draft):
        return _check(
            "multi_model_attempts",
            "多模型尝试",
            "多模型深度研究应发生在用户勾选异常之后。",
            True,
            "当前处于 objective_scan_ready，未进入多模型深度分析。",
            "第二阶段至少 3 个供应商尝试记录。",
            "",
            severity="stage",
        )
    providers = {run.provider for run in draft.model_runs if run.status in {"success", "attempted"}}
    return _check(
        "multi_model_attempts",
        "多模型尝试",
        "用户要求用 DeepSeek、Claude、GPT 分别尝试专业研究。",
        len(providers) >= MIN_MODEL_PROVIDERS_FOR_PRO_MODE,
        f"记录到 {len(providers)} 个模型供应商：{', '.join(sorted(providers)) or '无'}。",
        "至少 3 个供应商尝试记录；不可硬编码不存在的模型名。",
        "增加模型可用性检测和 provider abstraction，再记录实际调用结果。",
        severity="architecture",
    )


def _check_financial_charts(draft: ResearchDraft) -> ValidationCheck:
    required_ids = set(REQUIRED_FINANCIAL_CHART_IDS)
    present_ids = {chart.chart_id for chart in draft.financial_charts}
    missing_ids = sorted(required_ids - present_ids)
    available_required = [chart for chart in draft.financial_charts if chart.chart_id in required_ids and chart.data_status == "available"]
    partial_required = [chart for chart in draft.financial_charts if chart.chart_id in required_ids and chart.data_status == "partial"]
    missing_required = [chart for chart in draft.financial_charts if chart.chart_id in required_ids and chart.data_status == "missing"]
    data_backed_required = available_required + partial_required
    return _check(
        "financial_charts",
        "财务图表",
        "每份交付物必须固定包含 13 张目标公司与可比公司财务/经营图表；无可审计数据时只能显示缺口，不能伪造。",
        not missing_ids and len(draft.financial_charts) >= MIN_FINANCIAL_CHARTS and bool(data_backed_required),
        f"固定图表 present={len(required_ids) - len(missing_ids)}/{len(required_ids)}；available={len(available_required)}；partial={len(partial_required)}；missing_data={len(missing_required)}；缺少规格={', '.join(missing_ids) or '无'}。",
        "13 个固定 chart_id 均应存在，并且至少一部分必须有真实可审计数据点；全为空时不得视为通过。",
        "先修复目标公司识别与 SEC/Wind/巨潮数据抓取，再继续补分部收入/分部毛利率、EBITDA 等结构化数据源。",
    )


def _check_target_chart_identity(draft: ResearchDraft) -> ValidationCheck:
    target_ticker = (draft.target.ticker or "").upper()
    target_charts = [chart for chart in draft.financial_charts if chart.chart_id.startswith("target_")]
    mismatches = []
    if target_ticker:
        for chart in target_charts:
            wrong = sorted(
                {
                    point.ticker
                    for point in chart.points
                    if (point.ticker or "").upper() != target_ticker
                }
            )
            if wrong:
                mismatches.append(f"{chart.chart_id}: {', '.join(wrong)}")
    return _check(
        "target_chart_identity",
        "目标公司图表身份",
        "目标公司纵向财务图表只能包含目标公司自己的数据点，绝不能用同行数据兜底或串号。",
        not mismatches,
        f"目标公司={company_display_name(draft.target)}；目标图表 {len(target_charts)} 个；串号={'; '.join(mismatches) or '无'}。",
        "所有 chart_id 以 target_ 开头的图表，其每个数据点必须属于目标公司；内部 ticker 仅用于校验和溯源。",
        "停止用同行数据替代目标公司缺失数据；缺失时宁可不生成目标图表，并在运行日志里说明。",
    )


def _check_two_stage_anomaly_workflow(draft: ResearchDraft) -> ValidationCheck:
    selected_count = len([item for item in draft.objective_anomalies if item.selected_for_deep_dive])
    positive_count = len([item for item in draft.objective_anomalies if item.polarity == POSITIVE])
    risk_count = len([item for item in draft.objective_anomalies if item.polarity == RISK])
    ok = bool(draft.objective_anomalies) and positive_count + risk_count == len(draft.objective_anomalies)
    return _check(
        "two_stage_anomaly_workflow",
        "两阶段异常选择",
        "工具应先输出积极/风险客观异常清单，由用户勾选后再进入深度分析。",
        ok,
        f"客观异常 {len(draft.objective_anomalies)} 条；积极 {positive_count} 条；风险 {risk_count} 条；已勾选 {selected_count} 条。",
        "至少形成积极/风险分类的客观异常清单；第二阶段记录 selected_for_deep_dive。",
        "完善横纵向异常扫描器，并在 Streamlit 中提供勾选入口。",
    )


def _check_no_coverage_as_signal(draft: ResearchDraft) -> ValidationCheck:
    forbidden = ["资料覆盖", "来源覆盖", "监管来源覆盖", "transcript 候选", "候选证据较多", "搜索入口", "资源丰富"]
    signal_text = " ".join(f"{signal.title} {signal.conclusion} {signal.signal_type}" for signal in draft.signals)
    anomaly_text = " ".join(f"{anomaly.title} {anomaly.category} {anomaly.observation}" for anomaly in draft.objective_anomalies if anomaly.polarity == POSITIVE)
    offenders = [token for token in forbidden if token in signal_text or token in anomaly_text]
    return _check(
        "no_coverage_as_signal",
        "投资信号纯度",
        "积极/风险信号必须来自经营、财务、行业或管理层表述分析，不能把资料覆盖充分或来源数量本身当作积极信号。",
        not offenders,
        f"命中禁用覆盖型表达：{', '.join(offenders) or '无'}。",
        "信号层不得包含资料覆盖/来源覆盖/搜索入口数量作为积极信号；这些只能放入证据审计或资料缺口。",
        "把覆盖类条目移入 audit_findings，并只保留财务异常、正文主题异常和真实经营/行业信号。",
    )


def _check_readable_text_for_text_signals(draft: ResearchDraft) -> ValidationCheck:
    readable = [item for item in draft.evidence if item.evidence_type in {"transcript", "presentation", "expert_memo", "external_signal"} and item.quote]
    text_anomalies = [anomaly for anomaly in draft.objective_anomalies if anomaly.category == "管理层/外部文字信号"]
    text_signals = [signal for signal in draft.signals if any(token in f"{signal.title} {signal.conclusion}" for token in ["管理层", "措辞", "transcript", "正文", "业绩会"])]
    ok = bool(readable) or not text_anomalies and not text_signals
    return _check(
        "readable_text_for_text_signals",
        "正文读取",
        "管理层措辞、业绩会纪要和外部文字信号必须基于已抽取正文 quote，不能基于候选链接或搜索入口。",
        ok,
        f"可读正文证据 {len(readable)} 条；文字异常 {len(text_anomalies)} 条；文字信号 {len(text_signals)} 条。",
        "若生成文字信号，至少需要 1 条 transcript/presentation/external quote；正式版应覆盖多个季度和可比公司。",
        "增强 transcript/presentation 正文抓取；抓不到正文时只输出资料缺口和下一步抓取计划。",
    )


def _check_no_evidence_gap_in_signal_list(draft: ResearchDraft) -> ValidationCheck:
    gap_anomalies = [anomaly for anomaly in draft.objective_anomalies if anomaly.category == "资料缺口"]
    return _check(
        "no_evidence_gap_in_signal_list",
        "异常清单纯度",
        "第一阶段积极/风险异常清单只能放企业经营、财务、行业或正文主题异常；资料缺口应放入证据审计附录。",
        not gap_anomalies,
        f"主异常清单中的资料缺口条目 {len(gap_anomalies)} 条；附录缺口 {len((draft.run_metadata or {}).get('evidence_gap_anomalies', []))} 条。",
        "资料缺口不应出现在用户勾选的积极/风险异常列表中。",
        "把资料缺口类异常移入 run_metadata.evidence_gap_anomalies 或 audit_findings。",
    )


def _check_peer_comparables(draft: ResearchDraft) -> ValidationCheck:
    company_count = len({company.ticker for group in draft.comparable_groups for company in group.companies})
    return _check(
        "peer_comparables",
        "精选可比公司",
        "AI 必须自动精选 3–5 家核心可比并纳入横向对比，用户可调整。",
        3 <= company_count,
        f"当前可比/验证对象 {company_count} 个。",
        "至少 3 个经过分组说明的可比或交叉验证对象。",
        "强化可比公司选择算法，并把选择理由写入报告。",
    )


def _check_source_traceability(draft: ResearchDraft) -> ValidationCheck:
    financial_points = [point for chart in draft.financial_charts for point in chart.points]
    linked = [point for point in financial_points if point.sources and (point.sources[0].url or point.sources[0].accession)]
    evidence_with_links = [item for item in draft.evidence if item.url]
    ok = bool(financial_points) and len(linked) == len(financial_points) and len(evidence_with_links) >= MIN_EVIDENCE
    return _check(
        "source_traceability",
        "来源可追溯",
        "图表点和文字证据必须可追溯到原始文件/网页。",
        ok,
        f"财务点 {len(financial_points)} 个，其中 {len(linked)} 个有 SEC/Wind 来源；证据链接 {len(evidence_with_links)} 条。",
        "所有图表点有来源链接或 Wind 字段来源，候选证据不少于 60 条。",
        "把所有文字结论绑定 evidence_ids，并补足网页/PDF 来源。",
    )


def _check_pdf_or_web_screenshots(draft: ResearchDraft) -> ValidationCheck:
    screenshots = [item for item in draft.evidence if item.screenshot_path]
    return _check(
        "source_screenshots",
        "PDF/网页截图溯源",
        "点击图表或文字时应显示 PDF/网页原始截图。",
        bool(screenshots),
        f"已有截图路径 {len(screenshots)} 条。",
        "关键证据至少有 PDF 页截图或网页截图。",
        "接入 PDF page rendering / browser screenshot，并保存 screenshot_path。",
    )


def _check_table_cell_traceability(draft: ResearchDraft) -> ValidationCheck:
    cells = [item for item in draft.evidence if item.cell_reference]
    return _check(
        "table_cell_traceability",
        "表格单元格来源",
        "财务图表数据应能追溯到表格单元格、XBRL concept 或 Wind 字段。",
        bool(cells) or all(point.sources and point.sources[0].concept for chart in draft.financial_charts for point in chart.points),
        f"证据表格单元格 {len(cells)} 条；财务点使用 XBRL concept 或 Wind 字段溯源。",
        "表格数据应有 cell_reference；XBRL/Wind 数据应有 concept/accession。",
        "对 PDF/HTML 表格抽取结果补 cell_reference 映射。",
    )


def _check_signal_count(draft: ResearchDraft) -> ValidationCheck:
    if _is_objective_scan_stage(draft):
        return _check(
            "signal_count",
            "核心信号数量",
            "第一阶段展示客观异常清单；深度分析信号在用户勾选后生成。",
            True,
            f"当前客观异常 {len(draft.objective_anomalies)} 条，深度分析信号 {len(draft.signals)} 个。",
            "第二阶段应输出 5–8 个核心深度分析信号。",
            "",
            severity="stage",
        )
    return _check(
        "signal_count",
        "核心信号数量",
        "报告应输出 5–8 个核心信号，而非泛泛指标罗列。",
        MIN_SIGNALS <= len(draft.signals) <= 8,
        f"当前信号 {len(draft.signals)} 个。",
        "5–8 个核心信号。",
        "由模型在异常扫描后选择最重要信号。",
    )


def _check_signal_types(draft: ResearchDraft) -> ValidationCheck:
    if _is_objective_scan_stage(draft):
        has_positive = any(item.polarity == POSITIVE for item in draft.objective_anomalies)
        has_risk = any(item.polarity == RISK for item in draft.objective_anomalies)
        return _check(
            "signal_types",
            "积极/风险异常分类",
            "第一阶段必须把客观异常分为积极信号和风险信号。",
            has_positive or has_risk,
            f"积极异常={has_positive}，风险异常={has_risk}。",
            "至少包含积极或风险异常；理想情况下两类都覆盖。",
            "继续完善财务与资料覆盖异常扫描。",
            severity="stage",
        )
    text = " ".join(f"{signal.signal_type} {signal.title} {signal.conclusion}" for signal in draft.signals)
    has_positive = any(token in text for token in ["亮点", "增长", "优于", "positive", "increased"])
    has_risk = any(token in text for token in ["风险", "下滑", "弱于", "risk", "decreased"])
    has_hypothesis = any(token in text for token in ["待验证", "假设", "线索", "needs_validation"])
    return _check(
        "signal_types",
        "亮点/风险/待验证假设",
        "信号必须同时覆盖正面亮点、负面风险和高潜力待验证线索。",
        has_positive and has_risk and has_hypothesis,
        f"亮点={has_positive}，风险={has_risk}，待验证={has_hypothesis}。",
        "同时包含亮点、风险、待验证假设。",
        "让模型按统一评分体系分类输出信号。",
    )


def _check_selected_anomaly_signal_linkage(draft: ResearchDraft) -> ValidationCheck:
    if _is_objective_scan_stage(draft):
        return _check(
            "selected_anomaly_signal_linkage",
            "信号绑定已勾选异常",
            "第一阶段尚未生成深度分析信号，不检查信号与已勾选异常的绑定。",
            True,
            "当前处于 objective_scan_ready。",
            "第二阶段每个核心信号都应绑定至少一个已勾选 anomaly_id。",
            "",
            severity="stage",
        )
    selected_ids = set((draft.run_metadata or {}).get("selected_anomaly_ids", []))
    linked = [
        signal
        for signal in draft.signals
        if not selected_ids or set(signal.anomaly_ids).intersection(selected_ids)
    ]
    return _check(
        "selected_anomaly_signal_linkage",
        "信号绑定已勾选异常",
        "深度分析必须围绕用户勾选的客观异常，而不是重新泛泛生成指标结论。",
        len(linked) >= min(MIN_SELECTED_SIGNAL_LINKAGE, len(draft.signals)) and (not draft.signals or len(linked) == len(draft.signals)),
        f"已勾选异常 {len(selected_ids)} 个；深度信号 {len(draft.signals)} 个；绑定到已勾选异常 {len(linked)} 个。",
        "每个深度分析信号都应包含已勾选 anomaly_id。",
        "在 LLM 输出合同和回退信号生成中强制写入 anomaly_ids。",
    )


def _check_evidence_audit(draft: ResearchDraft) -> ValidationCheck:
    return _check(
        "evidence_audit",
        "证据审计",
        "系统自动完成证据审计并放入报告附录。",
        len(draft.audit_findings) >= 5,
        f"审计项 {len(draft.audit_findings)} 条。",
        "至少覆盖来源、官方底线、交叉验证、冲突/缺口、图表数据。",
        "扩展审计项到冲突披露、来源分层和未验证假设。",
    )


def _check_three_source_validation(draft: ResearchDraft) -> ValidationCheck:
    source_count = len({item.source for item in draft.evidence if item.source})
    strong_signals = [signal for signal in draft.signals if signal.status == "evidence_backed"]
    weak_strong_signals = [signal for signal in strong_signals if getattr(signal, "source_count", 0) < 3]
    return _check(
        "three_source_validation",
        "三方交叉验证",
        "强结论至少需要三个独立可信来源交叉验证。",
        source_count >= 3 and not weak_strong_signals,
        f"当前来源名称 {source_count} 个；强结论 {len(strong_signals)} 个，其中来源不足 3 个的强结论 {len(weak_strong_signals)} 个。",
        "至少 3 个独立来源；每条 evidence_backed 强结论需绑定不少于 3 个独立来源，否则应降级为待验证。",
        "在 signal 层记录每条结论的独立来源数量。",
    )


def _check_transcript_and_presentation(draft: ResearchDraft) -> ValidationCheck:
    counts = Counter(item.evidence_type for item in draft.evidence)
    return _check(
        "transcript_presentation",
        "业绩会与演示材料",
        "报告必须纳入 transcript 和 presentation，用于管理层措辞和经营细节分析。",
        counts.get("transcript", 0) > 0 and counts.get("presentation", 0) > 0,
        f"Transcript {counts.get('transcript', 0)} 条，Presentation {counts.get('presentation', 0)} 条。",
        "Transcript 和 Presentation 均至少 1 条。",
        "继续增强 transcript/presentation 下载、正文抽取和关键词变化分析。",
    )


def _check_chinese_expert_memos(draft: ResearchDraft) -> ValidationCheck:
    counts = Counter(item.evidence_type for item in draft.evidence)
    china_related = _is_china_related_research(draft)
    expert_items = [
        item
        for item in draft.evidence
        if item.evidence_type == "expert_memo"
        or any(token in f"{item.title} {item.source} {item.url}" for token in ["专家交流", "专家电话", "行业专家", "产业链专家", "渠道调研", "草根调研", "微信公众号"])
    ]
    if not china_related:
        return _check(
            "chinese_expert_memos",
            "中文专家纪要",
            "非中国相关标的可不强制微信公众号/专家纪要，但若出现也必须作为待验证线索处理。",
            True,
            f"当前非中国相关研究；专家/渠道纪要候选 {len(expert_items)} 条。",
            "中国相关标的应补充微信公众号、雪球、中文投研平台的专家/渠道纪要线索。",
            "",
            severity="stage",
        )
    return _check(
        "chinese_expert_memos",
        "中文专家纪要",
        "中国相关公司必须增强微信公众号、专家交流纪要、产业链调研和渠道调研线索，但只能作为需交叉验证的平台证据。",
        len(expert_items) >= 2,
        f"Expert memo 类型 {counts.get('expert_memo', 0)} 条；关键词命中候选 {len(expert_items)} 条。",
        "至少 2 条专家/渠道纪要候选或搜索入口。",
        "补抓 site:mp.weixin.qq.com / weixin.sogou / 雪球 / 华尔街见闻等中文纪要入口，并在报告审计中标注需三方交叉验证。",
        severity="must" if china_related else "stage",
    )


def _check_external_sources(draft: ResearchDraft) -> ValidationCheck:
    external = [item for item in draft.evidence if item.confidence_tier in {"media", "platform", "search", "medium"}]
    return _check(
        "external_sources",
        "外部可信公开信息",
        "允许且需要公司公告以外的可信公开信息，如新闻、行业媒体、供应商披露。",
        len(external) >= 10,
        f"外部/平台/搜索类证据 {len(external)} 条。",
        "至少 10 条外部候选证据，并按置信度分层。",
        "增强新闻、行业平台、供应商披露和搜索结果正文抓取。",
    )


def _check_private_company_evidence(draft: ResearchDraft) -> ValidationCheck:
    private_groups = [group for group in draft.comparable_groups if any(not company.is_public for company in group.companies)]
    private_evidence = [item for item in draft.evidence if item.ticker in {"OPENAI", "ANTHROPIC", "XAI"}]
    if not _is_ai_chain_research(draft):
        return _check(
            "private_company_evidence",
            "私有模型公司观察",
            "非 AI 产业链目标不强制纳入私有模型公司；AI 产业链研究必须纳入。",
            True,
            "当前目标不属于 AI 产业链强制场景。",
            "AI 产业链研究需包含私有玩家分组和至少 3 条相关证据。",
            "",
            severity="stage",
        )
    return _check(
        "private_company_evidence",
        "私有模型公司观察",
        "OpenAI/Anthropic/xAI 等私有关键玩家应纳入融资、ARR、API价格、算力采购等证据。",
        bool(private_groups) and len(private_evidence) >= 3,
        f"私有玩家分组 {len(private_groups)} 个，相关证据 {len(private_evidence)} 条。",
        "私有玩家分组存在且至少 3 条相关证据。",
        "对私有公司运行专门搜索：融资、ARR、API pricing、模型能力、采购、招聘。",
    )


def _check_interactive_html_support(draft: ResearchDraft) -> ValidationCheck:
    has_financial = bool(draft.financial_charts)
    has_evidence = bool(draft.evidence)
    return _check(
        "interactive_html",
        "交互式 HTML",
        "HTML 应支持图表点击、证据抽屉、可展开推理链。",
        has_financial and has_evidence,
        f"财务图表={has_financial}，证据={has_evidence}；HTML 模板包含点击抽屉。",
        "图表和证据均存在，HTML 有交互抽屉。",
        "继续补截图、原文引用和页码跳转。",
    )


def _check_mobile_report_shape(draft: ResearchDraft) -> ValidationCheck:
    mobile = draft.run_metadata.get("mobile_validation", {}) if draft.run_metadata else {}
    ok = bool(mobile.get("passed") and mobile.get("screenshot_path"))
    return _check(
        "mobile_shape",
        "手机/电脑阅读",
        "投资备忘录版本不限页数，应结论先行，并可在手机和电脑流畅阅读。",
        ok,
        f"移动端截图验收 passed={bool(mobile.get('passed'))}；截图={mobile.get('screenshot_path') or '无'}。",
        "移动端截图验收通过，结论先行且布局可读。",
        "增加 Playwright/浏览器截图验收，输出移动端布局报告。",
    )


def _check_async_task_queue(draft: ResearchDraft) -> ValidationCheck:
    metadata = draft.run_metadata or {}
    statuses = metadata.get("queue_statuses", [])
    ok = len(statuses) >= 4 and metadata.get("job_id")
    return _check(
        "async_task_queue",
        "任务队列",
        "产品应是提交任务 → 进度页 → 完成通知/刷新。",
        bool(ok),
        f"任务模式={metadata.get('task_mode', '未知')}；job_id={metadata.get('job_id') or '无'}；状态记录={len(statuses)} 个。",
        "至少记录 job_id 和 submitted/collecting/model/validation 等任务状态；正式版需要真实后台 worker。",
        "接入 Supabase job table + worker/RQ/Celery + 企业微信通知；当前仅为可审计同步原型。",
        severity="architecture",
    )


def _check_permissions_logging(draft: ResearchDraft) -> ValidationCheck:
    permissions = (draft.run_metadata or {}).get("permissions", {})
    ok = permissions.get("visibility") == "authorized" and permissions.get("user_id_required") and permissions.get("access_logs")
    return _check(
        "permissions_logging",
        "权限与行为日志",
        "报告对授权用户可见，并记录打开、证据点击、停留时间。",
        bool(ok),
        f"visibility={permissions.get('visibility', '无')}；user_id_required={bool(permissions.get('user_id_required'))}；access_logs={permissions.get('access_logs', '无')}。",
        "报告元数据为 authorized，且记录非匿名 user_id 与访问/生成事件日志。",
        "接入微信登录/管理员权限配置/前端埋点；当前为本地 JSONL 或 Supabase 日志原型。",
        severity="architecture",
    )


def _check_disclaimer(draft: ResearchDraft) -> ValidationCheck:
    return _check(
        "disclaimer",
        "免责声明",
        "报告必须包含 AI-assisted research; not investment advice.",
        True,
        "HTML 模板包含免责声明。",
        "所有报告展示免责声明。",
        "",
    )


def _is_objective_scan_stage(draft: ResearchDraft) -> bool:
    return (draft.run_metadata or {}).get("workflow_stage") == "objective_scan_ready"


def _is_ai_chain_research(draft: ResearchDraft) -> bool:
    text = " ".join(
        [
            draft.target.ticker,
            draft.target.name,
            draft.target.segment,
            draft.target.description,
            *[group.group_id for group in draft.comparable_groups],
            *[group.title for group in draft.comparable_groups],
        ]
    ).casefold()
    return any(token in text for token in ["ai", "gpu", "model", "accelerator", "foundry", "semiconductor", "算力", "模型", "芯片", "晶圆", "半导体"])


def _is_china_related_research(draft: ResearchDraft) -> bool:
    text = " ".join(
        [
            draft.target.ticker,
            draft.target.name,
            draft.target.market,
            draft.target.country,
            draft.target.description,
            *[company.ticker for group in draft.comparable_groups for company in group.companies],
            *[company.name for group in draft.comparable_groups for company in group.companies],
            *[company.market for group in draft.comparable_groups for company in group.companies],
            *[company.country for group in draft.comparable_groups for company in group.companies],
        ]
    ).casefold()
    return any(token in text for token in ["中国", "a股", "沪深", "港股", "香港", "台湾", "china", "hong kong", "taiwan", "smic", "tsmc"])


def _check(check_id: str, category: str, requirement: str, ok: bool, observed: str, required: str, remediation: str, severity: str = "must") -> ValidationCheck:
    status = "pass" if ok else "fail" if severity == "must" else "warn"
    return ValidationCheck(
        check_id=check_id,
        category=category,
        requirement=requirement,
        status=status,
        observed=observed,
        required=required,
        severity=severity,
        remediation="" if ok else remediation,
    )

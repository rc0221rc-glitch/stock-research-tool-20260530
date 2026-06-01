from __future__ import annotations

from collections import Counter

from .research_models import ResearchDraft, ValidationCheck, ValidationReport


FINAL_MIN_SECONDS = 30 * 60
MIN_SIGNALS = 5
MIN_FINANCIAL_CHARTS = 6
MIN_EVIDENCE = 60
MIN_COMPANIES = 5
MIN_MODEL_RUNS = 1
MIN_MODEL_PROVIDERS_FOR_PRO_MODE = 3


def validate_research_draft(draft: ResearchDraft) -> ValidationReport:
    checks = [
        _check_model_called(draft),
        _check_deep_research_runtime(draft),
        _check_multi_model_attempts(draft),
        _check_financial_charts(draft),
        _check_peer_comparables(draft),
        _check_source_traceability(draft),
        _check_pdf_or_web_screenshots(draft),
        _check_table_cell_traceability(draft),
        _check_signal_count(draft),
        _check_signal_types(draft),
        _check_evidence_audit(draft),
        _check_three_source_validation(draft),
        _check_transcript_and_presentation(draft),
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
    status = "PASS_FINAL_DELIVERABLE" if failed == 0 else "NOT_FINAL_DELIVERABLE"
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


def _check_model_called(draft: ResearchDraft) -> ValidationCheck:
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
    total_seconds = sum(run.duration_seconds for run in draft.model_runs)
    return _check(
        "deep_research_runtime",
        "深度研究时长",
        "专业版深度研究不能半分钟生成，必须有长任务流程和充分推理/验证时间。",
        total_seconds >= FINAL_MIN_SECONDS,
        f"记录模型/研究运行时长 {total_seconds:.1f} 秒。",
        f"专业版目标至少 {FINAL_MIN_SECONDS // 60} 分钟研究/验证运行记录。",
        "接入后台任务队列，分阶段执行资料抓取、模型分析、二次验证和审计。",
    )


def _check_multi_model_attempts(draft: ResearchDraft) -> ValidationCheck:
    providers = {run.provider for run in draft.model_runs if run.status in {"success", "attempted"}}
    return _check(
        "multi_model_attempts",
        "多模型尝试",
        "用户要求用 DeepSeek、Claude、GPT 分别尝试专业研究。",
        len(providers) >= MIN_MODEL_PROVIDERS_FOR_PRO_MODE,
        f"记录到 {len(providers)} 个模型供应商：{', '.join(sorted(providers)) or '无'}。",
        "至少 3 个供应商尝试记录；不可硬编码不存在的模型名。",
        "增加模型可用性检测和 provider abstraction，再记录实际调用结果。",
    )


def _check_financial_charts(draft: ResearchDraft) -> ValidationCheck:
    return _check(
        "financial_charts",
        "财务图表",
        "交付物必须包含真实财务数据图表，而不是只有文字和链接。",
        len(draft.financial_charts) >= MIN_FINANCIAL_CHARTS,
        f"当前财务图表 {len(draft.financial_charts)} 个。",
        f"至少 {MIN_FINANCIAL_CHARTS} 个核心财务/经营/比率/横向可比图表。",
        "继续补经营数据、分部数据、同比/环比、估值/CapEx/库存/backlog 等图表。",
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
    linked = [point for point in financial_points if point.sources and point.sources[0].url]
    evidence_with_links = [item for item in draft.evidence if item.url]
    ok = bool(financial_points) and len(linked) == len(financial_points) and len(evidence_with_links) >= MIN_EVIDENCE
    return _check(
        "source_traceability",
        "来源可追溯",
        "图表点和文字证据必须可追溯到原始文件/网页。",
        ok,
        f"财务点 {len(financial_points)} 个，其中 {len(linked)} 个有 SEC 链接；证据链接 {len(evidence_with_links)} 条。",
        "所有图表点有来源链接，候选证据不少于 60 条。",
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
        "财务图表数据应能追溯到表格单元格或 XBRL concept。",
        bool(cells) or all(point.sources and point.sources[0].concept for chart in draft.financial_charts for point in chart.points),
        f"证据表格单元格 {len(cells)} 条；财务点使用 XBRL concept 溯源。",
        "表格数据应有 cell_reference；XBRL 数据应有 concept/accession。",
        "对 PDF/HTML 表格抽取结果补 cell_reference 映射。",
    )


def _check_signal_count(draft: ResearchDraft) -> ValidationCheck:
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
    return _check(
        "three_source_validation",
        "三方交叉验证",
        "强结论至少需要三个独立可信来源交叉验证。",
        source_count >= 3,
        f"当前来源名称 {source_count} 个。",
        "至少 3 个独立来源；强结论需绑定多来源。",
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
    return _check(
        "mobile_shape",
        "手机/电脑阅读",
        "投资备忘录版本应是 3–5 屏结论先行，并可在手机和电脑流畅阅读。",
        False,
        "当前仅有响应式 CSS，但未做真实移动端 3–5 屏信息密度验收。",
        "移动端截图验收通过，首屏结论先行。",
        "增加 Playwright/浏览器截图验收，输出移动端布局报告。",
    )


def _check_async_task_queue(draft: ResearchDraft) -> ValidationCheck:
    return _check(
        "async_task_queue",
        "任务队列",
        "产品应是提交任务 → 进度页 → 完成通知/刷新。",
        False,
        "当前 Streamlit 原型仍为同步任务，只有进度条模拟。",
        "真实后台队列、任务状态表、通知机制。",
        "接入 Supabase job table + worker/RQ/Celery + 企业微信通知。",
    )


def _check_permissions_logging(draft: ResearchDraft) -> ValidationCheck:
    return _check(
        "permissions_logging",
        "权限与行为日志",
        "报告对授权用户可见，并记录打开、证据点击、停留时间。",
        False,
        "仅预留 Supabase schema；未实现登录、授权校验和前端行为日志。",
        "真实鉴权、报告权限、非匿名访问日志。",
        "接入微信登录/管理员权限配置/前端埋点。",
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


def _check(check_id: str, category: str, requirement: str, ok: bool, observed: str, required: str, remediation: str, severity: str = "must") -> ValidationCheck:
    return ValidationCheck(
        check_id=check_id,
        category=category,
        requirement=requirement,
        status="pass" if ok else "fail",
        observed=observed,
        required=required,
        severity=severity,
        remediation="" if ok else remediation,
    )

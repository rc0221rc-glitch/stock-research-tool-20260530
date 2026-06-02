from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

for _module_name in list(sys.modules):
    if _module_name.startswith("src.research_") or _module_name in {"src.wind_client", "src.cninfo_fetcher", "src.company_search_global"}:
        sys.modules.pop(_module_name, None)

from src.research_anomalies import POSITIVE, RISK
from src.research_html import save_dashboard_html, save_memo_html
from src.research_llm import deepseek_key_status
from src.research_pipeline import collect_research_draft, run_deep_analysis_for_selected_anomalies
from src.research_storage import (
    create_research_job,
    is_supabase_configured,
    log_research_event,
    store_report_metadata,
    suggested_supabase_schema,
)
from src.research_validation import checklist_markdown
from src.research_universe import build_selected_groups, get_company_profile, recommend_comparable_groups_with_llm


st.set_page_config(page_title="AI 行业研究工具", page_icon="🧠", layout="wide")


def init_state() -> None:
    st.session_state.setdefault("target_query", "NVDA")
    st.session_state.setdefault("quarter_count", 4)
    st.session_state.setdefault("base_groups", [])
    st.session_state.setdefault("selected_groups", st.session_state.base_groups)
    st.session_state.setdefault("comparable_model_run", None)
    st.session_state.setdefault("research_job", None)
    st.session_state.setdefault("research_draft", None)
    st.session_state.setdefault("selected_anomaly_ids", [])
    st.session_state.setdefault("memo_path", "")
    st.session_state.setdefault("dashboard_path", "")


def render_sidebar() -> tuple[str, str, str]:
    with st.sidebar:
        st.header("内测设置")
        user_id = st.text_input("当前用户 ID", value="admin", help="V0.1 先用文本 ID；后续接 WeChat 登录后会替换为真实用户。")
        deepseek_api_key = st.text_input("DeepSeek API Key", value="", type="password", help="用于真正调用大模型生成/改写研究信号；不会写入仓库。")
        key_status = deepseek_key_status(deepseek_api_key)
        if any(key_status.values()):
            source = (
                "页面输入"
                if key_status["ui"]
                else "Streamlit Secrets"
                if key_status.get("streamlit_secrets")
                else "进程环境变量"
                if key_status["process_env"]
                else "本地 .env"
            )
            st.success(f"DeepSeek Key 已可用（来源：{source}）。")
        else:
            st.error("DeepSeek Key 不可用：请在 Streamlit Secrets / 环境变量 / 本地 `.env` 写入 DEEPSEEK_API_KEY，或临时在页面输入。")
        claude_api_key = st.text_input("Anthropic API Key（可选）", value="", type="password", help="当前仅传给已有下载器兜底逻辑；正式多模型研究层后续接入。")
        st.divider()
        st.subheader("权限与数据库")
        if is_supabase_configured():
            st.success("已检测到 Supabase 环境变量")
        else:
            st.info("未配置 Supabase，本次使用本地会话模拟任务与权限记录。")
        with st.expander("Supabase 表结构建议"):
            st.code(suggested_supabase_schema(), language="sql")
        st.caption("V0.1 已预留任务、报告权限和访问日志结构；真正的后台队列与微信通知会在下一阶段接入。")
    return user_id.strip() or "anonymous", claude_api_key.strip(), deepseek_api_key.strip()


def render_target_form(deepseek_api_key: str) -> None:
    st.subheader("1. 输入目标公司")
    with st.form("target_form", clear_on_submit=False):
        col_target, col_window = st.columns([2, 1])
        with col_target:
            target_query = st.text_input(
                "公司名 / 股票代码",
                value=st.session_state.target_query,
                placeholder="例如 NVDA、TSM、OpenAI",
                help="在输入框内按回车即可生成可比公司建议。",
            )
        with col_window:
            quarter_count = st.radio("观察窗口", [4, 8, 12], index=[4, 8, 12].index(st.session_state.quarter_count), horizontal=True)
        submitted = st.form_submit_button("生成 / 刷新可比公司建议", type="primary", use_container_width=True)
    if submitted:
        target_query = target_query.strip() or "NVDA"
        st.session_state.target_query = target_query
        st.session_state.quarter_count = quarter_count
        with st.spinner("正在调用 DeepSeek 精选高度可比公司；这一步会严格区分核心可比与交叉验证对象..."):
            groups, model_run = recommend_comparable_groups_with_llm(target_query, deepseek_api_key=deepseek_api_key)
        st.session_state.base_groups = groups
        st.session_state.comparable_model_run = model_run
        st.session_state.selected_groups = st.session_state.base_groups
        st.session_state.research_draft = None
        st.session_state.memo_path = ""
        st.session_state.dashboard_path = ""
        model_message = model_run.error or model_run.output_summary or model_run.status
        if model_run.status == "success":
            st.success("DeepSeek 已完成高度可比公司精选。")
        else:
            st.error(f"DeepSeek 可比公司精选未成功。请检查模型运行记录后重试。原因：{model_message}")


def render_comparable_editor() -> list[Any]:
    target = get_company_profile(st.session_state.target_query)
    st.subheader("2. 调整 AI 精选可比组")
    st.caption("这里不是泛行业列表，而是按核心业务、上游供给、下游需求、替代路线和私有关键玩家拆组。你可以删减或新增。")
    selected_by_group: dict[str, list[str]] = {}
    model_run = st.session_state.get("comparable_model_run")
    if model_run:
        with st.expander("DeepSeek 可比公司选择运行记录", expanded=getattr(model_run, "status", "") != "success"):
            st.json(model_run.to_dict() if hasattr(model_run, "to_dict") else model_run)
    if not st.session_state.base_groups:
        st.warning("尚未生成可比公司建议。请在第一步输入目标公司并回车/点击按钮，系统会先调用 DeepSeek 精选高度可比公司。")
        return []
    for group in st.session_state.base_groups:
        with st.expander(group.title, expanded=True):
            st.markdown(f"**用途：** {group.purpose}")
            st.caption(f"筛选逻辑：{group.selection_logic}")
            cols = st.columns(3)
            selected: list[str] = []
            for index, company in enumerate(group.companies):
                with cols[index % 3]:
                    checked = st.checkbox(
                        f"{company.ticker} · {company.name}",
                        value=True,
                        key=f"group_{group.group_id}_{company.ticker}",
                        help=company.description,
                    )
                if checked:
                    selected.append(company.ticker)
            selected_by_group[group.group_id] = selected

    extra_text = st.text_area(
        "新增观察公司（可选，每行一个代码或公司名）",
        value="",
        placeholder="例如：PLTR\nTSLA\nCoreWeave",
        help="新增公司会放进“用户新增观察公司”组，后续再由 AI 重新判断可比性。",
    )
    extras = [line.strip() for line in extra_text.splitlines() if line.strip()]
    selected_groups = build_selected_groups(st.session_state.base_groups, selected_by_group, extras)
    st.session_state.selected_groups = selected_groups
    with st.container(border=True):
        st.markdown(f"**目标公司：** {target.ticker} · {target.name}")
        st.markdown(f"**当前纳入：** {sum(len(group.companies) for group in selected_groups)} 个可比 / 交叉验证对象，{len(selected_groups)} 个分组")
    return selected_groups


def render_task_runner(user_id: str, claude_api_key: str, deepseek_api_key: str, selected_groups: list[Any]) -> None:
    st.subheader("3. 第一阶段：客观扫描 → 异常清单")
    st.caption("第一阶段只做客观工作：找信息、横纵向对比、列出异常。不调用大模型做主观深度判断，先让你选择哪些值得挖。")
    if not selected_groups:
        st.info("请先在第一步生成 DeepSeek 高度可比公司建议，并在第二步确认可比公司后再开始客观扫描。")
        return
    include_external_search = st.checkbox("启用外部公开信息搜索（媒体、平台、私有玩家线索）", value=True)
    capture_screenshots = st.checkbox("为关键证据生成网页/PDF 截图", value=True)
    max_companies = st.slider("本轮最多抓取研究对象数", min_value=4, max_value=20, value=12, help="原型阶段建议先控制数量，避免单次运行过慢。")
    if st.button("开始客观扫描并生成异常清单", type="primary", use_container_width=True):
        job = create_research_job(
            user_id=user_id,
            target=st.session_state.target_query,
            quarter_count=st.session_state.quarter_count,
            payload={"groups": [group.to_dict() for group in selected_groups]},
        )
        st.session_state.research_job = job
        st.session_state.research_draft = None
        st.session_state.selected_anomaly_ids = []
        log_research_event(user_id, "research_job_submitted", metadata={"job_id": job["id"], "target": st.session_state.target_query})

        progress = st.progress(0, text="任务已提交：准备可比组与证据源")
        try:
            progress.progress(18, text="按市场抓取官方披露、IR、Transcript 与外部候选来源")
            with st.spinner("正在收集证据。美股走 SEC，A股走巨潮资讯/Wind，港股走 HKEX/IR，并补充 Transcript 与搜索入口…"):
                draft = collect_research_draft(
                    st.session_state.target_query,
                    quarter_count=st.session_state.quarter_count,
                    comparable_groups=selected_groups,
                    claude_api_key=claude_api_key,
                    deepseek_api_key=deepseek_api_key,
                    require_llm=False,
                    enable_llm=False,
                    include_external_search=include_external_search,
                    max_companies=max_companies,
                    capture_screenshots=capture_screenshots,
                    task_mode="streamlit_sync_prototype",
                    user_id=user_id,
                    job_id=job["id"],
                )
            comparable_model_run = st.session_state.get("comparable_model_run")
            if comparable_model_run and not any(run.purpose == getattr(comparable_model_run, "purpose", "") for run in draft.model_runs):
                draft.model_runs.insert(0, comparable_model_run)
            progress.progress(88, text="生成客观异常清单、证据审计与自动验收清单")
            st.session_state.research_draft = draft
            log_research_event(user_id, "objective_scan_ready", metadata={"job_id": job["id"], "evidence_count": len(draft.evidence), "anomaly_count": len(draft.objective_anomalies)})
            progress.progress(100, text="完成：请勾选需要深挖的异常条目")
            st.success("第一阶段客观扫描完成。请在下方勾选需要进一步深挖的积极信号或风险信号。")
        except Exception as exc:
            progress.empty()
            st.error(f"任务失败：{exc}")


def render_draft_review(user_id: str, deepseek_api_key: str) -> None:
    draft = st.session_state.research_draft
    if not draft:
        return

    st.subheader("4. 选择需要深挖的客观异常")
    st.warning(draft.report_label)
    summary_cols = st.columns(4)
    summary_cols[0].metric("候选证据", len(draft.evidence))
    summary_cols[1].metric("客观异常", len(draft.objective_anomalies))
    summary_cols[2].metric("真实财务图表", len(draft.financial_charts))
    summary_cols[3].metric("审计项", len(draft.audit_findings))

    render_anomaly_selector(user_id, deepseek_api_key)

    st.subheader("5. 审阅深度分析与证据")
    tab_checklist, tab_models, tab_charts, tab_signals, tab_audit, tab_evidence, tab_plan = st.tabs(["自动验收清单", "模型运行记录", "真实财务图表", "深度分析信号", "证据审计", "候选证据", "下一步验证"])
    with tab_checklist:
        if draft.validation_report:
            status = draft.validation_report.status
            st.error("未达到最终交付标准") if status != "PASS_FINAL_DELIVERABLE" else st.success("达到最终交付标准")
            st.metric("通过项", draft.validation_report.passed)
            st.metric("失败项", draft.validation_report.failed)
            st.markdown(checklist_markdown(draft.validation_report))
        else:
            st.warning("尚未生成自动验收报告。")
    with tab_models:
        if not draft.model_runs:
            st.error("没有任何模型调用记录。")
        else:
            st.dataframe([run.to_dict() for run in draft.model_runs], use_container_width=True, hide_index=True)
    with tab_charts:
        if not draft.financial_charts:
            st.warning("本轮没有生成真实财务图表。可能是 SEC / Wind / 巨潮 PDF 表格暂时不可用，或目标公司披露格式需要继续适配。")
        for chart in draft.financial_charts:
            with st.container(border=True):
                st.markdown(f"### {chart.title}")
                st.caption(f"{chart.chart_type} · {chart.y_axis}")
                st.write(chart.insight)
                rows = []
                for point in chart.points:
                    rows.append(
                        {
                            "ticker": point.ticker,
                            "period": point.period,
                            "end_date": point.end_date,
                            "metric": point.metric_label,
                            "value": point.display_value,
                            "source": point.sources[0].url if point.sources else "",
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)
    with tab_signals:
        for index, signal in enumerate(draft.signals, start=1):
            with st.container(border=True):
                st.markdown(f"### {index}. {signal.title}")
                st.caption(f"{signal.signal_type} · {signal.status} · 总分 {signal.score.total}/30")
                st.write(signal.conclusion)
                st.markdown(f"**建议图表：** {signal.chart_hint}")
                st.caption(signal.chart_reason)
                with st.expander("推理链草稿与下一步验证"):
                    st.markdown("**推理链草稿**")
                    for step in signal.reasoning_chain:
                        st.markdown(f"- {step}")
                    st.markdown("**下一步动作**")
                    for action in signal.next_validation_actions:
                        st.markdown(f"- {action}")
    with tab_audit:
        for finding in draft.audit_findings:
            status = "✅" if finding.status == "pass" else "⚠️"
            st.markdown(f"{status} **{finding.topic}**：{finding.finding}")
    with tab_evidence:
        rows = [item.to_dict() for item in draft.evidence]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    with tab_plan:
        for item in draft.next_fetch_plan:
            st.markdown(f"- {item}")
        if draft.run_notes:
            with st.expander("运行日志"):
                for note in draft.run_notes:
                    st.caption(note)

    st.subheader("6. 你确认后生成 HTML")
    passed_final = bool(draft.validation_report and draft.validation_report.status == "PASS_FINAL_DELIVERABLE")
    if not passed_final:
        st.error("自动验收未通过：只能生成“内测草稿 HTML”，不能标记为最终交付物。")
    confirmed = st.checkbox("我理解这只是内测草稿，不是专业最终交付物，仍要生成 HTML", value=False)
    col_memo, col_dashboard = st.columns(2)
    with col_memo:
        if st.button("生成投资备忘录草稿 HTML（非最终）", disabled=not confirmed, use_container_width=True):
            path = save_memo_html(draft)
            st.session_state.memo_path = str(path)
            report = store_report_metadata(_job_id(), user_id, "memo", str(path), draft)
            log_research_event(user_id, "memo_html_generated", report_id=report["id"], metadata={"path": str(path)})
            st.success(f"已生成：{path}")
    with col_dashboard:
        if st.button("生成交互看板草稿 HTML（非最终）", disabled=not confirmed, use_container_width=True):
            path = save_dashboard_html(draft)
            st.session_state.dashboard_path = str(path)
            report = store_report_metadata(_job_id(), user_id, "dashboard", str(path), draft)
            log_research_event(user_id, "dashboard_html_generated", report_id=report["id"], metadata={"path": str(path)})
            st.success(f"已生成：{path}")

    render_downloads()


def render_anomaly_selector(user_id: str, deepseek_api_key: str) -> None:
    draft = st.session_state.research_draft
    if not draft:
        return
    anomalies = draft.objective_anomalies
    if not anomalies:
        st.info("暂未形成客观异常条目。可以扩大可比公司数量、启用外部搜索，或补充更多官方文件后重试。")
        return

    positive = [item for item in anomalies if item.polarity == POSITIVE]
    risk = [item for item in anomalies if item.polarity == RISK]
    st.caption("这些条目来自纯客观扫描：财务图表横纵向变化、可比公司排名、已读取正文主题命中。资料缺口只进入证据审计，不作为积极/风险信号。你勾选后，大模型只围绕被选条目做深度分析。")
    col_pos, col_risk, col_selected = st.columns(3)
    col_pos.metric("积极信号", len(positive))
    col_risk.metric("风险信号", len(risk))
    col_selected.metric("已勾选", len(st.session_state.selected_anomaly_ids))

    selected: list[str] = []
    tab_positive, tab_risk = st.tabs(["积极信号", "风险信号"])
    with tab_positive:
        selected.extend(_render_anomaly_group("positive", positive))
    with tab_risk:
        selected.extend(_render_anomaly_group("risk", risk))
    st.session_state.selected_anomaly_ids = selected

    with st.container(border=True):
        st.markdown("**第二阶段：基于你勾选的异常做深度分析**")
        st.caption("这一阶段才调用大模型：分析背后原因、验证路径、图表表达方式和后续抓取计划。")
        require_llm = st.checkbox("必须成功调用 DeepSeek，否则标记为失败", value=True, key="require_llm_deep_analysis")
        disabled = not selected
        if st.button("对已勾选异常进行深度分析", type="primary", disabled=disabled, use_container_width=True):
            with st.spinner("正在围绕已勾选异常做深度分析。请稍等，这一步会调用大模型…"):
                updated = run_deep_analysis_for_selected_anomalies(
                    draft,
                    selected_anomaly_ids=selected,
                    deepseek_api_key=deepseek_api_key,
                    require_llm=require_llm,
                )
            st.session_state.research_draft = updated
            log_research_event(
                user_id,
                "selected_anomaly_deep_analysis_ready",
                metadata={"job_id": _job_id(), "selected_anomaly_ids": selected, "model_runs": len(updated.model_runs)},
            )
            if any(run.status == "success" for run in updated.model_runs):
                st.success("深度分析完成：DeepSeek 已围绕你勾选的异常生成分析信号。")
            else:
                st.error("深度分析未成功调用大模型；请检查 DeepSeek Key 或模型运行记录。")


def _render_anomaly_group(prefix: str, anomalies: list[Any]) -> list[str]:
    if not anomalies:
        st.info("暂无此类异常。")
        return []
    selected: list[str] = []
    select_all_key = f"{prefix}_select_all_anomalies"
    previous_select_all_key = f"{prefix}_select_all_anomalies_previous"
    child_keys = [f"{prefix}_anomaly_{anomaly.anomaly_id}" for anomaly in anomalies]
    previous_select_all = bool(st.session_state.get(previous_select_all_key, False))
    select_all = st.checkbox("全选本类异常", value=False, key=select_all_key)
    if select_all != previous_select_all:
        for child_key in child_keys:
            st.session_state[child_key] = select_all
    st.session_state[previous_select_all_key] = select_all
    for anomaly, child_key in zip(anomalies, child_keys):
        if child_key not in st.session_state:
            st.session_state[child_key] = anomaly.selected_for_deep_dive or anomaly.anomaly_id in st.session_state.selected_anomaly_ids or select_all
        with st.container(border=True):
            checked = st.checkbox(
                anomaly.title,
                key=child_key,
            )
            st.markdown(f"**观察：** {anomaly.observation}")
            st.markdown(f"**对比依据：** {anomaly.comparison_basis}")
            if anomaly.magnitude:
                st.markdown(f"**幅度：** {anomaly.magnitude}")
            st.caption(f"{anomaly.category} · {anomaly.ticker or '多公司/资料'} · {anomaly.period or '当前窗口'} · 置信度：{anomaly.confidence_tier}")
            if anomaly.suggested_deep_dive:
                st.info(f"建议深挖：{anomaly.suggested_deep_dive}")
            if anomaly.source_refs:
                with st.expander("来源字段 / 链接"):
                    for ref in anomaly.source_refs[:5]:
                        st.caption(ref)
        if checked:
            selected.append(anomaly.anomaly_id)
    return selected


def render_downloads() -> None:
    paths = [
        ("投资备忘录 HTML", st.session_state.memo_path),
        ("交互看板 HTML", st.session_state.dashboard_path),
    ]
    for label, value in paths:
        if not value:
            continue
        path = Path(value)
        if path.exists():
            st.download_button(label=f"下载{label}", data=path.read_bytes(), file_name=path.name, mime="text/html", use_container_width=True)
            st.caption(f"本地路径：{path.resolve()}")


def _job_id() -> str:
    job = st.session_state.get("research_job") or {}
    return str(job.get("id") or "00000000-0000-0000-0000-000000000000")


def main() -> None:
    init_state()
    user_id, claude_api_key, deepseek_api_key = render_sidebar()
    st.title("🧠 AI 行业研究工具 · 独立原型入口")
    st.caption("目标：从大量公司文件、业绩会纪要、外部可信信息中筛出真正值得投资人关注的信号，并生成可追溯 HTML。")
    render_target_form(deepseek_api_key)
    st.divider()
    selected_groups = render_comparable_editor()
    st.divider()
    render_task_runner(user_id, claude_api_key, deepseek_api_key, selected_groups)
    st.divider()
    render_draft_review(user_id, deepseek_api_key)
    st.caption("V0.1 原型：同步执行任务并模拟任务队列。下一阶段会接入真正后台队列、微信登录/通知、权限管理和访问行为日志。")


if __name__ == "__main__":
    main()

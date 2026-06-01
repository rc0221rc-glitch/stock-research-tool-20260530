from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from src.research_html import save_dashboard_html, save_memo_html
from src.research_pipeline import collect_research_draft
from src.research_storage import (
    create_research_job,
    is_supabase_configured,
    log_research_event,
    store_report_metadata,
    suggested_supabase_schema,
)
from src.research_universe import build_selected_groups, get_company_profile, recommend_comparable_groups


st.set_page_config(page_title="AI 行业研究工具", page_icon="🧠", layout="wide")


def init_state() -> None:
    st.session_state.setdefault("target_query", "NVDA")
    st.session_state.setdefault("quarter_count", 4)
    st.session_state.setdefault("base_groups", recommend_comparable_groups("NVDA"))
    st.session_state.setdefault("selected_groups", st.session_state.base_groups)
    st.session_state.setdefault("research_job", None)
    st.session_state.setdefault("research_draft", None)
    st.session_state.setdefault("memo_path", "")
    st.session_state.setdefault("dashboard_path", "")


def render_sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.header("内测设置")
        user_id = st.text_input("当前用户 ID", value="admin", help="V0.1 先用文本 ID；后续接 WeChat 登录后会替换为真实用户。")
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
    return user_id.strip() or "anonymous", claude_api_key.strip()


def render_target_form() -> None:
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
        st.session_state.base_groups = recommend_comparable_groups(target_query)
        st.session_state.selected_groups = st.session_state.base_groups
        st.session_state.research_draft = None
        st.session_state.memo_path = ""
        st.session_state.dashboard_path = ""
        st.success("已刷新可比公司建议。")


def render_comparable_editor() -> list[Any]:
    target = get_company_profile(st.session_state.target_query)
    st.subheader("2. 调整 AI 精选可比组")
    st.caption("这里不是泛行业列表，而是按核心业务、上游供给、下游需求、替代路线和私有关键玩家拆组。你可以删减或新增。")
    selected_by_group: dict[str, list[str]] = {}
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


def render_task_runner(user_id: str, claude_api_key: str, selected_groups: list[Any]) -> None:
    st.subheader("3. 提交任务 → 进度 → 证据审计与信号草稿")
    include_external_search = st.checkbox("启用外部公开信息搜索（媒体、平台、私有玩家线索）", value=True)
    max_companies = st.slider("本轮最多抓取研究对象数", min_value=4, max_value=20, value=12, help="原型阶段建议先控制数量，避免单次运行过慢。")
    if st.button("生成证据审计和信号草稿", type="primary", use_container_width=True):
        job = create_research_job(
            user_id=user_id,
            target=st.session_state.target_query,
            quarter_count=st.session_state.quarter_count,
            payload={"groups": [group.to_dict() for group in selected_groups]},
        )
        st.session_state.research_job = job
        st.session_state.research_draft = None
        log_research_event(user_id, "research_job_submitted", metadata={"job_id": job["id"], "target": st.session_state.target_query})

        progress = st.progress(0, text="任务已提交：准备可比组与证据源")
        try:
            progress.progress(18, text="抓取官方披露、IR、Transcript 与外部候选来源")
            with st.spinner("正在收集证据。这个阶段会访问 SEC、IR、Transcript 平台和搜索入口，可能需要几十秒…"):
                draft = collect_research_draft(
                    st.session_state.target_query,
                    quarter_count=st.session_state.quarter_count,
                    comparable_groups=selected_groups,
                    claude_api_key=claude_api_key,
                    include_external_search=include_external_search,
                    max_companies=max_companies,
                )
            progress.progress(78, text="生成证据审计与信号草稿")
            st.session_state.research_draft = draft
            log_research_event(user_id, "research_draft_ready", metadata={"job_id": job["id"], "evidence_count": len(draft.evidence)})
            progress.progress(100, text="完成：请审阅草稿后再生成最终 HTML")
            st.success("证据审计和信号草稿已生成。")
        except Exception as exc:
            progress.empty()
            st.error(f"任务失败：{exc}")


def render_draft_review(user_id: str) -> None:
    draft = st.session_state.research_draft
    if not draft:
        return

    st.subheader("4. 审阅草稿")
    summary_cols = st.columns(4)
    summary_cols[0].metric("候选证据", len(draft.evidence))
    summary_cols[1].metric("信号草稿", len(draft.signals))
    summary_cols[2].metric("审计项", len(draft.audit_findings))
    summary_cols[3].metric("可比组", len(draft.comparable_groups))

    tab_signals, tab_audit, tab_evidence, tab_plan = st.tabs(["信号草稿", "证据审计", "候选证据", "下一步验证"])
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

    st.subheader("5. 你确认后生成 HTML")
    confirmed = st.checkbox("我已审阅证据审计和信号草稿，允许生成 HTML 交付物", value=False)
    col_memo, col_dashboard = st.columns(2)
    with col_memo:
        if st.button("生成投资备忘录 HTML", disabled=not confirmed, use_container_width=True):
            path = save_memo_html(draft)
            st.session_state.memo_path = str(path)
            report = store_report_metadata(_job_id(), user_id, "memo", str(path), draft)
            log_research_event(user_id, "memo_html_generated", report_id=report["id"], metadata={"path": str(path)})
            st.success(f"已生成：{path}")
    with col_dashboard:
        if st.button("生成交互看板 HTML", disabled=not confirmed, use_container_width=True):
            path = save_dashboard_html(draft)
            st.session_state.dashboard_path = str(path)
            report = store_report_metadata(_job_id(), user_id, "dashboard", str(path), draft)
            log_research_event(user_id, "dashboard_html_generated", report_id=report["id"], metadata={"path": str(path)})
            st.success(f"已生成：{path}")

    render_downloads()


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
    user_id, claude_api_key = render_sidebar()
    st.title("🧠 AI 行业研究工具 · 独立原型入口")
    st.caption("目标：从大量公司文件、业绩会纪要、外部可信信息中筛出真正值得投资人关注的信号，并生成可追溯 HTML。")
    render_target_form()
    st.divider()
    selected_groups = render_comparable_editor()
    st.divider()
    render_task_runner(user_id, claude_api_key, selected_groups)
    st.divider()
    render_draft_review(user_id)
    st.caption("V0.1 原型：同步执行任务并模拟任务队列。下一阶段会接入真正后台队列、微信登录/通知、权限管理和访问行为日志。")


if __name__ == "__main__":
    main()

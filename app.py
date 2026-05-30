from __future__ import annotations

import importlib
import os
import shutil
from pathlib import Path
from typing import Any

import streamlit as st


st.set_page_config(page_title="全球上市公司文件下载工具", page_icon="📊", layout="wide")


MODULE_NAMES = {
    "company_search": "src.company_search_global",
    "sec": "src.filing_fetcher_us",
    "hkex": "src.hkex_fetcher",
    "ir": "src.ir_scraper",
    "transcript": "src.transcript_fetcher",
    "table": "src.table_extractor",
    "excel": "src.excel_writer",
    "packager": "src.download_packager",
    "utils": "src.utils",
}


@st.cache_resource(show_spinner=False)
def load_modules() -> tuple[dict[str, Any], dict[str, str]]:
    modules: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name, module_path in MODULE_NAMES.items():
        try:
            modules[name] = importlib.import_module(module_path)
        except Exception as exc:
            errors[name] = f"{module_path}: {exc}"
    return modules, errors


def get_kind_labels() -> dict[str, str]:
    return {
        "annual": "年度报告",
        "quarterly": "季度 / 中期报告",
        "prospectus": "招股说明书",
        "transcript": "Earnings Call Transcript",
        "presentation": "Earnings Presentation / IR Deck",
        "proxy": "Proxy 代理声明",
    }


def init_state() -> None:
    st.session_state.setdefault("search_results", [])
    st.session_state.setdefault("selected_company", None)
    st.session_state.setdefault("filing_results", [])
    st.session_state.setdefault("package_path", "")
    st.session_state.setdefault("package_summary", {})


def company_card(company: dict[str, Any], index: int) -> None:
    flag = company.get("flag", "🌐")
    name = company.get("name") or company.get("name_en") or "-"
    name_en = company.get("name_en") or ""
    ticker = company.get("ticker") or company.get("local_code") or "-"
    exchange = company.get("exchange") or company.get("market") or "-"
    source = company.get("source", "")
    with st.container(border=True):
        col_info, col_action = st.columns([5, 1])
        with col_info:
            st.markdown(f"### {flag} {name}")
            st.caption(f"{name_en} · {ticker} · {exchange} · {source}")
        with col_action:
            if st.button("选择", key=f"select_{index}", use_container_width=True):
                st.session_state.selected_company = company
                st.session_state.filing_results = []
                st.rerun()


def render_filing_group(source: str, items: list[dict[str, Any]]) -> None:
    with st.expander(f"{source} · {len(items)} 条", expanded=True):
        for item in items:
            icon = "📄" if item.get("is_direct_file", True) else "🔗"
            title = item.get("title") or item.get("url") or "未命名文件"
            url = item.get("url", "")
            date = item.get("date", "")
            form = item.get("form", "")
            note = item.get("note", "")
            line = f"{icon} [{title}]({url})"
            if date or form:
                line += f"  \n`{date}` `{form}`"
            if note:
                line += f"  \n{note}"
            st.markdown(line)
            index_url = item.get("index_url")
            if index_url:
                st.caption(f"索引页：{index_url}")


def get_hkex_filings(modules: dict[str, Any], company: dict[str, Any], kinds: list[str]) -> list[dict[str, Any]]:
    hkex = modules.get("hkex")
    if not hkex:
        return []
    if company.get("market") != "港股" and company.get("exchange") != "HKEX":
        return []
    try:
        return hkex.fetch_hkex_filings(company.get("local_code", ""), kinds=kinds, limit=20)
    except Exception:
        return []


def collect_filings(
    modules: dict[str, Any],
    company: dict[str, Any],
    kinds: list[str],
    year: str,
    enhanced_download: bool,
    claude_api_key: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    sec = modules.get("sec")
    ir = modules.get("ir")
    transcript = modules.get("transcript")
    utils = modules.get("utils")
    sec_kinds = [kind for kind in kinds if kind in {"annual", "quarterly", "prospectus", "presentation", "proxy"}]
    if sec and company.get("cik") and sec_kinds:
        try:
            results.extend(sec.fetch_sec_filings(company["cik"], kinds=sec_kinds, year=year, limit=50, include_exhibits=("presentation" in kinds)))
        except Exception:
            pass

    results.extend(get_hkex_filings(modules, company, kinds))

    if ir and any(kind in kinds for kind in ["annual", "quarterly", "presentation"]):
        try:
            results.extend(ir.find_ir_documents(company, kinds=kinds, claude_api_key=claude_api_key, max_results=12))
        except Exception:
            pass

    filing_dates = [item.get("date", "") for item in results if item.get("date")]
    if transcript and "transcript" in kinds:
        try:
            results.extend(
                transcript.find_transcripts(
                    company.get("ticker") or company.get("local_code") or "",
                    company.get("name_en") or company.get("name") or "",
                    filing_dates=filing_dates,
                    claude_api_key=claude_api_key,
                )
            )
        except Exception:
            pass

    if enhanced_download:
        ticker = company.get("ticker") or company.get("local_code") or "company"
        target_dir = Path("downloads") / str(ticker)
        if transcript and "transcript" in kinds:
            transcript_items = [item for item in results if item.get("kind") == "transcript"]
            try:
                transcript.download_transcript_items(transcript_items, target_dir / "Transcripts", ticker=ticker)
            except Exception:
                pass
        if ir and "presentation" in kinds:
            presentation_items = [item for item in results if item.get("kind") == "presentation"]
            try:
                ir.download_presentations(presentation_items, target_dir / "Presentations", ticker=ticker)
            except Exception:
                pass

    if utils:
        if not results:
            return utils.fallback_links(company, kinds)
        results = utils.dedupe_links(results)
        fallback = [
            dict(item, source="搜索建议")
            for item in utils.fallback_links(company, kinds)
        ]
        existing = {item.get("url") for item in results}
        results.extend(item for item in fallback if item.get("url") not in existing)
    return results


def create_zip_package(modules: dict[str, Any], company: dict[str, Any], items: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    packager = modules.get("packager")
    transcript = modules.get("transcript")
    ir = modules.get("ir")
    if not packager:
        return "", {"error": "打包模块未加载"}
    ticker = company.get("ticker") or company.get("local_code") or "company"
    safe_ticker = "".join(ch for ch in str(ticker) if ch.isalnum() or ch in "-_") or "company"
    root = Path("downloads") / safe_ticker
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    extra_files: list[Path] = []
    transcript_items = [item for item in items if item.get("kind") == "transcript"]
    presentation_items = [item for item in items if item.get("kind") == "presentation"]
    if transcript and transcript_items:
        try:
            extra_files.extend(transcript.download_transcript_items(transcript_items, root / "Transcripts", ticker=safe_ticker))
        except Exception:
            pass
    if ir and presentation_items:
        try:
            extra_files.extend(ir.download_presentations(presentation_items, root / "Presentations", ticker=safe_ticker))
        except Exception:
            pass
    general_items = [item for item in items if item not in transcript_items and item not in presentation_items]
    zip_path, downloaded = packager.package_downloads(general_items, root, f"{safe_ticker}_documents", extra_files=extra_files)
    summary = {
        "downloaded": len(downloaded),
        "extra": len(extra_files),
        "total": len(downloaded) + len(extra_files),
        "links": len(items),
    }
    return str(zip_path), summary


def render_sidebar(module_errors: dict[str, str]) -> str:
    with st.sidebar:
        st.header("设置")
        claude_api_key = st.text_input(
            "Anthropic API Key（可选）",
            type="password",
            help="仅用于表格 Sheet 智能命名，以及自动发现失败时的 LLM 兜底。",
        )
        st.divider()
        st.subheader("数据来源")
        st.caption("SEC EDGAR、港交所披露易、公司 IR 官网、公开网页搜索与用户上传 PDF。")
        st.caption("仅供学习研究，请遵守各数据源使用条款。")
        st.subheader("已知限制")
        st.caption("A 股、部分港股与欧洲公司可能只能提供官方平台跳转。扫描版 PDF 无法直接提取表格。")
        if module_errors:
            with st.expander("模块加载提醒"):
                for name, error in module_errors.items():
                    st.warning(f"{name}: {error}")
                st.caption("部分功能模块加载失败不影响基础搜索与其它功能。")
    return claude_api_key


def render_search(modules: dict[str, Any]) -> None:
    st.header("公司搜索")
    col_input, col_button = st.columns([5, 1])
    with col_input:
        query = st.text_input(
            "输入公司简称、中文名、英文名或证券代码",
            placeholder="TSMC、台积电、2330、Apple、AAPL、Infineon、腾讯、0700…",
            label_visibility="collapsed",
        )
    with col_button:
        search_clicked = st.button("搜索", type="primary", use_container_width=True)
    if search_clicked and query.strip():
        search_module = modules.get("company_search")
        if not search_module:
            st.error("公司搜索模块未加载。")
        else:
            with st.spinner("正在搜索全球上市公司…"):
                st.session_state.search_results = search_module.search_companies(query, limit=12)
                st.session_state.selected_company = None
                st.session_state.filing_results = []
    if st.session_state.search_results:
        st.subheader("搜索结果")
        for index, company in enumerate(st.session_state.search_results):
            company_card(company, index)


def render_company_detail(modules: dict[str, Any], claude_api_key: str) -> None:
    company = st.session_state.selected_company
    if not company:
        return
    st.header("公司详情")
    flag = company.get("flag", "🌐")
    st.markdown(f"### {flag} {company.get('name') or company.get('name_en')}")
    st.caption(
        f"{company.get('name_en','')} · {company.get('ticker') or company.get('local_code','')} · "
        f"{company.get('exchange','')} · CIK: {company.get('cik') or '无'}"
    )
    labels = get_kind_labels()
    default_labels = ["年度报告"]
    selected_labels = st.multiselect("文件类型", list(labels.values()), default=default_labels)
    reverse_labels = {label: key for key, label in labels.items()}
    kinds = [reverse_labels[label] for label in selected_labels]
    col_year, col_quarter, col_enhanced = st.columns([1, 1, 2])
    with col_year:
        year_choice = st.selectbox("报告年份", ["最新（不限年份）", "2026", "2025", "2024", "2023", "2022", "2021", "2020"], index=0)
    with col_quarter:
        st.selectbox("季度", ["全年 / 不限", "Q1", "Q2", "Q3", "Q4"], index=0)
    with col_enhanced:
        enhanced_download = st.checkbox("使用增强下载（Transcript & Presentation 存入本地 downloads/）", value=False)

    if st.button("🔍 获取文件列表", type="primary", use_container_width=True):
        year = "" if year_choice.startswith("最新") else year_choice
        with st.spinner("正在从 SEC、港交所、IR 官网与搜索兜底收集文件…"):
            st.session_state.filing_results = collect_filings(modules, company, kinds, year, enhanced_download, claude_api_key)

    if st.session_state.filing_results:
        st.subheader("文件清单")
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in st.session_state.filing_results:
            grouped.setdefault(item.get("source", "其它"), []).append(item)
        for source, items in grouped.items():
            render_filing_group(source, items)
        st.divider()
        col_pack, col_download = st.columns([1, 1])
        with col_pack:
            if st.button("📦 下载并打包全部可下载文件", type="primary", use_container_width=True):
                with st.spinner("正在下载直链文件、保存 transcript / presentation，并生成 ZIP…"):
                    path, summary = create_zip_package(modules, company, st.session_state.filing_results)
                    st.session_state.package_path = path
                    st.session_state.package_summary = summary
        with col_download:
            package_path = Path(st.session_state.package_path) if st.session_state.package_path else None
            if package_path and package_path.exists():
                summary = st.session_state.package_summary or {}
                st.success(f"已打包 {summary.get('total', 0)} 个文件，并附带 {summary.get('links', 0)} 条链接清单")
                st.download_button(
                    "下载 ZIP 文件包",
                    data=package_path.read_bytes(),
                    file_name=package_path.name,
                    mime="application/zip",
                    use_container_width=True,
                )


def render_table_extractor(modules: dict[str, Any], claude_api_key: str) -> None:
    st.header("PDF 表格提取")
    st.caption("支持文字版 PDF。扫描版或图片型 PDF 通常无法提取，需要先 OCR。")
    uploaded_files = st.file_uploader("上传一个或多个 PDF", type=["pdf"], accept_multiple_files=True)
    if not uploaded_files:
        return
    table_module = modules.get("table")
    excel_module = modules.get("excel")
    if not table_module or not excel_module:
        st.error("表格提取或 Excel 写出模块未加载。")
        return
    if st.button("📥 提取表格并生成 Excel", use_container_width=True):
        for uploaded_file in uploaded_files:
            with st.spinner(f"正在处理 {uploaded_file.name}…"):
                try:
                    tables = table_module.extract_tables_from_pdf(uploaded_file.getvalue())
                    workbook_bytes = excel_module.tables_to_workbook_bytes(tables, claude_api_key=claude_api_key)
                    filename = excel_module.excel_filename(uploaded_file.name)
                    st.success(f"{uploaded_file.name}：提取到 {len(tables)} 个表格")
                    st.download_button(
                        "下载 Excel",
                        data=workbook_bytes,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"download_{uploaded_file.name}",
                    )
                except Exception as exc:
                    st.error(f"{uploaded_file.name} 处理失败：{exc}")


def main() -> None:
    init_state()
    modules, module_errors = load_modules()
    claude_api_key = render_sidebar(module_errors)
    st.title("📊 全球上市公司文件下载工具")
    st.caption("搜索公司、勾选文件类型、获取公开披露文件链接，并把文字版 PDF 表格导出为 Excel。")

    tab_search, tab_tables = st.tabs(["文件下载", "PDF 表格提取"])
    with tab_search:
        render_search(modules)
        render_company_detail(modules, claude_api_key)
    with tab_tables:
        render_table_extractor(modules, claude_api_key)

    st.divider()
    st.caption("数据来自公开披露平台与公司官网。工具仅供学习研究，请遵守 SEC、HKEX、IR 托管平台及第三方网页的使用条款。")


if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    main()

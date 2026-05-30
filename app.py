from __future__ import annotations

import importlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


st.set_page_config(page_title="全球上市公司文件下载工具", page_icon="📊", layout="wide")


MODULE_NAMES = {
    "company_search": "src.company_search_global",
    "sec": "src.filing_fetcher_us",
    "hkex": "src.hkex_fetcher",
    "cninfo": "src.cninfo_fetcher",
    "ir": "src.ir_scraper",
    "transcript": "src.transcript_fetcher",
    "china": "src.china_sources",
    "bing": "src.bing_discovery",
    "platforms": "src.platform_discovery",
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
    years: list[str] | str,
    enhanced_download: bool,
    claude_api_key: str,
    quarters: list[str] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    sec = modules.get("sec")
    cninfo = modules.get("cninfo")
    ir = modules.get("ir")
    transcript = modules.get("transcript")
    china = modules.get("china")
    bing = modules.get("bing")
    platforms = modules.get("platforms")
    utils = modules.get("utils")
    selected_years = [years] if isinstance(years, str) and years else list(years or [])
    sec_kinds = [kind for kind in kinds if kind in {"annual", "quarterly", "prospectus", "presentation", "proxy"}]
    if sec and company.get("cik") and sec_kinds:
        try:
            results.extend(sec.fetch_sec_filings_for_years(company["cik"], kinds=sec_kinds, years=selected_years, limit_per_year=20, include_exhibits=("presentation" in kinds)))
        except Exception:
            pass

    if cninfo and any(kind in kinds for kind in ["annual", "quarterly"]):
        try:
            results.extend(cninfo.fetch_cninfo_filings(company, kinds=kinds, years=selected_years, quarters=quarters or [], limit=50))
        except Exception:
            pass

    results.extend(get_hkex_filings(modules, company, kinds))

    if ir and any(kind in kinds for kind in ["annual", "quarterly", "presentation"]):
        try:
            results.extend(ir.find_ir_documents(company, kinds=kinds, claude_api_key=claude_api_key, max_results=12))
        except Exception:
            pass

    if china and any(kind in kinds for kind in ["annual", "quarterly", "transcript", "presentation"]):
        try:
            results.extend(china.find_china_research_links(company, kinds=kinds, years=selected_years, quarters=quarters or [], max_results=24))
        except Exception:
            pass

    if bing and any(kind in kinds for kind in ["annual", "quarterly", "transcript", "presentation", "prospectus", "proxy"]):
        try:
            results.extend(bing.find_bing_targeted_links(company, kinds=kinds, years=selected_years, quarters=quarters or [], max_results=36, max_search_attempts=18))
        except Exception:
            pass

    if platforms and any(kind in kinds for kind in ["transcript", "presentation"]):
        try:
            results.extend(platforms.discover_platform_links(company, kinds=kinds, years=selected_years, quarters=quarters or [], max_results=28))
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
    return filter_results_by_years(results, selected_years)


def filter_results_by_years(items: list[dict[str, Any]], years: list[str]) -> list[dict[str, Any]]:
    if not years:
        return items
    selected = set(years)
    filtered: list[dict[str, Any]] = []
    strict_sources = {"SEC EDGAR", "SEC EDGAR 附件", "巨潮资讯官方公告", "港交所披露易", "IR 官网", "IR 官网 Presentation", "IR (Q4 Events)"}
    for item in items:
        source = str(item.get("source", ""))
        if source not in strict_sources:
            filtered.append(item)
            continue
        text = " ".join(str(item.get(field, "")) for field in ["date", "title", "url"])
        if any(year in text for year in selected):
            filtered.append(item)
    return filtered or items


def create_zip_package(modules: dict[str, Any], company: dict[str, Any], items: list[dict[str, Any]], claude_api_key: str = "") -> tuple[str, dict[str, Any]]:
    packager = modules.get("packager")
    transcript = modules.get("transcript")
    ir = modules.get("ir")
    table = modules.get("table")
    excel = modules.get("excel")
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
    zip_path, downloaded = packager.package_downloads(
        general_items,
        root,
        f"{safe_ticker}_documents",
        extra_files=extra_files,
        table_module=table,
        excel_module=excel,
        claude_api_key=claude_api_key,
    )
    excel_files = list((root / "Excel").glob("*.xlsx")) if (root / "Excel").exists() else []
    summary = {
        "downloaded": len(downloaded),
        "extra": len(extra_files),
        "total": len(downloaded) + len(extra_files),
        "links": len(items),
        "excel": len(excel_files),
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
        st.caption("SEC EDGAR、巨潮资讯、港交所披露易、公司 IR 官网、微信公众号 / 中文投研网页搜索、Bing 定向搜索、Transcript / Presentation 平台深搜。")
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
    with st.form("company_search_form", clear_on_submit=False):
        query = st.text_input(
            "输入公司简称、中文名、英文名或证券代码",
            placeholder="TSMC、台积电、2330、Apple、AAPL、Infineon、腾讯、0700…",
            label_visibility="collapsed",
        )
        search_clicked = st.form_submit_button("搜索", type="primary", use_container_width=True)
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
    st.markdown("**文件类型**")
    all_kinds_selected = st.checkbox("全选", value=False, key="kind_select_all")
    default_kinds = {"annual"}
    kinds: list[str] = []
    cols = st.columns(2)
    for index, (kind, label) in enumerate(labels.items()):
        with cols[index % 2]:
            checked = st.checkbox(label, value=all_kinds_selected or kind in default_kinds, key=f"kind_{kind}")
            if checked:
                kinds.append(kind)
    current_year = datetime.now().year
    year_options = [str(year) for year in range(current_year, current_year - 20, -1)]
    with st.expander("报告年份", expanded=True):
        year_select_all = st.checkbox("年份全选", value=False, key="year_select_all")
        year_cols = st.columns(5)
        selected_years: list[str] = []
        for index, year in enumerate(year_options):
            with year_cols[index % 5]:
                checked = st.checkbox(year, value=year_select_all or index < 3, key=f"year_{year}")
                if checked:
                    selected_years.append(year)
    with st.expander("季度", expanded=False):
        quarter_select_all = st.checkbox("季度全选", value=True, key="quarter_select_all")
        quarter_options = ["全年", "Q1", "Q2", "Q3", "Q4"]
        quarter_cols = st.columns(5)
        selected_quarters: list[str] = []
        for index, quarter in enumerate(quarter_options):
            with quarter_cols[index]:
                checked = st.checkbox(quarter, value=quarter_select_all or quarter == "全年", key=f"quarter_{quarter}")
                if checked:
                    selected_quarters.append(quarter)
    enhanced_download = st.checkbox("使用增强下载（Transcript & Presentation 存入本地 downloads/）", value=False)

    if st.button("🔍 获取文件列表", type="primary", use_container_width=True):
        if not kinds:
            st.warning("请至少选择一种文件类型。")
            return
        if not selected_years:
            st.warning("请至少选择一个年份。")
            return
        if not selected_quarters:
            st.warning("请至少选择一个季度。")
            return
        with st.spinner("正在从 SEC、港交所、IR 官网与搜索兜底收集文件…"):
            st.session_state.filing_results = collect_filings(modules, company, kinds, selected_years, enhanced_download, claude_api_key, selected_quarters)

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
            if st.button("📦 下载文件、提取表格并打包 ZIP", type="primary", use_container_width=True):
                with st.spinner("正在下载文件、提取表格、生成 Excel，并打包 ZIP…"):
                    path, summary = create_zip_package(modules, company, st.session_state.filing_results, claude_api_key)
                    st.session_state.package_path = path
                    st.session_state.package_summary = summary
        with col_download:
            package_path = Path(st.session_state.package_path) if st.session_state.package_path else None
            if package_path and package_path.exists():
                summary = st.session_state.package_summary or {}
                st.success(f"已打包 {summary.get('total', 0)} 个文件、{summary.get('excel', 0)} 个 Excel，并附带 {summary.get('links', 0)} 条链接清单")
                st.download_button(
                    "下载 ZIP 文件包",
                    data=package_path.read_bytes(),
                    file_name=package_path.name,
                    mime="application/zip",
                    use_container_width=True,
                )


def main() -> None:
    init_state()
    modules, module_errors = load_modules()
    claude_api_key = render_sidebar(module_errors)
    st.title("📊 全球上市公司文件下载工具")
    st.caption("搜索公司、勾选文件类型、获取公开披露文件，并在打包下载时自动提取表格生成 Excel。")

    render_search(modules)
    render_company_detail(modules, claude_api_key)

    st.divider()
    st.caption("数据来自公开披露平台与公司官网。工具仅供学习研究，请遵守 SEC、HKEX、IR 托管平台及第三方网页的使用条款。")


if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    main()

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .utils import DEFAULT_HEADERS, clean_filename, extension_from_response, html_link_manifest
from .web_pdf import pdf_filename_for_url, save_html_as_pdf


def _category_for_item(item: dict[str, Any]) -> str:
    kind = (item.get("kind") or "").casefold()
    source = (item.get("source") or "").casefold()
    form = (item.get("form") or "").casefold()
    if "transcript" in kind or "transcript" in source:
        return "Transcripts"
    if "presentation" in kind or "presentation" in source:
        return "Presentations"
    if "hkex" in source or "港交所" in source:
        return "HKEX"
    if "sec" in source or form:
        return "SEC_Filings"
    return "IR_and_Links"


def _filename_for_item(item: dict[str, Any], index: int) -> str:
    ticker = item.get("ticker") or ""
    form = item.get("form") or item.get("kind") or "document"
    date = item.get("date") or ""
    title = item.get("title") or item.get("url") or f"document_{index}"
    return clean_filename("_".join(str(part) for part in [ticker, form, date, title] if part), f"document_{index}")[:150]


def download_file_item(item: dict[str, Any], target_dir: Path, index: int, timeout: float = 18) -> Path | None:
    url = item.get("url", "")
    if not url or not url.startswith("http"):
        return None
    try:
        response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
    except Exception:
        return None
    if len(response.content) < 200:
        return None
    category_dir = target_dir / _category_for_item(item)
    category_dir.mkdir(parents=True, exist_ok=True)
    filename = _filename_for_item(item, index)
    content_type = response.headers.get("Content-Type", "")
    is_pdf = ".pdf" in urlparse(response.url or url).path.casefold() or "pdf" in content_type.casefold()
    is_html = "html" in content_type.casefold() or "<html" in response.text[:500].casefold()
    if not item.get("is_direct_file", True) or is_html:
        path = category_dir / pdf_filename_for_url(url, item.get("title") or filename, f"web_page_{index}")
        try:
            save_html_as_pdf(response.text, path, source_url=response.url or url, title=item.get("title") or "")
            return path
        except Exception:
            path = category_dir / f"{filename}.html"
            path.write_text(response.text, encoding="utf-8", errors="ignore")
            return path
    extension = ".pdf" if is_pdf else extension_from_response(url, content_type)
    path = category_dir / f"{filename}{extension}"
    counter = 2
    while path.exists():
        path = category_dir / f"{filename}_{counter}{extension}"
        counter += 1
    path.write_bytes(response.content)
    return path


def package_downloads(
    items: list[dict[str, Any]],
    output_root: str | Path,
    package_name: str,
    extra_files: list[str | Path] | None = None,
    table_module: Any = None,
    excel_module: Any = None,
    claude_api_key: str = "",
) -> tuple[Path, list[Path]]:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for index, item in enumerate(items, start=1):
        path = download_file_item(item, output_root, index)
        if path:
            downloaded.append(path)
    manifest_path = output_root / "links_manifest.html"
    manifest_path.write_text(html_link_manifest(items, title=f"{package_name} links"), encoding="utf-8")
    files = [*downloaded, manifest_path]
    for extra in extra_files or []:
        extra_path = Path(extra)
        if extra_path.exists():
            files.append(extra_path)
    excel_path = extract_tables_to_excel(files, output_root, package_name, table_module, excel_module, claude_api_key)
    if excel_path:
        files.append(excel_path)
    zip_path = output_root / f"{clean_filename(package_name, 'documents')}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.exists() and path != zip_path:
                archive.write(path, path.relative_to(output_root))
    return zip_path, downloaded


def extract_tables_to_excel(
    files: list[Path],
    output_root: Path,
    package_name: str,
    table_module: Any = None,
    excel_module: Any = None,
    claude_api_key: str = "",
) -> Path | None:
    if not table_module or not excel_module:
        return None
    all_tables = []
    for file_path in files:
        if file_path.suffix.lower() not in {".pdf", ".htm", ".html", ".xhtml"}:
            continue
        try:
            all_tables.extend(table_module.extract_tables_from_path(file_path))
        except Exception:
            continue
    if not all_tables:
        return None
    excel_dir = output_root / "Excel"
    excel_dir.mkdir(parents=True, exist_ok=True)
    workbook_bytes = excel_module.tables_to_workbook_bytes(all_tables, claude_api_key=claude_api_key)
    excel_path = excel_dir / f"{clean_filename(package_name, 'tables')}_tables.xlsx"
    excel_path.write_bytes(workbook_bytes)
    return excel_path

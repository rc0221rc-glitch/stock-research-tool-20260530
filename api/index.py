from __future__ import annotations

import base64
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from api.filings import collect_filings


ROOT = Path(__file__).resolve().parents[1]
MAX_PACKAGE_ITEMS = 12


def _json_payload(payload: Any, status: str = "200 OK") -> tuple[str, list[tuple[str, str]], bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Methods", "GET,POST,OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type"),
        ("Content-Length", str(len(body))),
    ]
    return status, headers, body


def _html_payload(html: str, status: str = "200 OK") -> tuple[str, list[tuple[str, str]], bytes]:
    body = html.encode("utf-8")
    return status, [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))], body


def _read_body(environ: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    raw = environ["wsgi.input"].read(length)
    return json.loads(raw.decode("utf-8") or "{}")


def _runtime_note() -> str:
    return (
        "Vercel 轻量版运行在 Serverless Function 上，适合搜索和小体积打包；"
        "大文件下载、长耗时网页转 PDF 和完整 Streamlit 交互建议使用 Streamlit Cloud 正式版。"
    )


def _serve_index() -> tuple[str, list[tuple[str, str]], bytes]:
    index_path = ROOT / "public" / "index.html"
    if not index_path.exists():
        return _html_payload("<h1>Vercel frontend not found</h1>", "404 Not Found")
    return _html_payload(index_path.read_text(encoding="utf-8"))


def _search(environ: dict[str, Any]) -> tuple[str, list[tuple[str, str]], bytes]:
    query = parse_qs(environ.get("QUERY_STRING", "")).get("q", [""])[0].strip()
    if not query:
        return _json_payload({"results": [], "note": _runtime_note()})
    from src.company_search_global import search_companies

    return _json_payload({"results": search_companies(query, limit=12), "note": _runtime_note()})


def _filings(environ: dict[str, Any]) -> tuple[str, list[tuple[str, str]], bytes]:
    body = _read_body(environ)
    company = body.get("company") or {}
    if not company:
        return _json_payload({"error": "Missing company"}, "400 Bad Request")
    results = collect_filings(company, body.get("kinds") or ["annual"], body.get("years") or [], body.get("quarters") or [])
    return _json_payload({"results": results, "note": _runtime_note()})


def _package(environ: dict[str, Any]) -> tuple[str, list[tuple[str, str]], bytes]:
    body = _read_body(environ)
    items = list(body.get("items") or [])[:MAX_PACKAGE_ITEMS]
    company = body.get("company") or {}
    if not items:
        return _json_payload({"error": "Missing items"}, "400 Bad Request")
    root = Path(tempfile.mkdtemp(prefix="stock_research_vercel_"))
    try:
        from src import download_packager, excel_writer, table_extractor
        from src.vercel_common import anthropic_key

        ticker = company.get("ticker") or company.get("local_code") or "company"
        safe_ticker = "".join(ch for ch in str(ticker) if ch.isalnum() or ch in "-_") or "company"
        zip_path, downloaded = download_packager.package_downloads(
            items,
            root,
            f"{safe_ticker}_vercel_documents",
            table_module=table_extractor,
            excel_module=excel_writer,
            claude_api_key=anthropic_key(),
        )
        size = zip_path.stat().st_size if zip_path.exists() else 0
        if size > 4_200_000:
            return _json_payload({"error": "ZIP 超过 Vercel Function 推荐响应体大小，请减少勾选链接或使用 Streamlit Cloud 正式版打包。"}, "413 Payload Too Large")
        payload = {
            "filename": zip_path.name,
            "content_base64": base64.b64encode(zip_path.read_bytes()).decode("ascii"),
            "downloaded": len(downloaded),
            "note": _runtime_note(),
        }
        return _json_payload(payload)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def app(environ: dict[str, Any], start_response: Callable[[str, list[tuple[str, str]]], None]) -> list[bytes]:
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")
    try:
        if method == "OPTIONS":
            status, headers, body = _json_payload({}, "204 No Content")
        elif path == "/" or path == "/index.html" or not path.startswith("/api/"):
            status, headers, body = _serve_index()
        elif path == "/api/search" and method == "GET":
            status, headers, body = _search(environ)
        elif path == "/api/filings" and method == "POST":
            status, headers, body = _filings(environ)
        elif path == "/api/package" and method == "POST":
            status, headers, body = _package(environ)
        else:
            status, headers, body = _json_payload({"error": "Not found"}, "404 Not Found")
    except Exception as exc:
        status, headers, body = _json_payload({"error": str(exc)}, "500 Internal Server Error")
    start_response(status, headers)
    return [body]

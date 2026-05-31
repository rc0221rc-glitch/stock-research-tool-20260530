from __future__ import annotations

import shutil
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from ._common import anthropic_key, encoded_file_response, error_response, handle_options, json_response, read_json_body, runtime_note


MAX_PACKAGE_ITEMS = 12


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        handle_options(self)

    def do_POST(self) -> None:
        if handle_options(self):
            return
        root = Path(tempfile.mkdtemp(prefix="stock_research_vercel_"))
        try:
            body = read_json_body(self)
            items = list(body.get("items") or [])[:MAX_PACKAGE_ITEMS]
            company = body.get("company") or {}
            if not items:
                error_response(self, "Missing items", status=400)
                return
            from src import download_packager, excel_writer, table_extractor

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
                error_response(
                    self,
                    "ZIP 超过 Vercel Function 推荐响应体大小，请减少勾选链接或使用 Streamlit Cloud 正式版打包。",
                    status=413,
                )
                return
            payload = encoded_file_response(zip_path)
            payload.update({"downloaded": len(downloaded), "note": runtime_note()})
            json_response(self, payload)
        except Exception as exc:
            error_response(self, str(exc))
        finally:
            shutil.rmtree(root, ignore_errors=True)

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any


def json_response(handler: Any, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def error_response(handler: Any, message: str, status: int = 500) -> None:
    json_response(handler, {"error": message}, status=status)


def read_json_body(handler: Any) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    data = handler.rfile.read(length)
    return json.loads(data.decode("utf-8") or "{}")


def handle_options(handler: Any) -> bool:
    if getattr(handler, "command", "") != "OPTIONS":
        return False
    handler.send_response(204)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    return True


def encoded_file_response(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    return {
        "filename": file_path.name,
        "content_base64": base64.b64encode(file_path.read_bytes()).decode("ascii"),
    }


def runtime_note() -> str:
    return (
        "Vercel 轻量版运行在 Serverless Function 上，适合搜索和小体积打包；"
        "大文件下载、长耗时网页转 PDF 和完整 Streamlit 交互建议使用 Streamlit Cloud 正式版。"
    )


def anthropic_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "")

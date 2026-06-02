from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


WIND_SKILL_DIR = Path(r"C:\Users\caojm\.agents\skills\wind-mcp-skill")
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
WIND_SOURCE_NOTE = "数据来源于万得 Wind 金融数据服务。"


class WindClientError(RuntimeError):
    pass


def is_wind_available() -> bool:
    return WIND_SKILL_DIR.exists() and (WIND_SKILL_DIR / "scripts" / "cli.mjs").exists()


def call_wind(server_type: str, tool_name: str, params: dict[str, Any], timeout: float = 80) -> dict[str, Any]:
    if not is_wind_available():
        raise WindClientError("Wind MCP skill is not installed.")
    params_json = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    if GIT_BASH.exists():
        return _call_with_git_bash(server_type, tool_name, params_json, timeout)
    return _call_with_subprocess(server_type, tool_name, params_json, timeout)


def wind_financial_query(windcode: str, question_suffix: str) -> dict[str, Any]:
    server_type = _server_type_for_windcode(windcode)
    tool_name = "get_stock_fundamentals" if server_type == "stock_data" else "get_global_stock_fundamentals"
    return call_wind(server_type, tool_name, {"question": f"{windcode}{question_suffix}"})


def parse_wind_tables(result: dict[str, Any]) -> list[dict[str, Any]]:
    text = _wind_content_text(result)
    if not text:
        return []
    payload = json.loads(text)
    if payload.get("error"):
        raise WindClientError(str(payload["error"]))
    tables = payload.get("data", {}).get("data", [])
    return tables if isinstance(tables, list) else []


def wind_rows_by_column(table: dict[str, Any]) -> list[dict[str, Any]]:
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    names = [str(column.get("name") or "") for column in columns]
    normalized_rows = []
    for row in rows:
        if isinstance(row, list):
            normalized_rows.append({names[index]: row[index] for index in range(min(len(names), len(row)))})
    return normalized_rows


def wind_units_by_column(table: dict[str, Any]) -> dict[str, str]:
    units = {}
    for column in table.get("columns") or []:
        name = str(column.get("name") or "")
        unit = str(column.get("unit") or "")
        if name:
            units[name] = unit
    return units


def normalize_windcode(value: str) -> str:
    ticker = (value or "").strip().upper()
    aliases = {
        "NVDA": "NVDA.O",
        "AMD": "AMD.O",
        "AVGO": "AVGO.O",
        "MRVL": "MRVL.O",
        "ARM": "ARM.O",
        "TSM": "TSM.N",
        "ASML": "ASML.O",
        "AMAT": "AMAT.O",
        "LRCX": "LRCX.O",
        "MU": "MU.O",
        "MSFT": "MSFT.O",
        "GOOGL": "GOOGL.O",
        "AMZN": "AMZN.O",
        "META": "META.O",
        "ORCL": "ORCL.N",
        "SMCI": "SMCI.O",
        "DELL": "DELL.N",
        "HPE": "HPE.N",
        "ANET": "ANET.N",
        "VRT": "VRT.N",
        "GFS": "GFS.O",
        "UMC": "UMC.N",
        "SMIC": "00981.HK",
        "0981.HK": "00981.HK",
        "981.HK": "00981.HK",
        "00700": "00700.HK",
    }
    if ticker in aliases:
        return aliases[ticker]
    if re.fullmatch(r"\d{6}", ticker):
        if ticker.startswith(("6", "9")):
            return f"{ticker}.SH"
        return f"{ticker}.SZ"
    if re.fullmatch(r"\d{1,5}\.HK", ticker):
        code = ticker.split(".", 1)[0].zfill(5)
        return f"{code}.HK"
    if ticker.endswith((".SH", ".SZ", ".BJ", ".HK", ".O", ".N", ".T", ".KS", ".KQ", ".TW", ".DE", ".F", ".L", ".PA", ".AS", ".SW")):
        return ticker
    return ticker


def _call_with_git_bash(server_type: str, tool_name: str, params_json: str, timeout: float) -> dict[str, Any]:
    script_text = (
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "cd /c/Users/caojm/.agents/skills/wind-mcp-skill\n"
        f"node scripts/cli.mjs call {server_type} {tool_name} '{_single_quote_safe(params_json)}'\n"
    )
    fd, script_name = tempfile.mkstemp(prefix="wind_call_", suffix=".sh")
    os.close(fd)
    script_path = Path(script_name)
    try:
        script_path.write_bytes(script_text.encode("utf-8"))
        proc = subprocess.run(
            [str(GIT_BASH), str(script_path)],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    finally:
        try:
            script_path.unlink(missing_ok=True)
        except Exception:
            pass
    return _parse_cli_result(proc)


def _call_with_subprocess(server_type: str, tool_name: str, params_json: str, timeout: float) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", "scripts/cli.mjs", "call", server_type, tool_name, params_json],
        cwd=WIND_SKILL_DIR,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return _parse_cli_result(proc)


def _parse_cli_result(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    stdout = proc.stdout.strip()
    if not stdout:
        raise WindClientError((proc.stderr or "Wind CLI returned no stdout.").strip())
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WindClientError(f"Wind CLI returned non-JSON output: {stdout[:300]}") from exc
    if proc.returncode != 0 or result.get("ok") is False or result.get("isError"):
        error = result.get("error") or result
        raise WindClientError(json.dumps(error, ensure_ascii=False)[:1000])
    return result


def _wind_content_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return str(item.get("text") or "")
    return ""


def _server_type_for_windcode(windcode: str) -> str:
    return "stock_data" if windcode.endswith((".SH", ".SZ", ".BJ")) else "global_stock_data"


def _single_quote_safe(value: str) -> str:
    return value.replace("'", "'\"'\"'")

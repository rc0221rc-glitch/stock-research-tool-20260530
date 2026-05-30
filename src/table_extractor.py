from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO


@dataclass
class ExtractedTable:
    page: int
    index: int
    rows: list[list[str]]
    title: str = ""

    @property
    def preview_text(self) -> str:
        cells: list[str] = []
        for row in self.rows[:4]:
            for cell in row[:5]:
                text = (cell or "").strip()
                if text:
                    cells.append(text)
        return " ".join(cells)[:240]


def _normalize_table(raw_table: list[list[Any]]) -> list[list[str]]:
    width = max((len(row or []) for row in raw_table), default=0)
    rows: list[list[str]] = []
    for row in raw_table:
        normalized = [("" if cell is None else str(cell).strip()) for cell in (row or [])]
        normalized.extend([""] * (width - len(normalized)))
        if any(cell for cell in normalized):
            rows.append(normalized)
    return rows


def _is_noise(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return True
    filled_cells = sum(1 for row in rows for cell in row if cell)
    return filled_cells < 4


def extract_tables_from_pdf(file_obj: BinaryIO | bytes, min_rows: int = 2) -> list[ExtractedTable]:
    import pdfplumber

    stream = io.BytesIO(file_obj) if isinstance(file_obj, bytes) else file_obj
    tables: list[ExtractedTable] = []
    with pdfplumber.open(stream) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            try:
                raw_tables = page.extract_tables() or []
            except Exception:
                raw_tables = []
            for table_index, raw_table in enumerate(raw_tables, start=1):
                rows = _normalize_table(raw_table)
                if len(rows) < min_rows or _is_noise(rows):
                    continue
                tables.append(ExtractedTable(page=page_number, index=table_index, rows=rows, title=f"P{page_number}_{table_index}"))
    return tables


def extract_tables_from_html(html_text: str, source_name: str = "HTML", min_rows: int = 2) -> list[ExtractedTable]:
    from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html_text, "lxml")
    tables: list[ExtractedTable] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        normalized = _normalize_table(rows)
        if len(normalized) < min_rows or _is_noise(normalized):
            continue
        tables.append(ExtractedTable(page=1, index=table_index, rows=normalized, title=f"{source_name}_{table_index}"))
    return tables


def extract_tables_from_path(path: str | Path, min_rows: int = 2) -> list[ExtractedTable]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        tables = extract_tables_from_pdf(file_path.read_bytes(), min_rows=min_rows)
    elif suffix in {".htm", ".html", ".xhtml"}:
        tables = extract_tables_from_html(file_path.read_text(encoding="utf-8", errors="ignore"), file_path.stem, min_rows=min_rows)
    else:
        return []
    for table in tables:
        table.title = f"{file_path.stem}_{table.title or f'T{table.index}'}"
    return tables


def table_context(table: ExtractedTable) -> str:
    return table.preview_text

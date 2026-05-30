from __future__ import annotations

import io
from dataclasses import dataclass
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


def table_context(table: ExtractedTable) -> str:
    return table.preview_text

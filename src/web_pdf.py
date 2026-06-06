from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .utils import clean_filename
from .web_readability import extract_readable_document


MAX_PARAGRAPHS = 180
MAX_TABLES = 18
MAX_TABLE_ROWS = 80
MAX_CELL_CHARS = 260


def _clean_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text


def _safe_paragraph(value: str) -> str:
    return html.escape(_clean_text(value)).replace("\n", "<br/>")


def _title_from_html(soup: BeautifulSoup, fallback: str = "Web Page") -> str:
    candidates = [
        soup.find("meta", property="og:title"),
        soup.find("meta", attrs={"name": "twitter:title"}),
    ]
    for node in candidates:
        content = _clean_text(node.get("content", "") if node else "")
        if content:
            return content[:180]
    if soup.title:
        title = _clean_text(soup.title.get_text(" ", strip=True))
        if title:
            return title[:180]
    h1 = soup.find("h1")
    if h1:
        title = _clean_text(h1.get_text(" ", strip=True))
        if title:
            return title[:180]
    return fallback


def _main_content_node(soup: BeautifulSoup) -> Any:
    for selector in [
        "article",
        "main",
        "[role='main']",
        "#transcript-panel-full",
        "div.article-body",
        "div.article-content",
        "div.entry-content",
        "div.post-content",
        "section.article-body",
        "div[itemprop='articleBody']",
    ]:
        node = soup.select_one(selector)
        if node and len(node.get_text(" ", strip=True)) > 400:
            return node
    candidates = []
    for node in soup.find_all(["article", "main", "section", "div"]):
        text = node.get_text(" ", strip=True)
        if len(text) < 800:
            continue
        score = len(text)
        class_text = " ".join(node.get("class", [])).casefold()
        if any(token in class_text for token in ["article", "content", "transcript", "body"]):
            score += 2000
        candidates.append((score, node))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]
    return soup.body or soup


def _remove_noise(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(["script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "footer", "header"]):
        tag.decompose()
    for selector in [
        "[aria-hidden='true']",
        ".advertisement",
        ".ad",
        ".ads",
        ".cookie",
        ".cookies",
        ".newsletter",
        ".subscribe",
        ".social",
        ".share",
        ".related",
        ".recommend",
    ]:
        for node in soup.select(selector):
            node.decompose()


def _extract_blocks(soup: BeautifulSoup) -> tuple[str, list[str], list[list[list[str]]]]:
    _remove_noise(soup)
    title = _title_from_html(soup)
    content = _main_content_node(soup)
    paragraphs: list[str] = []
    seen: set[str] = set()
    for node in content.find_all(["h1", "h2", "h3", "p", "li", "blockquote", "div"], recursive=True):
        if node.find_parent("table"):
            continue
        text = _clean_text(node.get_text(" ", strip=True))
        if len(text) < 35:
            continue
        lower = text.casefold()
        if any(token in lower[:120] for token in ["cookie", "advertisement", "subscribe", "sign up", "login", "all rights reserved"]):
            continue
        key = lower[:240]
        if key in seen:
            continue
        seen.add(key)
        paragraphs.append(text[:1800])
        if len(paragraphs) >= MAX_PARAGRAPHS:
            break

    tables: list[list[list[str]]] = []
    for table in content.find_all("table")[:MAX_TABLES]:
        rows: list[list[str]] = []
        for tr in table.find_all("tr")[:MAX_TABLE_ROWS]:
            cells = [_clean_text(cell.get_text(" ", strip=True))[:MAX_CELL_CHARS] for cell in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(cells)
        if len(rows) >= 2 and sum(1 for row in rows for cell in row if cell) >= 4:
            width = max(len(row) for row in rows)
            rows = [row + [""] * (width - len(row)) for row in rows]
            tables.append(rows)
    if not paragraphs:
        fallback = _clean_text(content.get_text(" ", strip=True))
        if fallback:
            paragraphs = [fallback[i : i + 1600] for i in range(0, min(len(fallback), 18000), 1600)]
    return title, paragraphs, tables


def _paragraphs_from_readable_text(text: str) -> list[str]:
    paragraphs: list[str] = []
    seen: set[str] = set()
    for raw_paragraph in re.split(r"\n{1,}", text or ""):
        paragraph = _clean_text(raw_paragraph)
        if len(paragraph) < 35:
            continue
        lower = paragraph.casefold()
        if any(token in lower[:120] for token in ["cookie", "advertisement", "subscribe", "sign up", "login", "all rights reserved"]):
            continue
        key = lower[:240]
        if key in seen:
            continue
        seen.add(key)
        paragraphs.append(paragraph[:1800])
        if len(paragraphs) >= MAX_PARAGRAPHS:
            break
    if not paragraphs:
        fallback = _clean_text(text)
        if fallback:
            paragraphs = [fallback[i : i + 1600] for i in range(0, min(len(fallback), 18000), 1600)]
    return paragraphs


def html_to_pdf_bytes(html_text: str, source_url: str = "", title: str = "") -> bytes:
    soup = BeautifulSoup(html_text or "", "lxml")
    html_title, paragraphs, tables = _extract_blocks(soup)
    readable = extract_readable_document(html_text or "", url=source_url, fallback_title=title or html_title or "Web Page")
    readable_paragraphs = _paragraphs_from_readable_text(readable.text)
    if len(" ".join(readable_paragraphs)) > len(" ".join(paragraphs)) * 0.8:
        paragraphs = readable_paragraphs
        html_title = readable.title or html_title
    title = _clean_text(title or html_title or "Web Page")

    from io import BytesIO

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        alignment=TA_LEFT,
        spaceAfter=5,
    )
    small_style = ParagraphStyle("Small", parent=body_style, fontSize=7, leading=10, textColor=colors.HexColor("#555555"))
    heading_style = ParagraphStyle("Heading", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=20, spaceAfter=8)
    table_cell_style = ParagraphStyle("Cell", parent=body_style, fontSize=7, leading=9)

    story: list[Any] = [
        Paragraph(_safe_paragraph(title), heading_style),
    ]
    if source_url:
        story.extend([Paragraph(_safe_paragraph(f"Source: {source_url}"), small_style), Spacer(1, 6)])
    for paragraph in paragraphs:
        story.append(Paragraph(_safe_paragraph(paragraph), body_style))
    for table_index, rows in enumerate(tables, start=1):
        if story:
            story.append(Spacer(1, 8))
        story.append(Paragraph(f"Table {table_index}", styles["Heading3"]))
        styled_rows = [[Paragraph(_safe_paragraph(cell), table_cell_style) for cell in row[:8]] for row in rows]
        table = Table(styled_rows, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(table)
        if table_index < len(tables):
            story.append(PageBreak())
    if len(story) <= (3 if source_url else 2):
        story.append(Paragraph("No readable article text was extracted from this page. Please use the source URL above.", body_style))
    doc.build(story)
    return output.getvalue()


def save_html_as_pdf(html_text: str, target_path: str | Path, source_url: str = "", title: str = "") -> Path:
    path = Path(target_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(html_to_pdf_bytes(html_text, source_url=source_url, title=title))
    return path


def pdf_filename_for_url(url: str, title: str = "", default: str = "web_page") -> str:
    parsed = urlparse(url or "")
    host = parsed.netloc.replace("www.", "")
    path_tail = parsed.path.strip("/").rsplit("/", 1)[-1]
    base = title or " ".join(part for part in [host, path_tail] if part) or default
    return f"{clean_filename(base, default)[:140]}.pdf"

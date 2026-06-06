from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings


@dataclass
class ReadableDocument:
    title: str
    text: str
    html: str = ""
    source: str = ""


def extract_readable_document(html_text: str, *, url: str = "", fallback_title: str = "Web Page") -> ReadableDocument:
    """Extract main article/transcript content using optional OSS tools, with BS4 fallback."""
    for extractor in (_extract_with_trafilatura, _extract_with_readability):
        document = extractor(html_text, url=url, fallback_title=fallback_title)
        if document and len(document.text) >= 500:
            return document
    return _extract_with_bs4(html_text, fallback_title=fallback_title)


def _extract_with_trafilatura(html_text: str, *, url: str, fallback_title: str) -> ReadableDocument | None:
    try:
        import trafilatura
    except Exception:
        return None
    try:
        text = trafilatura.extract(
            html_text,
            url=url or None,
            include_comments=False,
            include_tables=True,
            include_formatting=False,
            favor_recall=True,
        )
        if not text:
            return None
        metadata = trafilatura.extract_metadata(html_text, default_url=url or None)
        title = getattr(metadata, "title", "") if metadata else ""
        return ReadableDocument(title=_clean_text(title) or fallback_title, text=_normalize_text(text), source="trafilatura")
    except Exception:
        return None


def _extract_with_readability(html_text: str, *, url: str, fallback_title: str) -> ReadableDocument | None:
    try:
        from readability import Document
    except Exception:
        return None
    try:
        document = Document(html_text, url=url or None)
        title = _clean_text(document.short_title() or document.title() or fallback_title)
        content_html = document.summary(html_partial=True)
        text = _text_from_html(content_html)
        if not text:
            return None
        return ReadableDocument(title=title or fallback_title, text=text, html=content_html, source="readability-lxml")
    except Exception:
        return None


def _extract_with_bs4(html_text: str, *, fallback_title: str) -> ReadableDocument:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html_text or "", "lxml")
    title = _title_from_soup(soup, fallback_title=fallback_title)
    _remove_noise(soup)
    content = _main_content_node(soup)
    text = _normalize_text(content.get_text("\n", strip=True) if content else soup.get_text("\n", strip=True))
    return ReadableDocument(title=title, text=text, html=str(content or soup), source="beautifulsoup")


def _text_from_html(html_text: str) -> str:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html_text or "", "lxml")
    _remove_noise(soup)
    return _normalize_text(soup.get_text("\n", strip=True))


def _title_from_soup(soup: BeautifulSoup, fallback_title: str) -> str:
    candidates: list[Any] = [
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
    return fallback_title


def _main_content_node(soup: BeautifulSoup) -> Any:
    for selector in [
        "#transcript-panel-full",
        "article",
        "main",
        "[role='main']",
        "div.article-body",
        "div.article-content",
        "div.entry-content",
        "div.post-content",
        "section.article-body",
        "div.transcript-body",
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
        class_text = " ".join(node.get("class", [])).casefold()
        score = len(text) + (2000 if any(token in class_text for token in ["article", "content", "transcript", "body"]) else 0)
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


def _normalize_text(value: str) -> str:
    lines = [_clean_text(line) for line in re.split(r"[\r\n]+", value or "")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()

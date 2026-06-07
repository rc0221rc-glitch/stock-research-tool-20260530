from __future__ import annotations

import os
from typing import Any


def is_scrapling_enabled() -> bool:
    return os.getenv("DISABLE_SCRAPLING", "").strip().lower() not in {"1", "true", "yes", "on"}


def fetch_text_with_scrapling(url: str, timeout: float = 12, **kwargs: Any) -> str:
    if not is_scrapling_enabled():
        raise RuntimeError("Scrapling is disabled by DISABLE_SCRAPLING")
    from scrapling import Fetcher

    request_kwargs = dict(kwargs)
    request_kwargs.setdefault("timeout", timeout)
    page = Fetcher.get(url, **request_kwargs)
    status = int(getattr(page, "status", 0) or getattr(page, "status_code", 0) or 0)
    if status >= 400:
        raise RuntimeError(f"Scrapling returned HTTP {status}")
    return _page_text(page)


def _page_text(page: Any) -> str:
    for attr in ("text", "html", "body", "content"):
        value = getattr(page, attr, None)
        if callable(value):
            value = value()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, str) and value.strip():
            return value
    return str(page or "")

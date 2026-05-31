from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from src.vercel_common import error_response, handle_options, json_response, runtime_note


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        handle_options(self)

    def do_GET(self) -> None:
        if handle_options(self):
            return
        query = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
        if not query:
            json_response(self, {"results": [], "note": runtime_note()})
            return
        try:
            from src.company_search_global import search_companies

            results = search_companies(query, limit=12)
            json_response(self, {"results": results, "note": runtime_note()})
        except Exception as exc:
            error_response(self, str(exc))

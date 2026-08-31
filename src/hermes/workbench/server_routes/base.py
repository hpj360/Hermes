"""Shared request/response helpers for server_routes mixins.

从 server.py 拆出的公共基类：JSON/text 响应、请求体解析、query 参数
解析、loop 名校验。所有路由域 mixin 继承本类，由 server.DashboardHandler
最终与 BaseHTTPRequestHandler 组合成完整 MRO。
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

from hermes.workbench.errors import ValidationError

__all__ = ["RouteBase"]


class RouteBase:
    """Helpers shared by every route-domain mixin.

    Calls into ``self.send_response`` / ``self.wfile`` etc. — these exist at
    runtime once the final handler class mixes in ``BaseHTTPRequestHandler``.
    """

    # CORS ---------------------------------------------------------------

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    # Helpers ------------------------------------------------------------

    def _send_json(self, status: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_no_content(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_text(
        self, status: int, text: str, content_type: str = "text/plain; charset=utf-8"
    ) -> None:
        """Send a plain-text response (used by the Prometheus /metrics endpoint)."""
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValidationError(f"invalid JSON body: {e}") from e

    def _query_params(self) -> dict[str, str]:
        parsed = parse_qs(urlsplit(self.path).query)
        return {k: v[0] for k, v in parsed.items() if v}

    def _parse_int(self, value: Any, default: int) -> int:
        """Parse *value* as int, raising ValidationError (400) on bad input.

        Replaces raw ``int(...)`` on user input so non-numeric values surface
        as 400 instead of an uncaught ``ValueError`` → 500 with internal text.
        """
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise ValidationError(f"invalid integer: {value!r}") from e

    @staticmethod
    def _validate_loop_name(name: str) -> None:
        """Reject loop names that would escape ``loops_dir`` via ``..``/path chars."""
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValidationError(f"invalid loop name: {name!r}")

    def _method_not_allowed(self) -> None:
        self._send_json(405, {"error": "method not allowed"})

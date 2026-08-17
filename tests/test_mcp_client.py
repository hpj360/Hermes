"""Tests for hermes.mcp_client — generic MCP (stdio/HTTP) client.

验证协议级行为：
- stdio 传输：initialize 握手、tools/list、tools/call 正常/失败/超时/崩溃/坏行软降级
- HTTP 传输：请求头、JSON 响应、SSE 格式响应
- 配置加载容错
- 审计落盘
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from hermes.mcp_client import (
    MCPClient,
    MCPConfigError,
    HTTPTransport,
    load_mcp_config,
)


# ── stdio transport ──────────────────────────────────────────────────


def test_connect_and_list_tools(mcp_mock_config) -> None:
    client = MCPClient("mock", mcp_mock_config)
    try:
        client.connect()
        result = client.list_tools()
        assert result["success"] is True
        tools = result["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "echo" in names
        assert "fail" in names
    finally:
        client.close()


def test_ping_after_connect(mcp_mock_config) -> None:
    client = MCPClient("mock", mcp_mock_config)
    try:
        client.connect()
        assert client.ping()["success"] is True
    finally:
        client.close()


def test_call_tool_success(mcp_mock_config) -> None:
    client = MCPClient("mock", mcp_mock_config)
    try:
        client.connect()
        result = client.call_tool("echo", {"text": "hello hermes"})
        assert result["success"] is True
        content = result["result"]["content"]
        assert content[0]["text"] == "hello hermes"
    finally:
        client.close()


def test_call_tool_business_error_is_soft(mcp_mock_config) -> None:
    """isError=true 映射为 success=False，不抛异常（软降级契约）。"""
    client = MCPClient("mock", mcp_mock_config)
    try:
        client.connect()
        result = client.call_tool("fail", {})
        assert result["success"] is False
        assert result["isError"] is True
    finally:
        client.close()


def test_call_tool_protocol_error_is_soft(mcp_mock_config) -> None:
    """JSON-RPC error 结构映射为 success=False + error 消息。"""
    client = MCPClient("mock", mcp_mock_config)
    try:
        client.connect()
        result = client.call_tool("protocol_error", {})
        assert result["success"] is False
        assert "internal boom" in result["error"]
    finally:
        client.close()


def test_server_crash_soft_degrades(mcp_mock_config) -> None:
    """server 进程退出 → 请求返回 success=False（读取 EOF 触发），不抛异常。"""
    client = MCPClient("mock", mcp_mock_config)
    try:
        client.connect()
        result = client.call_tool("crash", {})
        assert result["success"] is False
        assert result["error"]
    finally:
        client.close()


def test_malformed_json_line_recovered(mcp_mock_config) -> None:
    """server 输出非法 JSON 行 → 跳过，后续合法响应仍正常。"""
    client = MCPClient("mock", mcp_mock_config)
    try:
        client.connect()
        result = client.call_tool("badjson", {})
        assert result["success"] is True
        assert result["result"]["content"][0]["text"] == "recovered"
    finally:
        client.close()


def test_timeout_soft_degrades(mcp_mock_config) -> None:
    """慢请求超时 → success=False + 超时信息，不抛异常。"""
    client = MCPClient("mock", mcp_mock_config, timeout=0.3)
    try:
        client.connect()
        result = client.call_tool("slow", {})
        assert result["success"] is False
        assert "timed out" in result["error"].lower() or "timeout" in result["error"].lower()
    finally:
        client.close()


def test_connect_requires_command_or_url() -> None:
    """配置既无 command 也无 url 时抛 MCPConfigError。"""
    client = MCPClient("bad", {"transport": "stdio", "args": ["x"]})
    with pytest.raises(MCPConfigError):
        client.connect()


def test_connect_command_not_found_soft_degrades() -> None:
    """command 不存在 → 启动抛 OSError（由调用方软降级）。"""
    client = MCPClient("ghost", {"command": "nonexistent-binary-that-should-not-exist"})
    with pytest.raises(OSError):
        client.connect()


# ── HTTP transport ───────────────────────────────────────────────────


class _MockHTTPServer:
    """线程内 mock MCP HTTP endpoint。返回 JSON 或 SSE 格式响应。"""

    def __init__(self, responder):
        self._seen_headers: dict[str, str] = {}
        self._requests: list[dict] = []
        self._responder = responder
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self):
        handler = self._make_handler()
        self._server = HTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                outer._seen_headers = {k: v for k, v in self.headers.items()}
                try:
                    outer._requests.append(json.loads(body))
                except json.JSONDecodeError:
                    outer._requests.append({"raw": body})
                status, content_type, payload = outer._responder(outer._requests[-1])
                data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:  # 静默，避免污染测试输出
                return

        return Handler

    @property
    def url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address
        return f"http://{host}:{port}/mcp"


def _json_responder(method_map):
    """构造 responder：按请求 method 返回 JSON，缺省 404。"""

    def respond(req: dict):
        method = req.get("method")
        if method == "initialize":
            return 200, "application/json", json.dumps(
                {"jsonrpc": "2.0", "id": req.get("id"),
                 "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}}}
            )
        if method == "tools/list":
            return 200, "application/json", json.dumps(
                {"jsonrpc": "2.0", "id": req.get("id"),
                 "result": {"tools": method_map.get("tools", [])}}
            )
        if method == "tools/call":
            return 200, "application/json", json.dumps(
                {"jsonrpc": "2.0", "id": req.get("id"),
                 "result": {"content": [{"type": "text", "text": "http-ok"}], "isError": False}}
            )
        return 404, "application/json", json.dumps({"error": "unknown method"})

    return respond


def test_http_transport_sends_headers() -> None:
    with _MockHTTPServer(_json_responder({"tools": []})) as srv:
        transport = HTTPTransport(srv.url, headers={"Authorization": "Bearer t0k3n"})
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        resp = transport.request(payload, timeout=5)
        assert resp["result"]["tools"] == []
        auth = srv._seen_headers.get("Authorization", "")
        assert auth == "Bearer t0k3n"
        assert srv._seen_headers.get("Content-Type", "").startswith("application/json")


def test_http_client_flow() -> None:
    with _MockHTTPServer(
        _json_responder({"tools": [{"name": "http_tool", "description": "d"}]})
    ) as srv:
        client = MCPClient("http-mock", {"url": srv.url, "headers": {"Authorization": "Bearer x"}})
        try:
            client.connect()
            tools = client.list_tools()
            assert tools["success"] is True
            assert tools["result"]["tools"][0]["name"] == "http_tool"
            call = client.call_tool("http_tool", {})
            assert call["success"] is True
        finally:
            client.close()


def test_http_sse_response_parsed() -> None:
    """Streamable HTTP 服务器可能返回 SSE 格式，客户端需能解析 data: 行。"""

    def sse_respond(req: dict):
        body = json.dumps({"jsonrpc": "2.0", "id": req.get("id"),
                           "result": {"tools": []}})
        return 200, "text/event-stream", f"data: {body}\n\n"

    with _MockHTTPServer(sse_respond) as srv:
        client = MCPClient("sse-mock", {"url": srv.url})
        try:
            client.connect()
            tools = client.list_tools()
            assert tools["success"] is True
        finally:
            client.close()


# ── 配置加载 ─────────────────────────────────────────────────────────


def test_load_config_missing_returns_empty(tmp_path: Path) -> None:
    assert load_mcp_config(tmp_path / "nope.json") == {}


def test_load_config_invalid_json_returns_empty(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_mcp_config(bad) == {}


def test_load_config_valid(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": {
                    "a": {"command": "od", "args": ["mcp", "server"]},
                    "b": {"url": "https://x/mcp", "headers": {"Authorization": "Bearer y"}},
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = load_mcp_config(cfg)
    assert set(loaded) == {"a", "b"}
    assert loaded["a"]["command"] == "od"
    assert loaded["b"]["url"].startswith("https://")


def test_load_config_no_servers_key_returns_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"other": 1}), encoding="utf-8")
    assert load_mcp_config(cfg) == {}


def test_load_config_servers_not_object_returns_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"servers": [1, 2]}), encoding="utf-8")
    assert load_mcp_config(cfg) == {}


# ── 审计 ─────────────────────────────────────────────────────────────


def test_audit_records_written(tmp_path: Path, mcp_mock_config, monkeypatch) -> None:
    """list_tools / call_tool 都会写入真实 AuditStore（落盘可查）。"""
    from hermes import mcp_client as mcp_mod
    from hermes.workbench.audit import AuditStore

    store = AuditStore(tmp_path)
    monkeypatch.setattr(mcp_mod, "_audit_impl", store.record)

    client = MCPClient("mock", mcp_mock_config)
    try:
        client.connect()
        client.list_tools()
        client.call_tool("echo", {"text": "x"})
    finally:
        client.close()

    records = store.list()
    methods = {r.method for r in records}
    assert "tools.list" in methods
    assert "tools.call" in methods
    assert all(r.server == "mock" for r in records)
    assert all(r.success for r in records)

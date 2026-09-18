"""Shared pytest fixtures for Hermes tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Force child skill scripts to emit UTF-8 on stdout/stderr. On Windows the
# locale default is GBK, which crashes scripts that print non-GBK characters
# (emoji, CJK, etc.) to a pipe. Setting PYTHONIOENCODING makes subprocess
# captures use UTF-8 regardless of the platform locale.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# 内嵌的最小 MCP server（stdio），用于 mcp_client / cli_mcp 的协议级测试。
# 覆盖 initialize 握手、tools/list、tools/call 的成功/失败/超时/崩溃/坏行场景。
MCP_MOCK_SERVER = r"""
import json
import sys
import time

TOOLS = [
    {"name": "echo", "description": "Echo text back", "inputSchema": {"type": "object",
     "properties": {"text": {"type": "string"}}}},
    {"name": "fail", "description": "always returns isError=true"},
    {"name": "protocol_error", "description": "returns a JSON-RPC error"},
    {"name": "slow", "description": "sleeps for a long time"},
    {"name": "crash", "description": "exits the process"},
    {"name": "badjson", "description": "emits a malformed line then responds"},
]

def _respond(msg, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "result": result}) + "\n")
    sys.stdout.flush()

def main():
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        method = msg.get("method")
        if method == "initialize":
            _respond(msg, {"protocolVersion": "2025-03-26",
                           "capabilities": {"tools": {}},
                           "serverInfo": {"name": "mock", "version": "1.0"}})
        elif method == "tools/list":
            _respond(msg, {"tools": TOOLS})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            args = (msg.get("params") or {}).get("arguments") or {}
            if name == "echo":
                _respond(msg, {"content": [{"type": "text", "text": args.get("text", "")}], "isError": False})
            elif name == "fail":
                _respond(msg, {"content": [{"type": "text", "text": "boom"}], "isError": True})
            elif name == "protocol_error":
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"),
                                             "error": {"code": -32000, "message": "internal boom"}}) + "\n")
                sys.stdout.flush()
            elif name == "slow":
                time.sleep(60)
            elif name == "crash":
                sys.exit(3)
            elif name == "badjson":
                sys.stdout.write("not-json{{{\n")
                sys.stdout.flush()
                _respond(msg, {"content": [{"type": "text", "text": "recovered"}], "isError": False})
            else:
                _respond(msg, {"content": [{"type": "text", "text": "unknown tool"}], "isError": True})
        # notifications (无 id) 忽略

if __name__ == "__main__":
    main()
"""


@pytest.fixture
def mcp_mock_server(tmp_path: Path) -> Path:
    """Write the embedded mock MCP server to a temp file and return its path."""
    server_file = tmp_path / "mcp_mock_server.py"
    server_file.write_text(MCP_MOCK_SERVER, encoding="utf-8")
    return server_file


@pytest.fixture
def mcp_mock_config(mcp_mock_server: Path) -> dict:
    """Config dict that launches the mock server via the current interpreter."""
    import sys

    return {"command": sys.executable, "args": [str(mcp_mock_server)]}


@pytest.fixture
def reset_settings() -> Iterator[None]:
    """Clear the settings singleton before and after the test."""
    from hermes import config as _config
    _config._hermes_settings = None
    yield
    _config._hermes_settings = None


@pytest.fixture(autouse=True)
def _isolate_state_paths(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """全局隔离状态/缓存/画像路径，防止测试写入真实 ``.state``。

    根因：多处代码直接使用 ``get_settings().hermes_state_dir``（如
    ``workbench.audit.default_audit_store`` 单例、``ProjectRegistry`` 的
    ``default`` 项目），仅 monkeypatch 工厂函数无法覆盖，会导致测试顺序
    敏感的潜伏污染（audit.jsonl / tasks.json / episodes 等）。这里统一把
    env 指向 per-test tmp 目录并强制重载 settings，覆盖所有旁路。

    注意：用 ``tmp_path_factory``（同级目录）而非 ``tmp_path``，避免隔离
    目录被以 ``tmp_path`` 为根的用例（如 skills 扫描）误当成业务目录。
    """
    root = tmp_path_factory.mktemp("_iso_state")
    state = root / "state"
    cache = root / "cache"
    state.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_CACHE_DIR", str(cache))
    monkeypatch.setenv("HERMES_PROFILE_PATH", str(root / "profile.json"))

    from hermes import config as _config

    _config._hermes_settings = None
    from hermes.config import get_settings

    get_settings(force_reload=True)
    yield
    _config._hermes_settings = None


@pytest.fixture
def tmp_state_dir(
    tmp_path: Path, reset_settings: Iterator[None], monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect HERMES_STATE_DIR/CACHE_DIR/PROFILE_PATH to tmp_path and reload settings."""
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    profile = tmp_path / "profile.json"
    state.mkdir()
    cache.mkdir()
    monkeypatch.setenv("HERMES_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_CACHE_DIR", str(cache))
    monkeypatch.setenv("HERMES_PROFILE_PATH", str(profile))
    from hermes.config import get_settings
    get_settings(force_reload=True)
    yield tmp_path

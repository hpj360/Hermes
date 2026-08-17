"""Tests for `hermes mcp <sub>` CLI commands.

Covers list / ping / tools / call happy & error paths, exit codes, and
integration with the mock stdio MCP server from tests/conftest.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.main import build_parser, main


@pytest.fixture(autouse=True)
def reset_settings_around():
    from hermes import config as _config

    _config._hermes_settings = None
    yield
    _config._hermes_settings = None


@pytest.fixture
def mcp_config_file(tmp_path: Path, mcp_mock_config) -> Path:
    """Write mcp_mock_config to a real mcp.json file and return its path."""
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({"servers": {"mock": mcp_mock_config}}), encoding="utf-8")
    return cfg_file


@pytest.fixture
def redirect_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把 mcp_client 的审计重定向到 tmp 的真实 AuditStore，避免写入真实 .state。"""
    from hermes import mcp_client as mcp_mod
    from hermes.workbench.audit import AuditStore

    store = AuditStore(tmp_path)
    monkeypatch.setattr(mcp_mod, "_audit_impl", store.record)


# ── Parser registration ─────────────────────────────────────────────


def test_build_parser_has_mcp_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["mcp", "list"])
    assert args.command == "mcp"
    assert args.mcp_cmd == "list"


def test_build_parser_mcp_requires_subcommand() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["mcp"])


# ── list ─────────────────────────────────────────────────────────────


def test_mcp_list_no_config_returns_zero(tmp_path: Path, capsys) -> None:
    rc = main(["mcp", "--config", str(tmp_path / "missing.json"), "list"])
    assert rc == 0
    assert "No MCP servers" in capsys.readouterr().out


def test_mcp_list_with_config(mcp_config_file: Path, capsys) -> None:
    rc = main(["mcp", "--config", str(mcp_config_file), "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "mock" in out
    assert "stdio" in out


def test_mcp_list_json(mcp_config_file: Path, capsys) -> None:
    rc = main(["mcp", "--config", str(mcp_config_file), "--json", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["servers"][0]["name"] == "mock"


# ── ping ─────────────────────────────────────────────────────────────


def test_mcp_ping_unknown_server_returns_one(mcp_config_file: Path, capsys) -> None:
    rc = main(["mcp", "--config", str(mcp_config_file), "ping", "nope"])
    assert rc == 1
    assert "Unknown MCP server" in capsys.readouterr().out


def test_mcp_ping_ok(mcp_config_file: Path, capsys, redirect_audit) -> None:
    rc = main(["mcp", "--config", str(mcp_config_file), "ping", "mock"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out


def test_mcp_ping_fail_when_server_missing(
    tmp_path: Path, capsys, redirect_audit
) -> None:
    """配置存在但 command 无法启动（空 command）→ ping 软失败，退出码 1。"""
    cfg_file = tmp_path / "mcp.json"
    cfg_file.write_text(json.dumps({"servers": {"ghost": {"command": ""}}}), encoding="utf-8")
    rc = main(["mcp", "--config", str(cfg_file), "ping", "ghost"])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


# ── tools ────────────────────────────────────────────────────────────


def test_mcp_tools_ok(mcp_config_file: Path, capsys, redirect_audit) -> None:
    rc = main(["mcp", "--config", str(mcp_config_file), "tools", "mock"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "echo" in out
    assert "Tools from 'mock'" in out


def test_mcp_tools_json(mcp_config_file: Path, capsys, redirect_audit) -> None:
    rc = main(["mcp", "--config", str(mcp_config_file), "--json", "tools", "mock"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    names = [t["name"] for t in payload["tools"]]
    assert "echo" in names


# ── call ─────────────────────────────────────────────────────────────


def test_mcp_call_ok(mcp_config_file: Path, capsys, redirect_audit) -> None:
    rc = main(
        ["mcp", "--config", str(mcp_config_file), "call", "mock", "echo",
         "--args", '{"text": "hi"}']
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "hi" in out


def test_mcp_call_invalid_args_returns_one(mcp_config_file: Path, capsys) -> None:
    rc = main(
        ["mcp", "--config", str(mcp_config_file), "call", "mock", "echo",
         "--args", "{not json"]
    )
    assert rc == 1
    assert "Invalid --args" in capsys.readouterr().out


def test_mcp_call_non_object_args_returns_one(mcp_config_file: Path, capsys) -> None:
    rc = main(
        ["mcp", "--config", str(mcp_config_file), "call", "mock", "echo",
         "--args", "[1, 2]"]
    )
    assert rc == 1
    assert "must be an object" in capsys.readouterr().out


def test_mcp_call_tool_failure_returns_one(
    mcp_config_file: Path, capsys, redirect_audit
) -> None:
    rc = main(["mcp", "--config", str(mcp_config_file), "call", "mock", "fail"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out


def test_mcp_call_json_output(mcp_config_file: Path, capsys, redirect_audit) -> None:
    rc = main(
        ["mcp", "--config", str(mcp_config_file), "--json", "call", "mock", "echo",
         "--args", '{"text": "j"}']
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["success"] is True

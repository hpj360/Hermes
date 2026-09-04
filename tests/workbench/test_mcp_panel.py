"""Tests for P3 MCP 治理面板（SystemRoutes._mcp_panel_data + /mcp/panel）.

覆盖：窗口过滤（旧记录排除）、按 server 聚合（calls/failures/
success_rate/last_error/last_activity）、分舱表透出、空审计的空面板。
"""

from __future__ import annotations

import time
from pathlib import Path

from hermes.workbench.audit import AuditStore
from hermes.workbench.server_routes.system import SystemRoutes


def _record(store: AuditStore, server: str, ok: bool, age_days: float = 0.0) -> None:
    store.record(server, "get_pr", ok)
    if age_days:
        # 回写 timestamp 模拟历史记录：直接改最后一行的 timestamp 字段
        path = store.state_dir / "audit.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        import json

        obj = json.loads(lines[-1])
        ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_days * 86400)
        )
        obj["timestamp"] = ts
        lines[-1] = json.dumps(obj)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_panel_aggregates_by_server(tmp_path: Path) -> None:
    store = AuditStore(state_dir=tmp_path)
    _record(store, "github", ok=True)
    _record(store, "github", ok=True)
    _record(store, "github", ok=False)
    _record(store, "slack", ok=True)

    data = SystemRoutes._mcp_panel_data(days=30, store=store)

    gh = data["servers"]["github"]
    assert gh["calls"] == 3
    assert gh["failures"] == 1
    assert gh["success_rate"] == round(2 / 3, 4)
    assert gh["last_activity"]  # ISO 时间戳非空
    assert data["servers"]["slack"]["calls"] == 1


def test_panel_window_filters_old_records(tmp_path: Path) -> None:
    store = AuditStore(state_dir=tmp_path)
    _record(store, "github", ok=True, age_days=45)  # 超出 30 天窗口
    _record(store, "github", ok=True)  # 今天

    data = SystemRoutes._mcp_panel_data(days=30, store=store)
    assert data["servers"]["github"]["calls"] == 1


def test_panel_empty_when_no_audit(tmp_path: Path) -> None:
    store = AuditStore(state_dir=tmp_path)
    data = SystemRoutes._mcp_panel_data(days=30, store=store)
    assert data["servers"] == {}
    assert data["window_days"] == 30


def test_panel_exposes_compartments(tmp_path: Path) -> None:
    store = AuditStore(state_dir=tmp_path)
    data = SystemRoutes._mcp_panel_data(days=30, store=store)
    # 分舱表来自 ROLE_MCP_WHITELIST：builder 只读 GitHub
    assert "builder" in data["compartments"]
    assert "github.get_pr" in data["compartments"]["builder"]
    # checker 系列无 MCP
    assert data["compartments"]["checker"] == []

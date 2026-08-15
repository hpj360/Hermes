"""Tests for Agent Preset capability-surface resolution (ADR-0018)."""

from __future__ import annotations

import json

import pytest

from hermes.presets import (
    DEFAULT_TOKEN_LIMIT,
    AgentPreset,
    apply_prompt_sections,
    builtin_presets,
    load_user_presets,
    resolve_preset,
)
from hermes.workbench.errors import ValidationError


# ── serialization ───────────────────────────────────────────────────


def test_preset_roundtrip():
    p = AgentPreset(
        name="data-analyst",
        tools=["read", "grep"],
        mcp_tools=[],
        denylist=["auth/"],
        token_limit=1234,
        model="m",
        prompt_sections=["inline section"],
    )
    d = p.to_dict()
    p2 = AgentPreset.from_dict(d)
    assert p2 == p


def test_preset_from_dict_minimal():
    p = AgentPreset.from_dict({"name": "x"})
    assert p.name == "x"
    assert p.tools is None
    assert p.mcp_tools is None
    assert p.denylist == []
    assert p.token_limit == DEFAULT_TOKEN_LIMIT


def test_preset_from_dict_requires_name():
    with pytest.raises(ValidationError):
        AgentPreset.from_dict({"tools": ["read"]})


# ── builtin presets ─────────────────────────────────────────────────


def test_builtin_presets_match_role_whitelist():
    """内置 preset 的 mcp_tools 与 ROLE_MCP_WHITELIST 一致（防漂移契约）。"""
    from hermes.orchestrator import ROLE_MCP_WHITELIST

    presets = builtin_presets()
    assert presets["builder-default"].mcp_tools == ROLE_MCP_WHITELIST["builder"]
    assert presets["checker"].mcp_tools == []
    assert presets["synthesizer"].mcp_tools == []
    assert presets["perspective"].mcp_tools is None  # 与现状一致（不限制）


def test_builtin_data_analyst_is_read_only():
    p = builtin_presets()["data-analyst"]
    assert "write" not in (p.tools or [])
    assert "edit" not in (p.tools or [])
    assert "bash" not in (p.tools or [])


# ── resolve_preset priority matrix ──────────────────────────────────


def _task(**kw):
    from hermes.orchestrator import AgentTask

    role = kw.pop("role", "builder")
    return AgentTask(role=role, **kw)


def test_resolve_preset_explicit_mcp_tools_wins():
    presets = {"builder-default": AgentPreset(name="builder-default", mcp_tools=["x"])}
    task = _task(allowed_mcp_tools=[])  # 显式禁全部
    resolve_preset(task, presets)
    assert task.allowed_mcp_tools == []


def test_resolve_preset_fills_mcp_tools_from_preset():
    # builder 角色默认是 3 个只读工具；preset 只能收紧（子集）
    presets = {"builder-default": AgentPreset(name="builder-default", mcp_tools=["github.get_pr"])}
    task = _task(allowed_mcp_tools=None)
    resolve_preset(task, presets)
    assert task.allowed_mcp_tools == ["github.get_pr"]


def test_resolve_preset_fills_tools_from_preset():
    presets = {"data-analyst": AgentPreset(name="data-analyst", tools=["read", "grep"])}
    task = _task(preset="data-analyst")
    resolve_preset(task, presets)
    assert task.tools == ["read", "grep"]


def test_resolve_preset_fills_model_from_preset():
    presets = {"builder-default": AgentPreset(name="builder-default", model="m1")}
    task = _task(model=None)
    resolve_preset(task, presets)
    assert task.model == "m1"


def test_resolve_preset_token_limit_default_overridable():
    presets = {"builder-default": AgentPreset(name="builder-default", token_limit=123)}
    task = _task(token_limit=DEFAULT_TOKEN_LIMIT)  # 默认值 → 视为未显式
    resolve_preset(task, presets)
    assert task.token_limit == 123


def test_resolve_preset_token_limit_explicit_zero_not_overridden():
    presets = {"builder-default": AgentPreset(name="builder-default", token_limit=123)}
    task = _task(token_limit=0)  # 显式 0=不限制
    resolve_preset(task, presets)
    assert task.token_limit == 0


def test_resolve_preset_unknown_name_raises():
    task = _task(preset="does-not-exist")
    with pytest.raises(ValidationError):
        resolve_preset(task, {"builder-default": AgentPreset(name="builder-default")})


def test_resolve_preset_no_preset_returns_none():
    task = _task(role="unknown-role")  # 无角色映射
    result = resolve_preset(task, builtin_presets())
    assert result is None
    assert task.allowed_mcp_tools is None


def test_resolve_preset_wider_mcp_uses_role_default(caplog):
    """preset 比角色默认更宽的 mcp_tools 被拒绝，采用角色默认。"""
    presets = {
        "builder-default": AgentPreset(
            name="builder-default",
            mcp_tools=["github.get_pr", "github.create_pr"],  # create_pr 越权
        )
    }
    task = _task(allowed_mcp_tools=None)
    resolve_preset(task, presets)
    # 角色默认只有 3 个只读工具
    assert "github.create_pr" not in task.allowed_mcp_tools


# ── L3 red line: denylist union ─────────────────────────────────────


def test_resolve_preset_denylist_is_union_not_replace():
    from hermes.orchestrator import AgentTask

    presets = {"builder-default": AgentPreset(name="builder-default", denylist=[])}
    task = AgentTask(role="builder", denylist=["auth/", "*.key"])
    resolve_preset(task, presets)
    # pattern 级保护不可被 preset 清空
    assert "auth/" in task.denylist
    assert "*.key" in task.denylist


def test_resolve_preset_adds_preset_denylist():
    from hermes.orchestrator import AgentTask

    presets = {"builder-default": AgentPreset(name="builder-default", denylist=["payment/"])}
    task = AgentTask(role="builder", denylist=["auth/"])
    resolve_preset(task, presets)
    assert "auth/" in task.denylist
    assert "payment/" in task.denylist


def test_resolve_preset_denylist_dedupes():
    from hermes.orchestrator import AgentTask

    presets = {"builder-default": AgentPreset(name="builder-default", denylist=["auth/"])}
    task = AgentTask(role="builder", denylist=["auth/"])
    resolve_preset(task, presets)
    assert task.denylist == ["auth/"]


# ── load_user_presets ───────────────────────────────────────────────


def test_load_user_presets_loads_valid(tmp_path):
    (tmp_path / "p1.json").write_text(
        json.dumps({"name": "p1", "tools": ["read"], "mcp_tools": []}), encoding="utf-8"
    )
    presets = load_user_presets(tmp_path)
    assert "p1" in presets
    assert presets["p1"].tools == ["read"]


def test_load_user_presets_skips_corrupt(tmp_path, caplog):
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "good.json").write_text(
        json.dumps({"name": "good", "tools": ["read"]}), encoding="utf-8"
    )
    presets = load_user_presets(tmp_path)
    assert "good" in presets
    assert "bad" not in presets


def test_load_user_presets_missing_dir(tmp_path):
    assert load_user_presets(tmp_path / "nope") == {}


# ── apply_prompt_sections ───────────────────────────────────────────


def test_apply_prompt_sections_inline_and_file(tmp_path):
    sec_file = tmp_path / "sec.md"
    sec_file.write_text("file section", encoding="utf-8")
    p = AgentPreset(
        name="x", prompt_sections=["inline section", str(sec_file)]
    )
    out = apply_prompt_sections("base", p)
    assert "base" in out
    assert "inline section" in out
    assert "file section" in out
    assert out.index("inline section") < out.index("file section")


def test_apply_prompt_sections_empty_base():
    p = AgentPreset(name="x", prompt_sections=["only section"])
    out = apply_prompt_sections("", p)
    assert out.strip() == "only section"


# ── orchestrator integration ────────────────────────────────────────


def test_orchestrator_payload_has_allowed_builtin_tools(tmp_path):
    from hermes.orchestrator import AgentTask, Orchestrator

    captured: list[dict] = []

    class FakeClient:
        def health_check(self):
            return True

        def spawn_payload(self, payload):
            captured.append(payload)
            return "session-1"

    orch = Orchestrator()
    orch.client = FakeClient()
    task = AgentTask(
        role="builder",
        task_description="query",
        preset="data-analyst",
        parallel=False,
    )
    orch.fan_out([task])
    assert captured[0]["allowed_builtin_tools"] == ["read", "grep", "glob"]
    # allowed_tools 仍是 MCP 白名单语义；data-analyst preset 把 MCP 收紧为 []
    assert captured[0]["allowed_tools"] == []


def test_orchestrator_checker_preset_keeps_empty_mcp(tmp_path):
    from hermes.orchestrator import AgentTask, Orchestrator

    captured: list[dict] = []

    class FakeClient:
        def health_check(self):
            return True

        def spawn_payload(self, payload):
            captured.append(payload)
            return "session-1"

    orch = Orchestrator()
    orch.client = FakeClient()
    task = AgentTask(role="checker_lint", task_description="lint", parallel=False)
    orch.fan_out([task])
    assert captured[0]["allowed_tools"] == []


def test_orchestrator_unknown_preset_fails_task(tmp_path):
    from hermes.orchestrator import AgentTask, Orchestrator

    class FakeClient:
        def health_check(self):
            return True

        def spawn_payload(self, payload):
            return "session-1"

    orch = Orchestrator()
    orch.client = FakeClient()
    task = AgentTask(role="builder", task_description="x", preset="nope", parallel=False)
    orch.fan_out([task])
    assert task.status == "failed"
    assert "preset resolution failed" in (task.result or "")


# ── builtin tool audit ──────────────────────────────────────────────


def test_audit_builtin_tool_violations_detects():
    from hermes.orchestrator import AgentTask, Orchestrator

    task = AgentTask(role="builder", tools=["read", "grep", "glob"])
    messages = [
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "read", "arguments": "{}"}},
            {"function": {"name": "write", "arguments": "{}"}},
        ]},
    ]
    Orchestrator._audit_builtin_tool_violations(task, messages)
    assert task.tool_violations == ["write"]


def test_audit_builtin_tool_violations_allows_whitelisted():
    from hermes.orchestrator import AgentTask, Orchestrator

    task = AgentTask(role="builder", tools=["read"])
    messages = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "read", "arguments": "{}"}}]},
    ]
    Orchestrator._audit_builtin_tool_violations(task, messages)
    assert task.tool_violations == []


def test_audit_builtin_tool_violations_skips_when_none():
    from hermes.orchestrator import AgentTask, Orchestrator

    task = AgentTask(role="builder", tools=None)
    messages = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "write", "arguments": "{}"}}]},
    ]
    Orchestrator._audit_builtin_tool_violations(task, messages)
    assert task.tool_violations == []


def test_audit_builtin_tool_violations_ignores_mcp():
    from hermes.orchestrator import AgentTask, Orchestrator

    task = AgentTask(role="builder", tools=["read"])
    messages = [
        {"role": "assistant", "tool_calls": [{"function": {"name": "mcp_github.create_pr", "arguments": "{}"}}]},
    ]
    Orchestrator._audit_builtin_tool_violations(task, messages)
    assert task.tool_violations == []  # mcp_ 前缀走 MCP 审计


# ── AgentTask.to_dict new fields ────────────────────────────────────


def test_agent_task_to_dict_includes_new_fields():
    from hermes.orchestrator import AgentTask

    task = AgentTask(role="builder", preset="x", tools=["read"], model="m")
    d = task.to_dict()
    assert d["preset"] == "x"
    assert d["tools"] == ["read"]
    assert d["model"] == "m"
    assert d["isolated"] is True
    assert d["tool_violations"] == []
    # transient 轨迹字段不进 to_dict
    assert "trajectory_request_seq" not in d

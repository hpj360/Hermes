"""场景化 skill 装配测试（agent_context + /api/runtime/skills）。"""
from __future__ import annotations

import pytest

from hermes.content_team.agent_context import (
    assemble_skill_context,
    resolve_skill_scenario,
)


def test_default_scenario_used_when_env_unset(monkeypatch):
    monkeypatch.delenv("HERMES_SKILL_SCENARIO", raising=False)
    assert resolve_skill_scenario() == "content-creation"
    ctx = assemble_skill_context()
    assert ctx["scenario"] == "content-creation"
    names = {s["name"] for s in ctx["skills"]}
    assert "xhs-hot-notes" in names
    assert "code-review" not in names


def test_env_scenario_overrides_default(monkeypatch):
    monkeypatch.setenv("HERMES_SKILL_SCENARIO", "engineering")
    assert resolve_skill_scenario() == "engineering"
    names = {s["name"] for s in assemble_skill_context()["skills"]}
    assert "code-review" in names
    assert "xhs-hot-notes" not in names


def test_env_none_disables_filtering(monkeypatch):
    monkeypatch.setenv("HERMES_SKILL_SCENARIO", "none")
    ctx = assemble_skill_context()
    assert ctx["scenario"] is None
    assert ctx["total"] == len({s.name for s in __import__("hermes").skills.discover_skills()})


def test_env_invalid_scenario_raises(monkeypatch):
    monkeypatch.setenv("HERMES_SKILL_SCENARIO", "nope")
    with pytest.raises(ValueError, match="未声明的 skill 场景"):
        assemble_skill_context()


def test_explicit_param_overrides_env(monkeypatch):
    monkeypatch.setenv("HERMES_SKILL_SCENARIO", "engineering")
    ctx = assemble_skill_context(scenario="workspace")
    assert ctx["scenario"] == "workspace"
    names = {s["name"] for s in ctx["skills"]}
    assert "find-skills" in names
    assert "code-review" not in names


def test_explicit_none_disables_filtering(monkeypatch):
    monkeypatch.setenv("HERMES_SKILL_SCENARIO", "engineering")
    ctx = assemble_skill_context(scenario="none")
    assert ctx["scenario"] is None
    assert ctx["total"] >= 50


# ---------------------------------------------------------------------------
# API 集成
# ---------------------------------------------------------------------------


async def test_runtime_skills_endpoint_default(client, monkeypatch):
    monkeypatch.delenv("HERMES_SKILL_SCENARIO", raising=False)
    resp = await client.get("/api/runtime/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"] == "content-creation"
    assert data["total"] == len(data["skills"])
    entry = data["skills"][0]
    assert set(entry.keys()) == {"name", "description"}


async def test_runtime_skills_endpoint_explicit(client):
    resp = await client.get("/api/runtime/skills?scenario=workspace")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"] == "workspace"
    names = {s["name"] for s in data["skills"]}
    assert "find-skills" in names


async def test_runtime_skills_endpoint_none(client):
    resp = await client.get("/api/runtime/skills?scenario=none")
    assert resp.status_code == 200
    assert resp.json()["scenario"] is None


async def test_runtime_skills_endpoint_invalid(client):
    resp = await client.get("/api/runtime/skills?scenario=bad-scenario")
    assert resp.status_code == 400
    assert "未声明的 skill 场景" in resp.json()["detail"]

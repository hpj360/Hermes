"""skill 场景隔离测试（profiles.json + discover_skills(scenario)）。"""
from __future__ import annotations

import pytest

from hermes.skills import (
    discover_skills,
    load_skill_profiles,
    scenario_names,
)


def test_profiles_declarations_loadable():
    profiles = load_skill_profiles()
    assert "content-creation" in profiles
    assert "engineering" in profiles
    assert "workspace" in profiles
    for name, item in profiles.items():
        assert item["skills"], f"场景 {name} 不应为空"
        assert isinstance(item["description"], str)


def test_scenario_names_ordered():
    names = scenario_names()
    assert names == list(load_skill_profiles().keys())


def test_full_coverage_every_skill_belongs_to_a_scenario():
    """覆盖校验：每个已安装 skill 至少归属一个场景。"""
    profiles = load_skill_profiles()
    declared: set[str] = set()
    for item in profiles.values():
        declared |= set(item["skills"])
    installed = {s.name for s in discover_skills()}
    missing = installed - declared
    assert not missing, f"未归属任何场景的 skill: {sorted(missing)}"


def test_all_declared_skills_exist():
    """防漂移：场景声明的每个 skill 都真实存在。"""
    profiles = load_skill_profiles()
    installed = {s.name for s in discover_skills()}
    for name, item in profiles.items():
        unknown = set(item["skills"]) - installed
        assert not unknown, f"场景 {name} 声明了不存在的 skill: {sorted(unknown)}"


def test_scenario_content_excludes_engineering():
    content = {s.name for s in discover_skills(scenario="content-creation")}
    assert "xhs-hot-notes" in content
    assert "banned-words-check" in content
    assert "code-review" not in content
    assert "diagnosing-bugs" not in content


def test_scenario_engineering_excludes_content():
    eng = {s.name for s in discover_skills(scenario="engineering")}
    assert "code-review" in eng
    assert "xhs-hot-notes" not in eng
    assert "douyin-reader" not in eng


def test_scenario_none_returns_all():
    assert len(discover_skills()) == len(discover_skills(scenario=None))


def test_unknown_scenario_raises():
    with pytest.raises(ValueError, match="未声明的场景"):
        discover_skills(scenario="nonexistent-scenario")


def test_workspace_scenario_small():
    ws = discover_skills(scenario="workspace")
    assert 0 < len(ws) < 10
    names = {s.name for s in ws}
    assert "find-skills" in names

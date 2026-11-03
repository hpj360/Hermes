"""内容 agent 会话的场景化 skill 装配（Level-1 Discovery 目录）。

内容工作台的 agent 会话（无论是前端助手还是 CLI 会话）通过本模块装配
其可用的 skill 目录：默认只装配 ``content-creation`` 场景，避免工程/通用
类 skill 混入内容运营上下文。

环境变量 ``HERMES_SKILL_SCENARIO``：
- 合法场景名（profiles.json 已声明）→ 使用该场景
- ``none`` / ``off`` → 不过滤（装载全部 skill）
- 未设置 → 默认 ``content-creation``
- 指向未声明场景 → 抛 ``ValueError``（显式失败，不静默回退）
"""
from __future__ import annotations

import os
from typing import Any

from hermes.skills import discover_skills, scenario_names

SCENARIO_ENV = "HERMES_SKILL_SCENARIO"
DEFAULT_SKILL_SCENARIO = "content-creation"
_NONE_VALUES = ("none", "off", "all", "-")


def resolve_skill_scenario(explicit: str | None = None) -> str | None:
    """解析当前生效的 skill 场景；``None`` 表示不过滤（全部装载）。

    优先级：显式入参 > 环境变量 > 默认值。
    """
    if explicit is not None:
        return _validate(explicit)
    raw = os.getenv(SCENARIO_ENV, "").strip()
    if raw:
        if raw.lower() in _NONE_VALUES:
            return None
        return _validate(raw)
    default = DEFAULT_SKILL_SCENARIO
    if default not in scenario_names():
        # profiles.json 缺失/未声明默认场景时退化为不过滤，保持可用
        return None
    return default


def _validate(scenario: str) -> str | None:
    if scenario.lower() in _NONE_VALUES:
        return None
    if scenario not in scenario_names():
        known = "、".join(scenario_names())
        raise ValueError(f"未声明的 skill 场景: {scenario}，可用: {known}")
    return scenario


def assemble_skill_context(scenario: str | None = None) -> dict[str, Any]:
    """装配 agent 会话的 skill 目录（Level-1 Discovery 载荷）。

    返回 ``{"scenario", "total", "skills": [{"name", "description"}]}``，
    description 为 SKILL.md frontmatter（~20 tokens/条），符合 agentskills.io
    渐进加载约定：会话先用目录决策，再按需 load_skill_content(name)。
    """
    active = resolve_skill_scenario(explicit=scenario)
    skills = discover_skills(scenario=active)
    return {
        "scenario": active,
        "total": len(skills),
        "skills": [
            {"name": s.name, "description": s.description} for s in skills
        ],
    }

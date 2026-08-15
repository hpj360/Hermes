"""Agent Preset: named capability-surface compositions for sub-agents (ADR-0018).

Inspired by DeepSeek Harness's per-session Preset. A preset bundles the tools,
MCP whitelist, path denylist, token limit, model override and prompt sections a
given sub-agent role may see — one place to declare "what this role can do".

Resolution precedence (enforced in :func:`resolve_preset`):
    explicit AgentTask field  >  preset  >  role default (ROLE_MCP_WHITELIST)

Security invariants:
    * ``denylist`` is a UNION (pattern-level protection can never be cleared).
    * ``mcp_tools`` from a preset may only *narrow* the role default, never
      widen it (least privilege).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes.workbench.errors import ValidationError

logger = logging.getLogger("hermes.presets")

DEFAULT_TOKEN_LIMIT = 50000


@dataclass
class AgentPreset:
    name: str
    description: str = ""
    tools: list[str] | None = None
    mcp_tools: list[str] | None = None
    denylist: list[str] = field(default_factory=list)
    token_limit: int = DEFAULT_TOKEN_LIMIT
    model: str | None = None
    prompt_sections: list[str] = field(default_factory=list)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
            "mcp_tools": self.mcp_tools,
            "denylist": self.denylist,
            "token_limit": self.token_limit,
            "model": self.model,
            "prompt_sections": self.prompt_sections,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentPreset":
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValidationError("preset requires a non-empty 'name'")
        tools = data.get("tools")
        mcp_tools = data.get("mcp_tools")
        denylist = data.get("denylist") or []
        prompt_sections = data.get("prompt_sections") or []
        return cls(
            name=name,
            description=str(data.get("description", "")),
            tools=tools if isinstance(tools, list) else None,
            mcp_tools=mcp_tools if isinstance(mcp_tools, list) else None,
            denylist=denylist if isinstance(denylist, list) else [],
            token_limit=int(data.get("token_limit", DEFAULT_TOKEN_LIMIT)),
            model=data.get("model") if isinstance(data.get("model"), str) else None,
            prompt_sections=(
                prompt_sections if isinstance(prompt_sections, list) else []
            ),
            schema_version=int(data.get("schema_version", 1)),
        )


def builtin_presets() -> dict[str, AgentPreset]:
    """Built-in presets.

    The ``mcp_tools`` values mirror ``ROLE_MCP_WHITELIST`` (orchestrator.py).
    A contract test asserts this equality to keep the two from drifting — the
    lazy lookup here avoids a top-level import cycle between the two modules.
    """
    from hermes.orchestrator import ROLE_MCP_WHITELIST

    builder_mcp = ROLE_MCP_WHITELIST.get("builder", [])
    return {
        "builder-default": AgentPreset(
            name="builder-default",
            description="Builder role: read-only GitHub MCP, default token limit",
            mcp_tools=list(builder_mcp),
            token_limit=DEFAULT_TOKEN_LIMIT,
        ),
        "checker": AgentPreset(
            name="checker",
            description="Checker role: no MCP, no write",
            mcp_tools=[],
            token_limit=DEFAULT_TOKEN_LIMIT,
        ),
        "synthesizer": AgentPreset(
            name="synthesizer",
            description="Synthesizer role: no MCP",
            mcp_tools=[],
            token_limit=DEFAULT_TOKEN_LIMIT,
        ),
        "perspective": AgentPreset(
            name="perspective",
            description="Perspective role: unrestricted MCP (status quo)",
            mcp_tools=None,
            token_limit=DEFAULT_TOKEN_LIMIT,
        ),
        "data-analyst": AgentPreset(
            name="data-analyst",
            description="Read-only data query agent (no edit/write/bash)",
            tools=["read", "grep", "glob"],
            mcp_tools=[],
            token_limit=DEFAULT_TOKEN_LIMIT,
            prompt_sections=[
                "你是一个只读的数据分析代理。只能使用 read/grep/glob 工具查询项目内容，"
                "不得修改任何文件。"
            ],
        ),
    }


# role name → builtin preset name (ADR-0018: 角色名约定，不激活 sub_agents 运行时读取)
_ROLE_PRESET_MAP: dict[str, str] = {
    "builder": "builder-default",
    "checker": "checker",
    "checker_lint": "checker",
    "checker_type": "checker",
    "checker_test": "checker",
    "synthesizer": "synthesizer",
    "perspective": "perspective",
}


def _role_to_preset(role: str) -> str | None:
    if role in _ROLE_PRESET_MAP:
        return _ROLE_PRESET_MAP[role]
    if role.startswith("checker"):
        return "checker"
    if role.startswith("perspective"):
        return "perspective"
    return None


def _role_default_mcp_tools(role: str) -> list[str] | None:
    from hermes.orchestrator import _get_role_whitelist

    return _get_role_whitelist(role)


def user_presets_dir() -> Path | None:
    from hermes.config import get_settings

    s = get_settings()
    if s.hermes_presets_dir:
        return Path(s.hermes_presets_dir)
    return s.hermes_state_dir / "presets"


def load_user_presets(presets_dir: Path | None = None) -> dict[str, AgentPreset]:
    """Load user-defined presets from ``*.json`` files.

    Corrupt/invalid files are skipped with a warning (data-issue tolerance).
    Missing directories yield an empty dict.
    """
    d = Path(presets_dir) if presets_dir is not None else user_presets_dir()
    result: dict[str, AgentPreset] = {}
    if d is None or not d.is_dir():
        return result
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            preset = AgentPreset.from_dict(data)
            result[preset.name] = preset
        except (json.JSONDecodeError, OSError, ValidationError, TypeError, ValueError) as exc:
            logger.warning("Skipping invalid preset file %s: %s", f, exc)
    return result


_merged_cache: dict[str, AgentPreset] | None = None


def merged_presets(force_reload: bool = False) -> dict[str, AgentPreset]:
    """Built-in presets overlaid with user presets (cached).

    ``force_reload=True`` rebuilds the cache (used by tests and long-running
    processes after editing ``HERMES_PRESETS_DIR``).
    """
    global _merged_cache
    if force_reload or _merged_cache is None:
        merged = builtin_presets()
        merged.update(load_user_presets())
        _merged_cache = merged
    return _merged_cache


def apply_prompt_sections(agent_definition: str, preset: AgentPreset) -> str:
    """Append the preset's prompt sections (files or inline text) in order."""
    parts: list[str] = [agent_definition] if agent_definition else []
    for section in preset.prompt_sections:
        p = Path(section)
        if p.is_file():
            parts.append(p.read_text(encoding="utf-8"))
        else:
            parts.append(section)
    return "\n\n".join(parts)


def resolve_preset(
    task: Any, presets: dict[str, AgentPreset]
) -> AgentPreset | None:
    """Resolve *task*'s preset, mutating unset fields in place.

    Returns the resolved :class:`AgentPreset` (or None when no preset applies).
    Raises :class:`ValidationError` for an unknown explicit preset name.
    """
    preset: AgentPreset | None = None
    if task.preset is not None:
        if task.preset not in presets:
            raise ValidationError(f"unknown preset: {task.preset!r}")
        preset = presets[task.preset]
    else:
        role_preset = _role_to_preset(task.role)
        if role_preset:
            preset = presets.get(role_preset)

    if preset is None:
        return None

    if task.allowed_mcp_tools is None and preset.mcp_tools is not None:
        default = _role_default_mcp_tools(task.role)
        if default is not None and set(preset.mcp_tools) - set(default):
            logger.warning(
                "preset %s mcp_tools wider than role default for %s; using role default",
                preset.name,
                task.role,
            )
            task.allowed_mcp_tools = list(default)
        else:
            task.allowed_mcp_tools = list(preset.mcp_tools)

    if task.tools is None and preset.tools is not None:
        task.tools = list(preset.tools)

    if task.model is None and preset.model is not None:
        task.model = preset.model

    if task.token_limit == DEFAULT_TOKEN_LIMIT and preset.token_limit != DEFAULT_TOKEN_LIMIT:
        task.token_limit = preset.token_limit

    if preset.denylist:
        merged = list(task.denylist)
        for item in preset.denylist:
            if item not in merged:
                merged.append(item)
        task.denylist = merged

    return preset

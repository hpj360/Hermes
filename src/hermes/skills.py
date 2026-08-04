"""Skill discovery and management for Hermes.

Loads skills copied from the main repository under ./skills/ and provides
utilities to list and inspect them.

支持 agentskills.io 三级渐进加载标准：
- Level 1 Discovery: discover_skills() 返回 name + description（~20 tokens）
- Level 2 Activation: load_skill_content() 返回完整 SKILL.md（~200 tokens）
- Level 3 Execution: load_skill_assets() 返回目录下所有文件路径（~1000+ tokens）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SkillInfo:
    """Metadata for a single installed skill."""

    name: str
    path: Path
    has_skill_md: bool
    has_meta: bool
    meta: dict[str, Any] | None = None
    description: str = ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skills_dir() -> Path:
    """Return the directory where skills are stored."""
    return _project_root() / "skills"


def knowledge_dir() -> Path:
    """Return the directory where knowledge docs are stored."""
    return _project_root() / "knowledge"


def get_skill_path(name: str) -> Path | None:
    """Return the path for a named skill, or None if not installed."""
    candidate = skills_dir() / name
    return candidate if candidate.exists() and candidate.is_dir() else None


# ---------------------------------------------------------------------------
# Frontmatter 解析（Level 1 Discovery 的基础）
# ---------------------------------------------------------------------------


def parse_skill_frontmatter(skill_md_path: Path) -> dict[str, Any]:
    """解析 SKILL.md 的 YAML frontmatter。

    返回 frontmatter 字典。如果没有 frontmatter，返回空字典。
    手动解析简单的 key: value 格式，不依赖 PyYAML（保持零依赖）。
    """
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    # frontmatter 必须以 --- 开头
    if not text.startswith("---"):
        return {}

    lines = text.split("\n")
    # 跳过首行 ---，查找结束标记 ---
    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}

    return _parse_frontmatter_lines(lines[1:end_idx])


def _find_key_separator(line: str) -> int:
    """找到 key 与 value 的分隔冒号位置。

    YAML 规范：分隔符是冒号后跟空格或位于行尾。返回冒号索引，-1 表示未找到。
    """
    for i, ch in enumerate(line):
        if ch == ":" and (i == len(line) - 1 or line[i + 1] == " "):
            return i
    return -1


def _is_quoted_complete(value: str, quote: str) -> bool:
    """判断引号字符串是否已完整闭合（考虑转义）。"""
    if not value.startswith(quote):
        return False
    i = 1
    while i < len(value):
        ch = value[i]
        if quote == '"' and ch == "\\":
            i += 2
            continue
        if ch == quote:
            # 单引号中 '' 是转义，不是闭合
            if quote == "'" and i + 1 < len(value) and value[i + 1] == quote:
                i += 2
                continue
            return True
        i += 1
    return False


def _unescape_double_quoted(s: str) -> str:
    """反转义双引号字符串内容（左到右逐字符处理，避免全局替换的歧义）。"""
    result: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == '"':
                result.append('"')
            elif nxt == "\\":
                result.append("\\")
            elif nxt == "n":
                result.append("\n")
            elif nxt == "t":
                result.append("\t")
            elif nxt == "r":
                result.append("\r")
            else:
                # 未知转义，保留原样
                result.append(s[i : i + 2])
            i += 2
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def _strip_quotes(value: str) -> str:
    """去除值两端的引号并处理转义。"""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _unescape_double_quoted(value[1:-1])
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        # 单引号中 '' 转义为 '
        return value[1:-1].replace("''", "'")
    return value


def _parse_block_scalar(lines: list[str], indicator: str) -> str:
    """解析 YAML 块标量（> 折叠，| 字面量）。

    保留原始行格式（含缩进），使 Level 1 description 是 Level 2 content 的子集。
    lines 为已收集的缩进行（含原始缩进）。
    """
    if not lines:
        return ""
    return "\n".join(lines).rstrip()


def _parse_quoted_multiline(
    value_part: str, lines: list[str], line_idx: int, quote: str
) -> tuple[str, int]:
    """解析可能跨行的引号值，返回 (去除引号后的值, 消耗的行数)。"""
    # 同行闭合
    if _is_quoted_complete(value_part, quote):
        return _strip_quotes(value_part), 1

    # 跨行收集后续行直到闭合（保留原始格式，不 strip 续行）
    collected: list[str] = [value_part]
    consumed = 1
    j = line_idx + 1
    while j < len(lines):
        collected.append(lines[j])
        consumed += 1
        if _is_quoted_complete("\n".join(collected), quote):
            return _strip_quotes("\n".join(collected)), consumed
        j += 1
    return _strip_quotes("\n".join(collected)), consumed


def _parse_frontmatter_lines(lines: list[str]) -> dict[str, Any]:
    """解析 frontmatter 行列表为字典。"""
    result: dict[str, Any] = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 跳过空行和注释
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # 缩进行属于上一个 key 的多行值，由对应逻辑处理
        if line[0] in (" ", "\t"):
            i += 1
            continue

        sep = _find_key_separator(line)
        if sep == -1:
            i += 1
            continue

        key = line[:sep].strip()
        value_part = line[sep + 1 :].strip()

        # 块标量（> 或 |）
        if value_part in (">", "|", ">-", "|-", ">+", "|+"):
            block_lines: list[str] = []
            i += 1
            while i < n and (lines[i].startswith((" ", "\t")) or lines[i].strip() == ""):
                block_lines.append(lines[i])
                i += 1
            # 去掉尾部空行
            while block_lines and block_lines[-1].strip() == "":
                block_lines.pop()
            result[key] = _parse_block_scalar(block_lines, value_part)
            continue

        # 双引号值（可能跨行）
        if value_part.startswith('"'):
            value, consumed = _parse_quoted_multiline(value_part, lines, i, '"')
            result[key] = value
            i += consumed
            continue

        # 单引号值（可能跨行）
        if value_part.startswith("'"):
            value, consumed = _parse_quoted_multiline(value_part, lines, i, "'")
            result[key] = value
            i += consumed
            continue

        # 列表（value 为空，后续缩进行以 - 开头）
        if value_part == "":
            list_items: list[str] = []
            j = i + 1
            while j < n and lines[j].startswith((" ", "\t")):
                item_line = lines[j].strip()
                if item_line.startswith("- "):
                    list_items.append(_strip_quotes(item_line[2:].strip()))
                elif item_line == "-":
                    list_items.append("")
                j += 1
            if list_items:
                result[key] = list_items
                i = j
                continue

        # 普通 scalar 值
        result[key] = value_part
        i += 1

    return result


# ---------------------------------------------------------------------------
# Level 1 Discovery：name + description（~20 tokens）
# ---------------------------------------------------------------------------


def discover_skills() -> list[SkillInfo]:
    """Scan the skills directory and return metadata for each skill found."""
    root = skills_dir()
    if not root.exists():
        return []

    result: list[SkillInfo] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        meta_json = entry / "_meta.json"
        meta: dict[str, Any] | None = None
        if meta_json.exists():
            try:
                meta = json.loads(meta_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = None
        # 从 SKILL.md frontmatter 提取 description
        description = ""
        if skill_md.exists():
            fm = parse_skill_frontmatter(skill_md)
            desc = fm.get("description")
            if isinstance(desc, str):
                description = desc
        result.append(
            SkillInfo(
                name=entry.name,
                path=entry,
                has_skill_md=skill_md.exists(),
                has_meta=meta_json.exists(),
                meta=meta,
                description=description,
            )
        )
    return result


def get_skill_description(name: str) -> str:
    """Level 1 Discovery: 只返回 skill 的 description。

    从 SKILL.md frontmatter 提取 description 字段。
    如果没有 frontmatter 或没有 description，返回空字符串。
    """
    skill_path = get_skill_path(name)
    if skill_path is None:
        return ""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return ""
    fm = parse_skill_frontmatter(skill_md)
    desc = fm.get("description")
    return desc if isinstance(desc, str) else ""


# ---------------------------------------------------------------------------
# Level 2 Activation：完整 SKILL.md（~200 tokens）
# ---------------------------------------------------------------------------


def load_skill_content(name: str) -> str | None:
    """Level 2 Activation: 加载完整 SKILL.md 内容。

    返回 SKILL.md 的完整文本（含 frontmatter）。
    如果 skill 不存在或没有 SKILL.md，返回 None。
    """
    skill_path = get_skill_path(name)
    if skill_path is None:
        return None
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        return skill_md.read_text(encoding="utf-8")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Level 3 Execution：目录下所有文件路径（~1000+ tokens）
# ---------------------------------------------------------------------------


def load_skill_assets(name: str) -> list[Path]:
    """Level 3 Execution: 返回 skill 目录下所有文件路径。

    不含 SKILL.md 本身（已在 Level 2 加载）。
    不含 _meta.json（内部元数据）。
    递归返回所有文件，按路径排序。
    """
    skill_path = get_skill_path(name)
    if skill_path is None:
        return []

    excluded = {skill_path / "SKILL.md", skill_path / "_meta.json"}
    assets = [p for p in skill_path.rglob("*") if p.is_file() and p not in excluded]
    return sorted(assets)


# ---------------------------------------------------------------------------
# 其他工具函数
# ---------------------------------------------------------------------------


def list_knowledge_docs() -> list[Path]:
    """Return list of knowledge document paths."""
    root = knowledge_dir()
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*.md") if p.is_file())

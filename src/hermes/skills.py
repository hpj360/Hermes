"""Skill discovery and management for Hermes.

Loads skills copied from the main repository under ./skills/ and provides
utilities to list and inspect them.
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


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skills_dir() -> Path:
    """Return the directory where skills are stored."""
    return _project_root() / "skills"


def knowledge_dir() -> Path:
    """Return the directory where knowledge docs are stored."""
    return _project_root() / "knowledge"


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
        result.append(
            SkillInfo(
                name=entry.name,
                path=entry,
                has_skill_md=skill_md.exists(),
                has_meta=meta_json.exists(),
                meta=meta,
            )
        )
    return result


def list_knowledge_docs() -> list[Path]:
    """Return list of knowledge document paths."""
    root = knowledge_dir()
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*.md") if p.is_file())


def get_skill_path(name: str) -> Path | None:
    """Return the path for a named skill, or None if not installed."""
    candidate = skills_dir() / name
    return candidate if candidate.exists() and candidate.is_dir() else None

"""User profile management for Hermes.

Stores and retrieves personal information, interests, skills, and preferences
in a structured JSON file under the project data/ directory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes.config import get_settings


def _profile_path() -> Path:
    settings = get_settings()
    return settings.hermes_profile_path


def load_profile() -> dict[str, Any]:
    """Load the user profile from disk. Returns an empty skeleton if missing."""
    path = _profile_path()
    if not path.exists():
        return dict(_default_profile())
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
        return data


def save_profile(profile: dict[str, Any]) -> None:
    """Persist the user profile to disk and update the timestamp."""
    path = _profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    with path.open("w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def update_field(section: str, key: str, value: Any) -> dict[str, Any]:
    """Update a single field in the profile and save. Returns the updated profile."""
    profile = load_profile()
    if section not in profile:
        profile[section] = {}
    profile[section][key] = value
    save_profile(profile)
    return profile


def append_to_list(section: str, key: str, items: list[str]) -> dict[str, Any]:
    """Append items to a list field, avoiding duplicates. Returns the updated profile."""
    profile = load_profile()
    if section not in profile:
        profile[section] = {}
    existing: list[str] = profile[section].get(key, []) or []
    for item in items:
        item = item.strip()
        if item and item not in existing:
            existing.append(item)
    profile[section][key] = existing
    save_profile(profile)
    return profile


def get_profile_markdown() -> str:
    """Render the user profile as a human-readable Markdown string."""
    p = load_profile()
    lines: list[str] = ["# 用户画像 / User Profile", ""]

    basic = p.get("basic_info", {})
    lines.append("## 基本信息")
    lines.append("")
    lines.append(f"- **称呼/昵称**: {basic.get('nickname') or '未设置'}")
    lines.append(f"- **姓名**: {basic.get('name') or '未设置'}")
    lines.append(f"- **性别**: {basic.get('gender') or '未设置'}")
    lines.append(f"- **年龄段**: {basic.get('age_range') or '未设置'}")
    lines.append(f"- **所在地**: {basic.get('location') or '未设置'}")
    lines.append(f"- **时区**: {basic.get('timezone') or 'Asia/Shanghai'}")
    lines.append(f"- **职业**: {basic.get('occupation') or '未设置'}")
    lines.append(f"- **行业**: {basic.get('industry') or '未设置'}")
    lines.append(f"- **教育背景**: {basic.get('education') or '未设置'}")
    lines.append("")

    contact = p.get("contact", {})
    lines.append("## 联系方式")
    lines.append("")
    lines.append(f"- **GitHub**: {contact.get('github') or '未设置'}")
    lines.append(f"- **Email**: {contact.get('email') or '未设置'}")
    lines.append(f"- **博客/网站**: {contact.get('blog') or contact.get('website') or '未设置'}")
    lines.append("")

    skills = p.get("skills", {})
    lines.append("## 技能栈")
    lines.append("")
    lines.append(f"- **编程语言**: {', '.join(skills.get('programming_languages', [])) or '未设置'}")
    lines.append(f"- **框架/库**: {', '.join(skills.get('frameworks', [])) or '未设置'}")
    lines.append(f"- **工具**: {', '.join(skills.get('tools', [])) or '未设置'}")
    lines.append(f"- **领域专长**: {', '.join(skills.get('domains', [])) or '未设置'}")
    lines.append(f"- **自然语言**: {', '.join(skills.get('languages_spoken', [])) or '未设置'}")
    lines.append("")

    interests = p.get("interests", {})
    lines.append("## 兴趣爱好")
    lines.append("")
    lines.append(f"- **技术兴趣**: {', '.join(interests.get('tech_interests', [])) or '未设置'}")
    lines.append(f"- **日常爱好**: {', '.join(interests.get('hobbies', [])) or '未设置'}")
    lines.append(f"- **阅读**: {', '.join(interests.get('reading', [])) or '未设置'}")
    lines.append(f"- **音乐**: {', '.join(interests.get('music', [])) or '未设置'}")
    lines.append(f"- **运动**: {', '.join(interests.get('sports', [])) or '未设置'}")
    lines.append(f"- **其他兴趣**: {', '.join(interests.get('other_interests', [])) or '未设置'}")
    lines.append("")

    work = p.get("work_style", {})
    lines.append("## 工作风格与偏好")
    lines.append("")
    lines.append(f"- **偏好语言**: {work.get('preferred_language') or '中文'}")
    lines.append(f"- **代码风格**: {', '.join(work.get('code_style', [])) or '未设置'}")
    lines.append(f"- **工作习惯**: {', '.join(work.get('work_habits', [])) or '未设置'}")
    lines.append(f"- **沟通风格**: {', '.join(work.get('communication_style', [])) or '未设置'}")
    lines.append(f"- **偏好工具**: {', '.join(work.get('tools_preferred', [])) or '未设置'}")
    lines.append("")

    projects = p.get("projects", [])
    lines.append("## 参与/关注的项目")
    lines.append("")
    if projects:
        for proj in projects:
            lines.append(f"- {proj}")
    else:
        lines.append("- 未设置")
    lines.append("")

    goals = p.get("goals", {})
    lines.append("## 目标")
    lines.append("")
    lines.append(f"- **短期目标**: {', '.join(goals.get('short_term', [])) or '未设置'}")
    lines.append(f"- **长期目标**: {', '.join(goals.get('long_term', [])) or '未设置'}")
    lines.append(f"- **学习计划**: {', '.join(goals.get('learning', [])) or '未设置'}")
    lines.append("")

    notes = p.get("notes", "")
    if notes:
        lines.append("## 备注")
        lines.append("")
        lines.append(notes)
        lines.append("")

    updated = p.get("updated_at", "")
    if updated:
        lines.append(f"---\n*最后更新: {updated}*")

    return "\n".join(lines)


def _default_profile() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "basic_info": {
            "name": None,
            "nickname": None,
            "gender": None,
            "age_range": None,
            "location": None,
            "timezone": "Asia/Shanghai",
            "occupation": None,
            "industry": None,
            "education": None,
        },
        "contact": {
            "email": None,
            "github": "hpj360",
            "blog": None,
            "website": None,
        },
        "skills": {
            "programming_languages": [],
            "frameworks": [],
            "tools": [],
            "domains": [],
            "languages_spoken": [],
            "skill_level": {},
        },
        "interests": {
            "tech_interests": [],
            "hobbies": [],
            "reading": [],
            "music": [],
            "sports": [],
            "other_interests": [],
        },
        "work_style": {
            "preferred_language": "中文",
            "code_style": [],
            "work_habits": [],
            "communication_style": [],
            "tools_preferred": [],
        },
        "projects": [],
        "goals": {
            "short_term": [],
            "long_term": [],
            "learning": [],
        },
        "notes": "",
    }

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

    _render_basic(lines, p)
    _render_pets(lines, p)
    _render_career(lines, p)
    _render_contact(lines, p)
    _render_skills(lines, p)
    _render_interests(lines, p)
    _render_work_style(lines, p)
    _render_projects(lines, p)
    _render_goals(lines, p)
    _render_notes(lines, p)

    updated = p.get("updated_at", "")
    if updated:
        lines.append(f"---\n*最后更新: {updated}*")

    return "\n".join(lines)


def _join(items: list[str] | None) -> str:
    if not items:
        return "未设置"
    return ", ".join(str(i) for i in items if i)


def _render_basic(lines: list[str], p: dict[str, Any]) -> None:
    basic = p.get("basic_info", {})
    lines.append("## 基本信息")
    lines.append("")
    lines.append(f"- **姓名**: {basic.get('name') or '未设置'}")
    lines.append(f"- **称呼/昵称**: {basic.get('nickname') or '未设置'}")
    lines.append(f"- **性别**: {basic.get('gender') or '未设置'}")
    lines.append(f"- **年龄段**: {basic.get('age_range') or '未设置'}")
    lines.append(f"- **所在地**: {basic.get('location') or '未设置'}")
    lines.append(f"- **时区**: {basic.get('timezone') or 'Asia/Shanghai'}")
    lines.append(f"- **职业**: {basic.get('occupation') or '未设置'}")
    lines.append(f"- **行业**: {basic.get('industry') or '未设置'}")
    if basic.get("work_experience_years"):
        lines.append(f"- **工作年限**: {basic['work_experience_years']}年")
    if basic.get("expected_salary"):
        lines.append(f"- **期望薪资**: {basic['expected_salary']}")
    lines.append(f"- **教育背景**: {basic.get('education') or '未设置'}")
    lines.append("")


def _render_pets(lines: list[str], p: dict[str, Any]) -> None:
    pets = p.get("pets", [])
    if not pets:
        return
    lines.append("## 萌宠")
    lines.append("")
    for pet in pets:
        lines.append(f"- {pet}")
    lines.append("")


def _render_contact(lines: list[str], p: dict[str, Any]) -> None:
    contact = p.get("contact", {})
    basic = p.get("basic_info", {})
    lines.append("## 联系方式")
    lines.append("")
    if basic.get("phone"):
        lines.append(f"- **电话**: {basic['phone']}")
    lines.append(f"- **Email**: {contact.get('email') or '未设置'}")
    lines.append(f"- **GitHub**: {contact.get('github') or '未设置'}")
    blog_or_site = contact.get("blog") or contact.get("website")
    lines.append(f"- **博客/网站**: {blog_or_site or '未设置'}")
    lines.append("")


def _render_skills(lines: list[str], p: dict[str, Any]) -> None:
    skills = p.get("skills", {})
    lines.append("## 技能栈")
    lines.append("")
    lines.append(f"- **编程语言**: {_join(skills.get('programming_languages', []))}")
    lines.append(f"- **框架/库**: {_join(skills.get('frameworks', []))}")
    lines.append(f"- **工具**: {_join(skills.get('tools', []))}")
    lines.append(f"- **领域专长**: {_join(skills.get('domains', []))}")
    lines.append(f"- **自然语言**: {_join(skills.get('languages_spoken', []))}")
    lines.append("")


def _render_career(lines: list[str], p: dict[str, Any]) -> None:
    career = p.get("career")
    if not career:
        return
    lines.append("## 职业履历")
    lines.append("")
    if career.get("summary"):
        lines.append(f"> {career['summary']}")
        lines.append("")
    if career.get("tags"):
        lines.append(f"- **标签**: {_join(career['tags'])}")
    sd = career.get("skills_detail", {})
    if sd:
        lines.append(f"- **SQL与数据能力**: {_join(sd.get('sql_and_data', []))}")
        lines.append(f"- **大数据生态**: {_join(sd.get('big_data_ecosystem', []))}")
        lines.append(f"- **常用平台/工具**: {_join(sd.get('platforms_and_tools', []))}")
    lines.append("")

    work = career.get("work_experience", [])
    if work:
        lines.append("### 工作经历")
        lines.append("")
        for w in work:
            lines.append(f"**{w.get('company', '')}** · {w.get('title', '')}  ({w.get('period', '')})")
            for h in w.get("highlights", []):
                lines.append(f"  - {h}")
            lines.append("")

    proj = career.get("projects", [])
    if proj:
        lines.append("### 项目经历")
        lines.append("")
        for pr in proj:
            lines.append(f"**{pr.get('name', '')}** · {pr.get('role', '')}  ({pr.get('period', '')})")
            if pr.get("description"):
                lines.append(f"  - {pr['description']}")
            lines.append("")

    campus = career.get("campus_experience", [])
    if campus:
        lines.append("### 校园经历")
        lines.append("")
        for c in campus:
            lines.append(f"- {c}")
        lines.append("")


def _render_interests(lines: list[str], p: dict[str, Any]) -> None:
    interests = p.get("interests", {})
    lines.append("## 兴趣爱好")
    lines.append("")
    lines.append(f"- **技术兴趣**: {_join(interests.get('tech_interests', []))}")
    lines.append(f"- **日常爱好**: {_join(interests.get('hobbies', []))}")
    if interests.get("alcohol"):
        lines.append(f"- **酒类偏好**: {_join(interests['alcohol'])}（酒类爱好者）")
    lines.append(f"- **运动**: {_join(interests.get('sports', []))}")
    if interests.get("film_directors"):
        lines.append(f"- **喜欢的导演**: {_join(interests['film_directors'])}")
    lines.append(f"- **音乐**: {_join(interests.get('music', []))}")
    lines.append(f"- **阅读**: {_join(interests.get('reading', []))}")
    other = interests.get("other_interests", [])
    if other:
        lines.append(f"- **其他**: {_join(other)}")
    lines.append("")


def _render_work_style(lines: list[str], p: dict[str, Any]) -> None:
    work = p.get("work_style", {})
    lines.append("## 工作风格与偏好")
    lines.append("")
    lines.append(f"- **偏好语言**: {work.get('preferred_language') or '中文'}")
    lines.append(f"- **代码风格**: {_join(work.get('code_style', []))}")
    lines.append(f"- **工作习惯**: {_join(work.get('work_habits', []))}")
    lines.append(f"- **沟通风格**: {_join(work.get('communication_style', []))}")
    lines.append(f"- **偏好工具**: {_join(work.get('tools_preferred', []))}")
    lines.append("")


def _render_projects(lines: list[str], p: dict[str, Any]) -> None:
    projects = p.get("personal_projects") or p.get("projects", [])
    lines.append("## 参与/关注的项目")
    lines.append("")
    if projects:
        for proj in projects:
            lines.append(f"- {proj}")
    else:
        lines.append("- 未设置")
    lines.append("")


def _render_goals(lines: list[str], p: dict[str, Any]) -> None:
    goals = p.get("goals", {})
    lines.append("## 目标")
    lines.append("")
    lines.append(f"- **短期目标**: {_join(goals.get('short_term', []))}")
    lines.append(f"- **长期目标**: {_join(goals.get('long_term', []))}")
    lines.append(f"- **学习计划**: {_join(goals.get('learning', []))}")
    lines.append("")


def _render_notes(lines: list[str], p: dict[str, Any]) -> None:
    notes = p.get("notes", "")
    if notes:
        lines.append("## 备注")
        lines.append("")
        lines.append(notes)
        lines.append("")


def _default_profile() -> dict[str, Any]:
    return {
        "version": 2,
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
            "phone": None,
            "expected_salary": None,
            "work_experience_years": None,
        },
        "contact": {
            "email": None,
            "github": "hpj360",
            "blog": None,
            "website": None,
        },
        "pets": [],
        "career": {
            "tags": [],
            "summary": None,
            "skills_detail": {
                "sql_and_data": [],
                "big_data_ecosystem": [],
                "platforms_and_tools": [],
            },
            "work_experience": [],
            "projects": [],
            "campus_experience": [],
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
            "alcohol": [],
            "film_directors": [],
            "other_interests": [],
        },
        "work_style": {
            "preferred_language": "中文",
            "code_style": [],
            "work_habits": [],
            "communication_style": [],
            "tools_preferred": [],
        },
        "personal_projects": [],
        "goals": {
            "short_term": [],
            "long_term": [],
            "learning": [],
        },
        "notes": "",
    }

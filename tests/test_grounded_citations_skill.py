"""Tests for the grounded-citations skill.

Verifies the skill that adapts Hermes Agent v0.20.0's Grounded Citations
capability into a verification layer for research-style loops:
1. SKILL.md exists with valid frontmatter and required sections.
2. Frontmatter declares triggers.
3. Content documents the three-state verification (verified/refuted/unverifiable)
   and the fact-check mode (站得住/站不住/无法验证).
4. manifest.json lists the skill and the total skill count is 44.
"""

from __future__ import annotations

import json
from pathlib import Path

from hermes.skills import discover_skills, get_skill_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "grounded-citations"


def _read_skill_md() -> tuple[str, str, str]:
    """Return (frontmatter, body, full_content) for the skill's SKILL.md.

    Uses the same "---"-split convention as test_skill_consolidation.py so the
    test stays free of a PyYAML dependency.
    """
    path = get_skill_path(SKILL_NAME)
    assert path is not None, f"skill path for {SKILL_NAME} not found"
    skill_md = path / "SKILL.md"
    content = skill_md.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    assert len(parts) >= 3, "SKILL.md should have frontmatter delimited by ---"
    # parts[0] is empty (before first ---), parts[1] is frontmatter, parts[2] body.
    frontmatter = parts[1]
    body = parts[2]
    return frontmatter, body, content


# ── SKILL.md existence ────────────────────────────────────────────


def test_skill_md_exists() -> None:
    """grounded-citations/SKILL.md should exist."""
    path = get_skill_path(SKILL_NAME)
    assert path is not None, "skills/grounded-citations/ directory should exist"
    assert (path / "SKILL.md").exists(), "grounded-citations/SKILL.md should exist"


# ── Frontmatter ──────────────────────────────────────────────────


def test_skill_md_has_valid_frontmatter() -> None:
    """SKILL.md frontmatter should declare the required skill fields."""
    frontmatter, _, _ = _read_skill_md()
    assert 'name: "grounded-citations"' in frontmatter or "name: grounded-citations" in (
        frontmatter
    ), "frontmatter should declare name"
    assert "description:" in frontmatter, "frontmatter should declare description"
    assert "version:" in frontmatter, "frontmatter should declare version"
    assert "user-invocable: true" in frontmatter, (
        "frontmatter should mark the skill user-invocable"
    )
    assert "command-dispatch:" in frontmatter, (
        "frontmatter should declare command-dispatch"
    )


def test_skill_md_has_triggers() -> None:
    """SKILL.md frontmatter should declare triggers (incl. Chinese + English)."""
    frontmatter, _, _ = _read_skill_md()
    assert "triggers:" in frontmatter, "frontmatter should declare triggers"
    assert "引文验证" in frontmatter, "triggers should include Chinese trigger"
    assert "fact-check" in frontmatter, "triggers should include English trigger"


# ── Required sections ────────────────────────────────────────────


def test_skill_md_has_required_sections() -> None:
    """SKILL.md should have Process / Completion criteria / Related skills sections."""
    _, body, _ = _read_skill_md()
    assert "## Process" in body, "should have a Process section"
    assert "## Completion criteria" in body, "should have a Completion criteria section"
    assert "## Related skills" in body, "should have a Related skills section"


# ── Three-state verification ─────────────────────────────────────


def test_skill_md_has_three_state_verification() -> None:
    """SKILL.md should document the three verification states."""
    _, body, _ = _read_skill_md()
    assert "verified" in body, "should mention the 'verified' state"
    assert "refuted" in body, "should mention the 'refuted' state"
    assert "unverifiable" in body, "should mention the 'unverifiable' state"
    # The emoji markers tie each state to its visual label.
    assert "✅" in body, "verified state should use the ✅ marker"
    assert "❌" in body, "refuted state should use the ❌ marker"
    assert "⚠️" in body, "unverifiable state should use the ⚠️ marker"


# ── Fact-check mode ──────────────────────────────────────────────


def test_skill_md_has_fact_check_mode() -> None:
    """SKILL.md should document the fact-check mode with its three outcomes."""
    _, body, _ = _read_skill_md()
    assert "事实核查模式" in body, "should document the fact-check mode"
    assert "站得住" in body, "fact-check mode should list the 'supported' outcome"
    assert "站不住" in body, "fact-check mode should list the 'refuted' outcome"
    assert "无法验证" in body, "fact-check mode should list the 'unverifiable' outcome"


# ── manifest.json ────────────────────────────────────────────────


def test_manifest_includes_skill() -> None:
    """manifest.json should list grounded-citations."""
    manifest_path = PROJECT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert SKILL_NAME in manifest.get("skills", []), (
        f"manifest.json should list {SKILL_NAME}"
    )


def test_manifest_skill_count_is_44() -> None:
    """manifest.json should list 50 skills (44 + 6 media skills migrated from content-team)."""
    manifest_path = PROJECT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    skills = manifest.get("skills", [])
    assert len(skills) == 50, f"Expected 50 skills, got {len(skills)}"


# ── Disk / manifest / discover consistency ───────────────────────


def test_skill_is_discoverable() -> None:
    """grounded-citations should be discoverable via discover_skills()."""
    names = [s.name for s in discover_skills()]
    assert SKILL_NAME in names, "grounded-citations should be discoverable"


def test_manifest_count_matches_disk() -> None:
    """manifest.json skill count should match the discover_skills() count."""
    manifest_path = PROJECT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_count = len(manifest.get("skills", []))
    disk_count = len(discover_skills())
    assert manifest_count == disk_count, (
        f"manifest has {manifest_count}, disk has {disk_count}"
    )

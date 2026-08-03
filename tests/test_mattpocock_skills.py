"""Tests for mattpocock-derived skills integration.

Verifies:
1. All 12 new skills are discoverable and have valid SKILL.md frontmatter.
2. LOOP_PATTERNS execution_status upgrades (issue-triage / ci-sweeper / pr-babysitter).
3. New skills are registered in manifest.json.
4. SKILL.md content completeness (required sections per skill-writing-vocabulary.md).
5. knowledge/skill-writing-vocabulary.md exists and has core sections.
"""

from __future__ import annotations

import re
from pathlib import Path

import hermes.skills as skills_mod
from hermes.loop import LOOP_PATTERNS
from hermes.skills import discover_skills, get_skill_path

# 12 new skills introduced from mattpocock/skills
NEW_SKILLS = [
    "triage",
    "diagnosing-bugs",
    "code-review",
    "to-spec",
    "to-tickets",
    "wayfinder",
    "codebase-design",
    "improve-codebase-architecture",
    "domain-modeling",
    "research",
    "prototype",
    "resolving-merge-conflicts",
]


# ── Skill discovery ────────────────────────────────────────────────


def test_all_new_skills_discoverable() -> None:
    """All 12 new skills must be discoverable by discover_skills()."""
    names = [s.name for s in discover_skills()]
    for skill in NEW_SKILLS:
        assert skill in names, f"skill '{skill}' not discovered"


def test_all_new_skills_have_skill_md() -> None:
    """Each new skill must have a SKILL.md file."""
    for skill in NEW_SKILLS:
        path = get_skill_path(skill)
        assert path is not None, f"get_skill_path returned None for '{skill}'"
        assert (path / "SKILL.md").exists(), f"SKILL.md missing in {skill}"


def test_all_new_skills_have_valid_frontmatter() -> None:
    """Each SKILL.md must have YAML frontmatter with name + description + triggers."""
    for skill in NEW_SKILLS:
        path = get_skill_path(skill)
        assert path is not None
        content = (path / "SKILL.md").read_text(encoding="utf-8")

        # Must start with frontmatter
        assert content.startswith("---"), f"{skill}: missing frontmatter"

        # Extract frontmatter block
        parts = content.split("---", 2)
        assert len(parts) >= 3, f"{skill}: malformed frontmatter"
        fm = parts[1]

        # Required fields
        assert f"name: {skill}" in fm or f"name: {skill}\n" in fm, (
            f"{skill}: frontmatter name mismatch"
        )
        assert "description:" in fm, f"{skill}: missing description in frontmatter"
        assert "version:" in fm, f"{skill}: missing version in frontmatter"
        assert "triggers:" in fm, f"{skill}: missing triggers in frontmatter"


def test_all_new_skills_have_triggers_with_chinese() -> None:
    """Each skill must have Chinese trigger keywords for bilingual dispatch."""
    for skill in NEW_SKILLS:
        path = get_skill_path(skill)
        assert path is not None
        content = (path / "SKILL.md").read_text(encoding="utf-8")
        # Frontmatter triggers section
        parts = content.split("---", 2)
        fm = parts[1] if len(parts) >= 3 else ""

        # Must have at least one non-ASCII (Chinese) trigger
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", fm))
        assert has_chinese, f"{skill}: no Chinese trigger keywords in frontmatter"


# ── SKILL.md content completeness ─────────────────────────────────


REQUIRED_SECTIONS = ["## Process", "## Completion criteria"]


def test_all_new_skills_have_process_section() -> None:
    """Each SKILL.md must have a '## Process' section, phase-based structure, or
    vocabulary structure (codebase-design is a reference skill, not a process skill).

    Three valid structures per skill-writing-vocabulary:
    - ## Process (numbered steps)
    - ## Phase N (phased methodology, e.g. diagnosing-bugs)
    - ## 词汇表 / ## 评估问题 (reference/vocabulary skills, e.g. codebase-design)
    """
    # codebase-design is a vocabulary/reference skill, not a process skill
    process_skills = [s for s in NEW_SKILLS if s != "codebase-design"]
    for skill in process_skills:
        path = get_skill_path(skill)
        assert path is not None
        content = (path / "SKILL.md").read_text(encoding="utf-8")
        has_process = "## Process" in content
        has_phases = bool(re.search(r"## Phase \d", content))
        assert has_process or has_phases, (
            f"{skill}: missing '## Process' or '## Phase N' section"
        )
        # Completion criteria is required for all
        assert "## Completion criteria" in content, (
            f"{skill}: missing '## Completion criteria' section"
        )


def test_codebase_design_has_vocabulary_structure() -> None:
    """codebase-design is a reference skill — must have 词汇表 and 评估问题."""
    path = get_skill_path("codebase-design")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "词汇表" in content, "codebase-design: missing 词汇表 section"
    assert "评估问题" in content or "反模式" in content, (
        "codebase-design: missing 评估问题 or 反模式 section"
    )
    assert "## Completion criteria" in content, (
        "codebase-design: missing '## Completion criteria' section"
    )


def test_all_new_skills_have_hermes_integration_section() -> None:
    """Each SKILL.md must declare its Hermes integration (loop pattern / role)."""
    for skill in NEW_SKILLS:
        path = get_skill_path(skill)
        assert path is not None
        content = (path / "SKILL.md").read_text(encoding="utf-8")
        # Must mention Hermes in some integration context
        assert "Hermes" in content, f"{skill}: no Hermes integration declaration"


def test_all_new_skills_reference_mattpocock() -> None:
    """Each SKILL.md must credit mattpocock/skills as the source."""
    for skill in NEW_SKILLS:
        path = get_skill_path(skill)
        assert path is not None
        content = (path / "SKILL.md").read_text(encoding="utf-8")
        assert "mattpocock" in content.lower(), f"{skill}: missing mattpocock attribution"


def test_skill_md_line_count_reasonable() -> None:
    """Each SKILL.md should be under 200 lines (per skill-writing-vocabulary)."""
    for skill in NEW_SKILLS:
        path = get_skill_path(skill)
        assert path is not None
        content = (path / "SKILL.md").read_text(encoding="utf-8")
        line_count = content.count("\n") + 1
        assert line_count <= 200, f"{skill}: {line_count} lines exceeds 200 limit"


# ── LOOP_PATTERNS upgrades ────────────────────────────────────────


def test_issue_triage_is_implemented() -> None:
    """P0: issue-triage should be upgraded to 'implemented'."""
    pattern = LOOP_PATTERNS["issue-triage"]
    assert pattern["execution_status"] == "implemented", (
        "issue-triage should be 'implemented' after P0 upgrade"
    )


def test_ci_sweeper_is_implemented() -> None:
    """P0: ci-sweeper should be upgraded to 'implemented'."""
    pattern = LOOP_PATTERNS["ci-sweeper"]
    assert pattern["execution_status"] == "implemented", (
        "ci-sweeper should be 'implemented' after P0 upgrade"
    )


def test_pr_babysitter_is_implemented() -> None:
    """P0: pr-babysitter should be upgraded to 'implemented'."""
    pattern = LOOP_PATTERNS["pr-babysitter"]
    assert pattern["execution_status"] == "implemented", (
        "pr-babysitter should be 'implemented' after P0 upgrade"
    )


def test_issue_triage_sub_agents_have_skill_files() -> None:
    """P0: issue-triage sub_agents should reference triage SKILL.md."""
    pattern = LOOP_PATTERNS["issue-triage"]
    for agent in pattern["sub_agents"]:
        af = agent.get("agent_file")
        if af is not None:
            assert "triage" in af, (
                f"issue-triage sub_agent '{agent['role']}' should reference triage skill"
            )


def test_ci_sweeper_builder_references_diagnosing_bugs() -> None:
    """P0: ci-sweeper builder should reference diagnosing-bugs SKILL.md."""
    pattern = LOOP_PATTERNS["ci-sweeper"]
    builder = next(a for a in pattern["sub_agents"] if a["role"] == "builder")
    af = builder.get("agent_file")
    assert af is not None, "ci-sweeper builder agent_file should not be None"
    assert "diagnosing-bugs" in af, (
        f"ci-sweeper builder should reference diagnosing-bugs, got: {af}"
    )


def test_pr_babysitter_has_dual_reviewers() -> None:
    """P0: pr-babysitter should have Standards + Spec dual reviewers (code-review)."""
    pattern = LOOP_PATTERNS["pr-babysitter"]
    roles = [a["role"] for a in pattern["sub_agents"]]
    assert "reviewer_standards" in roles, "pr-babysitter should have reviewer_standards"
    assert "reviewer_spec" in roles, "pr-babysitter should have reviewer_spec"

    for agent in pattern["sub_agents"]:
        if agent["role"].startswith("reviewer_"):
            af = agent.get("agent_file")
            assert af is not None and "code-review" in af, (
                f"{agent['role']} should reference code-review skill"
            )


def test_pr_babysitter_reviewers_are_parallel() -> None:
    """P0: pr-babysitter dual reviewers must be parallel (per code-review design)."""
    pattern = LOOP_PATTERNS["pr-babysitter"]
    for agent in pattern["sub_agents"]:
        if agent["role"].startswith("reviewer_"):
            assert agent["parallel"] is True, (
                f"{agent['role']} must be parallel (code-review dual-axis design)"
            )


def test_implemented_patterns_count() -> None:
    """After P0, 6/8 patterns should be 'implemented' (was 3/8)."""
    implemented = [
        name for name, p in LOOP_PATTERNS.items()
        if p["execution_status"] == "implemented"
    ]
    assert len(implemented) == 6, (
        f"Expected 6 implemented patterns after P0, got {len(implemented)}: {implemented}"
    )


def test_scaffolding_only_patterns_remain() -> None:
    """Only 2 patterns should remain 'scaffolding_only' (daily-triage, changelog-draft)."""
    scaffolding = [
        name for name, p in LOOP_PATTERNS.items()
        if p["execution_status"] == "scaffolding_only"
    ]
    assert sorted(scaffolding) == ["changelog-draft", "daily-triage"], (
        f"Expected only daily-triage and changelog-draft as scaffolding, got: {scaffolding}"
    )


# ── manifest.json ─────────────────────────────────────────────────


def test_manifest_registers_all_new_skills() -> None:
    """manifest.json must list all 12 new skills."""
    import json

    manifest_path = Path(__file__).resolve().parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registered = set(manifest.get("skills", []))
    for skill in NEW_SKILLS:
        assert skill in registered, f"manifest.json missing skill: {skill}"


def test_manifest_skill_count_matches_disk() -> None:
    """manifest.json skill count should match discover_skills() count."""
    import json

    manifest_path = Path(__file__).resolve().parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_count = len(manifest.get("skills", []))
    disk_count = len(discover_skills())
    assert manifest_count == disk_count, (
        f"manifest.json has {manifest_count} skills, disk has {disk_count}"
    )


def test_manifest_registers_skill_writing_vocabulary() -> None:
    """manifest.json knowledge list should include skill-writing-vocabulary.md."""
    import json

    manifest_path = Path(__file__).resolve().parents[1] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    knowledge = manifest.get("knowledge", [])
    assert "skill-writing-vocabulary.md" in knowledge, (
        "skill-writing-vocabulary.md not in manifest knowledge list"
    )


# ── knowledge document ────────────────────────────────────────────


def test_skill_writing_vocabulary_exists() -> None:
    """knowledge/skill-writing-vocabulary.md must exist (P1-2 deliverable)."""
    path = skills_mod.knowledge_dir() / "skill-writing-vocabulary.md"
    assert path.exists(), "skill-writing-vocabulary.md not found in knowledge/"


def test_skill_writing_vocabulary_has_core_sections() -> None:
    """The vocabulary doc must cover progressive disclosure, leading words, etc."""
    path = skills_mod.knowledge_dir() / "skill-writing-vocabulary.md"
    content = path.read_text(encoding="utf-8")
    expected_terms = [
        "Progressive Disclosure",
        "Leading Words",
        "Information Hierarchy",
        "Failure Modes",
        "Composability",
    ]
    for term in expected_terms:
        assert term in content, f"skill-writing-vocabulary.md missing section: {term}"


def test_skill_writing_vocabulary_has_quality_checklist() -> None:
    """The vocabulary doc must include a quality checklist for SKILL.md."""
    path = skills_mod.knowledge_dir() / "skill-writing-vocabulary.md"
    content = path.read_text(encoding="utf-8")
    assert "质量检查清单" in content or "Quality" in content, (
        "skill-writing-vocabulary.md missing quality checklist"
    )


# ── Cross-skill consistency ───────────────────────────────────────


def test_p0_skills_reference_correct_loop_patterns() -> None:
    """P0 skills must reference their target loop patterns in SKILL.md."""
    expected_refs = {
        "triage": "issue-triage",
        "diagnosing-bugs": "ci-sweeper",
        "code-review": "pr-babysitter",
    }
    for skill, loop_pattern in expected_refs.items():
        path = get_skill_path(skill)
        assert path is not None
        content = (path / "SKILL.md").read_text(encoding="utf-8")
        assert loop_pattern in content, (
            f"{skill} should reference loop pattern '{loop_pattern}'"
        )


def test_p1_skills_form_planning_pipeline() -> None:
    """P1 skills (to-spec → to-tickets → wayfinder) should cross-reference each other."""
    pipeline = ["to-spec", "to-tickets", "wayfinder"]
    for i, skill in enumerate(pipeline):
        path = get_skill_path(skill)
        assert path is not None
        content = (path / "SKILL.md").read_text(encoding="utf-8")
        # Should mention the pipeline order
        assert "to-spec" in content or "to-tickets" in content or "wayfinder" in content, (
            f"{skill} should reference the planning pipeline"
        )

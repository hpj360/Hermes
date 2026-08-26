"""Tests for skill consolidation (v0.7.0).

Verifies the skill deduplication and merging actions:
1. pskoett/ removed (was duplicate of self-improving-agent).
2. product-manager-skills/ merged into product-manager/ (SaaS metrics absorbed).
3. Functional-adjacent skill groups have "Related skills" boundary declarations.
4. manifest.json reflects the consolidated state (43 skills, later grown to 44
   with the addition of grounded-citations).
"""

from __future__ import annotations

from pathlib import Path

from hermes.skills import discover_skills, get_skill_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ── pskoett removal ───────────────────────────────────────────────


def test_pskoett_directory_removed() -> None:
    """pskoett/ should be deleted (was duplicate of self-improving-agent)."""
    pskoett_path = PROJECT_ROOT / "skills" / "pskoett"
    assert not pskoett_path.exists(), "skills/pskoett/ should be removed"


def test_pskoett_not_in_discover() -> None:
    """pskoett should not appear in discover_skills()."""
    names = [s.name for s in discover_skills()]
    assert "pskoett" not in names


def test_self_improving_agent_still_exists() -> None:
    """self-improving-agent (the canonical one) should still exist."""
    path = get_skill_path("self-improving-agent")
    assert path is not None, "self-improving-agent should still exist after pskoett removal"
    assert (path / "SKILL.md").exists()


# ── product-manager merge ─────────────────────────────────────────


def test_product_manager_skills_directory_removed() -> None:
    """product-manager-skills/ should be deleted (merged into product-manager)."""
    path = PROJECT_ROOT / "skills" / "product-manager-skills"
    assert not path.exists(), "skills/product-manager-skills/ should be removed"


def test_product_manager_skills_not_in_discover() -> None:
    """product-manager-skills should not appear in discover_skills()."""
    names = [s.name for s in discover_skills()]
    assert "product-manager-skills" not in names


def test_product_manager_still_exists() -> None:
    """product-manager should still exist after merge."""
    path = get_skill_path("product-manager")
    assert path is not None, "product-manager should still exist after merge"


def test_product_manager_absorbed_saas_metrics() -> None:
    """product-manager SKILL.md should contain SaaS metrics (absorbed from -skills)."""
    path = get_skill_path("product-manager")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    # Key capabilities from product-manager-skills should be present
    assert "SaaS Metrics" in content, "product-manager should have SaaS Metrics section"
    assert "MRR" in content, "product-manager should mention MRR"
    assert "NDR" in content, "product-manager should mention NDR"
    assert "PRD Critique" in content, "product-manager should have PRD Critique section"
    assert "Career Coaching" in content, "product-manager should have Career Coaching section"


def test_product_manager_has_triggers() -> None:
    """Merged product-manager should have triggers field (v2.0 upgrade)."""
    path = get_skill_path("product-manager")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    parts = content.split("---", 2)
    fm = parts[1] if len(parts) >= 3 else ""
    assert "triggers:" in fm, "product-manager v2.0 should have triggers field"
    assert "产品管理" in fm or "PRD" in fm, "product-manager should have Chinese triggers"


def test_product_manager_has_completion_criteria() -> None:
    """Merged product-manager should have Completion criteria (v2.0 upgrade)."""
    path = get_skill_path("product-manager")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "## Completion criteria" in content, (
        "product-manager v2.0 should have Completion criteria section"
    )


# ── manifest.json consistency ─────────────────────────────────────


def test_manifest_has_44_skills() -> None:
    """manifest.json should list 51 skills (50 + content-extraction shared engine)."""
    import json

    manifest_path = PROJECT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    skills = manifest.get("skills", [])
    assert len(skills) == 51, f"Expected 51 skills, got {len(skills)}"


def test_manifest_no_pskoett() -> None:
    """manifest.json should not list pskoett."""
    import json

    manifest_path = PROJECT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "pskoett" not in manifest.get("skills", [])


def test_manifest_no_product_manager_skills() -> None:
    """manifest.json should not list product-manager-skills."""
    import json

    manifest_path = PROJECT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "product-manager-skills" not in manifest.get("skills", [])


def test_manifest_has_product_manager() -> None:
    """manifest.json should still list product-manager."""
    import json

    manifest_path = PROJECT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "product-manager" in manifest.get("skills", [])


def test_manifest_skill_count_matches_disk() -> None:
    """manifest.json skill count should match discover_skills() count."""
    import json

    manifest_path = PROJECT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_count = len(manifest.get("skills", []))
    disk_count = len(discover_skills())
    assert manifest_count == disk_count, (
        f"manifest has {manifest_count}, disk has {disk_count}"
    )


# ── Related skills boundary declarations ──────────────────────────


def test_brave_search_has_related_skills() -> None:
    """brave-search should declare Related skills (tavily-search, agent-browser)."""
    path = get_skill_path("brave-search")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "## Related skills" in content
    assert "tavily-search" in content
    assert "agent-browser" in content


def test_tavily_search_has_related_skills() -> None:
    """tavily-search should declare Related skills (brave-search, agent-browser)."""
    path = get_skill_path("tavily-search")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "## Related skills" in content
    assert "brave-search" in content


def test_ui_review_checklist_has_related_skills() -> None:
    """ui-review-checklist should declare Related skills (prototype-validator)."""
    path = get_skill_path("ui-review-checklist")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "## Related skills" in content
    assert "prototype-validator" in content


def test_prototype_validator_has_related_skills() -> None:
    """prototype-validator should declare Related skills (ui-review-checklist)."""
    path = get_skill_path("prototype-validator")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "Related skills" in content
    assert "ui-review-checklist" in content


def test_ui_design_system_has_related_skills() -> None:
    """ui-design-system should declare Related skills (style-dictionary-sync)."""
    path = get_skill_path("ui-design-system")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "## Related skills" in content
    assert "style-dictionary-sync" in content


def test_codebase_design_has_related_skills() -> None:
    """codebase-design should declare Related skills (improve-codebase-architecture)."""
    path = get_skill_path("codebase-design")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "## Related skills" in content
    assert "improve-codebase-architecture" in content


def test_improve_codebase_architecture_has_related_skills() -> None:
    """improve-codebase-architecture should declare Related skills (codebase-design)."""
    path = get_skill_path("improve-codebase-architecture")
    assert path is not None
    content = (path / "SKILL.md").read_text(encoding="utf-8")
    assert "## Related skills" in content
    assert "codebase-design" in content


# ── Boundary declarations are bidirectional ───────────────────────


def test_search_skills_bidirectional_reference() -> None:
    """brave-search and tavily-search should reference each other."""
    brave = get_skill_path("brave-search")
    tavily = get_skill_path("tavily-search")
    assert brave is not None and tavily is not None
    brave_content = (brave / "SKILL.md").read_text(encoding="utf-8")
    tavily_content = (tavily / "SKILL.md").read_text(encoding="utf-8")
    assert "tavily-search" in brave_content, "brave-search should reference tavily-search"
    assert "brave-search" in tavily_content, "tavily-search should reference brave-search"


def test_ui_review_skills_bidirectional_reference() -> None:
    """ui-review-checklist and prototype-validator should reference each other."""
    review = get_skill_path("ui-review-checklist")
    validator = get_skill_path("prototype-validator")
    assert review is not None and validator is not None
    review_content = (review / "SKILL.md").read_text(encoding="utf-8")
    validator_content = (validator / "SKILL.md").read_text(encoding="utf-8")
    assert "prototype-validator" in review_content
    assert "ui-review-checklist" in validator_content


def test_architecture_skills_bidirectional_reference() -> None:
    """codebase-design and improve-codebase-architecture should reference each other."""
    vocab = get_skill_path("codebase-design")
    improve = get_skill_path("improve-codebase-architecture")
    assert vocab is not None and improve is not None
    vocab_content = (vocab / "SKILL.md").read_text(encoding="utf-8")
    improve_content = (improve / "SKILL.md").read_text(encoding="utf-8")
    assert "improve-codebase-architecture" in vocab_content
    assert "codebase-design" in improve_content

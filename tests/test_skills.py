"""Tests for hermes.skills discovery and helpers."""

from __future__ import annotations

from pathlib import Path

import hermes.skills as skills_mod
from hermes.skills import (
    discover_skills,
    get_skill_description,
    get_skill_path,
    knowledge_dir,
    list_knowledge_docs,
    load_skill_assets,
    load_skill_content,
    parse_skill_frontmatter,
    skills_dir,
)


def test_discover_skills_returns_nonempty_list() -> None:
    skills = discover_skills()
    assert isinstance(skills, list)
    assert len(skills) > 0


def test_each_skill_has_name_and_path() -> None:
    for s in discover_skills():
        assert isinstance(s.name, str) and s.name
        assert isinstance(s.path, Path)


def test_discover_finds_agent_browser() -> None:
    names = [s.name for s in discover_skills()]
    assert "agent-browser" in names


def test_get_skill_path_returns_dir_for_existing() -> None:
    p = get_skill_path("agent-browser")
    assert p is not None
    assert p.is_dir()


def test_get_skill_path_returns_none_for_missing() -> None:
    assert get_skill_path("does-not-exist-skill-xyz") is None


def test_list_knowledge_docs_returns_at_least_four_markdown() -> None:
    docs = list_knowledge_docs()
    assert len(docs) >= 4
    for d in docs:
        assert d.suffix == ".md"


def test_list_knowledge_docs_sorted() -> None:
    docs = list_knowledge_docs()
    names = [d.name for d in docs]
    assert names == sorted(names)


def test_skills_dir_path_ends_with_skills() -> None:
    assert skills_dir().name == "skills"


def test_knowledge_dir_path_ends_with_knowledge() -> None:
    assert knowledge_dir().name == "knowledge"


def test_discover_skills_handles_missing_dir(monkeypatch, tmp_path) -> None:
    nonexistent = tmp_path / "nonexistent"
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: nonexistent)
    assert discover_skills() == []


def test_discover_skills_count_matches_manifest() -> None:
    # 33 original + 12 mattpocock - 2 merged (pskoett dup, product-manager-skills merged) = 43 (v0.7.0).
    # +1 grounded-citations skill added after v0.7.0 → 44.
    assert len(discover_skills()) == 44


# ---------------------------------------------------------------------------
# parse_skill_frontmatter 测试
# ---------------------------------------------------------------------------


def test_parse_skill_frontmatter_extracts_description(tmp_path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: test-skill\n"
        'description: "A test skill for testing."\n'
        "version: 1.0.0\n"
        "---\n\n# Test\n",
        encoding="utf-8",
    )
    fm = parse_skill_frontmatter(skill_md)
    assert fm["name"] == "test-skill"
    assert fm["description"] == "A test skill for testing."
    assert fm["version"] == "1.0.0"


def test_parse_skill_frontmatter_no_frontmatter_returns_empty(tmp_path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("# No frontmatter here\n\nSome content.", encoding="utf-8")
    assert parse_skill_frontmatter(skill_md) == {}


def test_parse_skill_frontmatter_handles_quoted_values(tmp_path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\n"
        'desc_double: "double \\"quoted\\" value"\n'
        "desc_single: 'single ''quoted'' value'\n"
        'desc_plain: plain unquoted value\n'
        "---\n",
        encoding="utf-8",
    )
    fm = parse_skill_frontmatter(skill_md)
    assert fm["desc_double"] == 'double "quoted" value'
    assert fm["desc_single"] == "single 'quoted' value"
    assert fm["desc_plain"] == "plain unquoted value"


def test_parse_skill_frontmatter_handles_multiline_description(tmp_path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: multi\n"
        "description: |\n"
        "  Line one of the description.\n"
        "  Line two of the description.\n"
        "---\n",
        encoding="utf-8",
    )
    fm = parse_skill_frontmatter(skill_md)
    desc = fm["description"]
    assert isinstance(desc, str)
    assert "Line one of the description." in desc
    assert "Line two of the description." in desc


def test_parse_skill_frontmatter_handles_folded_description(tmp_path) -> None:
    """折叠块标量（>）将连续行合并为空格分隔。"""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "description: >\n"
        "  First part of the description.\n"
        "  Second part continues here.\n"
        "---\n",
        encoding="utf-8",
    )
    fm = parse_skill_frontmatter(skill_md)
    desc = fm["description"]
    assert isinstance(desc, str)
    assert "First part" in desc
    assert "Second part" in desc


def test_parse_skill_frontmatter_handles_list_values(tmp_path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: list-skill\n"
        "triggers:\n"
        '  - "first"\n'
        "  - second\n"
        "---\n",
        encoding="utf-8",
    )
    fm = parse_skill_frontmatter(skill_md)
    assert fm["name"] == "list-skill"
    assert fm["triggers"] == ["first", "second"]


def test_parse_skill_frontmatter_handles_inline_json_value(tmp_path) -> None:
    """含冒号的 JSON 内联值不应干扰 key 分隔符检测。"""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        "---\n"
        'metadata: {"key":"value","nested":{"a":1}}\n'
        "---\n",
        encoding="utf-8",
    )
    fm = parse_skill_frontmatter(skill_md)
    assert fm["metadata"] == '{"key":"value","nested":{"a":1}}'


def test_parse_skill_frontmatter_nonexistent_file_returns_empty(tmp_path) -> None:
    assert parse_skill_frontmatter(tmp_path / "missing.md") == {}


# ---------------------------------------------------------------------------
# load_skill_content 测试
# ---------------------------------------------------------------------------


def test_load_skill_content_returns_full_md(tmp_path, monkeypatch) -> None:
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    content = "---\nname: my-skill\n---\n\n# My Skill\n\nBody text.\n"
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assert load_skill_content("my-skill") == content


def test_load_skill_content_nonexistent_returns_none(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assert load_skill_content("no-such-skill") is None


def test_load_skill_content_missing_skill_md_returns_none(
    monkeypatch, tmp_path
) -> None:
    skill_dir = tmp_path / "empty-skill"
    skill_dir.mkdir()
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assert load_skill_content("empty-skill") is None


# ---------------------------------------------------------------------------
# load_skill_assets 测试
# ---------------------------------------------------------------------------


def test_load_skill_assets_excludes_skill_md_and_meta(
    monkeypatch, tmp_path
) -> None:
    skill_dir = tmp_path / "asset-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Skill", encoding="utf-8")
    (skill_dir / "_meta.json").write_text("{}", encoding="utf-8")
    (skill_dir / "script.py").write_text("# script", encoding="utf-8")
    sub = skill_dir / "data"
    sub.mkdir()
    (sub / "info.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assets = load_skill_assets("asset-skill")
    names = [p.name for p in assets]
    assert "SKILL.md" not in names
    assert "_meta.json" not in names
    assert "script.py" in names
    assert "info.json" in names


def test_load_skill_assets_returns_sorted_paths(monkeypatch, tmp_path) -> None:
    skill_dir = tmp_path / "sort-skill"
    skill_dir.mkdir()
    for name in ["zebra.py", "apple.py", "mango.py"]:
        (skill_dir / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assets = load_skill_assets("sort-skill")
    paths = [str(p) for p in assets]
    assert paths == sorted(paths)


def test_load_skill_assets_nonexistent_returns_empty(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assert load_skill_assets("ghost-skill") == []


def test_load_skill_assets_recurses_subdirectories(
    monkeypatch, tmp_path
) -> None:
    skill_dir = tmp_path / "recurse-skill"
    skill_dir.mkdir()
    deep = skill_dir / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep.txt").write_text("deep", encoding="utf-8")
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assets = load_skill_assets("recurse-skill")
    assert any(p.name == "deep.txt" for p in assets)


# ---------------------------------------------------------------------------
# get_skill_description 测试
# ---------------------------------------------------------------------------


def test_get_skill_description_from_frontmatter(monkeypatch, tmp_path) -> None:
    skill_dir = tmp_path / "desc-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: desc-skill\ndescription: \"My description.\"\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assert get_skill_description("desc-skill") == "My description."


def test_get_skill_description_no_frontmatter_returns_empty(
    monkeypatch, tmp_path
) -> None:
    skill_dir = tmp_path / "no-fm-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Just a heading\n", encoding="utf-8")
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assert get_skill_description("no-fm-skill") == ""


def test_get_skill_description_nonexistent_returns_empty(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assert get_skill_description("ghost") == ""


def test_get_skill_description_unquoted_value(monkeypatch, tmp_path) -> None:
    skill_dir = tmp_path / "unquoted-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: An unquoted description here.\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    assert get_skill_description("unquoted-skill") == "An unquoted description here."


# ---------------------------------------------------------------------------
# discover_skills 集成 description 测试
# ---------------------------------------------------------------------------


def test_discover_skills_includes_description(monkeypatch, tmp_path) -> None:
    skill_dir = tmp_path / "disc-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: disc-skill\ndescription: \"Discovered desc.\"\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    skills = discover_skills()
    assert len(skills) == 1
    assert skills[0].name == "disc-skill"
    assert skills[0].description == "Discovered desc."


def test_discover_skills_description_empty_when_no_frontmatter(
    monkeypatch, tmp_path
) -> None:
    skill_dir = tmp_path / "no-fm"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# No frontmatter\n", encoding="utf-8")
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    skills = discover_skills()
    assert len(skills) == 1
    assert skills[0].description == ""


# ---------------------------------------------------------------------------
# 三级加载一致性测试
# ---------------------------------------------------------------------------


def test_three_level_loading_consistency(monkeypatch, tmp_path) -> None:
    """Level 1 description 是 Level 2 content 的子集；Level 3 不含 SKILL.md。"""
    skill_dir = tmp_path / "three-level"
    skill_dir.mkdir()
    desc = "Three level consistency description."
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: three-level\ndescription: "{desc}"\n---\n\n# Body\n',
        encoding="utf-8",
    )
    (skill_dir / "helper.py").write_text("# helper", encoding="utf-8")
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)

    # Level 1: 只取 description
    level1 = get_skill_description("three-level")
    assert level1 == desc

    # Level 2: 加载完整 SKILL.md
    level2 = load_skill_content("three-level")
    assert level2 is not None
    # Level 1 的 description 是 Level 2 content 的子集
    assert desc in level2

    # Level 3: 加载目录下其他文件
    level3 = load_skill_assets("three-level")
    # SKILL.md 不在 assets 中（已在 Level 2 加载）
    assert all(p.name != "SKILL.md" for p in level3)
    # helper.py 在 assets 中
    assert any(p.name == "helper.py" for p in level3)

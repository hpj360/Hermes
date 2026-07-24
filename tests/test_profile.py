"""Tests for hermes.profile load/save/update/append/render."""

from __future__ import annotations

from pathlib import Path

from hermes.profile import (
    append_to_list,
    get_profile_markdown,
    load_profile,
    save_profile,
    update_field,
)


def test_load_profile_returns_default_when_missing(tmp_state_dir: Path) -> None:
    profile = load_profile()
    assert isinstance(profile, dict)
    assert "basic_info" in profile
    assert profile["version"] == 4


def test_save_profile_creates_file(tmp_state_dir: Path) -> None:
    profile = load_profile()
    save_profile(profile)
    # The profile path was redirected to tmp_state_dir / "profile.json"
    assert (tmp_state_dir / "profile.json").exists()


def test_save_profile_sets_updated_at(tmp_state_dir: Path) -> None:
    profile = load_profile()
    assert profile.get("updated_at") is None
    save_profile(profile)
    saved = load_profile()
    assert saved.get("updated_at")


def test_update_field_creates_section(tmp_state_dir: Path) -> None:
    profile = update_field("basic_info", "name", "Alice")
    assert profile["basic_info"]["name"] == "Alice"
    reloaded = load_profile()
    assert reloaded["basic_info"]["name"] == "Alice"


def test_append_to_list_adds_items(tmp_state_dir: Path) -> None:
    profile = append_to_list("skills", "programming_languages", ["Python", "Rust"])
    assert profile["skills"]["programming_languages"] == ["Python", "Rust"]


def test_append_to_list_avoids_duplicates(tmp_state_dir: Path) -> None:
    append_to_list("skills", "programming_languages", ["Python", "Rust"])
    profile = append_to_list("skills", "programming_languages", ["Rust", "Go"])
    assert profile["skills"]["programming_languages"] == ["Python", "Rust", "Go"]


def test_append_to_list_strips_whitespace(tmp_state_dir: Path) -> None:
    profile = append_to_list("skills", "tools", ["  git  ", "\tdocker\t"])
    assert profile["skills"]["tools"] == ["git", "docker"]


def test_append_to_list_skips_empty(tmp_state_dir: Path) -> None:
    profile = append_to_list("skills", "tools", ["", "   ", "real-tool"])
    assert profile["skills"]["tools"] == ["real-tool"]


def test_get_profile_markdown_returns_string(tmp_state_dir: Path) -> None:
    md = get_profile_markdown()
    assert isinstance(md, str)
    assert "用户画像" in md


def test_get_profile_markdown_renders_career_section(tmp_state_dir: Path) -> None:
    update_field("career", "summary", "Senior engineer")
    md = get_profile_markdown()
    assert "职业履历" in md


def test_get_profile_markdown_renders_pets(tmp_state_dir: Path) -> None:
    profile = load_profile()
    profile["pets"] = [{"name": "Mimi", "gender": "female", "age": 3}]
    save_profile(profile)
    md = get_profile_markdown()
    assert "萌宠" in md
    assert "Mimi" in md


def test_get_profile_markdown_renders_alcohol(tmp_state_dir: Path) -> None:
    update_field("alcohol_preferences", "identity", "Craft beer enthusiast")
    md = get_profile_markdown()
    assert "酒类偏好" in md


def test_get_profile_markdown_renders_notes(tmp_state_dir: Path) -> None:
    update_field("notes", "", "this is a note value if section becomes dict")
    # notes default is a string field; use direct save for clarity
    profile = load_profile()
    profile["notes"] = "remember to update skills"
    save_profile(profile)
    md = get_profile_markdown()
    assert "备注" in md
    assert "remember to update skills" in md


def test_default_profile_keys_present(tmp_state_dir: Path) -> None:
    profile = load_profile()
    expected = {
        "version",
        "updated_at",
        "basic_info",
        "contact",
        "social_accounts",
        "pets",
        "career",
        "skills",
        "alcohol_preferences",
        "interests",
        "content_creation",
        "work_style",
        "personal_projects",
        "goals",
        "notes",
    }
    assert expected.issubset(profile.keys())


def test_update_field_creates_new_section(tmp_state_dir: Path) -> None:
    profile = update_field("custom_section", "k", "v")
    assert profile["custom_section"] == {"k": "v"}


def test_save_then_load_roundtrip(tmp_state_dir: Path) -> None:
    profile = load_profile()
    profile["basic_info"]["name"] = "Bob"
    save_profile(profile)
    reloaded = load_profile()
    assert reloaded["basic_info"]["name"] == "Bob"


def test_load_profile_returns_dict_when_present(tmp_state_dir: Path) -> None:
    save_profile({"version": 4, "basic_info": {"name": "Carol"}})
    profile = load_profile()
    assert profile["basic_info"]["name"] == "Carol"


def test_append_to_list_creates_section_when_missing(tmp_state_dir: Path) -> None:
    profile = append_to_list("new_section", "items", ["a", "b"])
    assert profile["new_section"]["items"] == ["a", "b"]

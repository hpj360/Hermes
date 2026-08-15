"""Tests for hermes.skill_market (P3-4) and the `hermes skills install/pack/remote` CLI."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes.main import main
from hermes.skill_market import (
    _is_git_source,
    _is_zip_source,
    _safe_extract_zip,
    install_skill,
    list_registry,
    load_registry,
    pack_skill,
    registry_file,
    validate_skill_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(root: Path, name: str) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n\nbody\n", encoding="utf-8")
    return skill


def _make_zip(src_skill: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in src_skill.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=f"{src_skill.name}/{p.relative_to(src_skill).as_posix()}")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_load_registry_empty_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes.skill_market.registry_file", lambda: tmp_path / "nope.json")
    assert load_registry() == {}


def test_load_registry_parses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "registry.json"
    f.write_text(json.dumps({"foo": {"source": "https://x/foo.git", "version": "1.0"}}), encoding="utf-8")
    monkeypatch.setattr("hermes.skill_market.registry_file", lambda: f)
    reg = load_registry()
    assert reg["foo"]["source"] == "https://x/foo.git"


def test_load_registry_corrupt_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "registry.json"
    f.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr("hermes.skill_market.registry_file", lambda: f)
    assert load_registry() == {}


def test_registry_file_lives_in_skills_dir() -> None:
    assert registry_file().name == "registry.json"


# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------


def test_is_git_source() -> None:
    assert _is_git_source("git@github.com:x/y.git") is True
    assert _is_git_source("https://github.com/x/y.git") is True
    assert _is_git_source("ssh://git@github.com/x/y.git") is True
    assert _is_git_source("https://example.com/foo.zip") is False


def test_is_zip_source() -> None:
    assert _is_zip_source("https://example.com/foo.zip") is True
    assert _is_zip_source("/tmp/foo.zip") is True
    assert _is_zip_source("https://example.com/foo.git") is False


# ---------------------------------------------------------------------------
# install_skill
# ---------------------------------------------------------------------------


def test_install_from_local_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    src = _make_skill(tmp_path / "src", "foo")
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)

    result = install_skill("foo", source=str(src))
    assert result.success is True
    assert (dest / "foo" / "SKILL.md").exists()


def test_install_from_local_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    src = _make_skill(tmp_path / "src", "foo")
    archive = tmp_path / "foo-1.0.zip"
    _make_zip(src, archive)
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)

    result = install_skill("foo", source=str(archive))
    assert result.success is True
    assert (dest / "foo" / "SKILL.md").exists()


def test_install_duplicate_without_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    src = _make_skill(tmp_path / "src", "foo")
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)

    assert install_skill("foo", source=str(src)).success is True
    result = install_skill("foo", source=str(src))
    assert result.success is False
    assert "already installed" in result.message


def test_install_duplicate_with_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    src = _make_skill(tmp_path / "src", "foo")
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)

    install_skill("foo", source=str(src))
    result = install_skill("foo", source=str(src), force=True)
    assert result.success is True


def test_install_not_in_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)
    monkeypatch.setattr("hermes.skill_market.load_registry", lambda: {})

    result = install_skill("missing")
    assert result.success is False
    assert "not found" in result.message


def test_install_from_vendored_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    src = _make_skill(tmp_path / "src", "foo")
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)
    monkeypatch.setattr(
        "hermes.skill_market.load_registry", lambda: {"foo": {"source": str(src)}}
    )

    result = install_skill("foo")
    assert result.success is True
    assert result.details["resolved_from"] == "registry"


def test_install_from_remote_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    src = _make_skill(tmp_path / "src", "foo")
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)
    monkeypatch.setattr("hermes.skill_market.load_registry", lambda: {})
    monkeypatch.setattr("hermes.skill_market.remote_registry_url", lambda: "https://r/reg.json")
    monkeypatch.setattr(
        "hermes.skill_market.fetch_registry", lambda url: {"foo": {"source": str(src)}}
    )

    result = install_skill("foo")
    assert result.success is True
    assert result.details["resolved_from"] == "remote-registry"


def test_install_git_missing_returns_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)
    monkeypatch.setattr(
        "hermes.skill_market.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("git")),
    )

    result = install_skill("foo", source="git@github.com:x/foo.git")
    assert result.success is False
    assert "git" in result.message.lower()


# ---------------------------------------------------------------------------
# install_skill security (P0-1): path traversal + zip-slip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "../evil",
        "..\\evil",
        "foo/bar",
        "foo\\bar",
        ".hidden",
        "..",
        "",
        "a b",
        "foo;rm -rf",
    ],
)
def test_validate_skill_name_rejects_unsafe(
    bad_name: str,
) -> None:
    assert validate_skill_name(bad_name) is not None


@pytest.mark.parametrize("good_name", ["foo", "foo-bar", "foo.bar_baz", "a1"])
def test_validate_skill_name_accepts_safe(good_name: str) -> None:
    assert validate_skill_name(good_name) is None


def test_install_skill_rejects_traversal_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dest = tmp_path / "skills"
    dest.mkdir()
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: dest)

    result = install_skill("../evil", source=str(tmp_path))
    assert result.success is False
    # Nothing may be created outside the skills dir.
    assert not (tmp_path / "evil").exists()


def test_install_skill_target_stays_inside_dest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A validated name with an unexpected *dest* must not escape its parent."""
    src = _make_skill(tmp_path / "src", "foo")
    result = install_skill("foo", source=str(src), dest=tmp_path / "does" / "not" / "exist")
    # dest parent is created fine; success requires the name to stay inside.
    assert result.success is True
    assert (tmp_path / "does" / "not" / "exist" / "foo" / "SKILL.md").exists()


def test_safe_extract_zip_rejects_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", "pwned")
        zf.writestr("ok/inside.txt", "fine")
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    with pytest.raises(OSError):
        _safe_extract_zip(archive, extract_dir)
    assert not (tmp_path / "outside.txt").exists()


def test_safe_extract_zip_skips_symlink(tmp_path: Path) -> None:
    archive = tmp_path / "sym.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("link", "target")
        # Mark the entry as a symlink via external_attr (unix mode bits).
        for info in zf.infolist():
            if info.filename == "link":
                info.external_attr = (0o120777 << 16)
    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()

    _safe_extract_zip(archive, extract_dir)
    assert not (extract_dir / "link").exists()


# ---------------------------------------------------------------------------
# pack_skill
# ---------------------------------------------------------------------------


def test_pack_skill_creates_versioned_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills = tmp_path / "skills"
    _make_skill(skills, "foo")
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: skills)
    monkeypatch.setattr(
        "hermes.skill_market.load_skill_manifest",
        lambda name: SimpleNamespace(version="1.2.3"),
    )

    result = pack_skill("foo", output_dir=tmp_path / "out")
    assert result.success is True
    archive = Path(result.details["archive"])
    assert archive.name == "foo-1.2.3.zip"
    assert archive.exists()
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert "foo/SKILL.md" in names


def test_pack_skill_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: tmp_path / "nope")
    result = pack_skill("ghost")
    assert result.success is False


# ---------------------------------------------------------------------------
# list_registry / CLI
# ---------------------------------------------------------------------------


def test_list_registry_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes.skill_market.load_registry", lambda: {})
    monkeypatch.setattr("hermes.skill_market.remote_registry_url", lambda: "")
    assert list_registry() == {}


def test_cli_skills_remote_returns_zero(tmp_state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes.skill_market.list_registry", lambda: {})
    rc = main(["skills", "remote"])
    assert rc == 0


def test_cli_skills_pack_missing_returns_soft_fail(
    tmp_state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hermes.skill_market.skills_dir", lambda: Path("/nonexistent-skills"))
    rc = main(["skills", "pack", "ghost"])
    assert rc == 1

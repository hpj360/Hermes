"""Tests for hermes.workbench.asset_sync (Phase 3.6 cross-project asset sync).

Covers:
- AC-17: skills sync copies SKILL.md (+ entrypoint) from source to target
- AC-18: memory sync merges L1 facts (source overwrites) + L2 episodes (dedup)
- AC-19: sync with a missing source project raises NotFoundError
- scope="all" simultaneously syncs skills + memory + profile
- profile shallow-merge with source overriding target top-level keys
- multi-target fan-out
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.workbench.asset_sync import AssetSync, SyncResult
from hermes.workbench.errors import NotFoundError, ValidationError
from hermes.workbench.memory import make_episode
from hermes.workbench.persistence import atomic_write_json
from hermes.workbench.projects import ProjectRegistry, Router


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_skill_md(name: str, description: str = "") -> str:
    """Build a minimal SKILL.md with YAML front-matter."""
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {name}\n\nBody.\n"
    )


@pytest.fixture
def registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(state_dir=tmp_path / "registry")


@pytest.fixture
def router(registry: ProjectRegistry) -> Router:
    return Router(registry)


def _add_project(
    registry: ProjectRegistry,
    tmp_path: Path,
    conn_id: str,
) -> tuple[Path, Path]:
    """Register a project with state_dir + skills_dir under tmp_path.

    Returns (state_dir, skills_dir). Both directories are created.
    """
    state_dir = tmp_path / conn_id / "state"
    skills_dir = tmp_path / conn_id / "skills"
    state_dir.mkdir(parents=True, exist_ok=True)
    skills_dir.mkdir(parents=True, exist_ok=True)
    registry.add(
        name=conn_id,
        project_type="local",
        state_dir=str(state_dir),
        skills_dir=str(skills_dir),
        conn_id=conn_id,
    )
    return state_dir, skills_dir


# ---------------------------------------------------------------------------
# SyncResult dataclass
# ---------------------------------------------------------------------------


def test_sync_result_defaults() -> None:
    r = SyncResult(ok=True, scope="skills", source="a")
    assert r.ok is True
    assert r.scope == "skills"
    assert r.source == "a"
    assert r.targets == []
    assert r.synced_count == 0
    assert r.errors == []


def test_sync_result_full_construction() -> None:
    r = SyncResult(
        ok=False,
        scope="all",
        source="a",
        targets=["b", "c"],
        synced_count=5,
        errors=["boom"],
    )
    assert r.ok is False
    assert r.targets == ["b", "c"]
    assert r.synced_count == 5
    assert r.errors == ["boom"]


# ---------------------------------------------------------------------------
# AC-17: skills sync
# ---------------------------------------------------------------------------


def test_ac17_skills_sync_copies_skill_md(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """AC-17: proj-a has an echo skill; after sync(scope='skills') proj-b
    has echo/SKILL.md under its skills_dir.
    """
    _, src_skills = _add_project(registry, tmp_path, "proj-a")
    _, tgt_skills = _add_project(registry, tmp_path, "proj-b")

    echo_dir = src_skills / "echo"
    echo_dir.mkdir()
    (echo_dir / "SKILL.md").write_text(
        _make_skill_md("echo", "echo skill"), encoding="utf-8"
    )

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="skills")

    assert result.ok is True
    assert result.scope == "skills"
    assert result.source == "proj-a"
    assert result.targets == ["proj-b"]
    assert result.synced_count >= 1
    assert (tgt_skills / "echo" / "SKILL.md").exists()
    content = (tgt_skills / "echo" / "SKILL.md").read_text(encoding="utf-8")
    assert "echo" in content


def test_skills_sync_also_copies_entrypoint(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """Skills sync copies SKILL.md AND the detected entrypoint file."""
    _, src_skills = _add_project(registry, tmp_path, "proj-a")
    _, tgt_skills = _add_project(registry, tmp_path, "proj-b")

    echo_dir = src_skills / "echo"
    echo_dir.mkdir()
    (echo_dir / "SKILL.md").write_text(_make_skill_md("echo"), encoding="utf-8")
    (echo_dir / "run.py").write_text('print("hello")\n', encoding="utf-8")

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="skills")

    assert result.ok is True
    assert (tgt_skills / "echo" / "SKILL.md").exists()
    assert (tgt_skills / "echo" / "run.py").exists()
    # SKILL.md + run.py
    assert result.synced_count == 2


def test_skills_sync_creates_target_skills_dir(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """If the target skills_dir does not yet exist, it is created."""
    _, src_skills = _add_project(registry, tmp_path, "proj-a")
    # proj-b: register with a skills_dir that doesn't exist yet
    tgt_state = tmp_path / "proj-b" / "state"
    tgt_state.mkdir(parents=True)
    tgt_skills = tmp_path / "proj-b" / "skills"
    registry.add(
        name="proj-b",
        project_type="local",
        state_dir=str(tgt_state),
        skills_dir=str(tgt_skills),
        conn_id="proj-b",
    )

    echo_dir = src_skills / "echo"
    echo_dir.mkdir()
    (echo_dir / "SKILL.md").write_text(_make_skill_md("echo"), encoding="utf-8")

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="skills")

    assert result.ok is True
    assert tgt_skills.exists()
    assert (tgt_skills / "echo" / "SKILL.md").exists()


# ---------------------------------------------------------------------------
# AC-18: memory sync
# ---------------------------------------------------------------------------


def test_ac18_memory_sync_fact_source_overwrites(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """AC-18: proj-a has k=v, proj-b has k=old; after sync(scope='memory')
    proj-b's k=v (source overwrites target).
    """
    _add_project(registry, tmp_path, "proj-a")
    _add_project(registry, tmp_path, "proj-b")

    rt_a = router.resolve("proj-a")
    rt_b = router.resolve("proj-b")
    rt_a.memory().remember_fact("k", "v")
    rt_b.memory().remember_fact("k", "old")

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="memory")

    assert result.ok is True
    assert rt_b.memory().get_fact("k") == {"key": "k", "value": "v"}


def test_memory_sync_appends_new_episodes(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """L2 episodes from source are appended to target."""
    _add_project(registry, tmp_path, "proj-a")
    _add_project(registry, tmp_path, "proj-b")

    rt_a = router.resolve("proj-a")
    rt_b = router.resolve("proj-b")
    ep = make_episode("note", "from-a", {"x": 1})
    rt_a.memory().record_episode(ep)

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="memory")

    assert result.ok is True
    tgt_ids = [e.id for e in rt_b.memory().list_episodes(limit=100)]
    assert ep.id in tgt_ids


def test_memory_sync_dedup_episodes_by_id(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """If target already has an episode with the same id, it is not duplicated."""
    _add_project(registry, tmp_path, "proj-a")
    _add_project(registry, tmp_path, "proj-b")

    rt_a = router.resolve("proj-a")
    rt_b = router.resolve("proj-b")
    ep = make_episode("note", "shared", {"x": 1})
    rt_a.memory().record_episode(ep)
    rt_b.memory().record_episode(ep)  # already present in target

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="memory")

    assert result.ok is True
    matching = [e for e in rt_b.memory().list_episodes(limit=100) if e.id == ep.id]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# AC-19: NotFoundError on missing source / target
# ---------------------------------------------------------------------------


def test_ac19_sync_missing_source_raises_not_found_error(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """AC-19: sync with a non-existent source project raises NotFoundError."""
    _add_project(registry, tmp_path, "proj-b")
    syncer = AssetSync(router)
    with pytest.raises(NotFoundError, match="project not found"):
        syncer.sync("nonexistent", ["proj-b"], scope="skills")


def test_sync_missing_target_raises_not_found_error(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """A missing target project also raises NotFoundError."""
    _add_project(registry, tmp_path, "proj-a")
    syncer = AssetSync(router)
    with pytest.raises(NotFoundError, match="project not found"):
        syncer.sync("proj-a", ["nonexistent"], scope="skills")


# ---------------------------------------------------------------------------
# ValidationError on bad scope
# ---------------------------------------------------------------------------


def test_sync_invalid_scope_raises_validation_error(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    _add_project(registry, tmp_path, "proj-a")
    _add_project(registry, tmp_path, "proj-b")
    syncer = AssetSync(router)
    with pytest.raises(ValidationError):
        syncer.sync("proj-a", ["proj-b"], scope="bogus")


# ---------------------------------------------------------------------------
# scope="all"
# ---------------------------------------------------------------------------


def test_sync_all_scope_syncs_skills_memory_profile(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """scope='all' syncs skills + memory + profile in one call."""
    src_state, src_skills = _add_project(registry, tmp_path, "proj-a")
    tgt_state, tgt_skills = _add_project(registry, tmp_path, "proj-b")

    # Source: skill
    echo_dir = src_skills / "echo"
    echo_dir.mkdir()
    (echo_dir / "SKILL.md").write_text(_make_skill_md("echo"), encoding="utf-8")
    # Source: memory
    rt_a = router.resolve("proj-a")
    rt_a.memory().remember_fact("k", "v")
    # Source: profile
    atomic_write_json(src_state / "profile.json", {"a": 1, "b": 2})

    # Target pre-state
    rt_b = router.resolve("proj-b")
    rt_b.memory().remember_fact("k", "old")
    atomic_write_json(tgt_state / "profile.json", {"b": 3, "c": 4})

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="all")

    assert result.ok is True
    assert result.scope == "all"
    # Skills
    assert (tgt_skills / "echo" / "SKILL.md").exists()
    # Memory (source overwrites)
    assert rt_b.memory().get_fact("k") == {"key": "k", "value": "v"}
    # Profile (shallow merge: source overrides)
    merged = json.loads((tgt_state / "profile.json").read_text(encoding="utf-8"))
    assert merged == {"a": 1, "b": 2, "c": 4}


# ---------------------------------------------------------------------------
# Profile shallow merge
# ---------------------------------------------------------------------------


def test_profile_sync_shallow_merge_source_overrides(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """src {a:1,b:2}, tgt {b:3,c:4} -> tgt {a:1,b:2,c:4}."""
    src_state, _ = _add_project(registry, tmp_path, "proj-a")
    tgt_state, _ = _add_project(registry, tmp_path, "proj-b")
    atomic_write_json(src_state / "profile.json", {"a": 1, "b": 2})
    atomic_write_json(tgt_state / "profile.json", {"b": 3, "c": 4})

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="profile")

    assert result.ok is True
    merged = json.loads((tgt_state / "profile.json").read_text(encoding="utf-8"))
    assert merged == {"a": 1, "b": 2, "c": 4}


def test_profile_sync_skips_when_source_profile_missing(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """If source has no profile.json, sync is a no-op (synced_count=0)."""
    src_state, _ = _add_project(registry, tmp_path, "proj-a")
    tgt_state, _ = _add_project(registry, tmp_path, "proj-b")
    atomic_write_json(tgt_state / "profile.json", {"b": 3})
    # No source profile.json

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b"], scope="profile")

    assert result.ok is True
    assert result.synced_count == 0
    merged = json.loads((tgt_state / "profile.json").read_text(encoding="utf-8"))
    assert merged == {"b": 3}  # target unchanged


# ---------------------------------------------------------------------------
# Multi-target fan-out
# ---------------------------------------------------------------------------


def test_sync_multi_target(
    registry: ProjectRegistry, router: Router, tmp_path: Path
) -> None:
    """Sync fans out to multiple targets in one call."""
    _add_project(registry, tmp_path, "proj-a")
    _add_project(registry, tmp_path, "proj-b")
    _add_project(registry, tmp_path, "proj-c")

    rt_a = router.resolve("proj-a")
    rt_a.memory().remember_fact("shared", "yes")

    syncer = AssetSync(router)
    result = syncer.sync("proj-a", ["proj-b", "proj-c"], scope="memory")

    assert result.ok is True
    assert result.targets == ["proj-b", "proj-c"]
    rt_b = router.resolve("proj-b")
    rt_c = router.resolve("proj-c")
    assert rt_b.memory().get_fact("shared") == {"key": "shared", "value": "yes"}
    assert rt_c.memory().get_fact("shared") == {"key": "shared", "value": "yes"}

"""Tests for Skill Sync (Local mode): discovery, hashing, add/remove/sync, status.

Isolation strategy (mirrors tests/test_cli_loop.py): monkeypatch
`skill_sync.skills_dir`, `skill_sync.state_file`, and `Path.home` to point at a
tmp tree so no real agent directories or state files are touched.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from hermes import skill_sync
from hermes.skill_sync import (
    AgentDir,
    add_all_skills,
    add_custom_agent,
    add_skill,
    compute_hash,
    discover_agent_dirs,
    get_status,
    get_sync_state,
    load_sync_state,
    remove_skill,
    save_sync_state,
    sync_skill,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def sync_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> types.SimpleNamespace:
    """隔离中心仓库、状态文件与 home 目录到 tmp_path。"""
    central = tmp_path / "skills"
    central.mkdir()
    state = tmp_path / "state" / "skill_sync.json"
    state.parent.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.setattr(skill_sync, "skills_dir", lambda: central)
    monkeypatch.setattr(skill_sync, "state_file", lambda: state)
    monkeypatch.setattr(Path, "home", lambda: home)

    return types.SimpleNamespace(central=central, state=state, home=home)


def _make_skill(central: Path, name: str, content: str = "hello") -> Path:
    """在中心仓库创建一个 skill 目录。"""
    d = central / name
    d.mkdir()
    (d / "SKILL.md").write_text(f"# {name}\n{content}\n", encoding="utf-8")
    return d


def _make_agent(home: Path, name: str) -> Path:
    """创建一个已知 agent 的 skills 目录（home/.{name}/skills）。"""
    p = home / f".{name}" / "skills"
    p.mkdir(parents=True)
    return p


# ── discover_agent_dirs ─────────────────────────────────────────────


def test_discover_agent_dirs_finds_known_dirs(sync_env: types.SimpleNamespace) -> None:
    """自动发现已存在的常见 Agent 目录。"""
    for rel in (".codex/skills", ".claude-code/skills", ".cursor/skills"):
        (sync_env.home / rel).mkdir(parents=True)

    dirs = discover_agent_dirs()
    names = [d.name for d in dirs]
    assert "codex" in names
    assert "claude-code" in names
    assert "cursor" in names
    assert all(d.exists for d in dirs)
    assert all(not d.is_custom for d in dirs)


def test_discover_agent_dirs_includes_custom(
    sync_env: types.SimpleNamespace,
) -> None:
    """自定义 agent 目录被合并进发现列表，并标记 is_custom。"""
    custom_path = sync_env.home / "my-agent" / "skills"
    custom_path.mkdir(parents=True)

    dirs = discover_agent_dirs({"my-agent": str(custom_path)})
    custom = [d for d in dirs if d.name == "my-agent"]
    assert len(custom) == 1
    assert custom[0].is_custom is True
    assert custom[0].exists is True


# ── compute_hash ────────────────────────────────────────────────────


def test_compute_hash_consistent_for_same_content(tmp_path: Path) -> None:
    """内容相同的目录哈希一致。"""
    a = tmp_path / "a"
    a.mkdir()
    (a / "f.txt").write_text("x", encoding="utf-8")
    b = tmp_path / "b"
    b.mkdir()
    (b / "f.txt").write_text("x", encoding="utf-8")

    assert compute_hash(a) == compute_hash(b)
    assert compute_hash(a) != ""


def test_compute_hash_differs_for_different_content(tmp_path: Path) -> None:
    """内容不同的目录哈希不同。"""
    a = tmp_path / "a"
    a.mkdir()
    (a / "f.txt").write_text("x", encoding="utf-8")
    b = tmp_path / "b"
    b.mkdir()
    (b / "f.txt").write_text("y", encoding="utf-8")

    assert compute_hash(a) != compute_hash(b)


# ── add_skill ───────────────────────────────────────────────────────


def test_add_skill_symlink_mode(sync_env: types.SimpleNamespace) -> None:
    """symlink 模式：在 agent 目录创建指向中心仓库的 symlink。"""
    _make_skill(sync_env.central, "wechat-reader")
    _make_agent(sync_env.home, "codex")

    r = add_skill("wechat-reader")
    assert r.success

    dest = sync_env.home / ".codex" / "skills" / "wechat-reader"
    assert dest.is_symlink()
    state = load_sync_state()
    assert "wechat-reader" in state["managed_skills"]
    assert state["managed_skills"]["wechat-reader"]["mode"] == "symlink"
    assert "codex" in state["managed_skills"]["wechat-reader"]["agents"]


def test_add_skill_copy_mode(sync_env: types.SimpleNamespace) -> None:
    """copy 模式：复制内容到 agent 目录（非 symlink）。"""
    _make_skill(sync_env.central, "douyin-reader")
    _make_agent(sync_env.home, "codex")

    r = add_skill("douyin-reader", copy=True)
    assert r.success

    dest = sync_env.home / ".codex" / "skills" / "douyin-reader"
    assert dest.exists() and not dest.is_symlink()
    assert (dest / "SKILL.md").exists()
    state = load_sync_state()
    assert state["managed_skills"]["douyin-reader"]["mode"] == "copy"


def test_add_skill_all(sync_env: types.SimpleNamespace) -> None:
    """--all：把中心仓库全部 skill 纳入管理。"""
    _make_skill(sync_env.central, "a-skill")
    _make_skill(sync_env.central, "b-skill")
    _make_agent(sync_env.home, "codex")

    r = add_all_skills()
    assert r.success
    state = load_sync_state()
    assert "a-skill" in state["managed_skills"]
    assert "b-skill" in state["managed_skills"]


def test_add_skill_not_found(sync_env: types.SimpleNamespace) -> None:
    """中心仓库不存在的 skill 无法添加。"""
    _make_agent(sync_env.home, "codex")
    r = add_skill("nope")
    assert not r.success
    assert "not found" in r.message


# ── remove_skill ────────────────────────────────────────────────────


def test_remove_skill_symlink_keeps_central(
    sync_env: types.SimpleNamespace,
) -> None:
    """symlink 模式 remove：删除 symlink，保留中心仓库。"""
    _make_skill(sync_env.central, "tmp-skill")
    _make_agent(sync_env.home, "codex")
    add_skill("tmp-skill")

    central_path = sync_env.central / "tmp-skill"
    assert central_path.exists()

    r = remove_skill("tmp-skill")
    assert r.success
    assert central_path.exists()  # 中心仓库保留
    dest = sync_env.home / ".codex" / "skills" / "tmp-skill"
    assert not dest.exists()  # symlink 已删除
    state = load_sync_state()
    assert "tmp-skill" not in state["managed_skills"]


def test_remove_skill_copy_restores_to_agents(
    sync_env: types.SimpleNamespace,
) -> None:
    """copy 模式 remove：把内容复制回 agent 后删除中心仓库副本。"""
    _make_skill(sync_env.central, "copy-skill", content="v1")
    _make_agent(sync_env.home, "codex")
    add_skill("copy-skill", copy=True)

    central_path = sync_env.central / "copy-skill"
    r = remove_skill("copy-skill")
    assert r.success
    assert not central_path.exists()  # 中心副本已删除
    dest = sync_env.home / ".codex" / "skills" / "copy-skill"
    assert dest.exists() and (dest / "SKILL.md").exists()  # agent 保留副本
    state = load_sync_state()
    assert "copy-skill" not in state["managed_skills"]


# ── sync_skill ──────────────────────────────────────────────────────


def test_sync_skill_updates_hash(sync_env: types.SimpleNamespace) -> None:
    """copy 模式 sync：中心改动后同步刷新 agent 副本与记录哈希。"""
    _make_skill(sync_env.central, "sync-skill", content="v1")
    _make_agent(sync_env.home, "codex")
    add_skill("sync-skill", copy=True)

    (sync_env.central / "sync-skill" / "SKILL.md").write_text(
        "# sync-skill\nv2\n", encoding="utf-8"
    )
    new_hash = compute_hash(sync_env.central / "sync-skill")

    r = sync_skill("sync-skill")
    assert r.success
    state = load_sync_state()
    info = state["managed_skills"]["sync-skill"]
    assert info["central_hash"] == new_hash
    assert info["agents"]["codex"]["hash"] == new_hash
    agent_file = sync_env.home / ".codex" / "skills" / "sync-skill" / "SKILL.md"
    assert agent_file.read_text(encoding="utf-8") == "# sync-skill\nv2\n"


def test_sync_all_skills(sync_env: types.SimpleNamespace) -> None:
    """sync_skill(None)：同步所有 managed skill。"""
    _make_skill(sync_env.central, "s1", content="1")
    _make_skill(sync_env.central, "s2", content="2")
    _make_agent(sync_env.home, "codex")
    add_skill("s1", copy=True)
    add_skill("s2", copy=True)

    (sync_env.central / "s1" / "SKILL.md").write_text("# s1\n1b\n", encoding="utf-8")
    (sync_env.central / "s2" / "SKILL.md").write_text("# s2\n2b\n", encoding="utf-8")

    r = sync_skill(None)
    assert r.success
    state = load_sync_state()
    h1 = compute_hash(sync_env.central / "s1")
    h2 = compute_hash(sync_env.central / "s2")
    assert state["managed_skills"]["s1"]["central_hash"] == h1
    assert state["managed_skills"]["s1"]["agents"]["codex"]["hash"] == h1
    assert state["managed_skills"]["s2"]["central_hash"] == h2
    assert state["managed_skills"]["s2"]["agents"]["codex"]["hash"] == h2


# ── get_status ──────────────────────────────────────────────────────


def test_get_status_shows_managed_and_unmanaged(
    sync_env: types.SimpleNamespace,
) -> None:
    """status 同时展示 managed 与未管理（unmanaged）的 skill。"""
    _make_skill(sync_env.central, "managed-one")
    _make_skill(sync_env.central, "free-one")
    _make_agent(sync_env.home, "codex")
    # free-one 在 agent 目录中存在独立副本（未管理）
    free_dest = sync_env.home / ".codex" / "skills" / "free-one"
    free_dest.mkdir(parents=True)
    (free_dest / "SKILL.md").write_text("# free-one\n", encoding="utf-8")

    add_skill("managed-one")  # symlink 模式

    statuses = get_status()
    names = [s.skill_name for s in statuses]
    assert "managed-one" in names
    assert "free-one" in names

    managed = next(s for s in statuses if s.skill_name == "managed-one")
    assert any(a.state == "linked" for a in managed.agents)

    free = next(s for s in statuses if s.skill_name == "free-one")
    assert any(a.state == "unmanaged" for a in free.agents)


# ── add_custom_agent ────────────────────────────────────────────────


def test_add_custom_agent_persists(sync_env: types.SimpleNamespace) -> None:
    """add_custom_agent 持久化到状态文件并出现在发现列表中。"""
    p = sync_env.home / "custom" / "skills"
    p.mkdir(parents=True)

    r = add_custom_agent("my-agent", str(p))
    assert r.success
    state = load_sync_state()
    assert state["custom_agents"]["my-agent"] == str(p)

    dirs = discover_agent_dirs(state["custom_agents"])
    assert any(d.name == "my-agent" and d.is_custom for d in dirs)


# ── load/save state ─────────────────────────────────────────────────


def test_load_save_sync_state_roundtrip(sync_env: types.SimpleNamespace) -> None:
    """save → load 往返保持一致。"""
    state = {
        "managed_skills": {
            "x": {"central_hash": "h", "mode": "symlink", "agents": {}}
        },
        "custom_agents": {"a": "/p"},
    }
    save_sync_state(state)
    loaded = load_sync_state()
    assert loaded == state


def test_state_file_not_exists_returns_empty(
    sync_env: types.SimpleNamespace,
) -> None:
    """状态文件不存在时返回空结构。"""
    if sync_env.state.exists():
        sync_env.state.unlink()
    loaded = load_sync_state()
    assert loaded == {"managed_skills": {}, "custom_agents": {}}


# ── 冲突检测 ─────────────────────────────────────────────────────────


def test_conflict_detection(sync_env: types.SimpleNamespace) -> None:
    """中心与 agent 同时改动 → conflict。"""
    _make_skill(sync_env.central, "c-skill", content="orig")
    _make_agent(sync_env.home, "codex")
    add_skill("c-skill", copy=True)

    # 同时改动中心与 agent
    (sync_env.central / "c-skill" / "SKILL.md").write_text(
        "# c-skill\ncentral\n", encoding="utf-8"
    )
    agent_dest = sync_env.home / ".codex" / "skills" / "c-skill"
    (agent_dest / "SKILL.md").write_text("# c-skill\nagent\n", encoding="utf-8")

    state = load_sync_state()
    info = state["managed_skills"]["c-skill"]
    ad = AgentDir("codex", agent_dest.parent, True, False)
    st = get_sync_state("c-skill", ad, info)
    assert st.state == "conflict"


def test_external_changes_detection(sync_env: types.SimpleNamespace) -> None:
    """仅 agent 改动 → external_changes，且 sync 不会覆盖它。"""
    _make_skill(sync_env.central, "e-skill", content="orig")
    _make_agent(sync_env.home, "codex")
    add_skill("e-skill", copy=True)

    agent_dest = sync_env.home / ".codex" / "skills" / "e-skill"
    (agent_dest / "SKILL.md").write_text("# e-skill\nagent\n", encoding="utf-8")

    state = load_sync_state()
    info = state["managed_skills"]["e-skill"]
    ad = AgentDir("codex", agent_dest.parent, True, False)
    assert get_sync_state("e-skill", ad, info).state == "external_changes"

    r = sync_skill("e-skill")
    assert r.success
    # 被跳过，内容未被覆盖
    assert (
        agent_dest.joinpath("SKILL.md").read_text(encoding="utf-8")
        == "# e-skill\nagent\n"
    )


# ── CLI registration smoke test ─────────────────────────────────────


def test_skill_sync_subcommand_registered() -> None:
    """`hermes skill-sync` 已注册并可解析子命令。"""
    from hermes.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["skill-sync", "status"])
    assert args.command == "skill-sync"
    assert args.skill_sync_cmd == "status"

    # 无子命令时默认 status
    args2 = parser.parse_args(["skill-sync"])
    assert args2.skill_sync_cmd is None
    assert callable(getattr(args2, "func", None))

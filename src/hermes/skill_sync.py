"""Skill Sync: 多 Agent 时代的 Skill 管理方案（Local mode）。

中心仓库（skills/）作为单一信源，通过 symlink（默认）或 copy 分发到各 Agent 目录。
状态持久化到 .state/skill_sync.json，支持变更检测与保守的冲突报告（不自动合并）。

设计原则：
- 单一信源：skills/ 目录是唯一可信来源
- 默认软链接：零开销实时同步，改一处全局生效
- 状态可见：一个 get_status() 看清所有 Skill 状态
- 保守冲突：不擅自合并，只报告状态
- 安全降级：单个 agent 目录操作失败不影响其他
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes.config import get_settings
from hermes.skills import skills_dir

# 常见 Agent 目录（name, home 下相对路径）。自动发现时逐一探测。
KNOWN_AGENT_DIRS: list[tuple[str, str]] = [
    ("codex", ".codex/skills"),
    ("claude-code", ".claude-code/skills"),
    ("cursor", ".cursor/skills"),
    ("qoder", ".qoder/skills"),
    ("kiro", ".kiro/skills"),
    ("lingma", ".lingma/skills"),
    ("trae", ".trae/skills"),
]


@dataclass
class AgentDir:
    """一个被发现的 Agent skills 目录。"""

    name: str
    path: Path
    exists: bool
    is_custom: bool


@dataclass
class AgentSyncState:
    """某个 skill 在某个 agent 目录中的同步状态。"""

    agent_name: str
    mode: str  # symlink / copy / none
    state: str  # linked / synced / local_changes / external_changes / conflict / missing / unmanaged
    hash: str
    path: str


@dataclass
class SkillStatus:
    """某个 skill 的整体同步状态（含各 agent 的明细）。"""

    skill_name: str
    central_hash: str
    agents: list[AgentSyncState] = field(default_factory=list)


@dataclass
class SyncResult:
    """一次同步操作的结果。"""

    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# ── 状态文件读写 ────────────────────────────────────────────────────


def state_file() -> Path:
    """返回 skill sync 状态文件路径（位于 Hermes state 目录下）。"""
    return get_settings().hermes_state_dir / "skill_sync.json"


def load_sync_state() -> dict[str, Any]:
    """从 .state/skill_sync.json 加载状态；文件不存在或损坏时返回空结构。"""
    f = state_file()
    if not f.exists():
        return {"managed_skills": {}, "custom_agents": {}}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"managed_skills": {}, "custom_agents": {}}
    if not isinstance(data, dict):
        return {"managed_skills": {}, "custom_agents": {}}
    data.setdefault("managed_skills", {})
    data.setdefault("custom_agents", {})
    return data


def save_sync_state(state: dict[str, Any]) -> None:
    """保存状态到 .state/skill_sync.json。"""
    f = state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 发现与哈希 ──────────────────────────────────────────────────────


def discover_agent_dirs(custom_agents: dict[str, str] | None = None) -> list[AgentDir]:
    """自动发现常见 Agent 目录，合并自定义 agent 目录，返回存在的目录列表。"""
    home = Path.home()
    seen: set[Path] = set()
    result: list[AgentDir] = []

    for name, rel in KNOWN_AGENT_DIRS:
        path = home / rel
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            result.append(AgentDir(name=name, path=path, exists=True, is_custom=False))

    if custom_agents:
        for name, raw in custom_agents.items():
            path = Path(raw).expanduser()
            if path in seen:
                continue
            seen.add(path)
            result.append(
                AgentDir(name=name, path=path, exists=path.exists(), is_custom=True)
            )

    return result


def compute_hash(path: Path) -> str:
    """递归计算目录（或文件）的 SHA256 哈希，基于内容且确定性可重复。"""
    if not path.exists():
        return ""

    if path.is_file():
        return _hash_file(path)

    h = hashlib.sha256()
    files = sorted(
        (p for p in path.rglob("*") if p.is_file()),
        key=lambda p: str(p.relative_to(path)),
    )
    for f in files:
        # 把相对路径纳入哈希，避免同名内容不同位置被误判一致
        h.update(f.relative_to(path).as_posix().encode("utf-8"))
        h.update(_hash_file(f).encode("ascii"))
    return h.hexdigest()


def _hash_file(path: Path) -> str:
    """计算单个文件的 SHA256。"""
    h = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ── 状态判定 ────────────────────────────────────────────────────────


def _resolve_link(link_path: Path) -> Path:
    """解析 symlink 目标为绝对路径（相对目标基于 link 所在目录解析）。"""
    target = Path(os.readlink(link_path))
    if not target.is_absolute():
        target = link_path.parent / target
    return target.resolve()


def get_sync_state(
    skill_name: str, agent_dir: AgentDir, managed_info: dict[str, Any] | None
) -> AgentSyncState:
    """判断 skill 在某个 agent 目录的状态。

    - linked: symlink 指向中心仓库
    - synced: copy 模式，哈希与记录一致
    - local_changes: 中心仓库有改动
    - external_changes: agent 目录有改动
    - conflict: 双方都有改动
    - missing: agent 目录中不存在
    - unmanaged: 未纳入管理但 agent 目录中存在副本
    """
    central_path = skills_dir() / skill_name
    skill_path = agent_dir.path / skill_name
    mode = managed_info.get("mode", "symlink") if managed_info else "none"

    # 已是指向中心仓库的 symlink → linked
    if skill_path.is_symlink():
        try:
            if _resolve_link(skill_path) == central_path.resolve():
                return AgentSyncState(
                    agent_name=agent_dir.name,
                    mode="symlink",
                    state="linked",
                    hash=compute_hash(skill_path),
                    path=str(skill_path),
                )
        except OSError:
            pass

    # agent 目录中不存在 → missing
    if not skill_path.exists():
        return AgentSyncState(
            agent_name=agent_dir.name,
            mode=mode,
            state="missing",
            hash="",
            path=str(skill_path),
        )

    agent_hash = compute_hash(skill_path)

    # 未纳入管理但存在副本 → unmanaged
    if managed_info is None:
        return AgentSyncState(
            agent_name=agent_dir.name,
            mode="none",
            state="unmanaged",
            hash=agent_hash,
            path=str(skill_path),
        )

    # copy 模式：比对中心与 agent 各自相对记录哈希的变化
    recorded = managed_info.get("agents", {}).get(agent_dir.name, {})
    recorded_agent_hash = (
        recorded.get("hash", "") if isinstance(recorded, dict) else ""
    )
    recorded_central_hash = managed_info.get("central_hash", "")
    current_central_hash = compute_hash(central_path) if central_path.exists() else ""

    central_changed = (
        recorded_central_hash != "" and current_central_hash != recorded_central_hash
    )
    agent_changed = recorded_agent_hash != "" and agent_hash != recorded_agent_hash

    if central_changed and agent_changed:
        st = "conflict"
    elif central_changed:
        st = "local_changes"
    elif agent_changed:
        st = "external_changes"
    else:
        st = "synced"

    return AgentSyncState(
        agent_name=agent_dir.name,
        mode=mode,
        state=st,
        hash=agent_hash,
        path=str(skill_path),
    )


# ── 同步操作 ────────────────────────────────────────────────────────


def add_skill(skill_name: str, copy: bool = False) -> SyncResult:
    """将 skill 纳入同步管理，分发到所有已发现的 agent 目录。"""
    central = skills_dir()
    central_path = central / skill_name
    if not central_path.exists() or not central_path.is_dir():
        return SyncResult(
            False, f"Skill '{skill_name}' not found in central repo {central}"
        )

    mode = "copy" if copy else "symlink"
    central_hash = compute_hash(central_path)
    state = load_sync_state()
    managed = state.setdefault("managed_skills", {})
    agents_record: dict[str, Any] = {}
    errors: list[str] = []

    for ad in discover_agent_dirs(state.get("custom_agents", {})):
        if not ad.exists:
            continue
        dest = ad.path / skill_name
        try:
            if mode == "symlink":
                if dest.is_symlink():
                    # 已是指向中心的 symlink：幂等跳过
                    try:
                        already = _resolve_link(dest) == central_path.resolve()
                    except OSError:
                        already = False
                    if already:
                        agents_record[ad.name] = {
                            "path": str(dest),
                            "hash": central_hash,
                        }
                        continue
                    errors.append(f"{ad.name}: existing symlink to elsewhere, skipped")
                    continue
                if dest.exists():
                    errors.append(f"{ad.name}: existing content, skipped")
                    continue
                os.symlink(central_path, dest)
                agents_record[ad.name] = {"path": str(dest), "hash": central_hash}
            else:  # copy
                if dest.is_symlink():
                    os.unlink(dest)
                    shutil.copytree(central_path, dest)
                    agents_record[ad.name] = {"path": str(dest), "hash": central_hash}
                    continue
                if dest.exists():
                    errors.append(f"{ad.name}: existing content, skipped")
                    continue
                shutil.copytree(central_path, dest)
                agents_record[ad.name] = {"path": str(dest), "hash": central_hash}
        except OSError as exc:
            errors.append(f"{ad.name}: {exc}")

    managed[skill_name] = {
        "central_hash": central_hash,
        "mode": mode,
        "agents": agents_record,
    }
    save_sync_state(state)

    return SyncResult(
        True,
        f"Skill '{skill_name}' added ({mode}) to {len(agents_record)} agent(s)",
        {"agents": list(agents_record.keys()), "errors": errors, "mode": mode},
    )


def add_all_skills(copy: bool = False) -> SyncResult:
    """将中心仓库中所有 skill 纳入同步管理。"""
    central = skills_dir()
    if not central.exists():
        return SyncResult(False, f"Central skills dir not found: {central}")
    names = sorted(p.name for p in central.iterdir() if p.is_dir())
    if not names:
        return SyncResult(False, f"No skills found in {central}")

    added: list[str] = []
    errors: list[str] = []
    for name in names:
        r = add_skill(name, copy=copy)
        if r.success:
            added.append(name)
        else:
            errors.append(f"{name}: {r.message}")
    return SyncResult(
        True,
        f"Added {len(added)}/{len(names)} skills",
        {"added": added, "errors": errors},
    )


def remove_skill(skill_name: str) -> SyncResult:
    """取消 skill 的同步管理。

    symlink 模式：删除各 agent 中的 symlink（保留中心仓库）。
    copy 模式：把中心仓库最新内容复制回各 agent 目录后删除中心仓库副本。
    """
    state = load_sync_state()
    managed = state.get("managed_skills", {})
    if skill_name not in managed:
        return SyncResult(False, f"Skill '{skill_name}' is not managed")

    info = managed[skill_name]
    mode = info.get("mode", "symlink")
    agents = info.get("agents", {})
    central_path = skills_dir() / skill_name
    errors: list[str] = []

    for agent_name, arec in agents.items():
        dest = Path(arec.get("path", "")) if isinstance(arec, dict) else Path("")
        try:
            if mode == "symlink":
                if dest.is_symlink():
                    os.unlink(dest)
            else:  # copy: 用中心最新内容覆盖/恢复 agent 副本
                if central_path.exists():
                    if dest.is_symlink():
                        os.unlink(dest)
                        shutil.copytree(central_path, dest)
                    elif dest.exists() and dest.is_dir():
                        shutil.rmtree(dest)
                        shutil.copytree(central_path, dest)
                    else:
                        shutil.copytree(central_path, dest)
        except OSError as exc:
            errors.append(f"{agent_name}: {exc}")

    # copy 模式：所有 agent 已拿到最终副本，删除中心仓库副本
    if mode == "copy" and central_path.exists():
        try:
            shutil.rmtree(central_path)
        except OSError as exc:
            errors.append(f"central: {exc}")

    del managed[skill_name]
    save_sync_state(state)
    return SyncResult(
        True,
        f"Skill '{skill_name}' removed ({mode})",
        {"errors": errors, "mode": mode},
    )


def remove_all_skills() -> SyncResult:
    """取消所有 managed skill 的同步管理。"""
    state = load_sync_state()
    managed = state.get("managed_skills", {})
    names = list(managed.keys())
    if not names:
        return SyncResult(False, "No managed skills to remove")

    removed: list[str] = []
    errors: list[str] = []
    for name in names:
        r = remove_skill(name)
        if r.success:
            removed.append(name)
        else:
            errors.append(f"{name}: {r.message}")
    return SyncResult(
        True,
        f"Removed {len(removed)} skill(s)",
        {"removed": removed, "errors": errors},
    )


def sync_skill(skill_name: str | None = None) -> SyncResult:
    """同步中心仓库改动到所有 agent。

    skill_name=None 时同步所有 managed skill。
    symlink 模式：实时同步，仅修复缺失/损坏的 symlink 并刷新哈希记录。
    copy 模式：重新复制中心内容到 agent（跳过 external_changes/conflict 以免覆盖用户改动）。
    """
    state = load_sync_state()
    managed = state.get("managed_skills", {})

    if skill_name is None:
        names = list(managed.keys())
    else:
        if skill_name not in managed:
            return SyncResult(False, f"Skill '{skill_name}' is not managed")
        names = [skill_name]

    if not names:
        return SyncResult(False, "No managed skills to sync")

    synced: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for name in names:
        info = managed[name]
        mode = info.get("mode", "symlink")
        central_path = skills_dir() / name
        if not central_path.exists():
            errors.append(f"{name}: central skill missing")
            continue
        central_hash = compute_hash(central_path)
        agents = info.get("agents", {})

        for agent_name, arec in agents.items():
            dest = Path(arec.get("path", "")) if isinstance(arec, dict) else Path("")
            try:
                if mode == "symlink":
                    need_create = True
                    if dest.is_symlink():
                        try:
                            if _resolve_link(dest) == central_path.resolve():
                                need_create = False
                            else:
                                os.unlink(dest)
                        except OSError:
                            os.unlink(dest)
                    elif dest.exists():
                        # 真实内容，不覆盖
                        skipped.append(f"{name}/{agent_name}")
                        continue
                    if need_create:
                        os.symlink(central_path, dest)
                    agents[agent_name] = {"path": str(dest), "hash": central_hash}
                else:  # copy
                    # 存在 external 改动/冲突时跳过，避免覆盖用户修改
                    if dest.parent.exists():
                        ad = AgentDir(agent_name, dest.parent, True, False)
                        st_obj = get_sync_state(name, ad, info)
                        if st_obj.state in ("conflict", "external_changes"):
                            skipped.append(f"{name}/{agent_name} ({st_obj.state})")
                            continue
                    if dest.is_symlink():
                        os.unlink(dest)
                        shutil.copytree(central_path, dest)
                    elif dest.exists() and dest.is_dir():
                        shutil.rmtree(dest)
                        shutil.copytree(central_path, dest)
                    else:
                        shutil.copytree(central_path, dest)
                    agents[agent_name] = {"path": str(dest), "hash": central_hash}
            except OSError as exc:
                errors.append(f"{name}/{agent_name}: {exc}")

        info["central_hash"] = central_hash
        info["agents"] = agents
        synced.append(name)

    save_sync_state(state)
    return SyncResult(
        True,
        f"Synced {len(synced)} skill(s)",
        {"synced": synced, "skipped": skipped, "errors": errors},
    )


def get_status() -> list[SkillStatus]:
    """返回所有 managed skill 及未管理 skill 的状态总览。"""
    state = load_sync_state()
    managed = state.get("managed_skills", {})
    custom = state.get("custom_agents", {})
    central = skills_dir()
    result: list[SkillStatus] = []

    # managed skill
    for name, info in managed.items():
        central_path = central / name
        chash = compute_hash(central_path) if central_path.exists() else ""
        agents = [
            get_sync_state(name, ad, info) for ad in discover_agent_dirs(custom)
        ]
        result.append(
            SkillStatus(skill_name=name, central_hash=chash, agents=agents)
        )

    # 中心仓库中存在但未纳入管理的 skill
    if central.exists():
        for entry in sorted(central.iterdir()):
            if not entry.is_dir() or entry.name in managed:
                continue
            chash = compute_hash(entry)
            agents = [
                get_sync_state(entry.name, ad, None) for ad in discover_agent_dirs(custom)
            ]
            result.append(
                SkillStatus(skill_name=entry.name, central_hash=chash, agents=agents)
            )

    return result


def add_custom_agent(name: str, path: str) -> SyncResult:
    """添加自定义 agent 目录到发现列表，持久化到状态文件。"""
    state = load_sync_state()
    custom = state.setdefault("custom_agents", {})
    custom[name] = path
    save_sync_state(state)
    exists = Path(path).expanduser().exists()
    return SyncResult(
        True,
        f"Custom agent '{name}' added at {path}",
        {"exists": exists},
    )

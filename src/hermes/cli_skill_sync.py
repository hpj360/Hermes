"""Skill Sync CLI subcommands.

Exposes the Local-mode Skill Sync functions (status/agents/add/remove/sync/
add-agent) as `hermes skill-sync <sub>` commands.

Design (mirrors cli_loop.py):
- Thin wrappers: each cmd_* function calls the underlying skill_sync function,
  formats the result for human reading, and returns an exit code.
- --json flag on data-returning commands for machine consumption.
- Exit codes: 0=success, 1=soft fail, 2=hard error (raised exceptions → main).
- No business logic here — all logic lives in skill_sync.py.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any

from hermes.skill_sync import (
    SyncResult,
    add_all_skills,
    add_custom_agent,
    add_skill,
    discover_agent_dirs,
    get_status,
    load_sync_state,
    remove_all_skills,
    remove_skill,
    sync_skill,
)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _exit_code(result: SyncResult) -> int:
    """Map a SyncResult to exit code. 0=success, 1=soft fail."""
    return 0 if result.success else 1


def _emit(result: SyncResult, args: argparse.Namespace) -> int:
    """统一的 SyncResult 输出处理：JSON 或人类可读，附错误明细。"""
    if args.json:
        _print_json(asdict(result))
        return _exit_code(result)

    if not result.success:
        print(f"Error: {result.message}")
        return 1

    print(result.message)
    errors = result.details.get("errors") or []
    for e in errors:
        print(f"  ! {e}")
    return 0


# ── Command handlers ────────────────────────────────────────────────


def cmd_skill_sync_status(args: argparse.Namespace) -> int:
    """状态总览（默认子命令）。"""
    statuses = get_status()
    if args.json:
        _print_json(
            [
                {
                    "skill_name": s.skill_name,
                    "central_hash": s.central_hash,
                    "agents": [asdict(a) for a in s.agents],
                }
                for s in statuses
            ]
        )
        return 0

    if not statuses:
        print("No skills found in central repo.")
        return 0

    print(f"Skill Sync status ({len(statuses)} skills):")
    for s in statuses:
        chash = s.central_hash[:8] if s.central_hash else "-"
        print(f"  {s.skill_name}  central={chash}")
        if not s.agents:
            print("    (no agent directories discovered)")
        for a in s.agents:
            print(f"    [{a.state:<16}] {a.agent_name:<14} mode={a.mode}")
    return 0


def cmd_skill_sync_agents(args: argparse.Namespace) -> int:
    """列出发现的 Agent 目录。"""
    custom = load_sync_state().get("custom_agents", {})
    dirs = discover_agent_dirs(custom)

    if args.json:
        _print_json(
            [
                {
                    "name": d.name,
                    "path": str(d.path),
                    "exists": d.exists,
                    "is_custom": d.is_custom,
                }
                for d in dirs
            ]
        )
        return 0

    if not dirs:
        print("No agent directories discovered.")
        print("Add one with: hermes skill-sync add-agent <name> <path>")
        return 0

    print(f"Discovered agent directories ({len(dirs)}):")
    for d in dirs:
        mark = "*" if d.is_custom else " "
        suffix = "" if d.exists else " (missing)"
        print(f"  {mark} {d.name:<16} {d.path}{suffix}")
    return 0


def cmd_skill_sync_add(args: argparse.Namespace) -> int:
    """添加到同步管理。"""
    if args.all:
        result = add_all_skills(copy=args.copy)
    elif args.skill:
        result = add_skill(args.skill, copy=args.copy)
    else:
        print("Error: provide a skill name or use --all")
        return 2
    return _emit(result, args)


def cmd_skill_sync_remove(args: argparse.Namespace) -> int:
    """取消同步。"""
    if args.all:
        result = remove_all_skills()
    elif args.skill:
        result = remove_skill(args.skill)
    else:
        print("Error: provide a skill name or use --all")
        return 2
    return _emit(result, args)


def cmd_skill_sync_sync(args: argparse.Namespace) -> int:
    """执行同步。"""
    result = sync_skill(args.skill)
    if args.json:
        _print_json(asdict(result))
        return _exit_code(result)

    if not result.success:
        print(f"Error: {result.message}")
        return 1

    print(result.message)
    for key in ("synced", "skipped", "errors"):
        items = result.details.get(key) or []
        for item in items:
            prefix = {"synced": "  +", "skipped": "  ~", "errors": "  !"}[key]
            print(f"{prefix} {item}")
    return 0


def cmd_skill_sync_add_agent(args: argparse.Namespace) -> int:
    """添加自定义 Agent 目录。"""
    result = add_custom_agent(args.name, args.path)
    return _emit(result, args)


# ── Subparser registration ──────────────────────────────────────────


def add_skill_sync_subparser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `hermes skill-sync <sub>` commands on the top-level subparsers."""
    p = sub.add_parser(
        "skill-sync", help="Skill Sync: manage skills across agent directories"
    )
    # 无子命令时默认进入 status
    p.set_defaults(func=cmd_skill_sync_status, json=False)
    ss = p.add_subparsers(dest="skill_sync_cmd", required=False)

    # status
    p_status = ss.add_parser("status", help="Show sync status overview")
    p_status.add_argument("--json", action="store_true", help="Output JSON")
    p_status.set_defaults(func=cmd_skill_sync_status)

    # agents
    p_agents = ss.add_parser("agents", help="List discovered agent directories")
    p_agents.add_argument("--json", action="store_true", help="Output JSON")
    p_agents.set_defaults(func=cmd_skill_sync_agents)

    # add
    p_add = ss.add_parser("add", help="Add a skill to sync management")
    p_add.add_argument("skill", nargs="?", default=None, help="Skill name")
    p_add.add_argument("--all", action="store_true", help="Add all central skills")
    p_add.add_argument(
        "--copy", action="store_true", help="Use copy mode instead of symlink"
    )
    p_add.add_argument("--json", action="store_true", help="Output JSON")
    p_add.set_defaults(func=cmd_skill_sync_add)

    # remove
    p_rm = ss.add_parser("remove", help="Remove a skill from sync management")
    p_rm.add_argument("skill", nargs="?", default=None, help="Skill name")
    p_rm.add_argument("--all", action="store_true", help="Remove all managed skills")
    p_rm.add_argument("--json", action="store_true", help="Output JSON")
    p_rm.set_defaults(func=cmd_skill_sync_remove)

    # sync
    p_sync = ss.add_parser("sync", help="Sync central changes to agents")
    p_sync.add_argument("skill", nargs="?", default=None, help="Skill name (omit for all)")
    p_sync.add_argument("--json", action="store_true", help="Output JSON")
    p_sync.set_defaults(func=cmd_skill_sync_sync)

    # add-agent
    p_aa = ss.add_parser("add-agent", help="Add a custom agent directory")
    p_aa.add_argument("name", help="Agent name")
    p_aa.add_argument("path", help="Path to agent skills directory")
    p_aa.add_argument("--json", action="store_true", help="Output JSON")
    p_aa.set_defaults(func=cmd_skill_sync_add_agent)

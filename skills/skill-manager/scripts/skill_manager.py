#!/usr/bin/env python3
"""Skill Manager - 已安装 skill 的薄包装入口。

本脚本不含任何业务逻辑，只把旧的/友好的子命令名映射到 Hermes 的真实 CLI：

    skill-manager 命令              →  实际 Hermes 命令
    -----------------------------   →  -----------------------------
    list / status                   →  hermes skill-sync status
    agents                          →  hermes skill-sync agents
    search <query>                  →  hermes skills remote（目录，无过滤）
    install <name> [--source]       →  hermes skills install <name>
    uninstall <name>                →  hermes skill-sync remove <name>
    update [name] / sync [name]     →  hermes skill-sync sync [name]
    add <name|--all> [--copy]       →  hermes skill-sync add ...
    remove <name|--all>             →  hermes skill-sync remove ...
    add-agent <name> <path>         →  hermes skill-sync add-agent ...

真实能力（单一信源）位于 `hermes skill-sync`（跨 Agent 目录同步）与
`hermes skills`（marketplace：安装/打包/目录），见 SKILL.md。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """skill_manager.py 位于 <repo>/skills/skill-manager/scripts/ 下。"""
    return Path(__file__).resolve().parents[3]


def _resolve_hermes() -> list[str]:
    """定位 hermes CLI：仓库零安装入口 → venv console script → PATH。"""
    root = _repo_root()

    entry = root / "hermes"
    if entry.is_file() and os.access(entry, os.X_OK):
        return [str(entry)]

    suffix = "Scripts/hermes.exe" if os.name == "nt" else "bin/hermes"
    venv = root / ".venv" / suffix
    if venv.exists():
        return [str(venv)]

    which = shutil.which("hermes")
    if which:
        return [which]

    return []


def _forward(args: list[str]) -> int:
    hermes = _resolve_hermes()
    if not hermes:
        print(
            "Error: hermes CLI not found. 在仓库根目录运行 `bash scripts/bootstrap.sh` 引导。",
            file=sys.stderr,
        )
        return 2
    return subprocess.call([*hermes, *args])


# ── 子命令映射 ──────────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    return _forward(["skill-sync", "status"])


def cmd_status(args: argparse.Namespace) -> int:
    return _forward(["skill-sync", "status"])


def cmd_agents(args: argparse.Namespace) -> int:
    return _forward(["skill-sync", "agents"])


def cmd_search(args: argparse.Namespace) -> int:
    if args.query:
        print(
            "Note: 本地 registry 目录不支持关键词过滤，展示全部条目。",
            file=sys.stderr,
        )
    return _forward(["skills", "remote"])


def cmd_install(args: argparse.Namespace) -> int:
    argv = ["skills", "install", args.slug]
    if args.source:
        argv += ["--source", args.source]
    if args.force:
        argv.append("--force")
    return _forward(argv)


def cmd_uninstall(args: argparse.Namespace) -> int:
    return _forward(["skill-sync", "remove", args.slug])


def cmd_update(args: argparse.Namespace) -> int:
    argv = ["skill-sync", "sync"]
    if args.slug:
        argv.append(args.slug)
    return _forward(argv)


def cmd_sync(args: argparse.Namespace) -> int:
    argv = ["skill-sync", "sync"]
    if args.slug:
        argv.append(args.slug)
    return _forward(argv)


def cmd_add(args: argparse.Namespace) -> int:
    argv = ["skill-sync", "add"]
    if args.all:
        argv.append("--all")
    elif args.slug:
        argv.append(args.slug)
    else:
        print("Error: provide a skill name or use --all", file=sys.stderr)
        return 2
    if args.copy:
        argv.append("--copy")
    return _forward(argv)


def cmd_remove(args: argparse.Namespace) -> int:
    argv = ["skill-sync", "remove"]
    if args.all:
        argv.append("--all")
    elif args.slug:
        argv.append(args.slug)
    else:
        print("Error: provide a skill name or use --all", file=sys.stderr)
        return 2
    return _forward(argv)


def cmd_add_agent(args: argparse.Namespace) -> int:
    return _forward(["skill-sync", "add-agent", args.name, args.path])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Skill Manager（转发到 hermes skill-sync / hermes skills）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出所有 skill 及其同步状态").set_defaults(func=cmd_list)
    sub.add_parser("status", help="同步状态总览").set_defaults(func=cmd_status)
    sub.add_parser("agents", help="列出发现的 Agent 目录").set_defaults(func=cmd_agents)

    p_search = sub.add_parser("search", help="列出 registry 目录")
    p_search.add_argument("query", nargs="*", help="搜索关键词（本地目录不支持过滤）")
    p_search.set_defaults(func=cmd_search)

    p_install = sub.add_parser("install", help="从 registry/source 安装 skill")
    p_install.add_argument("slug", help="skill 名称")
    p_install.add_argument("--source", default=None, help="git URL / 本地路径 / zip URL")
    p_install.add_argument("--force", action="store_true", help="覆盖已安装 skill")
    p_install.set_defaults(func=cmd_install)

    p_uninstall = sub.add_parser("uninstall", help="取消 skill 跨 Agent 同步")
    p_uninstall.add_argument("slug", help="skill 名称")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_update = sub.add_parser("update", help="同步中心改动到 Agent（缺省同步全部）")
    p_update.add_argument("slug", nargs="?", default=None, help="skill 名称")
    p_update.set_defaults(func=cmd_update)

    p_sync = sub.add_parser("sync", help="同步中心改动到 Agent")
    p_sync.add_argument("slug", nargs="?", default=None, help="skill 名称")
    p_sync.set_defaults(func=cmd_sync)

    p_add = sub.add_parser("add", help="将 skill 纳入同步管理")
    p_add.add_argument("slug", nargs="?", default=None, help="skill 名称")
    p_add.add_argument("--all", action="store_true", help="纳入全部中心 skill")
    p_add.add_argument("--copy", action="store_true", help="用 copy 而非 symlink")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="取消 skill 的同步管理")
    p_remove.add_argument("slug", nargs="?", default=None, help="skill 名称")
    p_remove.add_argument("--all", action="store_true", help="取消全部 managed skill")
    p_remove.set_defaults(func=cmd_remove)

    p_add_agent = sub.add_parser("add-agent", help="添加自定义 Agent 目录")
    p_add_agent.add_argument("name", help="Agent 名称")
    p_add_agent.add_argument("path", help="Agent skills 目录路径")
    p_add_agent.set_defaults(func=cmd_add_agent)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
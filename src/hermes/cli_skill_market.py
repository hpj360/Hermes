"""Skill marketplace CLI subcommands (`hermes skills install/pack/remote`).

Thin wrappers over :mod:`hermes.skill_market` (P3-4), following the cli_secrets /
cli_skill_sync style: no business logic here, just argument handling, output
formatting, and exit codes (0=success, 1=soft fail, 2=hard error via main).
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from hermes.skill_market import install_skill, list_registry, pack_skill


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _emit(result: Any, args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        _print_json({"success": result.success, "message": result.message, **result.details})
        return 0 if result.success else 1
    if not result.success:
        print(f"Error: {result.message}")
        return 1
    print(result.message)
    return 0


# ── Command handlers ────────────────────────────────────────────────


def cmd_skills_install(args: argparse.Namespace) -> int:
    """Install a skill from the registry or an explicit source."""
    result = install_skill(args.name, source=args.source, force=args.force)
    return _emit(result, args)


def cmd_skills_pack(args: argparse.Namespace) -> int:
    """Pack a skill into a versioned zip for distribution."""
    from pathlib import Path

    result = pack_skill(args.name, output_dir=Path(args.output) if args.output else None)
    if args.json:
        _print_json({"success": result.success, "message": result.message, **result.details})
        return 0 if result.success else 1
    if not result.success:
        print(f"Error: {result.message}")
        return 1
    print(result.message)
    print(f"  archive: {result.details.get('archive')}")
    return 0


def cmd_skills_remote(args: argparse.Namespace) -> int:
    """List the registry catalog (vendored + remote merged)."""
    registry = list_registry()
    if args.json:
        _print_json({"count": len(registry), "skills": registry})
        return 0
    if not registry:
        print("Registry is empty. Add entries to skills/registry.json or set HERMES_SKILL_REGISTRY.")
        return 0
    print(f"Skill registry ({len(registry)}):")
    for name in sorted(registry):
        entry = registry[name]
        version = entry.get("version", "")
        desc = entry.get("description", "")
        line = f"  {name}"
        if version:
            line += f"  v{version}"
        if desc:
            line += f"  - {desc}"
        print(line)
    return 0


# ── Subparser registration ──────────────────────────────────────────


def add_skill_market_subcommands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `hermes skills install/pack/remote` onto the ``skills`` subparsers."""
    p_install = sub.add_parser("install", help="Install a skill from registry or source")
    p_install.add_argument("name", help="Skill name")
    p_install.add_argument(
        "--source",
        default=None,
        help="git URL / local path / zip URL (bypass the registry)",
    )
    p_install.add_argument("--force", action="store_true", help="Overwrite existing skill")
    p_install.add_argument("--json", action="store_true", help="Output JSON")
    p_install.set_defaults(func=cmd_skills_install)

    p_pack = sub.add_parser("pack", help="Pack a skill into a versioned zip")
    p_pack.add_argument("name", help="Skill name")
    p_pack.add_argument("--output", default=None, help="Output directory (default: cache dir)")
    p_pack.add_argument("--json", action="store_true", help="Output JSON")
    p_pack.set_defaults(func=cmd_skills_pack)

    p_remote = sub.add_parser("remote", help="List the skill registry catalog")
    p_remote.add_argument("--json", action="store_true", help="Output JSON")
    p_remote.set_defaults(func=cmd_skills_remote)

"""Hermes CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from hermes.config import get_settings
from hermes.logging import setup_logging
from hermes.profile import get_profile_markdown, load_profile
from hermes.skills import (
    SkillStatus,
    add_agent_target,
    add_all_skills,
    add_skill,
    discover_agents,
    discover_skills,
    knowledge_dir,
    list_knowledge_docs,
    refresh_status,
    remove_skill,
    resolve_conflict,
    skills_dir,
    sync_skills,
)


def cmd_start(args: argparse.Namespace) -> int:
    logger = logging.getLogger("hermes")
    settings = get_settings()
    logger.info("Hermes started")
    logger.info("Project root: %s", settings.hermes_project_root)
    logger.info("Main repo path: %s", settings.hermes_main_repo_path)
    logger.info("Primary model: %s", settings.openclaw_model_primary)
    logger.info("Configured providers: %s", ", ".join(settings.configured_providers()) or "(none)")
    logger.info("State dir: %s", settings.hermes_state_dir)
    logger.info("Cache dir: %s", settings.hermes_cache_dir)
    return 0


def cmd_skills_list(args: argparse.Namespace) -> int:
    skills = discover_skills()
    if not skills:
        print(f"No skills found in {skills_dir()}")
        return 0
    print(f"Installed skills ({len(skills)}):")
    for s in skills:
        meta_desc = ""
        if s.meta and isinstance(s.meta, dict):
            meta_desc = s.meta.get("description", "") or ""
        flags = []
        flags.append("md" if s.has_skill_md else "  ")
        flags.append("meta" if s.has_meta else "    ")
        status_marker = {
            SkillStatus.LINKED: "🔗",
            SkillStatus.SYNCED: "✓",
            SkillStatus.SYNCED: "✓",
            SkillStatus.LOCAL_CHANGES: "✏️",
            SkillStatus.EXTERNAL_CHANGES: "📥",
            SkillStatus.CONFLICT: "⚠️",
            SkillStatus.MISSING: "❌",
            SkillStatus.UNMANAGED: "○",
        }.get(s.status, " ")
        line = f"  [{ '|'.join(flags) }] {status_marker} {s.name}"
        if meta_desc:
            line += f"  - {meta_desc[:60]}"
        if s.status != SkillStatus.UNMANAGED and s.synced_agents:
            line += f"  → {','.join(s.synced_agents[:3])}"
        print(line)
    return 0


def cmd_knowledge_list(args: argparse.Namespace) -> int:
    docs = list_knowledge_docs()
    if not docs:
        print(f"No knowledge docs found in {knowledge_dir()}")
        return 0
    print(f"Knowledge documents ({len(docs)}):")
    for d in docs:
        print(f"  - {d.name}")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    settings = get_settings()
    print("[paths]")
    print(f"  project_root      = {settings.hermes_project_root}")
    print(f"  main_repo_path    = {settings.hermes_main_repo_path}")
    print(f"  state_dir         = {settings.hermes_state_dir}")
    print(f"  cache_dir         = {settings.hermes_cache_dir}")
    print(f"  skills_dir        = {skills_dir()}")
    print(f"  knowledge_dir     = {knowledge_dir()}")
    print()
    print("[models]")
    print(f"  primary           = {settings.openclaw_model_primary}")
    print(f"  fallback          = {settings.openclaw_model_fallback}")
    print(f"  providers_ready   = {', '.join(settings.configured_providers()) or '(none)'}")
    print()
    print("[gateway]")
    print(f"  gateway_port      = {settings.openclaw_gateway_port}")
    print(f"  gateway_token     = {'set' if settings.openclaw_gateway_token else 'unset'}")
    print()
    print("[channels]")
    print(f"  slack_bot_token   = {'set' if settings.slack_bot_token else 'unset'}")
    print(f"  slack_app_token   = {'set' if settings.slack_app_token else 'unset'}")
    print(f"  telegram_token    = {'set' if settings.telegram_bot_token else 'unset'}")
    print(f"  discord_token     = {'set' if settings.discord_bot_token else 'unset'}")
    print(f"  feishu_app_id     = {'set' if settings.feishu_app_id else 'unset'}")
    print()
    print("[tools]")
    print(f"  brave_api_key     = {'set' if settings.brave_api_key else 'unset'}")
    print(f"  tavily_api_key    = {'set' if settings.tavily_api_key else 'unset'}")
    print(f"  perplexity_key    = {'set' if settings.perplexity_api_key else 'unset'}")
    print(f"  firecrawl_key     = {'set' if settings.firecrawl_api_key else 'unset'}")
    print(f"  github_token      = {'set' if settings.github_token else 'unset'}")
    print(f"  notion_api_key    = {'set' if settings.notion_api_key else 'unset'}")
    print(f"  trello_key/token  = {settings.trello_api_key and settings.trello_api_token and 'set' or 'unset'}")
    print()
    print("[skillhub]")
    print(f"  api_base          = {settings.skillhub_api_base}")
    print(f"  cos_bucket        = {settings.skillhub_cos_bucket}")
    print(f"  cos_region        = {settings.skillhub_cos_region}")
    return 0


def cmd_profile_show(args: argparse.Namespace) -> int:
    profile = load_profile()
    if args.json:
        import json
        print(json.dumps(profile, ensure_ascii=False, indent=2))
    else:
        print(get_profile_markdown())
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run health checks on the Hermes environment (degraded-friendly)."""
    settings = get_settings()
    issues: list[str] = []
    warnings: list[str] = []

    if not settings.hermes_project_root.exists():
        issues.append(f"Project root missing: {settings.hermes_project_root}")
    if not settings.hermes_main_repo_path.exists():
        warnings.append(f"Main repo path not found: {settings.hermes_main_repo_path}")

    providers = settings.configured_providers()
    if not providers:
        warnings.append("No LLM provider API keys configured; set at least one in .env")

    if not settings.openclaw_gateway_token:
        warnings.append("OPENCLAW_GATEWAY_TOKEN is unset (recommended for production)")

    skills_count = len(discover_skills())
    docs_count = len(list_knowledge_docs())
    refresh = refresh_status()
    managed_count = refresh.get("total", 0)

    print("=== Hermes Doctor ===")
    print(f"Python:          {sys.version.split()[0]}")
    print(f"Project root:    {settings.hermes_project_root}")
    print(f"Main repo path:  {settings.hermes_main_repo_path}")
    print(f"Skills total:    {skills_count}")
    print(f"Skills managed:  {managed_count} (Skill Sync)")
    print(f"Knowledge docs:  {docs_count}")
    print(f"Providers ready: {', '.join(providers) or '(none)'}")
    print()

    if warnings:
        print("[warnings]")
        for w in warnings:
            print(f"  ! {w}")
    if issues:
        print("[errors]")
        for e in issues:
            print(f"  X {e}")
        return 1

    if not warnings:
        print("All checks passed.")
    else:
        print("Doctor completed with warnings.")
    return 0


# ── Skill Sync commands ──────────────────────────────────────────────

def cmd_sync_status(args: argparse.Namespace) -> int:
    refresh = refresh_status()
    skills = discover_skills()
    agents = discover_agents()
    state_summary = refresh["summary"]

    print("=== Skill Sync Status ===")
    print("Mode:             local")
    print("Profile:          default")
    print(f"Managed skills:   {refresh['total']}")
    print()

    status_labels = [
        (SkillStatus.LINKED, "Linked (symlink)"),
        (SkillStatus.SYNCED, "Synced (copy)"),
        (SkillStatus.LOCAL_CHANGES, "Local changes"),
        (SkillStatus.EXTERNAL_CHANGES, "External changes"),
        (SkillStatus.CONFLICT, "Conflict"),
        (SkillStatus.MISSING, "Missing"),
    ]
    print("Status summary:")
    for status, label in status_labels:
        count = state_summary.get(status.value, 0)
        if count > 0:
            print(f"  {label}: {count}")
    unmanaged = sum(1 for s in skills if s.status == SkillStatus.UNMANAGED)
    if unmanaged > 0:
        print(f"  Unmanaged:  {unmanaged}")
    print()

    print("Discovered agent directories:")
    for a in agents:
        marker = "✓" if a.exists else " "
        link_marker = "🔗" if a.is_symlink else "  "
        print(f"  [{marker}] {link_marker} {a.name:20s} → {a.path}  ({a.skill_count} skills)")
    print()

    managed_skills = [s for s in skills if s.status != SkillStatus.UNMANAGED]
    if managed_skills:
        print("Managed skills:")
        print(f"  {'SKILL':25s} {'STATUS':18s} {'AGENTS':30s} {'NEXT ACTION'}")
        print(f"  {'─'*25} {'─'*18} {'─'*30} {'─'*30}")
        for s in managed_skills:
            agents_str = ",".join(s.synced_agents[:4])
            if len(s.synced_agents) > 4:
                agents_str += f"+{len(s.synced_agents)-4}"
            print(f"  {s.name:25s} {s.status.value:18s} {agents_str:30s} {s.next_action}")
    else:
        print("No skills are currently managed by Skill Sync.")
        print("Use `hermes skill-sync add <skill>` or `hermes skill-sync add --all` to start managing skills.")

    return 0


def cmd_sync_agents(args: argparse.Namespace) -> int:
    agents = discover_agents()
    print("Discovered agent directories:")
    print()
    for a in agents:
        status = "exists" if a.exists else "not found"
        link = " (symlink)" if a.is_symlink else ""
        print(f"  {a.name:20s} {status}{link}")
        print(f"    Path: {a.path}")
        if a.exists:
            print(f"    Skills: {a.skill_count}")
        print()
    return 0


def cmd_sync_add(args: argparse.Namespace) -> int:
    use_symlink = not args.copy

    if args.all:
        results = add_all_skills(use_symlink=use_symlink)
        success = sum(1 for r in results if r.get("success"))
        failed = len(results) - success
        print(f"Added {success} skills to sync management ({failed} skipped/failed)")
        for r in results:
            if r.get("success"):
                print(f"  ✓ {r['skill']} → {len(r['agents'])} agents ({r['mode']})")
            elif "error" in r:
                print(f"  ! {r['skill']}: {r['error']}")
        return 0 if failed == 0 else 1

    if not args.skill:
        print("Error: specify a skill name or use --all")
        return 1

    result = add_skill(args.skill, source=args.source, use_symlink=use_symlink)
    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        if "found_in" in result:
            print(f"Found existing skill in: {result['found_in']}")
            print(f"Run with: --source {result['found_in']} to import from there, or --source central")
        return 1

    print(f"✓ Skill '{result['skill']}' is now managed (mode: {result['mode']})")
    print(f"  Synced to agents: {', '.join(result['agents'])}")
    return 0


def cmd_sync_remove(args: argparse.Namespace) -> int:
    if args.all:
        from hermes.skills import _load_sync_state
        state = _load_sync_state()
        managed = list(state.get("managed_skills", {}).keys())
        for name in managed:
            remove_skill(name)
        print(f"Removed {len(managed)} skills from sync management")
        return 0

    result = remove_skill(args.skill)
    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1
    print(f"✓ Skill '{result['skill']}' removed from sync management")
    print("  Note: symlinks were removed; copies in agent directories were preserved (converted to standalone copies)")
    return 0


def cmd_sync_sync(args: argparse.Namespace) -> int:
    results = sync_skills(args.skill)
    success = sum(1 for r in results if r.get("success"))
    failed = len(results) - success
    print(f"Synced {success} skills ({failed} failed)")
    for r in results:
        if r.get("success"):
            print(f"  ✓ {r['skill']} → {', '.join(r['agents'])}")
        else:
            print(f"  ✗ {r['skill']}: {r.get('error', 'unknown error')}")
    return 0 if failed == 0 else 1


def cmd_sync_resolve(args: argparse.Namespace) -> int:
    result = resolve_conflict(args.skill, args.source)
    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1
    print(f"✓ Conflict resolved for '{result['skill']}'")
    print(f"  Using version from: {result['resolved_from']}")
    print(f"  Re-synced to: {', '.join(result['agents'])}")
    return 0


def cmd_sync_add_agent(args: argparse.Namespace) -> int:
    result = add_agent_target(args.name, args.path)
    print(f"{'✓' if result.exists else ' '} Added agent target: {result.name}")
    print(f"  Path: {result.path}")
    if not result.exists:
        print("  Note: directory does not exist yet (will be used when created)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes",
        description="Hermes Agent - independent agent layer with inherited config and Skill Sync",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level (default: from HERMES_LOG_LEVEL or INFO)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional file path to write logs to",
    )

    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("start", help="Start Hermes (default)").set_defaults(func=cmd_start)

    p_skills = sub.add_parser("skills", help="Manage installed skills")
    p_skills_sub = p_skills.add_subparsers(dest="skills_cmd", required=True)
    p_skills_sub.add_parser("list", help="List installed skills").set_defaults(func=cmd_skills_list)

    p_know = sub.add_parser("knowledge", help="List knowledge documents")
    p_know_sub = p_know.add_subparsers(dest="know_cmd", required=True)
    p_know_sub.add_parser("list", help="List knowledge docs").set_defaults(func=cmd_knowledge_list)

    p_cfg = sub.add_parser("config", help="Show effective configuration")
    p_cfg_sub = p_cfg.add_subparsers(dest="cfg_cmd", required=True)
    p_cfg_sub.add_parser("show", help="Print current configuration").set_defaults(func=cmd_config_show)

    sub.add_parser("doctor", help="Run environment health checks").set_defaults(func=cmd_doctor)

    p_profile = sub.add_parser("profile", help="View user profile")
    p_profile_sub = p_profile.add_subparsers(dest="profile_cmd", required=True)
    p_profile_show = p_profile_sub.add_parser("show", help="Show user profile")
    p_profile_show.add_argument("--json", action="store_true", help="Output raw JSON")
    p_profile_show.set_defaults(func=cmd_profile_show)

    # ── skill-sync subcommand ──────────────────────────────────────
    p_sync = sub.add_parser(
        "skill-sync",
        help="Manage Skill Sync (central repository + multi-agent distribution)",
        description="Skill Sync implements the Nacos Skill Sync pattern: maintain a single source of truth for skills, distribute to multiple agent directories via symlink or copy, track status, and resolve conflicts conservatively.",
    )
    p_sync_sub = p_sync.add_subparsers(dest="sync_cmd", required=True)

    p_sync_status = p_sync_sub.add_parser("status", help="Show sync status overview")
    p_sync_status.set_defaults(func=cmd_sync_status)

    p_sync_agents = p_sync_sub.add_parser("agents", help="List discovered agent directories")
    p_sync_agents.set_defaults(func=cmd_sync_agents)

    p_sync_add = p_sync_sub.add_parser("add", help="Add a skill to sync management")
    p_sync_add.add_argument("skill", nargs="?", help="Skill name to add")
    p_sync_add.add_argument("--all", action="store_true", help="Add all existing skills in central repo")
    p_sync_add.add_argument("--source", help="Source agent to import from (or 'central')")
    p_sync_add.add_argument("--copy", action="store_true", help="Use copy mode instead of symlink (default: symlink)")
    p_sync_add.set_defaults(func=cmd_sync_add)

    p_sync_remove = p_sync_sub.add_parser("remove", help="Remove a skill from sync management")
    p_sync_remove.add_argument("skill", nargs="?", help="Skill name to remove")
    p_sync_remove.add_argument("--all", action="store_true", help="Remove all skills from sync management")
    p_sync_remove.set_defaults(func=cmd_sync_remove)

    p_sync_do_sync = p_sync_sub.add_parser("sync", help="Push central changes out to all agents")
    p_sync_do_sync.add_argument("skill", nargs="?", help="Specific skill to sync (default: all)")
    p_sync_do_sync.set_defaults(func=cmd_sync_sync)

    p_sync_resolve = p_sync_sub.add_parser("resolve", help="Resolve a conflict by choosing a source")
    p_sync_resolve.add_argument("skill", help="Conflict skill name")
    p_sync_resolve.add_argument("--source", required=True, help="Which version to keep: 'central' or an agent name")
    p_sync_resolve.set_defaults(func=cmd_sync_resolve)

    p_sync_add_agent = p_sync_sub.add_parser("add-agent", help="Register a custom agent skill directory")
    p_sync_add_agent.add_argument("name", help="Agent name (e.g., 'my-custom-agent')")
    p_sync_add_agent.add_argument("path", help="Path to the skills directory")
    p_sync_add_agent.set_defaults(func=cmd_sync_add_agent)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    log_level = args.log_level or settings.hermes_log_level
    setup_logging(level=log_level, log_file=args.log_file)

    func = getattr(args, "func", cmd_start)
    try:
        return func(args)
    except Exception as exc:  # degraded-friendly: never crash silently
        logging.getLogger("hermes").error("Command failed: %s", exc, exc_info=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Hermes CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any
from pathlib import Path

from hermes.config import get_settings
from hermes.logging import setup_logging
from hermes.loop import (
    LOOP_PATTERNS,
    STOP_RULES,
    LoopStage,
    advance_stage,
    audit_loop,
    check_budget,
    estimate_cost,
    get_loop,
    get_loop_history,
    init_loop,
    list_loops,
    loops_dir,
)
from hermes.runner import resume_loop, run_loop, run_loop_continuous
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
    # hermes_main_repo_path is an optional inherited-env source (OpenClaw),
    # not a hard dependency — a missing repo is informational, not a warning,
    # so an independent Hermes install does not flag its absence as a problem.
    if not settings.hermes_main_repo_path.exists():
        logging.getLogger("hermes").info(
            "Inherited repo path not found (optional): %s", settings.hermes_main_repo_path
        )

    providers = settings.configured_providers()
    if not providers:
        warnings.append("No LLM provider API keys configured; set at least one in .env")

    if not settings.openclaw_gateway_token:
        warnings.append("OPENCLAW_GATEWAY_TOKEN is unset (recommended for production)")

    skills_count = len(discover_skills())
    docs_count = len(list_knowledge_docs())
    refresh = refresh_status()
    managed_count = refresh.get("total", 0)
    loops_count = len(list_loops())

    print("=== Hermes Doctor ===")
    print(f"Python:          {sys.version.split()[0]}")
    print(f"Project root:    {settings.hermes_project_root}")
    print(f"Main repo path:  {settings.hermes_main_repo_path}")
    print(f"Skills total:    {skills_count}")
    print(f"Skills managed:  {managed_count} (Skill Sync)")
    print(f"Knowledge docs:  {docs_count}")
    print(f"Active loops:    {loops_count} (Loop Engineering)")
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


# ── Loop Engineering commands ────────────────────────────────────────

def cmd_loop_list(args: argparse.Namespace) -> int:
    loops = list_loops()
    if not loops:
        print(f"No loops found in {loops_dir()}")
        print("Use `hermes loop init <name>` to create your first loop.")
        print(f"Built-in patterns: {', '.join(LOOP_PATTERNS.keys())}")
        return 0
    print(f"Loops ({len(loops)}):")
    print()
    for loop in loops:
        stage_marker = {
            LoopStage.L1_REPORT: "📋",
            LoopStage.L2_ASSIST: "🔧",
            LoopStage.L3_AUTONOMOUS: "🚀",
        }.get(loop.stage, "?")
        status_marker = {
            "idle": "○",
            "running": "▶",
            "needs_human": "👤",
            "completed": "✓",
            "budget_exceeded": "💰",
            "error": "✗",
        }.get(loop.status.value, "?")
        print(f"  {stage_marker} {status_marker} {loop.name:25s} [{loop.pattern}]  stage={loop.stage.value}  round={loop.current_round}/{loop.max_rounds}")
    return 0


def cmd_loop_init(args: argparse.Namespace) -> int:
    # Interactive pain-point → pattern mapping
    if getattr(args, "interactive", False):
        selected = _interactive_pattern_picker()
        if selected is None:
            return 1
        args.pattern = selected
    elif getattr(args, "from_pain_point", None):
        selected = _recommend_pattern_for_pain_point(args.from_pain_point)
        if selected is None:
            print(f"Error: no pattern matches pain point '{args.from_pain_point}'")
            print("Try --interactive, or pass --pattern explicitly.")
            return 1
        print(f"  💡 Pain point '{args.from_pain_point}' → pattern: {selected}")
        args.pattern = selected

    pattern = args.pattern or "custom"
    if pattern != "custom" and pattern not in LOOP_PATTERNS:
        print(f"Unknown pattern: {pattern}")
        print(f"Available patterns: {', '.join(LOOP_PATTERNS.keys())}, custom")
        return 1
    result = init_loop(args.name, pattern=pattern)
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        return 1
    print(f"✓ Loop '{result['name']}' initialized (pattern: {result['pattern']}, stage: {result['stage']})")
    print(f"  Location: {result['path']}")
    print(f"  Files created: {', '.join(result['files'])}")
    print()
    print("Next steps:")
    print(f"  1. Edit {result['path']}/LOOP.md to define completion criteria and boundaries")
    print(f"  2. Run `hermes loop audit {result['name']}` to check readiness")
    print(f"  3. Run `hermes loop run {result['name']}` to execute (L1 report-only first!)")
    return 0


# Pain-point → pattern recommendation. Order is priority (first match wins).
# Mirrors the 7 built-in workflows in Cobus Greyling's loop-engineering.
PAIN_POINT_PATTERNS: list[tuple[str, str]] = [
    ("ci broken", "ci-sweeper"),
    ("ci fails", "ci-sweeper"),
    ("ci is", "ci-sweeper"),
    ("ci flaky", "ci-sweeper"),
    ("flaky", "ci-sweeper"),
    ("pr stuck", "pr-babysitter"),
    ("pr review", "pr-babysitter"),
    ("stuck", "pr-babysitter"),
    ("pr 慢", "pr-babysitter"),
    ("pr 卡", "pr-babysitter"),
    ("issue 乱", "issue-triage"),
    ("issue 太乱", "issue-triage"),
    ("issue triage", "issue-triage"),
    ("issue backlog", "issue-triage"),
    ("unlabeled", "issue-triage"),
    ("changelog", "changelog-draft"),
    ("release notes", "changelog-draft"),
    ("change log", "changelog-draft"),
    ("发版说明", "changelog-draft"),
    ("更新日志", "changelog-draft"),
    ("knowledge stale", "knowledge-hygiene"),
    ("knowledge 过期", "knowledge-hygiene"),
    ("知识库 乱", "knowledge-hygiene"),
    ("知识库 过期", "knowledge-hygiene"),
    ("每天巡检", "daily-triage"),
    ("daily check", "daily-triage"),
    ("巡检", "daily-triage"),
    ("bug fix", "builder-checker"),
    ("修 bug", "builder-checker"),
    ("重构", "builder-checker"),
    ("refactor", "builder-checker"),
]


def _recommend_pattern_for_pain_point(text: str) -> str | None:
    """Map a free-form pain-point description to a pattern. First substring match wins."""
    needle = text.lower()
    for keyword, pattern in PAIN_POINT_PATTERNS:
        if keyword.lower() in needle:
            return pattern
    return None


def _interactive_pattern_picker() -> str | None:
    """Interactive pain-point → pattern picker (stdin-driven).

    Asks the user to describe their pain in one phrase, then recommends a
    pattern. Designed to be safe in non-TTY contexts: if stdin is not a TTY,
    prints a guidance message and returns None (caller should pass --pattern
    explicitly). Falls back to a hard-coded sample picker if input is empty.
    """
    if not sys.stdin.isatty():
        print("  ⚠️  --interactive requires a TTY. Pass --pattern or --from-pain-point instead.")
        return None
    print("  What problem are you trying to solve? (one short phrase)")
    print("  Examples: 'PR keeps getting stuck', 'changelog is tedious', 'CI flaky'")
    print()
    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not raw:
        return None
    pattern = _recommend_pattern_for_pain_point(raw)
    if pattern is None:
        print(f"  No pattern matches '{raw}'. Showing all available patterns:")
        for key, p in LOOP_PATTERNS.items():
            print(f"    {key:25s}  {p['description']}")
        return None
    print(f"  → Recommended pattern: {pattern}")
    print(f"    {LOOP_PATTERNS[pattern]['description']}")
    return pattern


def cmd_loop_audit(args: argparse.Namespace) -> int:
    result = audit_loop(args.name)
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        return 1
    if result["total"] == 0:
        print(result.get("suggestions", ["No loops yet."])[0])
        return 0

    print("=== Loop Readiness Audit ===")
    print(f"Total loops: {result['total']}")
    print(f"Average score: {result['average_score']}/100")
    print(f"Readiness: {result['readiness']}")
    print()

    for lr in result["loops"]:
        print(f"── {lr['loop']} ({lr['pattern']}) ── score: {lr['score']}/100  stage: {lr['stage']}")
        for check in lr["checks"]:
            marker = "✓" if check["passed"] else "✗"
            print(f"  {marker} {check['name']}")
        if lr["suggestions"]:
            print("  Suggestions:")
            for s in lr["suggestions"]:
                print(f"    → {s}")
        print()

    # Badge generation (--badge flag)
    if getattr(args, "badge", False):
        for lr in result["loops"]:
            badge = _render_loop_badge(lr)
            print("── Loop Ready Badge ──")
            print(badge["markdown"])
            print()
            if getattr(args, "badge_format", "md") == "svg":
                print("── SVG ──")
                print(badge["svg"])
                print()
        return 0

    return 0


def _render_loop_badge(loop_result: dict[str, Any]) -> dict[str, str]:
    """Render a Loop Ready badge for one loop's audit result.

    Returns {"markdown": str, "svg": str} for embedding in README/docs.
    Threshold: score >= 85 = "Loop Ready" (green), >= 70 = "Loop Aware" (yellow),
    else "Loop Incubating" (grey). Mirrors the stage/audit semantics already
    used in audit_loop's "readiness" field.
    """
    score = loop_result["score"]
    name = loop_result["loop"]
    pattern = loop_result["pattern"]
    if score >= 85:
        label, color, emoji = "Loop Ready", "brightgreen", "🟢"
    elif score >= 70:
        label, color, emoji = "Loop Aware", "yellow", "🟡"
    else:
        label, color, emoji = "Loop Incubating", "lightgrey", "⚪"
    md = (
        f"![{label}](https://img.shields.io/badge/"
        f"{label.replace(' ', '_')}-{score}%2F100-{color}) "
        f"{emoji} **{name}** (`{pattern}`) — {label} · score {score}/100"
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="170" height="20" '
        f'role="img" aria-label="{label}: {score}/100">'
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="170" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="110" height="20" fill="#555"/>'
        f'<rect x="110" width="60" height="20" fill="{color if "bright" in color or "yellow" in color or "green" in color else "#9f9f9f"}"/>'
        f'<rect width="170" height="20" fill="url(#s)"/></g>'
        f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="110">'
        f'<text aria-hidden="true" x="565" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" textLength="1000">{label}</text>'
        f'<text x="565" y="140" transform="scale(.1)" fill="#fff" textLength="1000">{label}</text>'
        f'<text aria-hidden="true" x="1395" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" textLength="500">{score}/100</text>'
        f'<text x="1395" y="140" transform="scale(.1)" fill="#fff" textLength="500">{score}/100</text></g></svg>'
    )
    return {"markdown": md, "svg": svg}


def cmd_loop_budget(args: argparse.Namespace) -> int:
    """Token cost estimator (alias: cost).

    对应 Cobus Greyling loop-engineering 的 `loop-cost` 命令。
    拆分自 budget 子命令，提升可发现性。
    """
    result = estimate_cost(args.name)
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        return 1
    print(f"=== Loop Cost Estimate: {result['loop']} ===")
    print(f"  Per-round estimate:  {result['per_round_estimate_tokens']:,} tokens")
    print(f"  Max rounds:          {result['max_rounds']}")
    print(f"  Total estimate:      {result['total_estimate_tokens']:,} tokens")
    print()
    print(f"  Budget limit:        {result['budget_limit_tokens']:,} tokens")
    print(f"  Budget used:         {result['budget_used_tokens']:,} tokens")
    print(f"  Budget remaining:    {result['budget_remaining_tokens']:,} tokens")
    print(f"  Est. rounds left:    {result['estimated_rounds_remaining']}")
    print()
    if result["within_budget"]:
        print("  ✓ Within budget")
    else:
        print("  ✗ WARNING: Estimated cost exceeds budget! Consider reducing max_rounds or increasing limit.")
    return 0


# Alias for `hermes loop cost` (preferred name, matches loop-engineering convention).
cmd_loop_cost = cmd_loop_budget


def _format_escalation_info(info: dict[str, Any] | None) -> list[str]:
    """Format escalation_info diagnostic fields for display.

    P0-1：停止规则触发时持久化的诊断信息。不同规则返回不同键，这里统一挑选
    对人类排查最有价值的字段渲染，跳过 attempts / last_two_rounds 等冗长字段。
    """
    if not info or not isinstance(info, dict):
        return []
    lines: list[str] = []
    # 通用：matched_signals（beyond_capability）
    signals = info.get("matched_signals")
    if signals:
        lines.append(f"  Matched signals: {', '.join(signals)}")
    # 通用：blocker（beyond_capability）
    blocker = info.get("blocker")
    if blocker:
        lines.append(f"  Blocker: {blocker}")
    # regression / no_progress
    new_fails = info.get("new_failures")
    if new_fails:
        lines.append(f"  New failures: {', '.join(new_fails)}")
    fixed = info.get("previously_fixed")
    if fixed:
        lines.append(f"  Previously fixed: {', '.join(fixed)}")
    # regression
    persistent = info.get("persistent")
    if persistent:
        lines.append(f"  Persistent: {', '.join(persistent)}")
    # same_failure_twice
    repeated = info.get("repeated_failures")
    if repeated:
        lines.append(f"  Repeated failures: {', '.join(repeated)}")
    # no_progress
    counts = info.get("failure_counts")
    if counts and isinstance(counts, list) and len(counts) == 2:
        lines.append(f"  Failure counts: {counts[0]} → {counts[1]}")
    suggestion = info.get("suggestion")
    if suggestion:
        lines.append(f"  Suggestion: {suggestion}")
    # rounds_exhausted
    failed_items = info.get("failed_items")
    if failed_items:
        lines.append(f"  Failed items: {', '.join(failed_items[:5])}")
    return lines


def cmd_loop_advance(args: argparse.Namespace) -> int:
    result = advance_stage(args.name)
    if not result.get("success"):
        print(f"Error: {result.get('error')}")
        if "suggestions" in result:
            print("Fix these issues first:")
            for s in result["suggestions"]:
                print(f"  → {s}")
        return 1
    print(f"✓ Loop '{result['loop']}' advanced: {result['previous_stage']} → {result['new_stage']}")
    if result["new_stage"] == LoopStage.L2_ASSIST.value:
        print("  L2 mode: Generator will make small fixes; Evaluator MUST verify independently.")
    elif result["new_stage"] == LoopStage.L3_AUTONOMOUS.value:
        print("  ⚠ L3 mode: Autonomous execution enabled. Ensure denylist is complete!")
    return 0


def cmd_loop_run(args: argparse.Namespace) -> int:
    """Execute one round of a loop via the runner."""
    result = run_loop(args.name)
    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    mode = result.get("mode", "unknown")
    print(f"=== Loop Run: {args.name} (mode: {mode}) ===")
    print(f"Round: {result.get('round', '?')}")
    print()

    if mode == "local":
        # Knowledge hygiene scan
        scan = result.get("scan_result", {})
        hp = scan.get("high_priority", [])
        wl = scan.get("watch_list", [])
        ni = scan.get("noise", [])
        print(f"High Priority ({len(hp)}):")
        for item in hp:
            print(f"  - {item}")
        print()
        print(f"Watch List ({len(wl)}):")
        for item in wl:
            print(f"  - {item}")
        print()
        print(f"Recent Noise ({len(ni)}):")
        for item in ni:
            print(f"  - {item}")
        print()
        passed = result.get("passed", False)
        print(f"Result: {'ALL GREEN' if passed else 'FAILED'}")
        stop = result.get("stop_check", {})
        if stop.get("should_stop"):
            print(f"Stop rule triggered: {stop.get('rule_name', '?')}")
            print(f"  {stop.get('description', '')}")
            for line in _format_escalation_info(stop.get("escalation_info")):
                print(line)
        else:
            print("No stop rule triggered. Run again or use `hermes loop advance` to proceed.")
        return 0

    elif mode == "orchestrated":
        round_result = result.get("result", {})
        print(f"Status: {'ALL GREEN' if result.get('passed') else 'FAILED'}")
        print(f"Tokens used: {round_result.get('total_tokens', 0):,}")
        print(f"Summary: {round_result.get('summary', '')}")
        if round_result.get("failure_items"):
            print()
            print(f"Failures ({len(round_result['failure_items'])}):")
            for item in round_result["failure_items"][:10]:
                print(f"  - {item}")
        stop = result.get("stop_check", {})
        if stop.get("should_stop"):
            print()
            print(f"Stop rule triggered: {stop.get('rule_name', '?')}")
            print(f"  {stop.get('description', '')}")
            for line in _format_escalation_info(stop.get("escalation_info")):
                print(line)
        print()
        record = result.get("record", {})
        print(f"Budget: {record.get('budget_used', 0):,}/{record.get('budget_remaining', 0):,} tokens remaining")
        return 0

    elif mode == "guidance":
        # Guidance mode (Gateway unavailable)
        print(result.get("message", "Guidance mode."))
        print()
        if "instructions" in result:
            print("Execution instructions:")
            for line in result["instructions"]:
                print(f"  {line}")
        if "agent_files" in result:
            print()
            print("Agent definition files:")
            for role, path in result["agent_files"].items():
                print(f"  {role}: {path}")
        if "principles" in result:
            print()
            print("Key principles:")
            for line in result["principles"]:
                print(f"  {line}")
        print()
        loop = get_loop(args.name)
        if loop:
            print(f"LOOP config:  {loop.config_path}")
            print(f"STATE file:   {loop.state_path}")
            print(f"Budget file:  {loop.budget_path}")
        return 0

    else:
        print(f"Unknown mode: {mode}")
        return 1


def cmd_loop_continuous(args: argparse.Namespace) -> int:
    """Execute loop rounds continuously until a stop rule triggers."""
    print(f"=== Continuous Loop: {args.name} ===")
    # 经验H：--gated 每轮后暂停等待人工确认（默认 False）
    result = run_loop_continuous(args.name, gated=getattr(args, "gated", False))
    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    print(f"Rounds executed: {result['rounds_executed']}")
    final_stop = result.get("final_stop", {})
    print(f"Final stop: {final_stop.get('rule_name', 'none')} — {final_stop.get('description', '')}")
    for line in _format_escalation_info(final_stop.get("escalation_info")):
        print(line)
    print()
    for i, r in enumerate(result.get("rounds", [])):
        mode = r.get("mode", "?")
        passed = r.get("passed", False)
        round_num = r.get("round", i + 1)
        print(f"  Round {round_num}: mode={mode} {'✓' if passed else '✗'}")
    return 0


def cmd_loop_resume(args: argparse.Namespace) -> int:
    """Resume a loop from its last recorded state."""
    print(f"=== Resume Loop: {args.name} ===")
    # 经验H：--gated 保持 gated 模式（每轮后暂停等待人工确认），默认 False
    result = resume_loop(args.name, gated=getattr(args, "gated", False))
    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    print(f"Rounds executed: {result['rounds_executed']}")
    final_stop = result.get("final_stop", {})
    print(f"Final stop: {final_stop.get('rule_name', 'none')} — {final_stop.get('description', '')}")
    for line in _format_escalation_info(final_stop.get("escalation_info")):
        print(line)
    return 0


def cmd_loop_logs(args: argparse.Namespace) -> int:
    """View execution history for a loop."""
    history = get_loop_history(args.name)
    if not history.get("success"):
        print(f"Error: {history.get('error', 'unknown error')}")
        return 1

    print(f"=== Loop History: {args.name} ===")
    print(f"Status: {history['status']}")
    print(f"Round: {history['current_round']}/{history['max_rounds']}")
    print(f"Budget: {history['budget_used']:,}/{history['budget_limit']:,} tokens")
    print()

    rounds = history.get("rounds", [])
    if not rounds:
        print("No rounds executed yet.")
        return 0

    print(f"Execution history ({len(rounds)} rounds):")
    print()
    for r in rounds:
        marker = "✓" if r.get("passed") else "✗"
        print(f"  Round {r['round_num']} {marker} — {r.get('result_summary', '')}")
        if r.get("failure_items"):
            print(f"    Failures ({r.get('failure_count', 0)}): {', '.join(r['failure_items'][:3])}")
        if r.get("tokens_used"):
            print(f"    Tokens: {r['tokens_used']:,}")
        if r.get("agent_reports"):
            for role, report in r["agent_reports"].items():
                # Show first 200 chars of each agent report
                preview = report[:200] + ("..." if len(report) > 200 else "")
                print(f"    [{role}]: {preview}")
        # P0-1：展示持久化的诊断信息（停止规则触发时回填）
        esc_lines = _format_escalation_info(r.get("escalation_info"))
        if esc_lines:
            print("    Escalation:")
            for line in esc_lines:
                print(f"    {line}")
        print()
    return 0


def cmd_loop_status(args: argparse.Namespace) -> int:
    """Show current loop status and budget."""
    loop = get_loop(args.name)
    if not loop:
        print(f"Error: Loop '{args.name}' not found")
        return 1

    budget = check_budget(args.name)
    print(f"=== Loop Status: {args.name} ===")
    print(f"  Pattern:    {loop.pattern}")
    print(f"  Stage:      {loop.stage.value}")
    print(f"  Status:     {loop.status.value}")
    print(f"  Round:      {loop.current_round}/{loop.max_rounds}")
    print()
    print(f"  Budget:     {budget['used']:,}/{budget['limit']:,} tokens ({budget['percentage']}%)")
    print(f"  Remaining:  {budget['remaining']:,} tokens")
    print(f"  Budget level: {budget['level']} ({budget['action']})")
    print()

    if loop.rounds:
        print(f"  Last round: {loop.rounds[-1].action}")
        print(f"  Last result: {'✓ PASSED' if loop.rounds[-1].passed else '✗ FAILED'}")
    else:
        print("  No rounds executed yet.")
    return 0


def cmd_loop_stop_rules(args: argparse.Namespace) -> int:
    print("=== Loop Stop Rules (Seven Conditions) ===")
    print()
    for i, rule in enumerate(STOP_RULES, 1):
        action_marker = "✓" if rule["action"] == "stop_success" else "⚠"
        print(f"  {action_marker} {i}. {rule['name']}")
        print(f"     {rule['description']}")
        print(f"     Action: {rule['action']}")
        print()
    print("Red lines:")
    print("  - Never report success without checker output")
    print("  - Never weaken/delete/skip checks to achieve ALL GREEN")
    print("  - Never modify checker's tool whitelist")
    print()
    print("Escalation protocol (when stopping with failures):")
    print("  - Current round (Cycle N/max)")
    print("  - Still-failing items list")
    print("  - Each attempted fix method")
    print("  - Judgment: why continuing won't solve the problem")
    return 0


def cmd_loop_patterns(args: argparse.Namespace) -> int:
    print("Built-in loop patterns:")
    print()
    for key, p in LOOP_PATTERNS.items():
        print(f"  {key:25s}  default stage: {p['default_stage'].value}")
        print(f"    {p['description']}")
        print(f"    L1: {p['l1_capability']}")
        print(f"    L2: {p['l2_capability']}")
        print(f"    L3: {p['l3_capability']}")
        if p.get("denylist"):
            print(f"    Denylist: {', '.join(p['denylist'])}")
        print()
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

    # ── loop subcommand ────────────────────────────────────────────
    p_loop = sub.add_parser(
        "loop",
        help="Loop Engineering: create, audit, and run agent loops",
        description="Loop Engineering commands for structured, repeatable agent automation with L1/L2/L3 staged autonomy, Maker/Checker separation, and budget controls.",
    )
    p_loop_sub = p_loop.add_subparsers(dest="loop_cmd", required=True)

    p_loop_list = p_loop_sub.add_parser("list", help="List all configured loops")
    p_loop_list.set_defaults(func=cmd_loop_list)

    p_loop_patterns = p_loop_sub.add_parser("patterns", help="Show built-in loop patterns")
    p_loop_patterns.set_defaults(func=cmd_loop_patterns)

    p_loop_init = p_loop_sub.add_parser("init", help="Initialize a new loop with scaffolding")
    p_loop_init.add_argument("name", help="Loop name (e.g., 'daily-checks')")
    p_loop_init.add_argument(
        "--pattern", "-p",
        choices=list(LOOP_PATTERNS.keys()) + ["custom"],
        help="Built-in pattern to use (default: custom)",
    )
    p_loop_init.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Interactive picker: describe your pain, get a pattern recommendation",
    )
    p_loop_init.add_argument(
        "--from-pain-point",
        dest="from_pain_point",
        help="Non-interactive: pass a short pain-point phrase, get a pattern recommendation",
    )
    p_loop_init.set_defaults(func=cmd_loop_init)

    p_loop_audit = p_loop_sub.add_parser("audit", help="Audit loop readiness and quality")
    p_loop_audit.add_argument("name", nargs="?", help="Specific loop to audit (default: all)")
    p_loop_audit.add_argument(
        "--badge",
        action="store_true",
        help="Render a Loop Ready badge (markdown shields.io) for embedding in README/docs",
    )
    p_loop_audit.add_argument(
        "--badge-format",
        choices=["md", "svg"],
        default="md",
        help="Badge output format (default: md); only meaningful with --badge",
    )
    p_loop_audit.set_defaults(func=cmd_loop_audit)

    p_loop_budget = p_loop_sub.add_parser("budget", help="Estimate token cost for a loop (alias: cost)")
    p_loop_budget.add_argument("name", help="Loop name")
    p_loop_budget.set_defaults(func=cmd_loop_budget)

    # Preferred name: matches `loop-cost` in the loop-engineering reference CLI.
    # `budget` is kept as alias for backward compatibility.
    p_loop_cost = p_loop_sub.add_parser("cost", help="Estimate token cost for a loop (preferred over 'budget')")
    p_loop_cost.add_argument("name", help="Loop name")
    p_loop_cost.set_defaults(func=cmd_loop_cost)

    p_loop_advance = p_loop_sub.add_parser("advance", help="Advance loop to next autonomy stage (L1→L2→L3)")
    p_loop_advance.add_argument("name", help="Loop name")
    p_loop_advance.set_defaults(func=cmd_loop_advance)

    p_loop_run = p_loop_sub.add_parser("run", help="Execute one round of a loop")
    p_loop_run.add_argument("name", help="Loop name")
    p_loop_run.set_defaults(func=cmd_loop_run)

    p_loop_continuous = p_loop_sub.add_parser("continuous", help="Run loop continuously until stop rule triggers")
    p_loop_continuous.add_argument("name", help="Loop name")
    # 经验H：gated 模式——每轮后暂停等待人工确认
    p_loop_continuous.add_argument(
        "--gated",
        action="store_true",
        help="Pause after each round for human confirmation",
    )
    p_loop_continuous.set_defaults(func=cmd_loop_continuous)

    p_loop_resume = p_loop_sub.add_parser("resume", help="Resume a loop from last recorded state")
    p_loop_resume.add_argument("name", help="Loop name")
    # 经验H：gated 模式——resume 后保持每轮后暂停等待人工确认（修复对抗审查 Critical 1）
    p_loop_resume.add_argument(
        "--gated",
        action="store_true",
        help="Pause after each round for human confirmation (preserves gated mode)",
    )
    p_loop_resume.set_defaults(func=cmd_loop_resume)

    p_loop_logs = p_loop_sub.add_parser("logs", help="View execution history for a loop")
    p_loop_logs.add_argument("name", help="Loop name")
    p_loop_logs.set_defaults(func=cmd_loop_logs)

    p_loop_status = p_loop_sub.add_parser("status", help="Show current loop status and budget")
    p_loop_status.add_argument("name", help="Loop name")
    p_loop_status.set_defaults(func=cmd_loop_status)

    p_loop_stop = p_loop_sub.add_parser("stop-rules", help="Show the seven stop rules")
    p_loop_stop.set_defaults(func=cmd_loop_stop_rules)

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

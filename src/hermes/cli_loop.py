"""Loop Engineering CLI subcommands.

Exposes the implemented Loop Engine functions (init/run/audit/metrics/...) as
`hermes loop <sub>` commands. This closes the architecture-doc-vs-reality gap:
the functions in loop.py/runner.py were implemented and tested but had no CLI
entry point.

Design:
- Thin wrappers: each cmd_* function calls the underlying loop/runner function,
  formats the result dict for human reading, and returns an exit code.
- --json flag on data-returning commands for machine consumption.
- Exit codes: 0=success, 1=soft warning (e.g. loop not found), 2=hard error.
- No business logic here — all logic lives in loop.py/runner.py.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from hermes.loop import (
    LOOP_PATTERNS,
    STOP_RULES,
    audit_loop,
    check_budget,
    get_loop,
    get_loop_history,
    init_loop,
    list_loops,
    loop_metrics,
    advance_stage,
)
from hermes.runner import resume_loop, run_loop, run_loop_continuous


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _exit_code(result: dict[str, Any]) -> int:
    """Map a result dict to exit code. 0=success, 1=soft fail, 2=hard error."""
    if result.get("success"):
        return 0
    return 1


# ── Command handlers ────────────────────────────────────────────────


def cmd_loop_list(args: argparse.Namespace) -> int:
    """List all loops."""
    loops = list_loops()
    if not loops:
        print("No loops found. Run `hermes loop init <name>` to create one.")
        return 0

    if args.json:
        _print_json([
            {
                "name": loop.name,
                "pattern": loop.pattern,
                "stage": loop.stage.value,
                "status": loop.status.value,
                "current_round": loop.current_round,
                "max_rounds": loop.max_rounds,
            }
            for loop in loops
        ])
        return 0

    print(f"Loops ({len(loops)}):")
    for loop in loops:
        print(
            f"  {loop.name:<24} pattern={loop.pattern:<18} "
            f"stage={loop.stage.value:<10} status={loop.status.value:<14} "
            f"round={loop.current_round}/{loop.max_rounds}"
        )
    return 0


def cmd_loop_init(args: argparse.Namespace) -> int:
    """Initialize a new loop."""
    result = init_loop(args.name, pattern=args.pattern)
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    print(f"Initialized loop '{args.name}' (pattern={args.pattern})")
    print(f"  Location: {result.get('loop_dir', '?')}")
    return 0


def cmd_loop_run(args: argparse.Namespace) -> int:
    """Run one round of a loop."""
    result = run_loop(args.name)
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    # Human-readable summary
    mode = result.get("mode", "")
    summary = result.get("summary") or result.get("result_summary", "")
    stop = result.get("stop_rule") or {}
    print(f"Loop '{args.name}' round completed.")
    if mode:
        print(f"  Mode: {mode}")
    if summary:
        print(f"  Summary: {summary}")
    if stop.get("should_stop"):
        print(f"  Stop rule: {stop.get('rule_name', '?')} — {stop.get('description', '')}")
    return 0


def cmd_loop_continuous(args: argparse.Namespace) -> int:
    """Run loop rounds continuously until a stop rule triggers."""
    result = run_loop_continuous(
        args.name, max_rounds=args.max_rounds, gated=args.gated
    )
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    rounds = result.get("rounds_executed", [])
    stop = result.get("final_stop") or {}
    print(f"Loop '{args.name}' continuous run completed.")
    print(f"  Rounds executed: {len(rounds)}")
    if stop.get("should_stop"):
        print(f"  Stop rule: {stop.get('rule_name', '?')}")
        print(f"  Reason: {stop.get('description', '')}")
    if result.get("gated_paused"):
        print("  Paused for human review (gated mode). Run `hermes loop resume` to continue.")
    return 0


def cmd_loop_resume(args: argparse.Namespace) -> int:
    """Resume a loop from its last recorded state."""
    result = resume_loop(args.name, gated=args.gated)
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    stop = result.get("final_stop") or {}
    print(f"Loop '{args.name}' resumed.")
    if stop.get("should_stop"):
        print(f"  Stop rule: {stop.get('rule_name', '?')}")
        print(f"  Reason: {stop.get('description', '')}")
    return 0


def cmd_loop_audit(args: argparse.Namespace) -> int:
    """Run readiness audit on a loop (or all loops)."""
    result = audit_loop(args.name)
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    print(f"Loop Audit — score: {result.get('score', 0)}/100")
    for loop_result in result.get("loops", []):
        print(f"\n  Loop: {loop_result.get('name', '?')} (score={loop_result.get('score', 0)})")
        for check in loop_result.get("checks", []):
            mark = "✓" if check.get("passed") else "✗"
            print(f"    {mark} {check.get('name', '?')} (weight={check.get('weight', 0)})")
        if loop_result.get("suggestions"):
            print("    Suggestions:")
            for s in loop_result["suggestions"]:
                print(f"      - {s}")
    return 0


def cmd_loop_status(args: argparse.Namespace) -> int:
    """Show current state of a loop."""
    loop = get_loop(args.name)
    if loop is None:
        print(f"Loop '{args.name}' not found.")
        return 1

    if args.json:
        _print_json({
            "name": loop.name,
            "pattern": loop.pattern,
            "stage": loop.stage.value,
            "status": loop.status.value,
            "current_round": loop.current_round,
            "max_rounds": loop.max_rounds,
            "budget_used_tokens": loop.budget_used_tokens,
            "budget_limit_tokens": loop.budget_limit_tokens,
            "total_rounds": len(loop.rounds),
        })
        return 0

    print(f"Loop: {loop.name}")
    print(f"  Pattern: {loop.pattern}")
    print(f"  Stage:   {loop.stage.value}")
    print(f"  Status:  {loop.status.value}")
    print(f"  Round:   {loop.current_round}/{loop.max_rounds}")
    print(f"  Budget:  {loop.budget_used_tokens}/{loop.budget_limit_tokens} tokens")
    print(f"  Total recorded rounds: {len(loop.rounds)}")
    return 0


def cmd_loop_metrics(args: argparse.Namespace) -> int:
    """Show aggregated metrics for a loop."""
    result = loop_metrics(args.name)
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    print(f"Metrics for loop '{args.name}':")
    print(f"  Pattern:      {result.get('pattern', '?')}")
    print(f"  Status:       {result.get('status', '?')}")
    print(f"  Total rounds: {result.get('total_rounds', 0)}")
    print(f"  Passed:       {result.get('passed', 0)}")
    print(f"  Failed:       {result.get('failed', 0)}")
    print(f"  Pass rate:    {result.get('pass_rate', 0):.1f}%")
    print(f"  Total tokens: {result.get('total_tokens', 0)}")
    print(f"  Avg tokens:   {result.get('avg_tokens', 0):.0f}")
    print(f"  Budget used:  {result.get('budget_pct', 0):.1f}%")
    return 0


def cmd_loop_stop_rules(args: argparse.Namespace) -> int:
    """Print the seven stop rules (reference)."""
    if args.json:
        _print_json(STOP_RULES)
        return 0

    print(f"Stop Rules ({len(STOP_RULES)}):")
    for rule in STOP_RULES:
        gate = "[HARD]" if rule.get("hard_gate") else "[SOFT]"
        print(f"  {gate} {rule.get('id', '?')}: {rule.get('name', '?')}")
        print(f"        {rule.get('description', '')}")
        print(f"        action: {rule.get('action', '?')}")
    return 0


def cmd_loop_budget(args: argparse.Namespace) -> int:
    """Check budget status for a loop."""
    result = check_budget(args.name)
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    level = result.get("level", "?")
    print(f"Budget for loop '{args.name}':")
    print(f"  Used:      {result.get('used', 0)} / {result.get('limit', 0)} tokens")
    print(f"  Remaining: {result.get('remaining', 0)}")
    print(f"  Percentage: {result.get('percentage', 0):.1f}%")
    print(f"  Level:     {level}")
    print(f"  Action:    {result.get('action', '?')}")
    return 0


def cmd_loop_advance(args: argparse.Namespace) -> int:
    """Advance a loop to the next autonomy stage (L1→L2→L3)."""
    result = advance_stage(args.name)
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        if "score" in result:
            print(f"  Current score: {result.get('score', 0)} (required: {result.get('required', '?')})")
        return 1

    print(f"Loop '{args.name}' advanced to {result.get('new_stage', '?')}.")
    return 0


def cmd_loop_history(args: argparse.Namespace) -> int:
    """Show round history for a loop."""
    result = get_loop_history(args.name)
    if args.json:
        _print_json(result)
        return _exit_code(result)

    if not result.get("success"):
        print(f"Error: {result.get('error', 'unknown error')}")
        return 1

    rounds = result.get("rounds", [])
    print(f"History for loop '{args.name}' ({len(rounds)} rounds):")
    for r in rounds:
        passed = "✓" if r.get("passed") else "✗"
        print(
            f"  Round {r.get('round_num', '?')}: {passed}  "
            f"tokens={r.get('tokens_used', 0)}  "
            f"failures={r.get('failure_count', 0)}  "
            f"— {r.get('result_summary', '')[:80]}"
        )
    return 0


def cmd_loop_patterns(args: argparse.Namespace) -> int:
    """List available loop patterns."""
    if args.json:
        _print_json([
            {
                "key": k,
                "name": v.get("name", k),
                "description": v.get("description", ""),
                "default_stage": v.get("default_stage", "").value
                if hasattr(v.get("default_stage"), "value")
                else str(v.get("default_stage", "")),
                "max_rounds": v.get("max_rounds", 0),
                "execution_status": v.get("execution_status", ""),
            }
            for k, v in LOOP_PATTERNS.items()
        ])
        return 0

    print(f"Loop Patterns ({len(LOOP_PATTERNS)}):")
    for key, info in LOOP_PATTERNS.items():
        name = info.get("name", key)
        desc = info.get("description", "")
        status = info.get("execution_status", "")
        print(f"  {key:<20} {name}")
        print(f"    {desc}")
        if status:
            print(f"    execution: {status}")
    return 0


def cmd_loop_gepa(args: argparse.Namespace) -> int:
    """Show or run GEPA self-evolution experiments for a loop.

    Without --run: list experiments whose benchmark_task matches the loop.
    With --run: manually trigger a GEPA cycle (requires gepa_variants declared
    on the loop + an evaluator injected via set_gepa_evaluator).
    """
    loop = get_loop(args.name)
    if loop is None:
        print(f"Loop '{args.name}' not found.")
        return 1

    if args.run:
        # Manual trigger: call _maybe_run_gepa directly (bypasses terminal-state
        # check since user explicitly asked). But still needs variants + evaluator.
        from hermes.loop import _maybe_run_gepa, _GEPA_TRIGGER_STATUSES, get_gepa_evaluator
        from hermes.loop import LoopRound

        if not loop.gepa_variants:
            print(f"Loop '{args.name}' has no gepa_variants declared.")
            print("  Add variants to meta.json: gepa_variants: [{variant_id, agent_file}, ...]")
            return 1

        if get_gepa_evaluator() is None:
            print("No GEPA evaluator injected. Runner injects one when Gateway is available.")
            print("  In guidance mode, GEPA cannot run (no agent execution backend).")
            return 1

        # Force terminal status for manual trigger (user explicitly asked to run)
        if loop.status not in _GEPA_TRIGGER_STATUSES:
            print(
                f"Note: loop status is '{loop.status.value}' (non-terminal). "
                "Running GEPA anyway (--run flag)."
            )

        # Build a minimal round_data for _maybe_run_gepa (it needs round_data
        # but _maybe_run_gepa doesn't actually use round_data's content — only
        # loop state matters for the GEPA trigger).
        dummy_round = LoopRound(
            round_num=loop.current_round,
            timestamp="",
            action="gepa-manual-trigger",
            result_summary="manual GEPA trigger",
            verifier_result="",
            passed=False,
        )
        # Temporarily set status to a terminal state if not already, so
        # _maybe_run_gepa's guard passes. Restore after.
        original_status = loop.status
        if loop.status not in _GEPA_TRIGGER_STATUSES:
            from hermes.loop import LoopStatus
            loop.status = LoopStatus.COMPLETED
        try:
            result = _maybe_run_gepa(loop, dummy_round)
        finally:
            loop.status = original_status

        if args.json:
            _print_json(result)
            return 0 if result.get("ran") else 1

        if not result.get("ran"):
            print(f"GEPA did not run: {result.get('reason', 'unknown')}")
            return 1

        print(f"GEPA cycle completed for loop '{args.name}'.")
        print(f"  Experiment: {result.get('experiment_id', '?')}")
        winner = result.get("winner_id")
        if winner:
            print(f"  Winner: {winner}")
        else:
            print("  Winner: (none — no variant succeeded)")
        print(f"  Reason: {result.get('promotion_reason', '?')}")
        print(f"  Variants evaluated: {result.get('variants_evaluated', 0)}")
        return 0

    # Default: list experiments for this loop
    from hermes.gepa import list_experiments

    experiments = list_experiments()
    # Filter: benchmark_task contains the loop name (set by _maybe_run_gepa)
    loop_experiments = [
        e for e in experiments
        if f"loop:{args.name}" in e.benchmark_task
    ]

    if args.json:
        _print_json([
            {
                "experiment_id": e.experiment_id,
                "benchmark_task": e.benchmark_task,
                "winner_id": e.winner_id,
                "promotion_reason": e.promotion_reason,
                "created_at": e.created_at,
                "completed_at": e.completed_at,
                "variants_count": len(e.variants),
                "results_count": len(e.results),
            }
            for e in loop_experiments
        ])
        return 0

    if not loop_experiments:
        print(f"No GEPA experiments for loop '{args.name}'.")
        print(f"  Variants declared: {len(loop.gepa_variants)}")
        if loop.gepa_variants:
            print("  To run manually: hermes loop gepa <name> --run")
        else:
            print("  Declare gepa_variants in meta.json to enable self-evolution.")
        return 0

    print(f"GEPA experiments for loop '{args.name}' ({len(loop_experiments)}):")
    for e in loop_experiments:
        winner = e.winner_id or "(none)"
        print(f"  {e.experiment_id[:8]}  winner={winner}  created={e.created_at}")
        print(f"    {e.promotion_reason}")
    return 0


# ── Subparser registration ──────────────────────────────────────────


def add_loop_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register `hermes loop <sub>` commands on the top-level subparsers."""
    p_loop = sub.add_parser("loop", help="Loop Engineering (init/run/audit/metrics)")
    loop_sub = p_loop.add_subparsers(dest="loop_cmd", required=True)

    # list
    p_list = loop_sub.add_parser("list", help="List all loops")
    p_list.add_argument("--json", action="store_true", help="Output JSON")
    p_list.set_defaults(func=cmd_loop_list)

    # init
    p_init = loop_sub.add_parser("init", help="Initialize a new loop")
    p_init.add_argument("name", help="Loop name (becomes directory name)")
    p_init.add_argument(
        "--pattern", default="custom",
        help=f"Loop pattern (default: custom). Available: {', '.join(LOOP_PATTERNS.keys())}",
    )
    p_init.add_argument("--json", action="store_true", help="Output JSON")
    p_init.set_defaults(func=cmd_loop_init)

    # run
    p_run = loop_sub.add_parser("run", help="Run one round of a loop")
    p_run.add_argument("name", help="Loop name")
    p_run.add_argument("--json", action="store_true", help="Output JSON")
    p_run.set_defaults(func=cmd_loop_run)

    # continuous
    p_cont = loop_sub.add_parser("continuous", help="Run rounds until a stop rule triggers")
    p_cont.add_argument("name", help="Loop name")
    p_cont.add_argument("--max-rounds", type=int, default=None, help="Override max rounds")
    p_cont.add_argument("--gated", action="store_true", help="Pause after each round for human review")
    p_cont.add_argument("--json", action="store_true", help="Output JSON")
    p_cont.set_defaults(func=cmd_loop_continuous)

    # resume
    p_resume = loop_sub.add_parser("resume", help="Resume a loop from its last state")
    p_resume.add_argument("name", help="Loop name")
    p_resume.add_argument("--gated", action="store_true", help="Pause after each round for human review")
    p_resume.add_argument("--json", action="store_true", help="Output JSON")
    p_resume.set_defaults(func=cmd_loop_resume)

    # audit
    p_audit = loop_sub.add_parser("audit", help="Run readiness audit")
    p_audit.add_argument("name", nargs="?", default=None, help="Loop name (omit to audit all)")
    p_audit.add_argument("--json", action="store_true", help="Output JSON")
    p_audit.set_defaults(func=cmd_loop_audit)

    # status
    p_status = loop_sub.add_parser("status", help="Show current loop state")
    p_status.add_argument("name", help="Loop name")
    p_status.add_argument("--json", action="store_true", help="Output JSON")
    p_status.set_defaults(func=cmd_loop_status)

    # metrics
    p_metrics = loop_sub.add_parser("metrics", help="Show aggregated metrics")
    p_metrics.add_argument("name", help="Loop name")
    p_metrics.add_argument("--json", action="store_true", help="Output JSON")
    p_metrics.set_defaults(func=cmd_loop_metrics)

    # stop-rules
    p_stop = loop_sub.add_parser("stop-rules", help="Print the seven stop rules")
    p_stop.add_argument("--json", action="store_true", help="Output JSON")
    p_stop.set_defaults(func=cmd_loop_stop_rules)

    # budget
    p_budget = loop_sub.add_parser("budget", help="Check budget status")
    p_budget.add_argument("name", help="Loop name")
    p_budget.add_argument("--json", action="store_true", help="Output JSON")
    p_budget.set_defaults(func=cmd_loop_budget)

    # advance
    p_advance = loop_sub.add_parser("advance", help="Advance to next autonomy stage (L1→L2→L3)")
    p_advance.add_argument("name", help="Loop name")
    p_advance.add_argument("--json", action="store_true", help="Output JSON")
    p_advance.set_defaults(func=cmd_loop_advance)

    # history
    p_history = loop_sub.add_parser("history", help="Show round history")
    p_history.add_argument("name", help="Loop name")
    p_history.add_argument("--json", action="store_true", help="Output JSON")
    p_history.set_defaults(func=cmd_loop_history)

    # patterns
    p_patterns = loop_sub.add_parser("patterns", help="List available loop patterns")
    p_patterns.add_argument("--json", action="store_true", help="Output JSON")
    p_patterns.set_defaults(func=cmd_loop_patterns)

    # gepa (Stage 5: GEPA self-evolution wire-up)
    p_gepa = loop_sub.add_parser("gepa", help="Show/run GEPA self-evolution experiments")
    p_gepa.add_argument("name", help="Loop name")
    p_gepa.add_argument("--run", action="store_true", help="Manually trigger a GEPA cycle")
    p_gepa.add_argument("--json", action="store_true", help="Output JSON")
    p_gepa.set_defaults(func=cmd_loop_gepa)

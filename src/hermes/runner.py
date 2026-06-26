"""Loop execution runner for Hermes.

Bridges the Orchestrator (sub-agent scheduling) with the Loop engine
(state management, stop rules, budget control). Supports:

- run_loop(): Execute one round of a loop
- run_loop_continuous(): Execute rounds until a stop rule triggers
- resume_loop(): Resume from the last recorded state
- Guidance mode fallback when the Gateway is unavailable
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes.loop import (
    LoopRound,
    LoopStage,
    LoopStatus,
    check_budget,
    check_stop_rules,
    get_loop,
    knowledge_hygiene_scan,
    loops_dir,
    record_round,
)
from hermes.orchestrator import Orchestrator, RoundResult

logger = logging.getLogger("hermes.runner")


def _guidance_mode(loop_name: str, pattern: str) -> dict[str, Any]:
    """Return guidance-only result when Gateway is unavailable."""
    return {
        "success": True,
        "mode": "guidance",
        "loop": loop_name,
        "pattern": pattern,
        "message": (
            "Gateway unavailable — running in guidance mode. "
            "Execute the loop manually using the agent definition files."
        ),
    }


def run_loop(name: str) -> dict[str, Any]:
    """Execute one round of a loop.

    Behavior depends on the loop's pattern and stage:
    - knowledge-hygiene L1: Runs the local file scan (no Gateway needed)
    - builder-checker L2+: Uses the Orchestrator to spawn builder/checker agents
    - Other patterns: Guidance mode if Gateway unavailable

    Returns a dict with round results, including stop rule evaluation.
    """
    loop = get_loop(name)
    if not loop:
        return {"success": False, "error": f"Loop '{name}' not found"}

    if loop.status == LoopStatus.COMPLETED:
        return {"success": False, "error": "Loop already completed. Use `hermes loop resume` to restart."}
    if loop.status == LoopStatus.BUDGET_EXCEEDED:
        return {"success": False, "error": "Budget exceeded. Increase budget or reset the loop."}

    # Check budget before starting
    budget = check_budget(name)
    if not budget.get("success"):
        return budget
    if budget["action"] == "hard_stop":
        return {"success": False, "error": f"Budget exceeded: {budget['used']}/{budget['limit']} tokens"}

    round_num = loop.current_round + 1
    loop_dir = loops_dir() / name
    now = datetime.now(timezone.utc).isoformat()

    # Pattern-specific execution
    if loop.pattern == "knowledge-hygiene" and loop.stage == LoopStage.L1_REPORT:
        return _run_knowledge_hygiene(name, round_num, now, loop_dir)

    if loop.pattern == "builder-checker":
        return _run_builder_checker(name, loop, round_num, now, loop_dir)

    # Default: try orchestrator, fall back to guidance
    orchestrator = Orchestrator()
    if not orchestrator.is_available():
        return _guidance_mode(name, loop.pattern)

    # For other patterns with Gateway available, run a generic round
    return _run_generic_with_gateway(name, loop, round_num, now, loop_dir, orchestrator)


def _run_knowledge_hygiene(
    name: str,
    round_num: int,
    now: str,
    loop_dir: Path,
) -> dict[str, Any]:
    """Execute knowledge-hygiene L1 scan (local, no Gateway needed)."""
    scan_result = knowledge_hygiene_scan()

    hp = scan_result["high_priority"]
    wl = scan_result["watch_list"]
    noise = scan_result["noise"]

    failure_items = hp + wl
    passed = len(hp) == 0

    round_data = LoopRound(
        round_num=round_num,
        timestamp=now,
        action="L1 knowledge hygiene scan",
        result_summary=f"High: {len(hp)}, Watch: {len(wl)}, Noise: {len(noise)}",
        verifier_result=scan_result["summary"].__str__(),
        passed=passed,
        failure_count=len(failure_items),
        failure_items=failure_items,
        tokens_used=0,
    )

    record_result = record_round(name, round_data, tokens_used=0)

    # Check stop rules
    loop = get_loop(name)
    if loop:
        stop = check_stop_rules(name, loop.current_round, loop.max_rounds, loop.rounds)
    else:
        stop = {"should_stop": False, "action": "continue"}

    return {
        "success": True,
        "mode": "local",
        "loop": name,
        "round": round_num,
        "scan_result": scan_result,
        "passed": passed,
        "stop_check": stop,
        "record": record_result,
    }


def _run_builder_checker(
    name: str,
    loop: Any,
    round_num: int,
    now: str,
    loop_dir: Path,
) -> dict[str, Any]:
    """Execute a builder-checker round via the Orchestrator."""
    orchestrator = Orchestrator()

    if not orchestrator.is_available():
        # Guidance mode: print execution instructions
        return _guidance_builder_checker(name, loop, round_num, loop_dir)

    # Get previous checker report for builder context (don't filter!)
    previous_report = ""
    if loop.rounds:
        last_round = loop.rounds[-1]
        if last_round.agent_reports:
            previous_report = last_round.agent_reports.get("checker", "")

    # Determine if parallel checks are enabled (based on sub_agents config)
    parallel_checks = True  # Default: parallel checker execution

    # Generate builder task based on round number
    if round_num == 1:
        builder_task = (
            f"Cycle {round_num}/{loop.max_rounds}. "
            "Read the project structure and LOOP.md, then implement the task described in LOOP.md. "
            "Follow the builder.md instructions."
        )
    else:
        builder_task = (
            f"Cycle {round_num}/{loop.max_rounds}. "
            "The checker found the following failures in the previous round. "
            "Fix them:\n\n"
            f"{previous_report}"
        )

    # Execute the round via orchestrator
    result: RoundResult = orchestrator.run_builder_checker_round(
        loop_dir=loop_dir,
        round_num=round_num,
        builder_task=builder_task,
        checker_context=previous_report,
        parallel_checks=parallel_checks,
    )

    # Build LoopRound from result
    agent_reports: dict[str, str] = {}
    for task in result.tasks:
        if task.result:
            agent_reports[task.role] = task.result

    round_data = LoopRound(
        round_num=round_num,
        timestamp=now,
        action=f"builder-checker round (parallel={parallel_checks})",
        result_summary=result.summary,
        verifier_result=result.checker_report,
        passed=result.all_passed,
        failure_count=len(result.failure_items),
        failure_items=result.failure_items,
        tokens_used=result.total_tokens,
        agent_reports=agent_reports,
    )

    record_result = record_round(name, round_data, tokens_used=result.total_tokens)

    # Check stop rules
    updated_loop = get_loop(name)
    if updated_loop:
        stop = check_stop_rules(
            name, updated_loop.current_round, updated_loop.max_rounds, updated_loop.rounds
        )
    else:
        stop = {"should_stop": False, "action": "continue"}

    return {
        "success": True,
        "mode": "orchestrated",
        "loop": name,
        "round": round_num,
        "result": result.to_dict(),
        "passed": result.all_passed,
        "stop_check": stop,
        "record": record_result,
    }


def _guidance_builder_checker(
    name: str,
    loop: Any,
    round_num: int,
    loop_dir: Path,
) -> dict[str, Any]:
    """Print guidance for manual builder-checker execution."""
    builder_path = loop_dir / "builder.md"
    checker_path = loop_dir / "checker.md"
    stop_rules_path = loop_dir / "stop-rules.md"

    guidance = _guidance_mode(name, "builder-checker")
    guidance.update({
        "round": round_num,
        "max_rounds": loop.max_rounds,
        "agent_files": {
            "builder": str(builder_path),
            "checker": str(checker_path),
            "stop_rules": str(stop_rules_path),
        },
        "instructions": [
            f"1. Cycle {round_num}/{loop.max_rounds}",
            f"2. Send task to builder agent: {builder_path}",
            "3. Send checker agent to run all checks",
            "4. If ALL GREEN -> stop",
            "5. If FAILED -> forward checker's RAW report to builder (do NOT interpret)",
            f"6. Repeat until ALL GREEN or stop rule triggers (max {loop.max_rounds} rounds)",
            "7. Record round result: hermes loop record <name> --passed/--failed --summary '...'",
        ],
        "principles": [
            "Tool-level hard isolation: checker physically cannot modify files",
            "Don't filter: pass checker's raw failure report to builder verbatim",
            "6 stop rules: ALL GREEN / rounds exhausted / same failure twice /",
            "  regression / no progress / beyond capability",
        ],
    })
    return guidance


def _run_generic_with_gateway(
    name: str,
    loop: Any,
    round_num: int,
    now: str,
    loop_dir: Path,
    orchestrator: Orchestrator,
) -> dict[str, Any]:
    """Run a generic loop round using the orchestrator."""
    # For now, generic patterns use guidance mode
    # Future: implement pattern-specific orchestration
    return _guidance_mode(name, loop.pattern)


def run_loop_continuous(name: str, max_rounds: int | None = None) -> dict[str, Any]:
    """Execute loop rounds continuously until a stop rule triggers.

    Args:
        name: Loop name
        max_rounds: Override max rounds (default: use loop's max_rounds)

    Returns:
        Summary of all rounds executed and final stop reason.
    """
    loop = get_loop(name)
    if not loop:
        return {"success": False, "error": f"Loop '{name}' not found"}

    effective_max = max_rounds or loop.max_rounds
    rounds_executed: list[dict[str, Any]] = []
    final_stop: dict[str, Any] = {"should_stop": False, "action": "continue"}

    while True:
        # Check budget
        budget = check_budget(name)
        if not budget.get("success"):
            break
        if budget["action"] == "hard_stop":
            final_stop = {
                "should_stop": True,
                "rule_id": "budget_exceeded",
                "rule_name": "预算耗尽",
                "description": f"Budget exhausted: {budget['used']}/{budget['limit']} tokens",
                "action": "stop_budget",
            }
            break
        if budget["action"] == "alert":
            logger.warning(
                "Budget warning: %s/%s tokens (%.1f%%)",
                budget["used"], budget["limit"], budget["percentage"],
            )

        # Execute one round
        result = run_loop(name)
        rounds_executed.append(result)

        if not result.get("success"):
            break

        # Check if guidance mode was used
        if result.get("mode") == "guidance":
            break

        # Check stop rules
        stop = result.get("stop_check", {})
        if stop.get("should_stop"):
            final_stop = stop
            break

        # Check round limit
        updated_loop = get_loop(name)
        if not updated_loop or updated_loop.current_round >= effective_max:
            final_stop = {
                "should_stop": True,
                "rule_id": "rounds_exhausted",
                "rule_name": "轮次用尽",
                "description": f"Reached {effective_max} rounds",
                "action": "stop_escalate",
            }
            break

        if updated_loop.status in (LoopStatus.COMPLETED, LoopStatus.NEEDS_HUMAN, LoopStatus.BUDGET_EXCEEDED):
            final_stop = {
                "should_stop": True,
                "rule_id": "status_change",
                "rule_name": f"状态变更: {updated_loop.status.value}",
                "description": f"Loop status changed to {updated_loop.status.value}",
                "action": "stop",
            }
            break

    return {
        "success": True,
        "loop": name,
        "rounds_executed": len(rounds_executed),
        "rounds": rounds_executed,
        "final_stop": final_stop,
    }


def resume_loop(name: str) -> dict[str, Any]:
    """Resume a loop from its last recorded state.

    Resets the loop status to RUNNING if it was NEEDS_HUMAN or ERROR,
    then continues execution from the next round.
    """
    loop = get_loop(name)
    if not loop:
        return {"success": False, "error": f"Loop '{name}' not found"}

    if loop.status in (LoopStatus.NEEDS_HUMAN, LoopStatus.ERROR):
        loop.status = LoopStatus.IDLE
        from hermes.loop import _save_loop_meta
        _save_loop_meta(loop)
        logger.info("Loop '%s' status reset to IDLE for resume", name)

    return run_loop_continuous(name)

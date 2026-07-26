"""Eval CLI subcommands.

Exposes `hermes eval <sub>` for skill-up integration:
- run: Run skill-up on a skill dir, parse result.json
- validate: Validate eval.yaml config (no execution)
- list: List cases in an eval config
- report: Generate HTML/JUnit report from a workspace

Design mirrors cli_loop.py: thin wrappers that call EvalRunner, format
output for humans, return exit codes. --json flag for machine consumption.
"""

from __future__ import annotations

import argparse
from typing import Any

from hermes.eval.client import SkillUpError, SkillUpNotFoundError
from hermes.eval.runner import EvalRunner


def _print_json(data: Any) -> None:
    import json
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ── Command handlers ────────────────────────────────────────────────


def cmd_eval_run(args: argparse.Namespace) -> int:
    """Run skill-up on a skill directory."""
    runner = EvalRunner()

    if not runner.is_available():
        print("skill-up binary not found. Install via:")
        print("  curl -fsSL https://raw.githubusercontent.com/alibaba/skill-up/main/install.sh | bash")
        return 2

    try:
        result = runner.run(
            args.skill_dir,
            include_case=args.include_case or None,
            exclude_case=args.exclude_case or None,
            fmt=args.format or None,
            output_dir=args.output_dir or None,
            iteration=args.iteration,
            engine=args.engine,
            model=args.model,
            timeout=args.timeout,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1
    except SkillUpNotFoundError as exc:
        print(f"Error: {exc}")
        return 2
    except SkillUpError as exc:
        print(f"Error: {exc}")
        return 2

    if args.json:
        _print_json(result.to_dict())
        return 0 if result.all_passed else 1

    # Human-readable summary
    print(f"Eval run completed for '{args.skill_dir}'.")
    print(f"  Total:   {result.total}")
    print(f"  Passed:  {result.passed}")
    print(f"  Failed:  {result.failed}")
    print(f"  Rate:    {result.pass_rate * 100:.1f}%")
    print(f"  Workspace: {result.workspace}")
    if result.cases:
        print("  Cases:")
        for c in result.cases:
            mark = "✓" if c.passed else "✗"
            print(f"    {mark} {c.name or c.id:<30} {c.status:<10} tokens={c.tokens_used}")
    return 0 if result.all_passed else 1


def cmd_eval_validate(args: argparse.Namespace) -> int:
    """Validate eval.yaml config (no execution)."""
    runner = EvalRunner()

    if not runner.is_available():
        print("skill-up binary not found. Install via:")
        print("  curl -fsSL https://raw.githubusercontent.com/alibaba/skill-up/main/install.sh | bash")
        return 2

    try:
        result = runner.validate(args.skill_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1
    except SkillUpNotFoundError as exc:
        print(f"Error: {exc}")
        return 2
    except SkillUpError as exc:
        print(f"Error: {exc}")
        return 2

    if args.json:
        _print_json(result.to_dict())
        return 0 if result.valid else 1

    if result.valid:
        print(f"✓ Valid ({result.case_count} case(s))")
        if result.message:
            print(f"  {result.message}")
        return 0
    else:
        print("✗ Invalid")
        if result.message:
            print(f"  {result.message}")
        return 1


def cmd_eval_list(args: argparse.Namespace) -> int:
    """List cases in an eval config."""
    runner = EvalRunner()

    if not runner.is_available():
        print("skill-up binary not found. Install via:")
        print("  curl -fsSL https://raw.githubusercontent.com/alibaba/skill-up/main/install.sh | bash")
        return 2

    try:
        cases = runner.list_cases(args.skill_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1
    except SkillUpNotFoundError as exc:
        print(f"Error: {exc}")
        return 2
    except SkillUpError as exc:
        print(f"Error: {exc}")
        return 2

    if args.json:
        _print_json(cases)
        return 0

    if not cases:
        print(f"No cases found in '{args.skill_dir}'.")
        return 0

    print(f"Cases ({len(cases)}):")
    for c in cases:
        print(f"  {c}")
    return 0


def cmd_eval_report(args: argparse.Namespace) -> int:
    """Generate report from a workspace."""
    runner = EvalRunner()

    if not runner.is_available():
        print("skill-up binary not found. Install via:")
        print("  curl -fsSL https://raw.githubusercontent.com/alibaba/skill-up/main/install.sh | bash")
        return 2

    result = runner.report(args.workspace, fmt=args.format or None)

    if args.json:
        _print_json(result)
        return 0 if result.get("success") else 1

    if not result.get("success"):
        print(f"Error: {result.get('error', 'report generation failed')}")
        return 1

    print("Report generated.")
    if result.get("stdout"):
        print(result["stdout"])
    return 0


def cmd_eval_doctor(args: argparse.Namespace) -> int:
    """Check skill-up availability and version."""
    runner = EvalRunner()

    if args.json:
        info = {
            "available": runner.is_available(),
            "version": runner.client.version() if runner.is_available() else None,
        }
        _print_json(info)
        return 0 if runner.is_available() else 1

    if not runner.is_available():
        print("✗ skill-up not installed")
        print("  Install: curl -fsSL https://raw.githubusercontent.com/alibaba/skill-up/main/install.sh | bash")
        return 1

    version = runner.client.version()
    print(f"✓ skill-up available (version: {version})")
    return 0


# ── Subparser registration ──────────────────────────────────────────


def add_eval_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register `hermes eval` subcommands."""
    p_eval = sub.add_parser("eval", help="Skill evaluation via skill-up (alibaba/skill-up)")
    eval_sub = p_eval.add_subparsers(dest="eval_cmd", required=True)

    # eval run
    p_run = eval_sub.add_parser("run", help="Run skill-up on a skill directory")
    p_run.add_argument("skill_dir", help="Path to skill directory (containing evals/eval.yaml)")
    p_run.add_argument("--include-case", action="append", help="Include case (glob, repeatable)")
    p_run.add_argument("--exclude-case", action="append", help="Exclude case (glob, repeatable)")
    p_run.add_argument("--format", action="append", help="Extra report format: junit/html (repeatable)")
    p_run.add_argument("--output-dir", help="Override default output directory")
    p_run.add_argument("--iteration", type=int, help="Iteration number (default: 1 or next)")
    p_run.add_argument("--engine", help="Override eval.yaml engine (claude_code/codex/qoder)")
    p_run.add_argument("--model", help="Override eval.yaml model (format: provider/name)")
    p_run.add_argument("--timeout", type=float, default=600.0, help="Per-run timeout in seconds")
    p_run.add_argument("--json", action="store_true", help="Output JSON")
    p_run.set_defaults(func=cmd_eval_run)

    # eval validate
    p_val = eval_sub.add_parser("validate", help="Validate eval.yaml (no execution)")
    p_val.add_argument("skill_dir", help="Path to skill directory")
    p_val.add_argument("--json", action="store_true", help="Output JSON")
    p_val.set_defaults(func=cmd_eval_validate)

    # eval list
    p_list = eval_sub.add_parser("list", help="List cases in an eval config")
    p_list.add_argument("skill_dir", help="Path to skill directory")
    p_list.add_argument("--json", action="store_true", help="Output JSON")
    p_list.set_defaults(func=cmd_eval_list)

    # eval report
    p_report = eval_sub.add_parser("report", help="Generate report from a workspace")
    p_report.add_argument("workspace", help="Path to workspace dir (iteration-N parent)")
    p_report.add_argument("--format", action="append", help="Report format: junit/html (repeatable)")
    p_report.add_argument("--json", action="store_true", help="Output JSON")
    p_report.set_defaults(func=cmd_eval_report)

    # eval doctor
    p_doc = eval_sub.add_parser("doctor", help="Check skill-up availability")
    p_doc.add_argument("--json", action="store_true", help="Output JSON")
    p_doc.set_defaults(func=cmd_eval_doctor)

"""Eval orchestration: find config, run skill-up, locate result.json.

EvalRunner ties together SkillUpClient (subprocess) + result.py (parsing)
+ filesystem conventions. It knows where skill-up writes artifacts and
how to locate them after a run.

Conventions (from skill-up docs):
- eval.yaml lives in <skill_dir>/evals/eval.yaml
- Default output dir is <skill_dir>-workspace/ (sibling of skill_dir)
- Each run writes iteration-N/ subdir; N defaults to 1
- result.json is at <output_dir>/iteration-N/result.json
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes.eval.client import SkillUpClient, SkillUpError, SkillUpNotFoundError
from hermes.eval.result import EvalResult, parse_result_json

logger = logging.getLogger("hermes.eval.runner")


@dataclass
class ValidationResult:
    """Result of `skill-up validate`. Config-only, no execution."""

    valid: bool
    case_count: int = 0
    message: str = ""
    raw_stdout: str = ""
    raw_stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "case_count": self.case_count,
            "message": self.message,
        }


@dataclass
class EvalRunner:
    """Orchestrates skill-up runs and result parsing.

    Args:
        client: SkillUpClient instance (injectable for tests).
    """

    client: SkillUpClient = field(default_factory=SkillUpClient)

    # ── Path helpers ───────────────────────────────────────────────────

    @staticmethod
    def find_eval_yaml(skill_dir: str | Path) -> Path | None:
        """Locate eval.yaml for a skill directory.

        skill-up convention: evals/eval.yaml under the skill dir.
        Returns None if not found (caller decides whether to error).
        """
        skill_path = Path(skill_dir)
        candidates = [
            skill_path / "evals" / "eval.yaml",
            skill_path / "eval.yaml",  # fallback: flat layout
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    @staticmethod
    def default_output_dir(skill_dir: str | Path) -> Path:
        """Compute default output dir for a skill.

        skill-up writes to <skill_dir>-workspace/ (sibling, not child).
        """
        skill_path = Path(skill_dir).resolve()
        return skill_path.parent / f"{skill_path.name}-workspace"

    @staticmethod
    def find_latest_iteration(workspace: str | Path) -> Path | None:
        """Find the latest iteration-N/ dir in a workspace.

        Returns the highest-N iteration dir, or None if none exist.
        """
        ws = Path(workspace)
        if not ws.exists():
            return None
        # Match iteration-N directories
        iter_re = re.compile(r"^iteration-(\d+)$")
        iterations: list[tuple[int, Path]] = []
        for child in ws.iterdir():
            if not child.is_dir():
                continue
            m = iter_re.match(child.name)
            if m:
                iterations.append((int(m.group(1)), child))
        if not iterations:
            return None
        # Highest N wins
        iterations.sort(key=lambda t: t[0])
        return iterations[-1][1]

    @staticmethod
    def find_result_json(workspace: str | Path) -> Path | None:
        """Locate result.json in the latest iteration of a workspace."""
        latest = EvalRunner.find_latest_iteration(workspace)
        if latest is None:
            return None
        result = latest / "result.json"
        return result if result.exists() else None

    # ── Operations ─────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if skill-up binary is available."""
        return self.client.is_available()

    def validate(self, skill_dir: str | Path) -> ValidationResult:
        """Run `skill-up validate`. Config-only, no Agent execution.

        Raises:
            SkillUpNotFoundError: binary missing.
            SkillUpError: invocation failed.
            FileNotFoundError: eval.yaml not found in skill_dir.
        """
        eval_yaml = self.find_eval_yaml(skill_dir)
        if eval_yaml is None:
            raise FileNotFoundError(
                f"evals/eval.yaml not found in {skill_dir}. "
                "Create one with `skill-up init` or manually."
            )

        try:
            proc = self.client.validate(eval_yaml, cwd=skill_dir)
        except SkillUpError as exc:
            return ValidationResult(
                valid=False,
                message=str(exc),
                raw_stderr=str(exc),
            )

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        # skill-up validate outputs: "✓ eval.yaml is valid (loaded N case(s))"
        # Parse case count from stdout; fall back to 0.
        case_count = 0
        m = re.search(r"loaded\s+(\d+)\s+case", stdout)
        if m:
            case_count = int(m.group(1))

        return ValidationResult(
            valid=proc.returncode == 0,
            case_count=case_count,
            message=stdout.strip() or stderr.strip(),
            raw_stdout=stdout,
            raw_stderr=stderr,
        )

    def list_cases(self, skill_dir: str | Path) -> list[str]:
        """Run `skill-up list-cases`. Returns list of case IDs.

        Returns empty list on error (with logged warning).
        """
        eval_yaml = self.find_eval_yaml(skill_dir)
        if eval_yaml is None:
            raise FileNotFoundError(
                f"evals/eval.yaml not found in {skill_dir}"
            )

        try:
            proc = self.client.list_cases(eval_yaml, cwd=skill_dir)
        except SkillUpError as exc:
            logger.warning("skill-up list-cases failed: %s", exc)
            return []

        if proc.returncode != 0:
            logger.warning(
                "skill-up list-cases exited %d: %s",
                proc.returncode,
                proc.stderr or proc.stdout,
            )
            return []

        # Parse case IDs from stdout (one per line, or JSON)
        stdout = proc.stdout or ""
        lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        return lines

    def run(
        self,
        skill_dir: str | Path,
        *,
        include_case: list[str] | None = None,
        exclude_case: list[str] | None = None,
        fmt: list[str] | None = None,
        output_dir: str | Path | None = None,
        iteration: int | None = None,
        engine: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> EvalResult:
        """Run `skill-up run` and parse result.json.

        Args:
            skill_dir: Directory containing evals/eval.yaml (or SKILL.md).
            include_case/exclude_case: Glob filters for case selection.
            fmt: Extra report formats (e.g. ["junit", "html"]).
            output_dir: Override default <skill>-workspace/ location.
            iteration: Override iteration number (default: 1 or next).
            engine: Override eval.yaml engine.
            model: Override eval.yaml model (format: provider/name).
            timeout: Per-run timeout in seconds.

        Returns:
            EvalResult parsed from result.json.

        Raises:
            SkillUpNotFoundError: binary missing.
            SkillUpError: invocation failed (timeout, OSError).
            FileNotFoundError: eval.yaml or result.json not found.
        """
        eval_yaml = self.find_eval_yaml(skill_dir)
        if eval_yaml is None:
            raise FileNotFoundError(
                f"evals/eval.yaml not found in {skill_dir}"
            )

        effective_output = Path(output_dir) if output_dir else self.default_output_dir(skill_dir)

        try:
            proc = self.client.run(
                eval_yaml,
                include_case=include_case,
                exclude_case=exclude_case,
                fmt=fmt,
                output_dir=effective_output,
                iteration=iteration,
                engine=engine,
                model=model,
                timeout=timeout,
                cwd=skill_dir,
            )
        except SkillUpNotFoundError:
            raise
        except SkillUpError as exc:
            logger.error("skill-up run failed: %s", exc)
            raise

        # skill-up may exit non-zero on partial failures; result.json
        # is still written. Log the exit code but don't suppress parsing.
        if proc.returncode != 0:
            logger.warning(
                "skill-up run exited %d (partial failure?). stderr=%s",
                proc.returncode,
                (proc.stderr or "")[:500],
            )

        # Locate result.json
        result_path = self.find_result_json(effective_output)
        if result_path is None:
            raise FileNotFoundError(
                f"result.json not found in {effective_output} after run. "
                f"skill-up stdout: {proc.stdout or ''}"
            )

        return parse_result_json(result_path)

    def report(
        self,
        workspace: str | Path,
        *,
        fmt: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run `skill-up report` on a workspace. Returns parsed output.

        Returns dict with stdout/stderr/returncode. Caller formats as needed.
        """
        try:
            proc = self.client.report(workspace, fmt=fmt)
        except SkillUpError as exc:
            return {"success": False, "error": str(exc)}

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }

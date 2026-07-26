"""Bridge skill-up eval results into GEPA's evaluator interface.

GEPA's `EvaluateFn` signature is:
    (variant: dict, benchmark_task: str, benchmark_context: str) -> dict
where the returned dict has VariantResult fields (variant_id, success,
tokens_used, rounds_to_converge, failure_items, error).

This module produces such an evaluator backed by skill-up. The evaluator:
1. Looks up the skill_dir associated with the variant (via variant.metadata).
2. Runs `skill-up run` on that skill_dir.
3. Parses result.json into EvalResult.
4. Maps EvalResult → VariantResult-shaped dict.

The mapping is conservative:
- success = eval_result.all_passed (all cases passed)
- tokens_used = sum of all case tokens
- rounds_to_converge = 1 (single eval run; GEPA loop adds rounds externally)
- failure_items = list of failed case IDs + their errors
- error = None (or error message if skill-up itself crashed)

Design note: the evaluator returns a dict (not VariantResult) because
hermes.loop._maybe_run_gepa wraps it via an adapter that constructs
VariantResult. Keeping the bridge dict-based avoids importing gepa here,
preserving the decoupling (eval module knows nothing about GEPA).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from hermes.eval.client import SkillUpError
from hermes.eval.runner import EvalRunner
from hermes.eval.result import EvalResult

logger = logging.getLogger("hermes.eval.gepa_bridge")

# Type alias: GEPA evaluator signature (variant dict, task, context) -> result dict.
# Matches hermes.loop._maybe_run_gepa's expected evaluator shape.
GepaEvaluator = Callable[[dict[str, Any], str, str], dict[str, Any]]


def eval_result_to_variant_dict(
    result: EvalResult,
    variant_id: str,
    error: str | None = None,
) -> dict[str, Any]:
    """Map an EvalResult into a VariantResult-shaped dict.

    Args:
        result: Parsed skill-up result.
        variant_id: ID of the variant being evaluated.
        error: If skill-up itself crashed, the error message (overrides success).

    Returns:
        Dict with keys: variant_id, success, tokens_used,
        rounds_to_converge, failure_items, error.
    """
    if error is not None:
        return {
            "variant_id": variant_id,
            "success": False,
            "tokens_used": 0,
            "rounds_to_converge": 0,
            "failure_items": [],
            "error": error,
        }

    # Collect failure items: "<case_id>: <error or status>"
    failure_items: list[str] = []
    for case in result.cases:
        if not case.passed:
            err = case.error or case.status
            failure_items.append(f"{case.id or case.name}: {err}")

    return {
        "variant_id": variant_id,
        "success": result.all_passed,
        "tokens_used": sum(c.tokens_used for c in result.cases),
        "rounds_to_converge": 1 if result.all_passed else 0,
        "failure_items": failure_items,
        "error": None,
    }


def make_evaluator(
    skill_dir_resolver: Callable[[dict[str, Any]], str | Path | None],
    *,
    runner: EvalRunner | None = None,
    include_case: list[str] | None = None,
    exclude_case: list[str] | None = None,
    fmt: list[str] | None = None,
    output_dir: str | Path | None = None,
    engine: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> GepaEvaluator:
    """Build a GEPA evaluator backed by skill-up.

    Args:
        skill_dir_resolver: Function that takes a variant dict and returns
            the skill_dir to evaluate. Typically reads variant["metadata"]["skill_dir"]
            or variant["agent_file"] parent. Returns None if no skill_dir
            can be resolved (evaluator reports failure with clear error).
        runner: EvalRunner to use (default: new EvalRunner with default client).
        include_case/exclude_case/fmt/output_dir/engine/model/timeout:
            Forwarded to EvalRunner.run().

    Returns:
        GepaEvaluator callable matching GEPA's EvaluateFn shape (returns dict).

    The returned evaluator never raises — all errors are caught and returned
    as failed VariantResult dicts. This is critical because GEPA's
    run_gepa_cycle wraps each variant evaluation in try/except, but we
    preserve that contract defensively.
    """
    eval_runner = runner or EvalRunner()

    def evaluator(variant: dict[str, Any], task: str, context: str) -> dict[str, Any]:
        variant_id = str(variant.get("variant_id", ""))

        # Resolve skill_dir from variant metadata
        try:
            skill_dir = skill_dir_resolver(variant)
        except Exception as exc:  # noqa: BLE001 — resolver is user-supplied
            logger.exception("skill_dir_resolver crashed for variant %s", variant_id)
            return eval_result_to_variant_dict(
                EvalResult(),  # empty
                variant_id=variant_id,
                error=f"resolver crash: {type(exc).__name__}: {exc}",
            )

        if skill_dir is None:
            return eval_result_to_variant_dict(
                EvalResult(),
                variant_id=variant_id,
                error=f"no skill_dir resolved for variant {variant_id}",
            )

        # Run skill-up
        try:
            result = eval_runner.run(
                skill_dir,
                include_case=include_case,
                exclude_case=exclude_case,
                fmt=fmt,
                output_dir=output_dir,
                engine=engine,
                model=model,
                timeout=timeout,
            )
        except (SkillUpError, FileNotFoundError) as exc:
            logger.warning(
                "skill-up run failed for variant %s: %s", variant_id, exc
            )
            return eval_result_to_variant_dict(
                EvalResult(),
                variant_id=variant_id,
                error=f"skill-up run failed: {type(exc).__name__}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — defensive: don't crash GEPA
            logger.exception(
                "unexpected error evaluating variant %s", variant_id
            )
            return eval_result_to_variant_dict(
                EvalResult(),
                variant_id=variant_id,
                error=f"unexpected: {type(exc).__name__}: {exc}",
            )

        return eval_result_to_variant_dict(result, variant_id=variant_id)

    return evaluator


def default_skill_dir_resolver(variant: dict[str, Any]) -> str | Path | None:
    """Default resolver: read skill_dir from variant metadata.

    Convention: variant["metadata"]["skill_dir"] holds the path.
    Falls back to None if not set.

    This is a sensible default for variants declared in loop meta.json:
        gepa_variants:
          - variant_id: v1
            agent_file: builder.md
            description: "..."
            metadata:
              skill_dir: /path/to/my-skill
    """
    metadata = variant.get("metadata") or {}
    skill_dir = metadata.get("skill_dir")
    if skill_dir:
        return str(skill_dir)
    return None

"""GEPA (Generate-Evaluate-Promote-Apply) cycle for self-evolution.

A minimal prototype (雏形) of periodic self-improvement:
- Generate: caller supplies variant agent definitions (different prompts)
- Evaluate: each variant runs on a benchmark task via a caller-supplied fn
- Promote: pick the winner by a scoring function (success >> tokens >> rounds)
- Apply: persist promotion record for audit + future retrieval

Design principles (第一性原理):
- Decoupled: GEPA does not depend on Orchestrator internals. Evaluation is
  delegated to a caller-supplied callable, making the module testable in
  isolation and allowing future evaluation backends (mock / Orchestrator /
  external benchmark service).
- Audit-first: every experiment is persisted to disk. Self-evolution without
  audit trail is dangerous (a bad promotion can silently regress the system).
- Conservative promotion: only successful variants get promoted. If all
  variants fail, no promotion happens (better no evolution than wrong evolution).
- Scoring is explicit and tunable, not magic: success dominates, then token
  efficiency, then convergence speed.

This is a 雏形: variant generation is manual (caller supplies variants).
Future iterations can add LLM-driven variant generation and cross-project
promotion.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("hermes.gepa")


# ── Scoring weights ──────────────────────────────────────────────────
#
# Priority: success >> tokens >> rounds.
# - Success is binary and dominant: a successful variant always beats a failed
#   one regardless of token cost (correctness > efficiency).
# - SUCCESS_WEIGHT is sized to dominate the worst-case penalty envelope so the
#   "success always wins" contract holds for any realistic benchmark:
#     worst_case_penalty = |TOKENS| * 1_000_000 + |ROUNDS| * 100
#                       = 0.01 * 1_000_000 + 50 * 100 = 10_000 + 5_000 = 15_000
#   SUCCESS_WEIGHT=20_000 leaves a 5_000 safety margin below that envelope.
#   Bumping TOKENS/ROUNDS magnitudes requires re-checking this bound.
# - Token efficiency: slight negative weight (fewer tokens = higher score).
#   Weight is small so it only breaks ties between successful variants.
# - Rounds to converge: moderate negative weight. Faster convergence is better
#   but secondary to correctness and token cost.
SCORE_WEIGHT_SUCCESS = 20000.0
SCORE_WEIGHT_TOKENS = -0.01
SCORE_WEIGHT_ROUNDS = -50.0


# ── Data model ───────────────────────────────────────────────────────


@dataclass
class Variant:
    """A candidate agent definition variant for GEPA evaluation.

    The agent_file field points to an agent definition .md file (e.g., a
    builder.md with a different prompt strategy). GEPA itself does not parse
    the file — it just passes the path to the evaluation function.
    """

    variant_id: str
    agent_file: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "agent_file": self.agent_file,
            "description": self.description,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Variant":
        return cls(
            variant_id=str(data.get("variant_id", "")),
            agent_file=str(data.get("agent_file", "")),
            description=str(data.get("description", "")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class VariantResult:
    """Evaluation result for a single variant.

    Fields are designed to map cleanly onto RoundResult metrics:
    - success: did the variant solve the benchmark task?
    - tokens_used: total tokens consumed (efficiency signal)
    - rounds_to_converge: how many builder-checker rounds to ALL GREEN
      (0 = never converged; lower is better)
    - failure_items: verbatim failure list (for debugging failed variants)
    - error: exception message if evaluation crashed (None = clean run)
    """

    variant_id: str
    success: bool = False
    tokens_used: int = 0
    rounds_to_converge: int = 0
    failure_items: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "success": self.success,
            "tokens_used": self.tokens_used,
            "rounds_to_converge": self.rounds_to_converge,
            "failure_items": list(self.failure_items),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VariantResult":
        return cls(
            variant_id=str(data.get("variant_id", "")),
            success=bool(data.get("success", False)),
            tokens_used=int(data.get("tokens_used", 0) or 0),
            rounds_to_converge=int(data.get("rounds_to_converge", 0) or 0),
            failure_items=list(data.get("failure_items") or []),
            error=data.get("error"),
        )


@dataclass
class GEPAExperiment:
    """A complete GEPA cycle: variants + benchmark + results + winner.

    Lifecycle: created (variants set) -> running (results filling in) ->
    completed (winner picked, if any). The winner_id is None when no variant
    succeeded — conservative promotion policy.
    """

    experiment_id: str
    benchmark_task: str
    benchmark_context: str = ""
    variants: list[Variant] = field(default_factory=list)
    results: list[VariantResult] = field(default_factory=list)
    winner_id: str | None = None
    promotion_reason: str = ""
    created_at: str = ""
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "benchmark_task": self.benchmark_task,
            "benchmark_context": self.benchmark_context,
            "variants": [v.to_dict() for v in self.variants],
            "results": [r.to_dict() for r in self.results],
            "winner_id": self.winner_id,
            "promotion_reason": self.promotion_reason,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GEPAExperiment":
        return cls(
            experiment_id=str(data.get("experiment_id", "")),
            benchmark_task=str(data.get("benchmark_task", "")),
            benchmark_context=str(data.get("benchmark_context", "")),
            variants=[Variant.from_dict(v) for v in data.get("variants") or []],
            results=[VariantResult.from_dict(r) for r in data.get("results") or []],
            winner_id=data.get("winner_id"),
            promotion_reason=str(data.get("promotion_reason", "")),
            created_at=str(data.get("created_at", "")),
            completed_at=data.get("completed_at"),
        )


# ── Scoring ──────────────────────────────────────────────────────────


def score_variant(result: VariantResult) -> float:
    """Score a variant result. Higher = better.

    Priority: success >> tokens >> rounds.
    Failed variants still get a score (for ranking/debugging), but a
    successful variant always outscores a failed one due to the dominant
    success weight.

    The weights are module-level constants (SCORE_WEIGHT_*) so they can be
    tuned without code changes to the scoring function.
    """
    score = 0.0
    if result.success:
        score += SCORE_WEIGHT_SUCCESS
    score += SCORE_WEIGHT_TOKENS * result.tokens_used
    score += SCORE_WEIGHT_ROUNDS * result.rounds_to_converge
    return score


# ── Cycle orchestration ──────────────────────────────────────────────


# Evaluation function signature: takes (variant, benchmark_task,
# benchmark_context) and returns a VariantResult. The caller supplies this
# so GEPA stays decoupled from Orchestrator internals.
EvaluateFn = Callable[[Variant, str, str], VariantResult]


def run_gepa_cycle(
    benchmark_task: str,
    variants: list[Variant],
    evaluate_fn: EvaluateFn,
    benchmark_context: str = "",
) -> GEPAExperiment:
    """Run one GEPA cycle: evaluate all variants on the benchmark, pick winner.

    Args:
        benchmark_task: The task description all variants must solve.
        variants: List of Variant objects (each points to an agent .md file).
        evaluate_fn: Caller-supplied evaluation function. Called once per
            variant with (variant, benchmark_task, benchmark_context).
            Must return a VariantResult. Exceptions are caught and recorded
            as failed VariantResult (with error message), so one bad variant
            does not crash the whole cycle.
        benchmark_context: Additional context for the benchmark task.

    Returns:
        GEPAExperiment with results filled in and winner_id set (or None if
        no variant succeeded).

    Conservative promotion: winner is only set if at least one variant
    succeeded. If all fail, winner_id=None and promotion_reason explains why.
    """
    experiment = GEPAExperiment(
        experiment_id=str(uuid.uuid4()),
        benchmark_task=benchmark_task,
        benchmark_context=benchmark_context,
        variants=list(variants),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    if not variants:
        # No variants = nothing to evaluate. Mark completed with no winner.
        experiment.winner_id = None
        experiment.promotion_reason = "no variants provided"
        experiment.completed_at = datetime.now(timezone.utc).isoformat()
        logger.warning("GEPA cycle %s: no variants provided", experiment.experiment_id)
        return experiment

    # Evaluate each variant (failures isolated — one bad variant doesn't crash cycle)
    for variant in variants:
        try:
            result = evaluate_fn(variant, benchmark_task, benchmark_context)
            # Sanity: ensure variant_id matches (caller may have forgotten)
            if not result.variant_id:
                result.variant_id = variant.variant_id
        except Exception as exc:  # noqa: BLE001 - GEPA must be crash-resistant
            logger.exception(
                "GEPA cycle %s: variant %s evaluation crashed",
                experiment.experiment_id, variant.variant_id,
            )
            result = VariantResult(
                variant_id=variant.variant_id,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        experiment.results.append(result)

    # Pick winner by score (only successful variants are eligible)
    successful = [r for r in experiment.results if r.success]
    if successful:
        best = max(successful, key=score_variant)
        experiment.winner_id = best.variant_id
        experiment.promotion_reason = (
            f"score={score_variant(best):.2f} "
            f"(tokens={best.tokens_used}, rounds={best.rounds_to_converge}, "
            f"variants_evaluated={len(experiment.results)}, "
            f"successful={len(successful)})"
        )
        logger.info(
            "GEPA cycle %s: promoted variant %s (%s)",
            experiment.experiment_id, best.variant_id, experiment.promotion_reason,
        )
    else:
        experiment.winner_id = None
        experiment.promotion_reason = (
            f"no variant succeeded out of {len(experiment.results)} evaluated; "
            "no promotion (conservative policy)"
        )
        logger.warning(
            "GEPA cycle %s: no variant succeeded", experiment.experiment_id,
        )

    experiment.completed_at = datetime.now(timezone.utc).isoformat()
    return experiment


# ── Persistence ──────────────────────────────────────────────────────


def gepa_dir() -> Path:
    """Return the GEPA registry directory (created lazily on first save)."""
    root = Path(__file__).resolve().parents[2]
    return root / ".gepa"


def save_experiment(experiment: GEPAExperiment) -> Path:
    """Persist an experiment to .gepa/<experiment_id>.json.

    Returns the path written. Creates .gepa/ if missing. Audit trail:
    every experiment (success or failure) is persisted, never overwritten.
    """
    out_dir = gepa_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{experiment.experiment_id}.json"
    out_path.write_text(
        json.dumps(experiment.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_path


def load_experiment(experiment_id: str) -> GEPAExperiment | None:
    """Load an experiment by ID. Returns None if not found."""
    path = gepa_dir() / f"{experiment_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to load GEPA experiment %s", experiment_id)
        return None
    return GEPAExperiment.from_dict(data)


def list_experiments() -> list[GEPAExperiment]:
    """List all persisted experiments, sorted by created_at descending."""
    out_dir = gepa_dir()
    if not out_dir.exists():
        return []
    experiments: list[GEPAExperiment] = []
    for entry in sorted(out_dir.iterdir(), reverse=True):
        if not entry.is_file() or entry.suffix != ".json":
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
            experiments.append(GEPAExperiment.from_dict(data))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    # Sort by created_at desc (newest first)
    experiments.sort(key=lambda e: e.created_at, reverse=True)
    return experiments


def get_latest_promotion() -> GEPAExperiment | None:
    """Return the most recent experiment that promoted a winner.

    Used to look up the current "production" variant. Returns None if no
    experiment has ever promoted a winner.
    """
    for experiment in list_experiments():
        if experiment.winner_id is not None:
            return experiment
    return None

"""Three-state deterministic scoring for agent evaluation.

Adapted from the Agent Trajectory-As-Judge methodology (see
``knowledge/harness-evaluation-methodology.md`` for the source analysis):

- **benchmark 判定唯一权威** — the verifier reward is the trust anchor;
  scorers never re-judge pass/fail, only attribute finer-grained signal
  on top of it.
- **三维正交** — outcome / compliance / process each own one question
  (this module implements outcome; compliance lives in
  ``hermes.eval.compliance``).
- **三态语义** — every dimension is either ``verified`` (has evidence,
  scored) or ``not_verifiable`` (evidence structurally missing). NV
  dimensions are excluded from normalization — never guessed, never
  silently defaulted to 0 in the denominator.
- **缺证据 ≠ 合规/满分** — a run without recoverable evidence cannot rank
  alongside an evidenced run; the no-trajectory cap enforces this.
- **封顶（caps）** — reward<1 → 0.50; reward missing → 0.70; timeout →
  0.50 then −0.10; no trajectory → 0.85. A constraint-violating or
  unauditable run must not tie with a clean full mark.

All scoring is rule-based and deterministic: same input, same output
(distinguishes this from LLM-as-judge variance and leniency bias).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = [
    "DimensionScore",
    "OutcomeScore",
    "apply_cap",
    "normalize",
    "score_outcome",
]

# Dimension states
VERIFIED = "verified"
NOT_VERIFIABLE = "not_verifiable"

# Outcome dimension weights (sum to 1.0 over the verified set)
WEIGHT_O1_VERIFIER = 0.55
WEIGHT_O2_ASSERTIONS = 0.25
WEIGHT_O3_ARTIFACTS = 0.20

# Cap values (keep unauditable / constraint-violating runs below clean marks)
CAP_REWARD_BELOW_ONE = 0.50
CAP_REWARD_MISSING = 0.70
CAP_TIMEOUT = 0.50
CAP_NO_TRAJECTORY = 0.85
TIMEOUT_EXTRA_PENALTY = 0.10


@dataclass
class DimensionScore:
    """One scored dimension with explicit evidence state."""

    dimension_id: str
    weight: float
    score: float = 0.0
    state: str = VERIFIED
    explanation: str = ""

    @property
    def effective_weight(self) -> float:
        """Weight counted in normalization: 0 for not_verifiable dims."""
        return self.weight if self.state == VERIFIED else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension_id": self.dimension_id,
            "weight": self.weight,
            "score": round(self.score, 4),
            "state": self.state,
            "explanation": self.explanation,
        }


def normalize(dimensions: Sequence[DimensionScore]) -> tuple[float, bool]:
    """Weighted mean over verified dimensions only.

    Returns ``(score, all_not_verifiable)``. When every dimension is NV the
    score is 0.0 and the flag is True — "no evidence" must surface as a
    distinct verdict, not as a silent zero that mixes with evidenced zeros.
    """
    total_w = sum(d.effective_weight for d in dimensions)
    if total_w <= 0:
        return 0.0, True
    raw = sum(d.score * d.effective_weight for d in dimensions) / total_w
    return max(0.0, min(1.0, raw)), False


@dataclass
class OutcomeScore:
    """Result of the outcome scorer: dimensions + raw + capped final."""

    dimensions: list[DimensionScore] = field(default_factory=list)
    raw: float = 0.0
    score: float = 0.0
    caps_applied: list[str] = field(default_factory=list)
    not_verifiable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": [d.to_dict() for d in self.dimensions],
            "raw": round(self.raw, 4),
            "score": round(self.score, 4),
            "caps_applied": list(self.caps_applied),
            "not_verifiable": self.not_verifiable,
        }


def apply_cap(score: float, cap: float, reason: str, caps: list[str]) -> float:
    """Apply a ceiling to *score*, recording the reason when it binds."""
    if score > cap:
        caps.append(reason)
        return cap
    return score


def score_outcome(
    *,
    verifier_reward: float | None,
    case_results: Sequence[tuple[str, bool]] | None = None,
    required_artifacts: Sequence[str] | None = None,
    written_artifacts: Sequence[str] | None = None,
    duration_sec: float | None = None,
    budget_sec: float | None = None,
    has_trajectory: bool = True,
) -> OutcomeScore:
    """Score task completion (outcome) on top of the verifier verdict.

    Args:
        verifier_reward: The benchmark verifier's reward (1.0/0.0), the sole
            authority on pass/fail. ``None`` when the reward is missing
            (eval crashed before producing a verdict).
        case_results: Per-assertion/per-case ``(id, passed)`` pairs when the
            verifier emits itemized detail; ``None`` when only an aggregate
            exists.
        required_artifacts: Paths the answer key actually checks. ``None``
            when the task declares none (O3 becomes not_verifiable).
        written_artifacts: Paths actually written by the agent. ``None``
            when there is no write evidence (counts as nothing written).
        duration_sec / budget_sec: Wall-clock usage and declared budget.
            Touching the budget caps the score — time limits are part of
            the task contract, not an environment detail.
        has_trajectory: Whether an auditable trajectory exists. Runs
            without one cannot tie with evidenced full marks.

    Returns:
        OutcomeScore with O1/O2/O3 dimensions, raw normalized score, and
        the capped final score.
    """
    dims: list[DimensionScore] = []

    # ── O1: verifier verdict (55%) — never re-judged, only adopted ──
    if verifier_reward is not None:
        reward = max(0.0, min(1.0, float(verifier_reward)))
        dims.append(
            DimensionScore(
                dimension_id="O1",
                weight=WEIGHT_O1_VERIFIER,
                score=reward,
                explanation=f"verifier reward adopted as-is: {reward}",
            )
        )
    elif case_results:
        # Fallback per the methodology: reward missing → aggregate pass rate.
        passed = sum(1 for _cid, ok in case_results if ok)
        agg = passed / len(case_results)
        dims.append(
            DimensionScore(
                dimension_id="O1",
                weight=WEIGHT_O1_VERIFIER,
                score=agg,
                explanation=f"reward missing; fell back to aggregate pass rate {passed}/{len(case_results)}",
            )
        )
    else:
        dims.append(
            DimensionScore(
                dimension_id="O1",
                weight=WEIGHT_O1_VERIFIER,
                state=NOT_VERIFIABLE,
                explanation="no verifier reward and no per-case detail",
            )
        )

    # ── O2: assertion-unit pass rate (25%) ──
    if case_results:
        passed = sum(1 for _cid, ok in case_results if ok)
        dims.append(
            DimensionScore(
                dimension_id="O2",
                weight=WEIGHT_O2_ASSERTIONS,
                score=passed / len(case_results),
                explanation=f"{passed}/{len(case_results)} assertion units passed",
            )
        )
    else:
        dims.append(
            DimensionScore(
                dimension_id="O2",
                weight=WEIGHT_O2_ASSERTIONS,
                state=NOT_VERIFIABLE,
                explanation="no itemized per-case results",
            )
        )

    # ── O3: artifact completeness (20%) ──
    if required_artifacts:
        required = list(required_artifacts)
        written = set(written_artifacts or [])
        produced = [p for p in required if p in written]
        dims.append(
            DimensionScore(
                dimension_id="O3",
                weight=WEIGHT_O3_ARTIFACTS,
                score=len(produced) / len(required),
                explanation=(
                    f"{len(produced)}/{len(required)} required artifacts written"
                    + (f"; missing: {sorted(set(required) - written)}" if len(produced) < len(required) else "")
                ),
            )
        )
    else:
        dims.append(
            DimensionScore(
                dimension_id="O3",
                weight=WEIGHT_O3_ARTIFACTS,
                state=NOT_VERIFIABLE,
                explanation="answer key declares no artifact paths",
            )
        )

    raw, all_nv = normalize(dims)
    caps: list[str] = []
    score = raw

    # Cap order follows the methodology's severity ladder. The timeout cap
    # applies even when reward=1: a finished-but-late run must not tie with
    # an on-time full mark (observed methodology cases score exactly 0.50).
    # The extra −0.10 penalty stacks only when the reward verdict was also
    # bad/missing (double violation: late AND not clean).
    if not has_trajectory:
        score = apply_cap(score, CAP_NO_TRAJECTORY, "no-trajectory:<=0.85", caps)
    reward_bad = verifier_reward is None or verifier_reward < 1
    if verifier_reward is None:
        score = apply_cap(score, CAP_REWARD_MISSING, "reward-missing:<=0.70", caps)
    elif verifier_reward < 1:
        score = apply_cap(score, CAP_REWARD_BELOW_ONE, "reward<1:<=0.50", caps)
    timed_out = (
        duration_sec is not None
        and budget_sec is not None
        and budget_sec > 0
        and duration_sec >= budget_sec
    )
    if timed_out:
        score = apply_cap(score, CAP_TIMEOUT, "timeout:<=0.50", caps)
        if reward_bad:
            score = max(0.0, score - TIMEOUT_EXTRA_PENALTY)
            caps.append("timeout-extra:-0.10")

    return OutcomeScore(
        dimensions=dims,
        raw=raw,
        score=score,
        caps_applied=caps,
        not_verifiable=all_nv,
    )

"""Statistical significance for GEPA promotion (split-run + Welch's t-test).

P1-6: a variant must not be promoted on a single lucky run. Promotion now
requires *min_repeats* independent evaluation runs per variant and a
statistically significant score difference (Welch's t-test, p < alpha).

Zero external dependencies: the incomplete-beta function and t-distribution
CDF are implemented directly (Numerical Recipes continued-fraction method),
so the project keeps its stdlib-only constraint.

Public surface:
    * :func:`mean` / :func:`stddev` — basic sample statistics
    * :func:`welch_ttest` — (t_statistic, p_value) for two independent samples
    * :func:`compare_variants` — significance verdict for baseline vs challenger
    * :class:`SplitRunResult` — structured verdict
    * :func:`should_promote` — high-level promotion gate
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "SplitRunResult",
    "compare_variants",
    "mean",
    "should_promote",
    "stddev",
    "welch_ttest",
]


# ---------------------------------------------------------------------------
# Basic statistics
# ---------------------------------------------------------------------------


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean of *values* (empty → 0.0)."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _sample_variance(values: Sequence[float]) -> float:
    """Sample variance (n-1 denominator). Empty/single → 0.0."""
    n = len(values)
    if n < 2:
        return 0.0
    m = mean(values)
    return sum((x - m) ** 2 for x in values) / (n - 1)


def stddev(values: Sequence[float]) -> float:
    """Sample standard deviation (empty → 0.0)."""
    return math.sqrt(_sample_variance(values))


# ---------------------------------------------------------------------------
# Incomplete beta function (regularized I_x(a, b)) — Numerical Recipes betacf
# ---------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function."""
    max_iter = 200
    eps = 3.0e-7
    fpmin = 1.0e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _incomplete_beta(x: float, a: float, b: float) -> float:
    """Regularized incomplete beta function I_x(a, b) for 0 <= x <= 1."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    bt = math.exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_survival(t: float, df: float) -> float:
    """Two-sided survival of Student's t: P(|T| > t) for t >= 0."""
    if t <= 0.0:
        return 1.0
    x = df / (df + t * t)
    return _incomplete_beta(x, df / 2.0, 0.5)


# ---------------------------------------------------------------------------
# Welch's t-test
# ---------------------------------------------------------------------------


def welch_ttest(
    sample_a: Sequence[float],
    sample_b: Sequence[float],
) -> tuple[float, float]:
    """Two-sample Welch's t-test (unequal variances).

    Returns ``(t_statistic, p_value)``. The p-value is two-sided. Handles the
    degenerate cases (empty / zero-variance samples) gracefully so callers
    never divide by zero.
    """
    n_a, n_b = len(sample_a), len(sample_b)
    if n_a < 2 or n_b < 2:
        # Not enough data to estimate variance → not significant.
        return 0.0, 1.0
    mean_a, mean_b = mean(sample_a), mean(sample_b)
    var_a = _sample_variance(sample_a)
    var_b = _sample_variance(sample_b)
    denom_a = var_a / n_a
    denom_b = var_b / n_b
    se = math.sqrt(denom_a + denom_b)
    if se == 0.0:
        # Identical samples (zero variance difference).
        if mean_a == mean_b:
            return 0.0, 1.0
        # Deterministic difference with zero noise → infinitely significant.
        return float("inf"), 0.0
    t = (mean_a - mean_b) / se
    # Welch–Satterthwaite degrees of freedom.
    df_num = (denom_a + denom_b) ** 2
    df_den = (denom_a**2) / (n_a - 1) + (denom_b**2) / (n_b - 1)
    df = df_num / df_den if df_den > 0 else 1.0
    p = _t_survival(abs(t), df)
    return t, p


# ---------------------------------------------------------------------------
# Split-run comparison
# ---------------------------------------------------------------------------


@dataclass
class SplitRunResult:
    """Verdict of a split-run comparison between two variants."""

    baseline_scores: list[float]
    challenger_scores: list[float]
    baseline_mean: float
    challenger_mean: float
    t_statistic: float
    p_value: float
    alpha: float
    min_repeats: int

    @property
    def enough_repeats(self) -> bool:
        """Both variants ran at least ``min_repeats`` times."""
        return (
            len(self.baseline_scores) >= self.min_repeats
            and len(self.challenger_scores) >= self.min_repeats
        )

    @property
    def challenger_better(self) -> bool:
        """Challenger's mean score is strictly higher than baseline's."""
        return self.challenger_mean > self.baseline_mean

    @property
    def significant(self) -> bool:
        """Two-sided p-value below ``alpha``."""
        return self.p_value < self.alpha

    @property
    def promote(self) -> bool:
        """Promote only when there is enough data, the challenger is better,
        and the difference is statistically significant."""
        return self.enough_repeats and self.challenger_better and self.significant


def compare_variants(
    baseline_scores: Sequence[float],
    challenger_scores: Sequence[float],
    *,
    alpha: float = 0.05,
    min_repeats: int = 5,
) -> SplitRunResult:
    """Compare a challenger against a baseline using Welch's t-test.

    Args:
        baseline_scores: repeated scores of the incumbent variant.
        challenger_scores: repeated scores of the candidate variant.
        alpha: significance threshold (default 0.05).
        min_repeats: minimum runs per variant before promotion is allowed.

    Returns a :class:`SplitRunResult`; callers gate on ``result.promote``.
    """
    base = list(baseline_scores)
    chal = list(challenger_scores)
    t, p = welch_ttest(base, chal)
    return SplitRunResult(
        baseline_scores=base,
        challenger_scores=chal,
        baseline_mean=mean(base),
        challenger_mean=mean(chal),
        t_statistic=t,
        p_value=p,
        alpha=alpha,
        min_repeats=min_repeats,
    )


def should_promote(
    baseline_scores: Sequence[float],
    challenger_scores: Sequence[float],
    *,
    alpha: float = 0.05,
    min_repeats: int = 5,
) -> bool:
    """High-level gate: True only if promotion is statistically justified."""
    return compare_variants(
        baseline_scores,
        challenger_scores,
        alpha=alpha,
        min_repeats=min_repeats,
    ).promote

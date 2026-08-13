"""Tests for hermes.gepa_stats (split-run statistical significance)."""

from __future__ import annotations

import math

from hermes.gepa_stats import (
    SplitRunResult,
    compare_variants,
    mean,
    should_promote,
    stddev,
    welch_ttest,
)


# ---------------------------------------------------------------------------
# Basic statistics
# ---------------------------------------------------------------------------


def test_mean_empty_is_zero() -> None:
    assert mean([]) == 0.0


def test_mean_basic() -> None:
    assert mean([1.0, 2.0, 3.0]) == 2.0


def test_stddev_basic() -> None:
    # [1, 2, 3, 4, 5] sample variance = 2.5 → stddev = sqrt(2.5)
    assert math.isclose(stddev([1.0, 2.0, 3.0, 4.0, 5.0]), math.sqrt(2.5))


def test_stddev_single_element_zero() -> None:
    assert stddev([5.0]) == 0.0


# ---------------------------------------------------------------------------
# Welch's t-test
# ---------------------------------------------------------------------------


def test_welch_ttest_clearly_separated() -> None:
    """Two clearly separated samples should yield a small p-value."""
    t, p = welch_ttest([1.0, 2.0, 3.0, 4.0, 5.0], [6.0, 7.0, 8.0, 9.0, 10.0])
    assert t < 0  # baseline mean is lower
    assert p < 0.01


def test_welch_ttest_identical_samples_not_significant() -> None:
    """Identical samples → p ≈ 1.0."""
    t, p = welch_ttest([1.0, 2.0, 3.0, 4.0, 5.0], [2.0, 1.0, 3.0, 5.0, 4.0])
    assert p == 1.0


def test_welch_ttest_small_sample_not_significant() -> None:
    """Insufficient data (<2 each) → p = 1.0 (conservative)."""
    _, p = welch_ttest([1.0], [5.0])
    assert p == 1.0


def test_welch_ttest_symmetric() -> None:
    """Swapping samples should flip the t-statistic sign, keep p identical."""
    a = [1.0, 2.0, 3.0, 4.0, 5.0]
    b = [6.0, 7.0, 8.0, 9.0, 10.0]
    t1, p1 = welch_ttest(a, b)
    t2, p2 = welch_ttest(b, a)
    assert math.isclose(t1, -t2, rel_tol=1e-9)
    assert math.isclose(p1, p2, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# compare_variants / should_promote
# ---------------------------------------------------------------------------


def _baseline() -> list[float]:
    return [10.0, 11.0, 10.5, 10.2, 10.8]


def _challenger() -> list[float]:
    return [15.0, 16.0, 15.5, 14.8, 15.2]


def test_compare_variants_significant_better() -> None:
    result = compare_variants(_baseline(), _challenger())
    assert isinstance(result, SplitRunResult)
    assert result.enough_repeats
    assert result.challenger_better
    assert result.significant
    assert result.promote


def test_should_promote_significant_better() -> None:
    assert should_promote(_baseline(), _challenger())


def test_no_promote_when_challenger_worse() -> None:
    """A worse challenger must not be promoted even if the gap is significant."""
    assert not should_promote(_challenger(), _baseline())


def test_no_promote_when_not_significant() -> None:
    """Overlapping distributions → not significant → no promotion."""
    noise_a = [10.0, 11.0, 12.0, 9.0, 11.5, 10.5, 10.2]
    noise_b = [10.5, 9.5, 11.2, 10.0, 11.8, 10.3, 10.1]
    result = compare_variants(noise_a, noise_b)
    assert not result.promote


def test_no_promote_when_insufficient_repeats() -> None:
    """Fewer than min_repeats runs → no promotion regardless of gap."""
    result = compare_variants([10.0], [20.0], min_repeats=5)
    assert not result.enough_repeats
    assert not result.promote


def test_min_repeats_respected_with_custom_threshold() -> None:
    """With min_repeats=2, a strong 2-vs-2 gap should promote."""
    result = compare_variants([10.0, 10.5], [20.0, 19.5], min_repeats=2)
    assert result.enough_repeats
    assert result.promote

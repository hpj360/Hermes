"""Tests for agent_evolve.stats: Welch's t-test, promotion gate, degenerate cases."""

from __future__ import annotations

import math

from agent_evolve.stats import (
    compare_variants,
    mean,
    should_promote,
    stddev,
    welch_ttest,
)


class TestBasicStats:
    def test_mean(self):
        assert mean([1.0, 2.0, 3.0]) == 2.0

    def test_mean_empty(self):
        assert mean([]) == 0.0

    def test_stddev(self):
        # stddev of [2, 4] with n-1 denominator: sqrt(((2-3)^2+(4-3)^2)/1) = sqrt(2)
        assert math.isclose(stddev([2.0, 4.0]), math.sqrt(2.0))

    def test_stddev_empty(self):
        assert stddev([]) == 0.0


class TestWelchTtest:
    def test_clearly_different_samples_significant(self):
        a = [10.0, 10.5, 10.2, 10.3, 10.4]
        b = [20.0, 20.5, 20.2, 20.3, 20.4]
        t, p = welch_ttest(a, b)
        assert abs(t) > 10
        assert p < 0.001

    def test_identical_samples_not_significant(self):
        a = [5.0, 5.0, 5.0, 5.0]
        _t, p = welch_ttest(a, list(a))
        assert p == 1.0

    def test_too_few_samples(self):
        t, p = welch_ttest([1.0], [2.0, 3.0])
        assert t == 0.0
        assert p == 1.0

    def test_zero_variance_not_significant(self):
        # Deterministic gap must not be flagged significant.
        _t, p = welch_ttest([1.0, 1.0, 1.0], [2.0, 2.0, 2.0])
        assert p == 1.0


class TestCompareVariants:
    def test_promote_on_clear_win(self):
        baseline = [50 + (i % 3) * 0.1 for i in range(10)]
        challenger = [80 + (i % 3) * 0.1 for i in range(10)]
        result = compare_variants(baseline, challenger, alpha=0.05, min_repeats=5)
        assert result.challenger_better
        assert result.significant
        assert result.promote is True

    def test_no_promote_on_tie(self):
        scores = [50.0, 51.0, 49.0, 50.5, 49.5]
        result = compare_variants(scores, list(scores), alpha=0.05, min_repeats=5)
        assert result.challenger_better is False
        assert result.promote is False

    def test_no_promote_when_worse(self):
        baseline = [80.0] * 10
        challenger = [50.0] * 10
        # Zero variance -> not significant; even with variance, worse is worse.
        result = compare_variants(baseline, challenger)
        assert result.challenger_better is False
        assert result.promote is False

    def test_not_enough_repeats_blocks_promotion(self):
        baseline = [50.0, 50.1]
        challenger = [80.0, 80.1]
        result = compare_variants(baseline, challenger, min_repeats=5)
        assert result.enough_repeats is False
        assert result.promote is False


class TestShouldPromote:
    def test_gate_true_only_when_justified(self):
        baseline = [50.0 + (i % 4) for i in range(12)]
        challenger = [70.0 + (i % 4) for i in range(12)]
        assert should_promote(baseline, challenger, min_repeats=5) is True

    def test_gate_false_on_noise(self):
        baseline = [50.0, 50.2, 49.8, 50.1, 49.9, 50.0]
        challenger = [50.1, 49.9, 50.0, 50.2, 49.8, 50.1]
        assert should_promote(baseline, challenger, min_repeats=5) is False

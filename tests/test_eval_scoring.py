"""Tests for hermes.eval.scoring: three-state semantics, outcome partial credit, caps.

Methodology reference: knowledge/harness-evaluation-methodology.md
(Agent Trajectory-As-Judge, Alibaba AgentLoop DSH evaluation practice).
"""

from __future__ import annotations

from hermes.eval.scoring import (
    NOT_VERIFIABLE,
    VERIFIED,
    DimensionScore,
    apply_cap,
    normalize,
    score_outcome,
)


# ── normalize: three-state semantics ─────────────────────────────────


class TestNormalize:
    def test_weighted_mean_over_verified(self):
        dims = [
            DimensionScore("O1", 0.55, 1.0),
            DimensionScore("O2", 0.25, 0.5),
            DimensionScore("O3", 0.20, 0.0),
        ]
        score, all_nv = normalize(dims)
        assert score == 0.55 + 0.125
        assert all_nv is False

    def test_not_verifiable_excluded_from_denominator(self):
        # O3 NV → denominator shrinks to 0.8; O1=0, O2=0 → score 0 but verified
        dims = [
            DimensionScore("O1", 0.55, 0.0),
            DimensionScore("O2", 0.25, 0.0),
            DimensionScore("O3", 0.20, state=NOT_VERIFIABLE),
        ]
        score, all_nv = normalize(dims)
        assert score == 0.0
        assert all_nv is False

    def test_nv_exclusion_changes_score(self):
        # With O3 NV and O1=1, O2=1 → 1.0 (not 0.8) — NV dims must not
        # silently drag the score down like zero-valued verified dims would.
        dims = [
            DimensionScore("O1", 0.55, 1.0),
            DimensionScore("O2", 0.25, 1.0),
            DimensionScore("O3", 0.20, 0.0, state=NOT_VERIFIABLE),
        ]
        score, _ = normalize(dims)
        assert score == 1.0

    def test_all_not_verifiable_flags(self):
        dims = [
            DimensionScore("O1", 0.55, state=NOT_VERIFIABLE),
            DimensionScore("O2", 0.25, state=NOT_VERIFIABLE),
        ]
        score, all_nv = normalize(dims)
        assert score == 0.0
        assert all_nv is True

    def test_clamped_to_unit_interval(self):
        dims = [DimensionScore("O1", 1.0, 2.0)]
        score, _ = normalize(dims)
        assert score == 1.0


# ── apply_cap ────────────────────────────────────────────────────────


class TestApplyCap:
    def test_cap_binds_and_records(self):
        caps: list[str] = []
        assert apply_cap(0.9, 0.5, "cap:0.5", caps) == 0.5
        assert caps == ["cap:0.5"]

    def test_cap_not_binding_silent(self):
        caps: list[str] = []
        assert apply_cap(0.3, 0.5, "cap:0.5", caps) == 0.3
        assert caps == []


# ── score_outcome: dimensions ────────────────────────────────────────


class TestOutcomeDimensions:
    def test_full_pass_scores_one(self):
        s = score_outcome(
            verifier_reward=1.0,
            case_results=[("t1", True), ("t2", True)],
            required_artifacts=["a.csv"],
            written_artifacts=["a.csv"],
        )
        assert s.raw == 1.0
        assert s.score == 1.0
        assert s.caps_applied == []
        assert all(d.state == VERIFIED for d in s.dimensions)

    def test_reward_adopted_never_rejudged(self):
        # reward=0 with all cases "passed" → O1 still 0 (verifier is authority)
        s = score_outcome(
            verifier_reward=0.0,
            case_results=[("t1", True)],
        )
        assert s.dimensions[0].score == 0.0

    def test_o2_partial_credit(self):
        # reward=0 but 1/2 assertions passed → O2=0.5 gives failure gradient
        s = score_outcome(
            verifier_reward=0.0,
            case_results=[("t1", True), ("t2", False)],
        )
        o2 = next(d for d in s.dimensions if d.dimension_id == "O2")
        assert o2.score == 0.5

    def test_o1_falls_back_to_aggregate_when_reward_missing(self):
        s = score_outcome(
            verifier_reward=None,
            case_results=[("t1", True), ("t2", True), ("t3", False)],
        )
        o1 = next(d for d in s.dimensions if d.dimension_id == "O1")
        assert o1.state == VERIFIED
        assert abs(o1.score - 2 / 3) < 1e-9
        assert "fell back" in o1.explanation

    def test_o3_counts_written_only(self):
        # "仅提及不算，跑测试不算写" — only actually-written artifacts count
        s = score_outcome(
            verifier_reward=1.0,
            required_artifacts=["a.csv", "b.csv", "c.csv"],
            written_artifacts=["a.csv"],  # mentioned b/c but never wrote them
        )
        o3 = next(d for d in s.dimensions if d.dimension_id == "O3")
        assert o3.score == 1 / 3
        assert "missing" in o3.explanation

    def test_o3_not_verifiable_when_undeclared(self):
        s = score_outcome(
            verifier_reward=1.0,
            required_artifacts=None,
        )
        o3 = next(d for d in s.dimensions if d.dimension_id == "O3")
        assert o3.state == NOT_VERIFIABLE

    def test_o3_zero_when_required_but_no_write_evidence(self):
        s = score_outcome(
            verifier_reward=1.0,
            required_artifacts=["a.csv"],
            written_artifacts=None,
        )
        o3 = next(d for d in s.dimensions if d.dimension_id == "O3")
        assert o3.state == VERIFIED
        assert o3.score == 0.0

    def test_all_nv_flags_outcome(self):
        s = score_outcome(verifier_reward=None, case_results=None)
        assert s.not_verifiable is True
        assert s.raw == 0.0


# ── score_outcome: caps (methodology fidelity) ───────────────────────


class TestOutcomeCaps:
    def test_reward_below_one_caps_at_half(self):
        # Partial reward 0.9 with all assertions+artifacts done → raw 0.945,
        # capped 0.5: a non-clean verdict can never tie with a full mark.
        s = score_outcome(
            verifier_reward=0.9,
            case_results=[("t1", True), ("t2", True)],
            required_artifacts=["a.csv"],
            written_artifacts=["a.csv"],
        )
        assert abs(s.raw - 0.945) < 1e-9
        assert s.score == 0.5
        assert "reward<1:<=0.50" in s.caps_applied

    def test_reward_zero_raw_never_exceeds_cap(self):
        # reward=0 → O1 contributes 0, raw ≤ 0.45 by construction; the cap
        # is then redundant but the invariant (score ≤ 0.5) still holds.
        s = score_outcome(
            verifier_reward=0.0,
            case_results=[("t1", True)],
            required_artifacts=["a.csv"],
            written_artifacts=["a.csv"],
        )
        assert s.raw == 0.45
        assert s.score <= 0.5

    def test_reward_missing_caps_at_07(self):
        s = score_outcome(
            verifier_reward=None,
            case_results=[("t1", True), ("t2", True)],
        )
        assert s.score <= 0.70
        assert "reward-missing:<=0.70" in s.caps_applied

    def test_timeout_caps_even_when_reward_is_one(self):
        # hf-model-inference pattern: reward=1, raw=1.0, over budget → 0.5
        # (no extra −0.10: the run was late but the verdict was clean)
        s = score_outcome(
            verifier_reward=1.0,
            case_results=[("t1", True)],
            duration_sec=1207.0,
            budget_sec=900.0,
        )
        assert s.raw == 1.0
        assert s.score == 0.5
        assert "timeout:<=0.50" in s.caps_applied
        assert "timeout-extra:-0.10" not in s.caps_applied

    def test_timeout_extra_penalty_only_on_stacked_violation(self):
        # reward<1 AND timeout → double violation: raw-penalized −0.10
        s = score_outcome(
            verifier_reward=0.0,
            case_results=[("t1", True), ("t2", False)],
            duration_sec=1000.0,
            budget_sec=900.0,
        )
        # raw: O1=0, O2=0.5, O3 NV → 0.125/0.80 = 0.15625
        assert abs(s.raw - 0.15625) < 1e-9
        assert abs(s.score - 0.05625) < 1e-9
        assert "timeout-extra:-0.10" in s.caps_applied

    def test_no_trajectory_caps_at_085(self):
        s = score_outcome(
            verifier_reward=1.0,
            case_results=[("t1", True)],
            has_trajectory=False,
        )
        assert s.score == 0.85
        assert "no-trajectory:<=0.85" in s.caps_applied

    def test_on_time_run_uncapped(self):
        s = score_outcome(
            verifier_reward=1.0,
            case_results=[("t1", True)],
            duration_sec=800.0,
            budget_sec=900.0,
        )
        assert s.score == 1.0
        assert s.caps_applied == []

    def test_zero_budget_disables_timeout_cap(self):
        s = score_outcome(
            verifier_reward=1.0,
            case_results=[("t1", True)],
            duration_sec=9999.0,
            budget_sec=0,
        )
        assert s.score == 1.0

    def test_to_dict_roundtrip_shape(self):
        s = score_outcome(
            verifier_reward=0.0,
            case_results=[("t1", False)],
            required_artifacts=["a"],
        )
        d = s.to_dict()
        assert {"dimensions", "raw", "score", "caps_applied", "not_verifiable"} <= set(d)
        assert d["dimensions"][0]["dimension_id"] == "O1"

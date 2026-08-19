"""Tests for agent_budget_guard: tiered three-layer token circuit breaker semantics."""

from __future__ import annotations

from agent_budget_guard import (
    AGENT_FAILURE_THRESHOLD,
    BudgetGuard,
    DifficultyTier,
    RoleFailureTracker,
    TIER_BUDGETS,
    TokenLimitBreaker,
    resolve_tier,
    tier_budget,
)

# ── Layer 1: TokenLimitBreaker ──────────────────────────────────────


class TestTokenLimitBreaker:
    def test_under_limit_allowed(self):
        v = TokenLimitBreaker().check(tokens_used=1000, limit=50_000)
        assert v.allowed and not v.tripped

    def test_over_limit_trips(self):
        v = TokenLimitBreaker().check(tokens_used=50_001, limit=50_000)
        assert v.tripped
        assert "Token limit exceeded" in v.message
        assert v.tokens_used == 50_001
        assert v.limit == 50_000

    def test_exactly_at_limit_allowed(self):
        # Strictly greater-than semantics: 50000 used with 50000 limit passes.
        v = TokenLimitBreaker().check(tokens_used=50_000, limit=50_000)
        assert not v.tripped

    def test_zero_or_negative_limit_disables(self):
        b = TokenLimitBreaker()
        assert not b.check(tokens_used=10**9, limit=0).tripped
        assert not b.check(tokens_used=10**9, limit=-1).tripped


# ── Layer 2: RoleFailureTracker ─────────────────────────────────────


class TestRoleFailureTracker:
    def test_single_failure_not_tripped(self):
        t = RoleFailureTracker()
        t.update({"builder": "failed"})
        assert t.tripped_roles() == []

    def test_two_consecutive_failures_trip(self):
        t = RoleFailureTracker()
        t.update({"builder": "failed"})
        t.update({"builder": "failed"})
        assert t.tripped_roles() == ["builder"]
        assert t.is_tripped("builder")

    def test_success_resets_window(self):
        t = RoleFailureTracker()
        t.update({"builder": "failed"})
        t.update({"builder": "completed"})  # success window reset
        t.update({"builder": "failed"})
        assert t.tripped_roles() == []  # 1 consecutive failure only

    def test_non_failed_status_also_resets(self):
        t = RoleFailureTracker()
        t.update({"builder": "failed"})
        t.update({"builder": "unknown"})
        assert t.failure_counts["builder"] == 0

    def test_absent_role_keeps_count(self):
        # A role skipped by the fuse must not have its count reset by the skip.
        t = RoleFailureTracker()
        t.update({"builder": "failed"})
        t.update({"checker": "completed"})  # builder absent this round
        assert t.failure_counts["builder"] == 1

    def test_empty_or_none_status_noop(self):
        t = RoleFailureTracker(failure_counts={"builder": 1})
        t.update({})
        t.update(None)
        assert t.failure_counts == {"builder": 1}

    def test_multiple_roles_tracked_independently(self):
        t = RoleFailureTracker()
        t.update({"builder": "failed", "checker": "failed"})
        t.update({"builder": "failed", "checker": "completed"})
        assert t.tripped_roles() == ["builder"]
        assert not t.is_tripped("checker")

    def test_default_threshold_constant(self):
        assert AGENT_FAILURE_THRESHOLD == 2

    def test_custom_threshold(self):
        t = RoleFailureTracker(threshold=3)
        t.update({"builder": "failed"})
        t.update({"builder": "failed"})
        assert t.tripped_roles() == []
        t.update({"builder": "failed"})
        assert t.tripped_roles() == ["builder"]

    def test_roundtrip_serialization(self):
        t = RoleFailureTracker()
        t.update({"builder": "failed"})
        restored = RoleFailureTracker.from_dict(t.to_dict())
        assert restored.failure_counts == {"builder": 1}


class TestRoleFailureTrackerDeserialization:
    def test_drops_non_string_keys(self):
        raw = {1: 2, "builder": 1}
        t = RoleFailureTracker.from_dict(raw)
        assert t.failure_counts == {"builder": 1}

    def test_drops_non_int_values(self):
        raw = {"builder": 1, "checker": "2", "meta": None, "ratio": 1.5}
        t = RoleFailureTracker.from_dict(raw)
        assert t.failure_counts == {"builder": 1}

    def test_bool_values_rejected(self):
        # bool is an int subclass but must not sneak through.
        raw = {"builder": True}
        t = RoleFailureTracker.from_dict(raw)
        assert t.failure_counts == {}

    def test_non_dict_input(self):
        assert RoleFailureTracker.from_dict(None).failure_counts == {}
        assert RoleFailureTracker.from_dict("junk").failure_counts == {}
        assert RoleFailureTracker.from_dict([1, 2]).failure_counts == {}


# ── Layer 3: BudgetGuard ────────────────────────────────────────────


class TestBudgetGuard:
    def test_under_budget(self):
        g = BudgetGuard(used=0, limit=100_000)
        v = g.add(40_000)
        assert not v.exceeded
        assert v.used == 40_000
        assert v.remaining == 60_000
        assert v.terminal is None

    def test_exactly_exhausted_trips(self):
        # used >= limit trips (nothing left for another round).
        g = BudgetGuard(used=0, limit=100_000)
        v = g.add(100_000)
        assert v.exceeded
        assert v.terminal == "budget_exceeded"

    def test_accumulates_across_rounds(self):
        g = BudgetGuard(used=0, limit=100)
        g.add(30)
        g.add(30)
        v = g.add(40)
        assert v.exceeded
        assert g.used == 100
        assert g.history == [30, 30, 40]

    def test_negative_tokens_clamped(self):
        g = BudgetGuard(used=0, limit=100)
        g.add(-50)
        assert g.used == 0

    def test_zero_or_negative_limit_disables(self):
        g = BudgetGuard(used=10**9, limit=0)
        assert not g.check().exceeded
        g2 = BudgetGuard(used=10**9, limit=-1)
        assert not g2.check().exceeded

    def test_exceeded_takes_priority_over_green(self):
        # Mirrors record_round: budget-exceeded wins even if the round passed.
        g = BudgetGuard(used=0, limit=100)
        v = g.add(100)
        assert v.exceeded  # a green-but-over-budget loop must still stop

    def test_remaining_never_negative(self):
        g = BudgetGuard(used=200, limit=100)
        assert g.check().remaining == 0

    def test_disabled_limit_remaining_sentinel(self):
        g = BudgetGuard(used=200, limit=0)
        assert g.check().remaining == -1

    def test_rounds_remaining(self):
        g = BudgetGuard(used=0, limit=100_000)
        assert g.rounds_remaining(25_000) == 4
        assert g.rounds_remaining(30_000) == 3

    def test_rounds_remaining_zero_when_exhausted(self):
        g = BudgetGuard(used=100_000, limit=100_000)
        assert g.rounds_remaining(25_000) == 0

    def test_rounds_remaining_disabled_or_bad_estimate(self):
        g = BudgetGuard(used=10, limit=0)
        assert g.rounds_remaining(1000) == 10**9
        assert g.rounds_remaining(0) == 10**9
        assert g.rounds_remaining(-5) == 10**9


# ── Layer 0: difficulty-tiered budgets ──────────────────────────────


class TestResolveTier:
    def test_explicit_declaration_wins(self):
        assert resolve_tier(declared="hard") is DifficultyTier.HARD
        assert resolve_tier(declared="easy") is DifficultyTier.EASY

    def test_declaration_case_and_whitespace_tolerant(self):
        assert resolve_tier(declared="  HARD ") is DifficultyTier.HARD
        assert resolve_tier(declared="Medium") is DifficultyTier.MEDIUM

    def test_declaration_overrides_assertion_count(self):
        """显式声明优先于断言数推导（契约声明是最高权威）。"""
        assert resolve_tier(declared="easy", assertion_count=50) is DifficultyTier.EASY

    def test_unknown_declaration_falls_back_to_medium(self):
        """脏元数据回退 MEDIUM，不抛异常（guard 必须降级而非崩溃）。"""
        assert resolve_tier(declared="extreme") is DifficultyTier.MEDIUM
        assert resolve_tier(declared="") is DifficultyTier.MEDIUM
        assert resolve_tier(declared=None, assertion_count=None) is DifficultyTier.MEDIUM

    def test_derived_from_assertion_count_boundaries(self):
        """未声明时按 answer key 的断言单元数推导。"""
        assert resolve_tier(assertion_count=0) is DifficultyTier.EASY
        assert resolve_tier(assertion_count=2) is DifficultyTier.EASY
        assert resolve_tier(assertion_count=3) is DifficultyTier.MEDIUM
        assert resolve_tier(assertion_count=8) is DifficultyTier.MEDIUM
        assert resolve_tier(assertion_count=9) is DifficultyTier.HARD
        assert resolve_tier(assertion_count=100) is DifficultyTier.HARD

    def test_negative_assertion_count_ignored(self):
        assert resolve_tier(assertion_count=-3) is DifficultyTier.MEDIUM


class TestTierBudgets:
    def test_budgets_monotonic_by_tier(self):
        """预算随难度单调递增（锁死配置，防止编辑倒挂）。"""
        assert (
            TIER_BUDGETS[DifficultyTier.EASY]
            < TIER_BUDGETS[DifficultyTier.MEDIUM]
            < TIER_BUDGETS[DifficultyTier.HARD]
        )

    def test_tier_budget_lookup(self):
        assert tier_budget(DifficultyTier.EASY) == TIER_BUDGETS[DifficultyTier.EASY]
        assert tier_budget(DifficultyTier.HARD) == TIER_BUDGETS[DifficultyTier.HARD]

    def test_for_tier_constructor_sets_limit(self):
        g = BudgetGuard.for_tier(DifficultyTier.HARD)
        assert g.limit == TIER_BUDGETS[DifficultyTier.HARD]
        assert g.used == 0

    def test_for_tier_preserves_used(self):
        g = BudgetGuard.for_tier(DifficultyTier.EASY, used=40_000)
        assert g.used == 40_000

    def test_hard_task_not_starved_by_medium_budget(self):
        """分档动机：hard 任务的消耗在 medium 预算下会被误判 budget_exceeded，
        用 hard 档预算则不会（区分"预算不足"与"能力不足"）。"""
        spend = 1_200_000
        medium_guard = BudgetGuard.for_tier(DifficultyTier.MEDIUM)
        assert medium_guard.add(spend).exceeded is True  # flat budget starves

        hard_guard = BudgetGuard.for_tier(DifficultyTier.HARD)
        assert hard_guard.add(spend).exceeded is False  # tiered budget fits

    def test_easy_task_still_fused(self):
        """分档不是放松：easy 任务超档预算仍然熔断。"""
        g = BudgetGuard.for_tier(DifficultyTier.EASY)
        verdict = g.add(TIER_BUDGETS[DifficultyTier.EASY])
        assert verdict.exceeded is True
        assert verdict.terminal == "budget_exceeded"

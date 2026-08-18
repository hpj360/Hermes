"""Tests for agent_budget_guard: three-layer token circuit breaker semantics."""

from __future__ import annotations

from agent_budget_guard import (
    AGENT_FAILURE_THRESHOLD,
    BudgetGuard,
    RoleFailureTracker,
    TokenLimitBreaker,
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

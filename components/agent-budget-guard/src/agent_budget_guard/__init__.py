"""agent-budget-guard: tiered three-layer token circuit breaker for multi-agent systems."""

from .guard import (
    AGENT_FAILURE_THRESHOLD,
    BudgetGuard,
    BudgetVerdict,
    DifficultyTier,
    RoleFailureTracker,
    TIER_BUDGETS,
    TokenLimitBreaker,
    TokenVerdict,
    resolve_tier,
    tier_budget,
)

__all__ = [
    "AGENT_FAILURE_THRESHOLD",
    "BudgetGuard",
    "BudgetVerdict",
    "DifficultyTier",
    "RoleFailureTracker",
    "TIER_BUDGETS",
    "TokenLimitBreaker",
    "TokenVerdict",
    "resolve_tier",
    "tier_budget",
]

__version__ = "0.2.0"

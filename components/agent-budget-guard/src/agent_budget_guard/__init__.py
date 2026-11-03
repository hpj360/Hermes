"""agent-budget-guard: tiered three-layer token circuit breaker for multi-agent systems."""

from .guard import (
    AGENT_FAILURE_THRESHOLD,
    TIER_BUDGETS,
    BudgetGuard,
    BudgetVerdict,
    DifficultyTier,
    RoleFailureTracker,
    TokenLimitBreaker,
    TokenVerdict,
    resolve_tier,
    tier_budget,
)

__all__ = [
    "AGENT_FAILURE_THRESHOLD",
    "TIER_BUDGETS",
    "BudgetGuard",
    "BudgetVerdict",
    "DifficultyTier",
    "RoleFailureTracker",
    "TokenLimitBreaker",
    "TokenVerdict",
    "resolve_tier",
    "tier_budget",
]

__version__ = "0.2.0"

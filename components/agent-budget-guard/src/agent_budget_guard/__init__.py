"""agent-budget-guard: three-layer token circuit breaker for multi-agent systems."""

from .guard import (
    AGENT_FAILURE_THRESHOLD,
    BudgetGuard,
    BudgetVerdict,
    RoleFailureTracker,
    TokenLimitBreaker,
    TokenVerdict,
)

__all__ = [
    "AGENT_FAILURE_THRESHOLD",
    "BudgetGuard",
    "BudgetVerdict",
    "RoleFailureTracker",
    "TokenLimitBreaker",
    "TokenVerdict",
]

__version__ = "0.1.0"

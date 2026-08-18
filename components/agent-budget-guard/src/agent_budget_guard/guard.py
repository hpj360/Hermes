"""Three-layer token circuit breaker for multi-agent systems.

The failure mode this package guards against: a multi-agent loop where one
agent (or one role, or the whole loop) keeps burning tokens without making
progress. Without fuses at every layer, a single stuck agent can drain the
entire budget.

The three layers, from finest to coarsest:

**Layer 1 — per-agent token limit** (:class:`TokenLimitBreaker`).
Each dispatched agent gets a token ceiling; exceeding it flips the run from
``completed`` to ``failed``. ``limit <= 0`` disables the check (backward
compatible).

**Layer 2 — per-role consecutive-failure skip** (:class:`RoleFailureTracker`).
A role that fails *N times in a row* (default 2 — the first failure may be
noise such as a network blip; two consecutive failures mean the role really
cannot do the task) is tripped: the next round skips dispatching it at all.
A single success resets the counter (sliding success window). A role absent
from a round's status map keeps its counter — an agent skipped by the fuse
must not have its failure count reset by the skip itself.

**Layer 3 — loop-wide budget fuse** (:class:`BudgetGuard`).
Accumulates tokens across rounds against a total limit. When used >= limit,
the loop must stop (budget-exceeded terminal state) — this check takes
priority over "all checks passed" so a green-but-over-budget loop cannot
silently continue. ``limit <= 0`` disables the fuse.

Extracted from the Hermes agent framework (orchestrator._check_token_limit,
loop._update_failure_counts / get_tripped_roles / record_round budget gate),
with the loop state machine decoupled into plain classes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AGENT_FAILURE_THRESHOLD",
    "BudgetGuard",
    "BudgetVerdict",
    "RoleFailureTracker",
    "TokenLimitBreaker",
    "TokenVerdict",
]

# Layer 2 threshold: a role failing this many consecutive rounds is tripped.
# 1 failure may be noise; 2 consecutive failures mean the role truly cannot
# complete the current task — continuing would just burn tokens.
AGENT_FAILURE_THRESHOLD = 2


# ── Layer 1: per-agent token limit ──────────────────────────────────


@dataclass
class TokenVerdict:
    """Outcome of a Layer-1 token limit check."""

    tripped: bool
    tokens_used: int = 0
    limit: int = 0
    message: str = ""

    @property
    def allowed(self) -> bool:
        return not self.tripped


class TokenLimitBreaker:
    """Layer 1: fail an agent run that exceeded its token ceiling.

    Semantics (mirrors Hermes ``orchestrator._check_token_limit``):
    - ``limit <= 0`` disables the check (always allowed).
    - ``tokens_used > limit`` trips: the run is marked failed even if the
      agent itself reported success.
    - Exactly at the limit is allowed (strictly greater-than).
    """

    def check(self, tokens_used: int, limit: int) -> TokenVerdict:
        if limit <= 0:
            return TokenVerdict(tripped=False, tokens_used=tokens_used, limit=limit)
        if tokens_used > limit:
            return TokenVerdict(
                tripped=True,
                tokens_used=tokens_used,
                limit=limit,
                message=(
                    f"Token limit exceeded: used {tokens_used}, limit {limit}"
                ),
            )
        return TokenVerdict(tripped=False, tokens_used=tokens_used, limit=limit)


# ── Layer 2: per-role consecutive-failure skip ──────────────────────


class RoleFailureTracker:
    """Layer 2: trip roles that keep failing, skip them next round.

    Feed each round's ``{role: "completed"|"failed"|...}`` map into
    :meth:`update`; query :meth:`tripped_roles` before dispatching the next
    round. Semantics (mirrors Hermes ``loop._update_failure_counts``):

    - ``failed`` status: counter +1
    - any non-failed status (completed / unknown / ...): counter reset to 0
    - role absent from the map: counter unchanged (a role skipped by this
      fuse must not have its count reset by the skip)
    - empty / None status map: no-op (round recorded nothing)
    """

    def __init__(
        self,
        failure_counts: dict[str, int] | None = None,
        threshold: int = AGENT_FAILURE_THRESHOLD,
    ) -> None:
        self.failure_counts: dict[str, int] = dict(failure_counts or {})
        self.threshold = threshold

    def update(self, agent_status: dict[str, str] | None) -> None:
        if not agent_status:
            return
        for role, status in agent_status.items():
            if status == "failed":
                self.failure_counts[role] = self.failure_counts.get(role, 0) + 1
            else:
                # Any non-failed status counts as success: reset the window.
                self.failure_counts[role] = 0

    def tripped_roles(self) -> list[str]:
        return [role for role, count in self.failure_counts.items() if count >= self.threshold]

    def is_tripped(self, role: str) -> bool:
        return self.failure_counts.get(role, 0) >= self.threshold

    def to_dict(self) -> dict[str, int]:
        return dict(self.failure_counts)

    @classmethod
    def from_dict(cls, raw: Any, threshold: int = AGENT_FAILURE_THRESHOLD) -> RoleFailureTracker:
        """Strict deserialization: drop non-str keys and non-int values.

        Guards against dirty data (hand-edited state files) entering the
        state machine. ``bool`` is explicitly rejected even though it is an
        ``int`` subclass.
        """
        if not isinstance(raw, dict):
            return cls(threshold=threshold)
        counts: dict[str, int] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                counts[key] = value
        return cls(failure_counts=counts, threshold=threshold)


# ── Layer 3: loop-wide budget fuse ──────────────────────────────────


@dataclass
class BudgetVerdict:
    """Outcome of a Layer-3 budget check after recording a round."""

    exceeded: bool
    used: int = 0
    limit: int = 0
    remaining: int = 0

    @property
    def terminal(self) -> str | None:
        """Terminal state to force when exceeded, else None.

        Budget-exceeded takes priority over "all checks passed": a loop that
        is green but over budget must still stop.
        """
        return "budget_exceeded" if self.exceeded else None


@dataclass
class BudgetGuard:
    """Layer 3: accumulate round spend against a loop-wide token budget.

    Semantics (mirrors the Hermes ``record_round`` budget gate):
    - ``limit <= 0`` disables the fuse (never exceeded).
    - A round's tokens are added *before* the check.
    - ``used >= limit`` (not strictly greater) trips the fuse — once the
      budget is fully consumed there is nothing left for another round.
    """

    used: int = 0
    limit: int = 500_000
    history: list[int] = field(default_factory=list)

    def add(self, tokens: int) -> BudgetVerdict:
        """Record one round's spend and return the verdict."""
        self.used += max(0, tokens)
        self.history.append(max(0, tokens))
        return self.check()

    def check(self) -> BudgetVerdict:
        exceeded = self.limit > 0 and self.used >= self.limit
        return BudgetVerdict(
            exceeded=exceeded,
            used=self.used,
            limit=self.limit,
            remaining=max(0, self.limit - self.used) if self.limit > 0 else -1,
        )

    def rounds_remaining(self, per_round_estimate: int) -> int:
        """How many more rounds the budget can absorb, given an estimate.

        Returns a large sentinel (``10**9``) when the fuse is disabled or
        the estimate is non-positive.
        """
        if self.limit <= 0 or per_round_estimate <= 0:
            return 10**9
        return max(0, (self.limit - self.used) // per_round_estimate)

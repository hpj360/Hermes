# agent-budget-guard

Three-layer token circuit breaker for multi-agent systems: **per-agent token limit → per-role consecutive-failure skip → loop-wide budget fuse**. Prevents runaway token burn from a single agent, a repeatedly failing role, or an entire loop. **Zero dependencies** (Python 3.10+, stdlib only).

Extracted from the [Hermes](https://github.com/hpj360/Hermes) agent framework (`orchestrator._check_token_limit`, `loop._update_failure_counts` / `get_tripped_roles` / the `record_round` budget gate), decoupled from the loop state machine into plain, composable classes.

## Why

The failure mode of unguarded multi-agent loops: something gets stuck (a builder that cannot solve the task, a checker that always fails, a task that never converges) and the loop keeps dispatching round after round, burning the entire token budget on work that will never succeed.

A single fuse is not enough — the failure can live at three different granularities, so the guard must too:

| Layer | Failure it stops | Behavior |
|---|---|---|
| **L1** `TokenLimitBreaker` | One agent burns tokens in a single run | Run flips `completed → failed` when `tokens_used > limit`; `limit <= 0` disables |
| **L2** `RoleFailureTracker` | One role (e.g. builder) fails every round | Role failing ≥ N consecutive rounds (default 2) is tripped — skip dispatching it next round |
| **L3** `BudgetGuard` | The whole loop overruns the total budget | `used >= limit` forces a `budget_exceeded` terminal state, **even if all checks are green** |

## Design decisions (and why)

- **L2 threshold = 2**: the first failure may be noise (network blip); two consecutive failures mean the role truly cannot do the task.
- **L2 success resets the window**: one success clears the count — the fuse tracks *consecutive* failure, not lifetime failure.
- **L2 absent ≠ reset**: a role skipped by the fuse must not have its count reset by the skip itself (otherwise the fuse would never stay tripped).
- **L3 `>=` not `>`**: once the budget is fully consumed there is nothing left for another round.
- **L3 priority over green**: a loop that passes all checks but is over budget still stops — cost control is not optional.
- **Strict deserialization**: `RoleFailureTracker.from_dict` drops non-str keys, non-int values, and `bool`s — dirty state files cannot corrupt the state machine.

## Install

```bash
pip install agent-budget-guard
# or from source
pip install -e .
```

## Quick start

```python
from agent_budget_guard import BudgetGuard, RoleFailureTracker, TokenLimitBreaker

l1 = TokenLimitBreaker()
l2 = RoleFailureTracker()
l3 = BudgetGuard(used=0, limit=500_000)

# ── each round ──────────────────────────────────────────────
for round_num in range(max_rounds):
    # L2: skip roles that keep failing
    for role in ["builder", "checker"]:
        if l2.is_tripped(role):
            continue  # do not dispatch — it would just burn tokens
        result = dispatch(role)  # your agent runtime call

        # L1: per-agent fuse
        verdict = l1.check(result.tokens_used, limit=50_000)
        if verdict.tripped:
            result.status = "failed"

        l2.update({role: result.status})

    # L3: loop-wide fuse (check takes priority over "all green")
    budget = l3.add(total_tokens_this_round)
    if budget.exceeded:
        break  # terminal: budget_exceeded
```

### Persistence (survive restarts)

```python
# save
state = {"failure_counts": l2.to_dict(), "budget_used": l3.used}

# restore — dirty data is dropped, not crashed on
l2 = RoleFailureTracker.from_dict(state["failure_counts"])
l3 = BudgetGuard(used=state["budget_used"], limit=500_000)
```

## API surface

### `TokenLimitBreaker` (L1)
- `check(tokens_used, limit)` → `TokenVerdict(tripped, message, ...)` — exactly-at-limit passes, `limit <= 0` disables

### `RoleFailureTracker` (L2)
- `update(agent_status: dict[str, str])` — `"failed"` → +1, any other value → reset, absent → unchanged, empty/None → no-op
- `tripped_roles()` / `is_tripped(role)` — tripped when count >= threshold
- `to_dict()` / `from_dict(raw)` — strict (de)serialization

### `BudgetGuard` (L3)
- `add(tokens)` → `BudgetVerdict(exceeded, used, remaining, terminal)` — clamps negative spend, records history
- `check()` → verdict without recording
- `rounds_remaining(per_round_estimate)` — how many more rounds fit (sentinel `10**9` when disabled)

## Testing

```bash
pip install -e ".[dev]"
pytest            # 29 tests
ruff check src tests
```

## License

MIT

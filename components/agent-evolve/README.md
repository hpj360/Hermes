# agent-evolve

GEPA-style agent-definition self-evolution with statistical rigor: generate variants, evaluate on real runs, promote only statistically significant winners (Welch's t-test + Bonferroni correction). **Zero dependencies** (Python 3.10+, stdlib only).

Extracted from the [Hermes](https://github.com/hpj360/Hermes) agent framework (`hermes.gepa` / `hermes.gepa_stats` / `hermes.gepa_redteam`), decoupled into a standalone package.

## Why

Self-improving agents are dangerous without guardrails. The two failure modes this library is designed against:

1. **Lucky-run promotion** — a variant that won one benchmark run by chance gets promoted and silently regresses the system.
2. **Compromised evolution** — a hijacked LLM generates "plausible" variants that are actually malicious (credential harvesting, disabling safety checks).

## What it provides

| Module | Purpose |
|---|---|
| `evolve` | `run_cycle` / `run_split_run` evolution cycles, `Variant` / `Experiment` data model, JSON audit registry, LLM-driven variant generation with a prompt safety screen |
| `stats` | Welch's t-test with incomplete-beta implemented from scratch (no scipy), split-run promotion gate |
| `redteam` | Malicious path corpus + `audit_denylist_coverage()` for denylist strength regression |

### Design principles

- **Conservative promotion** — only successful variants are eligible; if all variants fail, nothing is promoted ("better no evolution than wrong evolution").
- **Audit-first** — every experiment (success or failure) is persisted to a JSON registry, never overwritten. A bad promotion must be traceable.
- **Crash-resistant** — one variant's evaluation crash never aborts the cycle; it is recorded as a failed result.
- **Explicit scoring** — `success >> tokens >> rounds`, with clamped penalty terms so an unbounded metric cannot break the "success always wins" invariant.

## Install

```bash
pip install agent-evolve
# or from source
pip install -e .
```

## Quick start

```python
from agent_evolve import Variant, VariantResult, run_cycle, save_experiment

variants = [
    Variant(variant_id="diag-first", agent_file="agents/diag.md"),
    Variant(variant_id="test-first", agent_file="agents/test-first.md"),
]

def evaluate(variant, task, ctx):
    # run your agent on the benchmark, measure the outcome
    return VariantResult(
        variant_id=variant.variant_id,
        success=True,
        tokens_used=12_000,
        rounds_to_converge=2,
    )

experiment = run_cycle("make all tests pass", variants, evaluate)
print(experiment.winner_id, experiment.promotion_reason)
save_experiment(experiment)  # audit trail: .agent-evolve/<id>.json
```

### Statistically gated promotion (split-run)

```python
from agent_evolve import run_split_run

experiment = run_split_run(
    "make all tests pass",
    baseline=Variant(variant_id="incumbent", agent_file="agents/v1.md"),
    challengers=[Variant(variant_id="v2", agent_file="agents/v2.md")],
    evaluate_fn=evaluate,
    min_repeats=5,   # each variant runs >= 5 times
    alpha=0.05,      # Bonferroni-corrected across challengers
)
# winner_id is set only if a challenger significantly beat the baseline
```

### Denylist strength audit

```python
from agent_evolve import audit_denylist_coverage

report = audit_denylist_coverage(["auth/", ".env", "*.key"])
print(report["coverage"])  # fraction of must-block paths actually blocked
print(report["missed"])    # e.g. extensionless keys like id_rsa
```

## API surface

### `evolve`
- `run_cycle(benchmark_task, variants, evaluate_fn, benchmark_context="")` → `Experiment`
- `run_split_run(benchmark_task, baseline, challengers, evaluate_fn, *, min_repeats=5, alpha=0.05)` → `Experiment`
- `auto_generate_variants(llm, benchmark_task, ...)` → `list[Variant]` (degrades to `[]` on any LLM failure; unsafe prompts rejected)
- `save_experiment` / `load_experiment` / `list_experiments` / `get_latest_promotion` — audit registry (JSONL-free, one JSON per experiment)
- `score_variant(result)` — explicit scoring: `success(20000) − 0.01·tokens − 50·rounds` (clamped)

### `stats`
- `welch_ttest(a, b)` → `(t, p)` — handles degenerate cases (empty / zero-variance → not significant)
- `compare_variants(baseline, challenger, *, alpha, min_repeats)` → `SplitRunResult` with `.promote`
- `should_promote(...)` → `bool` — the high-level gate

### `redteam`
- `matches_denylist(path, denylist)` → matched pattern or `None`
- `audit_denylist_coverage(denylist=None, redteam_paths=None)` → `{blocked, missed, false_positive, coverage}`

## Testing

```bash
pip install -e ".[dev]"
pytest            # 56 tests
ruff check src tests
```

## License

MIT

# traj-verify

Append-only dispatch trajectory log with a **reconstruction invariant**: every payload dispatched to a sub-agent must be replayable byte-for-byte from disk. Includes an offline audit for sequence gaps, request/result pairing, and content hashes. **Zero dependencies** (Python 3.10+, stdlib only).

Extracted from the [Hermes](https://github.com/hpj360/Hermes) agent framework (`hermes.trajectory`, ADR-0017), with the atomic-append storage primitive inlined so the package is fully standalone.

## Why

Agent orchestrators are control planes: they dispatch sub-agents to gateways/runtimes and consume results. When something goes wrong (a bad promotion, a suspicious file edit, a heisenbug), you need to answer:

> "Exactly what did we send to the agent that did this?"

A printf log cannot answer that — it is written *beside* the dispatch path and can drift from the payload actually sent. This library makes the log itself the source of truth by enforcing a runtime invariant: **before dispatch, the request snapshot is read back from disk and must equal the payload about to be sent** (a serialization round-trip gate). Desync aborts the dispatch.

## What it provides

| Piece | Purpose |
|---|---|
| `TrajectoryLogger` | Append-only JSONL event log. Cross-process file lock (fcntl/msvcrt) + in-process lock; sequence counter resumes from an existing file; corrupt lines skipped on read, counted on audit |
| `assert_reconstructable` | The invariant: replay a `dispatch/request` event and compare (key-order-insensitive JSON normalization). Raises `TrajectoryDesyncError` on mismatch or missing event |
| `verify_trajectory` | Offline audit of a finished trajectory: line integrity, seq continuity, request/result pairing, orphan/malformed results, agent-file SHA-256 drift |
| `archive_trajectory` | Rotate the log per cycle (`trajectory.jsonl` → `trajectory.1.jsonl`) so cycles never interleave |

## Install

```bash
pip install traj-verify
# or from source
pip install -e .
```

## Quick start

```python
from pathlib import Path
from traj_verify import TrajectoryLogger

log = TrajectoryLogger(Path("trajectory.jsonl"))

payload = {"task": "fix the failing test", "denylist": ["auth/", ".env"]}
seq = log.record("dispatch/request", {"role": "builder", "payload": payload})

# The invariant gate — call right before the actual dispatch.
# Raises TrajectoryDesyncError if disk does not match the payload.
log.assert_reconstructable(seq, payload)

result = dispatch(payload)  # your gateway/runtime call
log.record("dispatch/result", {"request_seq": seq, "status": "completed",
                               "tokens_used": result.tokens})
```

### Offline audit (CI / post-mortem)

```python
from traj_verify import verify_trajectory

report = verify_trajectory(Path("trajectory.jsonl"))
print(report["ok"])               # False if anything is off
print(report["seq_gaps"])         # e.g. [3] — events missing from the middle
print(report["unpaired_requests"])  # requests that never got a result
print(report["hash_mismatches"])  # agent definition changed since dispatch
```

## Semantics worth knowing

- **Fail-loud writes**: `record()` raises `OSError` on write failure — an audit log must not silently drop events.
- **Seq resumes**: a fresh `TrajectoryLogger` over an existing file continues the counter instead of restarting at 1, so `request_seq` correlation survives across logger instances.
- **Concurrency**: 10 threads × 50 appends produce exactly 500 unique, monotonically ordered seqs (in-process lock); multiple processes appending to the same file get line-atomic writes (file lock).
- **Tamper detection scope**: free-text fields cannot be audited offline against a tampered-but-self-consistent log; the audit is explicit about what it can and cannot check.

## Testing

```bash
pip install -e ".[dev]"
pytest            # 25 tests
ruff check src tests
```

## License

MIT

"""Phase 3.4 crash recovery.

On process startup, scan the persisted :class:`JobStore` and resolve
non-terminal jobs left over from a previous (crashed) run. Strategy per
ADR-0002:

* PENDING  → skipped (waiting for explicit submit or DAG upstream)
* QUEUED   → re-enqueue (job is ready, no worker has consumed it yet)
* RUNNING  → mark ABANDONED (we cannot safely resume mid-execution)

Each recovery action (requeue / abandon) is recorded as an L2 episode with
``kind="recovery"`` when a :class:`MemoryService` is wired in.

If ``enabled=False`` (HERMES_SCHEDULER_RECOVERY=off), QUEUED and RUNNING are
both marked ABANDONED — the operator has opted out of automatic recovery.

Stdlib-only; reuses ``JobStore`` (Lock + atomic_write_json) and
``JobQueue`` from :mod:`hermes.workbench.scheduler`.
"""

from __future__ import annotations

from typing import Any

from hermes.workbench.memory import make_episode
from hermes.workbench.scheduler import JobQueue, JobStatus, JobStore


__all__ = ["RecoveryManager"]


class RecoveryManager:
    """Scan ``jobs.json`` at startup and resolve non-terminal jobs."""

    def __init__(
        self,
        store: JobStore,
        queue: JobQueue,
        memory: Any = None,
        enabled: bool = True,
    ) -> None:
        self._store = store
        self._queue = queue
        self._memory = memory
        self._enabled = enabled

    def recover(self) -> dict[str, Any]:
        """Execute recovery, returning ``{requeued, abandoned, skipped}``.

        Iterates over a snapshot of all jobs in the store and applies the
        ADR-0002 strategy. Each requeue / abandon action is recorded as an
        L2 episode when a memory service is available; episode-recording
        failures never break recovery.
        """
        stats = {"requeued": 0, "abandoned": 0, "skipped": 0}
        # Snapshot once — recovery must not iterate over a mutating dict.
        for job in self._store.list():
            status = job.status
            if status.is_terminal():
                stats["skipped"] += 1
                continue
            if status is JobStatus.PENDING:
                # Wait for explicit submit or DAG upstream resolution.
                stats["skipped"] += 1
                continue
            if status is JobStatus.QUEUED:
                if self._enabled:
                    self._queue.put(job)
                    stats["requeued"] += 1
                    self._record_episode(
                        summary=f"requeued job {job.job_id}",
                        details={
                            "job_id": job.job_id,
                            "action": "requeue",
                            "from_status": status.value,
                        },
                    )
                else:
                    self._store.update_status(job.job_id, JobStatus.ABANDONED)
                    stats["abandoned"] += 1
                    self._record_episode(
                        summary=f"abandoned job {job.job_id} (recovery disabled)",
                        details={
                            "job_id": job.job_id,
                            "action": "abandon",
                            "from_status": status.value,
                            "reason": "recovery_disabled",
                        },
                    )
                continue
            if status is JobStatus.RUNNING:
                # Cannot safely resume mid-execution — abandon.
                self._store.update_status(job.job_id, JobStatus.ABANDONED)
                stats["abandoned"] += 1
                self._record_episode(
                    summary=f"abandoned job {job.job_id} (was RUNNING)",
                    details={
                        "job_id": job.job_id,
                        "action": "abandon",
                        "from_status": status.value,
                        "reason": "interrupted_run",
                    },
                )
                continue
            # Defensive: any other non-terminal state we don't recognize.
            stats["skipped"] += 1
        return stats

    def _record_episode(self, summary: str, details: dict[str, Any]) -> None:
        """Record a recovery action as an L2 episode, best-effort."""
        if self._memory is None:
            return
        try:
            episode = make_episode("recovery", summary, details)
            self._memory.record_episode(episode)
        except Exception:  # noqa: BLE001
            # Episode recording must never break recovery.
            pass

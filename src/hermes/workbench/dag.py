"""Phase 3.5 DAG dependency management.

Provides ``DependencyGraph`` for managing job-to-job dependencies on top of
``JobStore`` / ``JobQueue``:

- Cycle detection at register time (DFS); cycles raise ``ValidationError``.
- Depth limit (10) to prevent recursion stack overflow on pathological chains.
- ``ready_to_queue(job_id)``: True when all deps are SUCCEEDED.
- ``on_job_done(job_id, status)``: upstream-done callback that either
  enqueues ready downstream jobs (on SUCCEEDED) or cascade-cancels them
  (on FAILED/CANCELLED/TIMEOUT/ABANDONED), recording a synthetic
  ``JobExecution`` on each cancelled job with ``error="upstream <id> <status>"``.

All concurrency uses ``threading.Lock``; no external dependencies.
"""

from __future__ import annotations

import threading
from typing import Any

from hermes.workbench.errors import ValidationError
from hermes.workbench.scheduler import (
    JobExecution,
    JobQueue,
    JobStatus,
    JobStore,
    _now_iso,
)


__all__ = ["DependencyGraph"]


class DependencyGraph:
    """DAG dependency manager: job_id → depends_on mapping.

    Lifecycle contract:
    - ``register`` is called at submit time, before the job is enqueued.
    - ``on_job_done`` is called by the worker when a job reaches a terminal
      state. The worker is responsible for persisting the job's final status
      to ``JobStore`` *before* invoking this callback (so ``ready_to_queue``
      sees the updated upstream status).
    """

    def __init__(
        self,
        store: JobStore,
        queue: JobQueue,
        bus: Any = None,  # StatusBus, optional
    ) -> None:
        self._deps: dict[str, list[str]] = {}        # job_id -> depends_on
        self._dependents: dict[str, list[str]] = {}   # job_id -> who depends on it
        self._lock = threading.Lock()
        self._store = store
        self._queue = queue
        self._bus = bus
        self._max_depth = 10

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, job_id: str, depends_on: list[str]) -> None:
        """Register job dependencies with cycle + depth validation.

        Raises ``ValidationError`` if adding these deps would create a cycle
        or push the DAG depth past ``_max_depth``.
        """
        with self._lock:
            new_depth = self._compute_depth(job_id, depends_on)
            if new_depth > self._max_depth:
                raise ValidationError(
                    f"DAG depth {new_depth} exceeds limit {self._max_depth} "
                    f"for job {job_id}"
                )
            if self._detect_cycle(job_id, depends_on):
                raise ValidationError(
                    f"registering dependencies {depends_on} for job {job_id} "
                    f"would create a cycle"
                )
            self._deps[job_id] = list(depends_on)
            for dep in depends_on:
                self._dependents.setdefault(dep, []).append(job_id)

    def ready_to_queue(self, job_id: str) -> bool:
        """Return True iff every dep of ``job_id`` is SUCCEEDED.

        A job with no deps (or an unregistered job_id) is always ready.
        """
        with self._lock:
            deps = list(self._deps.get(job_id, []))
        if not deps:
            return True
        for dep_id in deps:
            dep = self._store.get(dep_id)
            if dep is None or dep.status != JobStatus.SUCCEEDED:
                return False
        return True

    def on_job_done(self, job_id: str, status: JobStatus) -> None:
        """Callback when a job reaches a terminal state.

        - SUCCEEDED: enqueue downstreams whose deps are now all SUCCEEDED.
        - FAILED/CANCELLED/TIMEOUT/ABANDONED: cascade-cancel all downstreams.
        - Other statuses (PENDING/QUEUED/RUNNING): no-op.
        """
        with self._lock:
            downstreams = list(self._dependents.get(job_id, []))
        if not downstreams:
            return
        if status == JobStatus.SUCCEEDED:
            self._enqueue_ready_downstreams(downstreams)
        elif status in {
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
            JobStatus.ABANDONED,
        }:
            reason = f"upstream {job_id} {status.value}"
            for dep_id in downstreams:
                self._cascade_cancel(dep_id, reason, depth=1)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _enqueue_ready_downstreams(self, downstreams: list[str]) -> None:
        """Enqueue each downstream that is ready and still PENDING."""
        for dep_id in downstreams:
            if not self.ready_to_queue(dep_id):
                continue
            job = self._store.get(dep_id)
            if job is None or job.status != JobStatus.PENDING:
                # Already queued/running/terminal — do not double-enqueue.
                continue
            job.status = JobStatus.QUEUED
            self._store.save(job)
            if self._bus is not None:
                self._bus.emit(job)
            self._queue.put(job)

    def _detect_cycle(self, job_id: str, depends_on: list[str]) -> bool:
        """DFS cycle detection: can ``job_id`` be reached from any dep?"""
        visited: set[str] = set()
        for dep in depends_on:
            if dep == job_id:
                return True  # direct self-loop
            if self._dfs_reach(dep, job_id, visited):
                return True
        return False

    def _dfs_reach(self, start: str, target: str, visited: set[str]) -> bool:
        """Return True if ``target`` is reachable from ``start`` via depends_on."""
        if start == target:
            return True
        if start in visited:
            return False
        visited.add(start)
        for nxt in self._deps.get(start, []):
            if self._dfs_reach(nxt, target, visited):
                return True
        return False

    def _compute_depth(self, job_id: str, depends_on: list[str]) -> int:
        """Compute the depth of ``job_id`` if registered with ``depends_on``.

        Depth = 1 + max(depth of deps), or 1 if no deps. Self-loops are
        skipped here (the cycle check rejects them separately).
        """
        if not depends_on:
            return 1
        max_dep_depth = 0
        for dep in depends_on:
            if dep == job_id:
                continue
            dep_depth = self._compute_depth_of_existing(dep, set())
            if dep_depth > max_dep_depth:
                max_dep_depth = dep_depth
        return max_dep_depth + 1

    def _compute_depth_of_existing(self, job_id: str, visited: set[str]) -> int:
        """Compute depth of an already-registered job."""
        if job_id in visited:
            return 0  # cycle protection (shouldn't happen post-check)
        visited.add(job_id)
        deps = self._deps.get(job_id, [])
        if not deps:
            return 1
        return 1 + max(
            (self._compute_depth_of_existing(d, visited) for d in deps),
            default=0,
        )

    def _cascade_cancel(self, job_id: str, reason: str, depth: int = 0) -> None:
        """Recursively cancel ``job_id`` and all its downstreams.

        Records a synthetic ``JobExecution`` (attempt_num=0, status=CANCELLED,
        error=reason) on each newly-cancelled job. Already-terminal jobs are
        not re-cancelled, but recursion still continues into their
        downstreams so an indirectly-blocked descendant is never left
        dangling.

        Raises ``ValidationError`` if depth exceeds ``_max_depth``.
        """
        if depth > self._max_depth:
            raise ValidationError(
                f"cascade cancel depth {depth} exceeds limit {self._max_depth}"
            )
        with self._lock:
            downstreams = list(self._dependents.get(job_id, []))
        job = self._store.get(job_id)
        if job is not None and not job.status.is_terminal():
            exec_record = JobExecution(
                attempt_num=0,
                started_at=_now_iso(),
                ended_at=_now_iso(),
                status=JobStatus.CANCELLED,
                error=reason,
            )
            job.attempts.append(exec_record)
            job.status = JobStatus.CANCELLED
            self._store.save(job)
            if self._bus is not None:
                self._bus.emit(job)
        for dep_id in downstreams:
            self._cascade_cancel(dep_id, reason, depth=depth + 1)

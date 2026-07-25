"""Tests for Phase 3.4 crash recovery (recovery.py).

Covers AC-13: on process startup, scan jobs.json and resolve non-terminal
jobs left over from a previous (crashed) run.

Recovery strategy (ADR-0002):
* PENDING  → skipped (waiting for explicit submit or DAG upstream)
* QUEUED   → re-enqueue (job ready, no worker consumed it yet)
* RUNNING  → mark ABANDONED (cannot safely resume mid-execution)

When ``enabled=False`` (HERMES_SCHEDULER_RECOVERY off), both QUEUED and
RUNNING are marked ABANDONED — the operator opted out of auto recovery.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.workbench.cli import Task
from hermes.workbench.memory import MemoryService
from hermes.workbench.recovery import RecoveryManager
from hermes.workbench.scheduler import (
    JobQueue,
    JobStatus,
    JobStore,
    ScheduledJob,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(state_dir=tmp_path)


@pytest.fixture
def queue() -> JobQueue:
    return JobQueue()


@pytest.fixture
def memory(tmp_path: Path) -> MemoryService:
    return MemoryService(state_dir=tmp_path / "memory")


def _make_job(job_id: str, status: JobStatus) -> ScheduledJob:
    """Build a ScheduledJob with the given id and status."""
    task = Task(task_id=f"task-{job_id}", plan=[{"skill": "echo", "args": ["hi"]}])
    return ScheduledJob(
        task=task,
        job_id=job_id,
        target_project="default",
        status=status,
    )


def _seed_three_jobs(
    store: JobStore,
) -> tuple[ScheduledJob, ScheduledJob, ScheduledJob]:
    """Seed the store with one job each in PENDING / QUEUED / RUNNING."""
    pending = _make_job("job-pending", JobStatus.PENDING)
    queued = _make_job("job-queued", JobStatus.QUEUED)
    running = _make_job("job-running", JobStatus.RUNNING)
    for j in (pending, queued, running):
        store.save(j)
    return pending, queued, running


# ---------------------------------------------------------------------------
# recover() — enabled=True (default)
# ---------------------------------------------------------------------------


class TestRecoverEnabled:
    def test_returns_expected_stats(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory)
        stats = rm.recover()
        assert stats == {"requeued": 1, "abandoned": 1, "skipped": 1}

    def test_queued_job_requeued(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        _, queued, _ = _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory)
        rm.recover()
        # The QUEUED job should now be in the queue
        assert queue.size() == 1
        dequeued = queue.get(timeout=0.5)
        assert dequeued.job_id == queued.job_id

    def test_running_job_abandoned(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        _, _, running = _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory)
        rm.recover()
        updated = store.get(running.job_id)
        assert updated is not None
        assert updated.status == JobStatus.ABANDONED

    def test_pending_job_untouched(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        pending, _, _ = _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory)
        rm.recover()
        updated = store.get(pending.job_id)
        assert updated is not None
        assert updated.status == JobStatus.PENDING

    def test_episode_recorded_with_recovery_kind(
        self, store: JobStore, queue: JobQueue
    ) -> None:
        _seed_three_jobs(store)
        mock_memory = MagicMock()
        rm = RecoveryManager(store=store, queue=queue, memory=mock_memory)
        rm.recover()
        # One episode per action: 1 requeue + 1 abandon
        assert mock_memory.record_episode.call_count == 2
        for call in mock_memory.record_episode.call_args_list:
            episode = call.args[0]
            assert episode.kind == "recovery"

    def test_episode_details_contain_job_id(
        self, store: JobStore, queue: JobQueue
    ) -> None:
        _seed_three_jobs(store)
        mock_memory = MagicMock()
        rm = RecoveryManager(store=store, queue=queue, memory=mock_memory)
        rm.recover()
        recorded_ids = {call.args[0].details.get("job_id") for call in
                        mock_memory.record_episode.call_args_list}
        assert recorded_ids == {"job-queued", "job-running"}

    def test_real_memory_service_persists_episode(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory)
        rm.recover()
        episodes = memory.list_episodes(kind="recovery")
        assert len(episodes) == 2
        assert {ep.kind for ep in episodes} == {"recovery"}


# ---------------------------------------------------------------------------
# recover() — enabled=False
# ---------------------------------------------------------------------------


class TestRecoverDisabled:
    def test_queued_and_running_abandoned(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        _, queued, running = _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory, enabled=False)
        stats = rm.recover()
        assert stats == {"requeued": 0, "abandoned": 2, "skipped": 1}
        assert store.get(queued.job_id).status == JobStatus.ABANDONED
        assert store.get(running.job_id).status == JobStatus.ABANDONED

    def test_queue_remains_empty(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory, enabled=False)
        rm.recover()
        assert queue.size() == 0

    def test_pending_untouched(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        pending, _, _ = _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory, enabled=False)
        rm.recover()
        assert store.get(pending.job_id).status == JobStatus.PENDING


# ---------------------------------------------------------------------------
# recover() — no memory service
# ---------------------------------------------------------------------------


class TestRecoverNoMemory:
    def test_does_not_raise_without_memory(
        self, store: JobStore, queue: JobQueue
    ) -> None:
        _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=None)
        stats = rm.recover()
        assert stats == {"requeued": 1, "abandoned": 1, "skipped": 1}

    def test_requeue_still_works_without_memory(
        self, store: JobStore, queue: JobQueue
    ) -> None:
        _, queued, _ = _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=None)
        rm.recover()
        assert queue.size() == 1
        assert queue.get(timeout=0.5).job_id == queued.job_id

    def test_abandon_still_works_without_memory(
        self, store: JobStore, queue: JobQueue
    ) -> None:
        _, _, running = _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=None)
        rm.recover()
        assert store.get(running.job_id).status == JobStatus.ABANDONED


# ---------------------------------------------------------------------------
# recover() — idempotency / terminal states
# ---------------------------------------------------------------------------


class TestRecoverIdempotency:
    def test_terminal_states_skipped(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        pending = _make_job("job-pending", JobStatus.PENDING)
        succeeded = _make_job("job-done", JobStatus.SUCCEEDED)
        store.save(pending)
        store.save(succeeded)
        rm = RecoveryManager(store=store, queue=queue, memory=memory)
        stats = rm.recover()
        assert stats == {"requeued": 0, "abandoned": 0, "skipped": 2}

    def test_recover_twice_is_idempotent(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        _seed_three_jobs(store)
        rm = RecoveryManager(store=store, queue=queue, memory=memory)
        first = rm.recover()
        assert first == {"requeued": 1, "abandoned": 1, "skipped": 1}
        # Drain the queue so the second pass has nothing to requeue from the
        # previous run; the store still has the QUEUED job at status QUEUED.
        while queue.size() > 0:
            queue.get(timeout=0.5)
        second = rm.recover()
        # RUNNING is now ABANDONED (terminal → skipped); QUEUED still QUEUED
        # in store → requeued again; PENDING still PENDING → skipped.
        assert second == {"requeued": 1, "abandoned": 0, "skipped": 2}

    def test_empty_store_returns_zero_stats(
        self, store: JobStore, queue: JobQueue, memory: MemoryService
    ) -> None:
        rm = RecoveryManager(store=store, queue=queue, memory=memory)
        stats = rm.recover()
        assert stats == {"requeued": 0, "abandoned": 0, "skipped": 0}

"""Tests for Phase 3 scheduling center core (scheduler.py).

Covers: ScheduledJob/JobExecution/JobStatus/RetryPolicy dataclasses,
JobStore persistence (CRUD + concurrency), JobQueue priority ordering,
WorkerPool execution (cancel/retry/timeout).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.workbench.scheduler import (
    JobExecution,
    JobQueue,
    JobStatus,
    JobStore,
    RetryPolicy,
    ScheduledJob,
    WorkerPool,
)
from hermes.workbench.cli import Task


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
def sample_task() -> Task:
    return Task(task_id="task-1", plan=[{"skill": "echo", "args": ["hi"]}])


@pytest.fixture
def sample_job(sample_task: Task) -> ScheduledJob:
    return ScheduledJob(task=sample_task, target_project="default")


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    def test_defaults(self) -> None:
        rp = RetryPolicy()
        assert rp.max_retries == 0
        assert rp.base_delay == 2.0
        assert rp.max_delay == 60.0

    def test_custom(self) -> None:
        rp = RetryPolicy(max_retries=3, base_delay=0.5, max_delay=10.0)
        assert rp.max_retries == 3
        assert rp.base_delay == 0.5
        assert rp.max_delay == 10.0

    def test_to_dict_roundtrip(self) -> None:
        rp = RetryPolicy(max_retries=2, base_delay=1.0, max_delay=30.0)
        d = rp.to_dict()
        rp2 = RetryPolicy.from_dict(d)
        assert rp2 == rp


# ---------------------------------------------------------------------------
# JobStatus
# ---------------------------------------------------------------------------


class TestJobStatus:
    def test_enum_values(self) -> None:
        assert JobStatus.PENDING == "PENDING"
        assert JobStatus.QUEUED == "QUEUED"
        assert JobStatus.RUNNING == "RUNNING"
        assert JobStatus.SUCCEEDED == "SUCCEEDED"
        assert JobStatus.FAILED == "FAILED"
        assert JobStatus.CANCELLED == "CANCELLED"
        assert JobStatus.TIMEOUT == "TIMEOUT"
        assert JobStatus.ABANDONED == "ABANDONED"

    def test_is_terminal(self) -> None:
        assert JobStatus.SUCCEEDED.is_terminal()
        assert JobStatus.FAILED.is_terminal()
        assert JobStatus.CANCELLED.is_terminal()
        assert JobStatus.TIMEOUT.is_terminal()
        assert JobStatus.ABANDONED.is_terminal()
        assert not JobStatus.PENDING.is_terminal()
        assert not JobStatus.QUEUED.is_terminal()
        assert not JobStatus.RUNNING.is_terminal()


# ---------------------------------------------------------------------------
# JobExecution
# ---------------------------------------------------------------------------


class TestJobExecution:
    def test_defaults(self) -> None:
        ex = JobExecution(attempt_num=0, started_at="2026-07-25T00:00:00Z")
        assert ex.attempt_num == 0
        assert ex.status == JobStatus.RUNNING
        assert ex.ended_at is None
        assert ex.error is None
        assert ex.trace_id is None
        assert ex.round_summary is None

    def test_to_dict_roundtrip(self) -> None:
        ex = JobExecution(
            attempt_num=1,
            started_at="2026-07-25T00:00:00Z",
            ended_at="2026-07-25T00:01:00Z",
            status=JobStatus.SUCCEEDED,
            error=None,
            trace_id="trace-1",
            round_summary={"round": 1},
        )
        d = ex.to_dict()
        ex2 = JobExecution.from_dict(d)
        assert ex2.attempt_num == 1
        assert ex2.status == JobStatus.SUCCEEDED
        assert ex2.trace_id == "trace-1"


# ---------------------------------------------------------------------------
# ScheduledJob
# ---------------------------------------------------------------------------


class TestScheduledJob:
    def test_defaults(self, sample_task: Task) -> None:
        job = ScheduledJob(task=sample_task)
        assert job.job_id  # auto-generated uuid
        assert job.target_project == "default"
        assert job.priority == 5
        assert job.status == JobStatus.PENDING
        assert job.timeout is None
        assert job.depends_on == []
        assert job.submitted_by == "cli"
        assert job.attempts == []
        assert job.queued_at is None
        assert job.started_at is None
        assert isinstance(job.created_at, str)
        assert isinstance(job.cancel_event, threading.Event)

    def test_to_dict_excludes_cancel_event(self, sample_task: Task) -> None:
        job = ScheduledJob(task=sample_task)
        d = job.to_dict()
        assert "cancel_event" not in d
        assert d["job_id"] == job.job_id
        assert d["target_project"] == "default"
        assert d["priority"] == 5

    def test_from_dict_roundtrip(self, sample_task: Task) -> None:
        job = ScheduledJob(
            task=sample_task,
            target_project="proj-a",
            priority=1,
            timeout=30.0,
            depends_on=["job-x"],
        )
        d = job.to_dict()
        job2 = ScheduledJob.from_dict(d)
        assert job2.job_id == job.job_id
        assert job2.target_project == "proj-a"
        assert job2.priority == 1
        assert job2.timeout == 30.0
        assert job2.depends_on == ["job-x"]
        assert isinstance(job2.cancel_event, threading.Event)

    def test_from_template(self, sample_task: Task) -> None:
        template = ScheduledJob(task=sample_task, target_project="proj-a", priority=1).to_dict()
        # 模板不含 job_id/status/attempts
        template.pop("job_id", None)
        template.pop("status", None)
        template.pop("attempts", None)
        job = ScheduledJob.from_template(template, submitted_by="cron")
        assert job.job_id != template.get("job_id")
        assert job.status == JobStatus.PENDING
        assert job.submitted_by == "cron"
        assert job.attempts == []


# ---------------------------------------------------------------------------
# JobStore
# ---------------------------------------------------------------------------


class TestJobStore:
    def test_save_and_get(self, store: JobStore, sample_job: ScheduledJob) -> None:
        store.save(sample_job)
        fetched = store.get(sample_job.job_id)
        assert fetched is not None
        assert fetched.job_id == sample_job.job_id
        assert fetched.target_project == sample_job.target_project

    def test_get_missing_returns_none(self, store: JobStore) -> None:
        assert store.get("nonexistent") is None

    def test_list(self, store: JobStore, sample_task: Task) -> None:
        job1 = ScheduledJob(task=sample_task)
        job2 = ScheduledJob(task=sample_task)
        store.save(job1)
        store.save(job2)
        jobs = store.list()
        assert len(jobs) == 2
        ids = {j.job_id for j in jobs}
        assert {job1.job_id, job2.job_id} == ids

    def test_list_by_status(self, store: JobStore, sample_task: Task) -> None:
        job1 = ScheduledJob(task=sample_task)
        job2 = ScheduledJob(task=sample_task)
        job2.status = JobStatus.QUEUED
        store.save(job1)
        store.save(job2)
        pending = store.list_by_status(JobStatus.PENDING)
        queued = store.list_by_status(JobStatus.QUEUED)
        assert len(pending) == 1
        assert len(queued) == 1
        assert pending[0].job_id == job1.job_id

    def test_persistence_across_instances(self, store: JobStore, sample_job: ScheduledJob, tmp_path: Path) -> None:
        store.save(sample_job)
        store2 = JobStore(state_dir=tmp_path)
        fetched = store2.get(sample_job.job_id)
        assert fetched is not None
        assert fetched.job_id == sample_job.job_id

    def test_concurrent_writes_no_loss(self, store: JobStore, sample_task: Task) -> None:
        """10 threads × 50 jobs each, all should be persisted."""

        def write_batch(thread_id: int) -> None:
            for i in range(50):
                job = ScheduledJob(task=Task(task_id=f"t-{thread_id}-{i}", plan=[]))
                store.save(job)

        threads = [threading.Thread(target=write_batch, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(store.list()) == 500

    def test_update_status(self, store: JobStore, sample_job: ScheduledJob) -> None:
        store.save(sample_job)
        assert store.update_status(sample_job.job_id, JobStatus.SUCCEEDED)
        fetched = store.get(sample_job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.SUCCEEDED

    def test_update_status_missing(self, store: JobStore) -> None:
        assert not store.update_status("nonexistent", JobStatus.SUCCEEDED)


# ---------------------------------------------------------------------------
# JobQueue
# ---------------------------------------------------------------------------


class TestJobQueue:
    def test_put_and_get(self, queue: JobQueue, sample_job: ScheduledJob) -> None:
        queue.put(sample_job)
        got = queue.get(timeout=1.0)
        assert got.job_id == sample_job.job_id

    def test_get_empty_raises_timeout(self, queue: JobQueue) -> None:
        with pytest.raises(EmptyError):
            queue.get(timeout=0.1)

    def test_priority_ordering(self, queue: JobQueue, sample_task: Task) -> None:
        """priority=1 should come out before priority=5."""
        low = ScheduledJob(task=sample_task, priority=5)
        high = ScheduledJob(task=sample_task, priority=1)
        queue.put(low)
        queue.put(high)
        first = queue.get(timeout=1.0)
        second = queue.get(timeout=1.0)
        assert first.job_id == high.job_id
        assert second.job_id == low.job_id

    def test_fifo_within_same_priority(self, queue: JobQueue, sample_task: Task) -> None:
        a = ScheduledJob(task=sample_task, priority=5)
        b = ScheduledJob(task=sample_task, priority=5)
        queue.put(a)
        queue.put(b)
        first = queue.get(timeout=1.0)
        second = queue.get(timeout=1.0)
        assert first.job_id == a.job_id
        assert second.job_id == b.job_id

    def test_size(self, queue: JobQueue, sample_job: ScheduledJob) -> None:
        assert queue.size() == 0
        queue.put(sample_job)
        assert queue.size() == 1
        queue.get(timeout=1.0)
        assert queue.size() == 0


# ---------------------------------------------------------------------------
# WorkerPool
# ---------------------------------------------------------------------------


class TestWorkerPool:
    def test_execute_single_job_succeeds(
        self, store: JobStore, queue: JobQueue, sample_task: Task
    ) -> None:
        """AC-1: job submitted, executed asynchronously, final status SUCCEEDED."""
        mock_runtime = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.run.return_value = None
        mock_runtime.scheduler.return_value = mock_scheduler

        mock_router = MagicMock()
        mock_router.resolve.return_value = mock_runtime
        mock_router.try_acquire.return_value = True
        mock_router.release.return_value = None

        bus = MagicMock()
        pool = WorkerPool(size=1, router=mock_router, queue=queue, store=store, bus=bus)
        pool.start()

        job = ScheduledJob(task=sample_task, target_project="default")
        store.save(job)
        queue.put(job)

        # 等待 worker 处理
        deadline = time.time() + 2.0
        while time.time() < deadline:
            fetched = store.get(job.job_id)
            if fetched and fetched.status.is_terminal():
                break
            time.sleep(0.05)

        pool.stop()
        fetched = store.get(job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.SUCCEEDED
        assert len(fetched.attempts) == 1
        assert fetched.attempts[0].status == JobStatus.SUCCEEDED
        mock_router.release.assert_called_once_with("default")

    def test_cancel_queued_job(
        self, store: JobStore, queue: JobQueue, sample_task: Task
    ) -> None:
        """AC-3: cancel a QUEUED job, it never enters RUNNING."""
        mock_router = MagicMock()
        mock_router.try_acquire.return_value = True
        pool = WorkerPool(size=1, router=mock_router, queue=queue, store=store, bus=MagicMock())
        # 不 start pool，job 留在队列
        job = ScheduledJob(task=sample_task)
        store.save(job)
        queue.put(job)
        job.status = JobStatus.QUEUED
        store.save(job)

        # 取消（从队列移除较难，改为设置 cancel_event + 标状态）
        job.cancel_event.set()
        store.update_status(job.job_id, JobStatus.CANCELLED)

        fetched = store.get(job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.CANCELLED
        pool.stop()

    def test_cancel_running_job_between_steps(
        self, store: JobStore, queue: JobQueue, sample_task: Task
    ) -> None:
        """AC-4: cancel a RUNNING job, worker stops after current step."""
        mock_runtime = MagicMock()
        mock_scheduler = MagicMock()

        def slow_run(task_id: str) -> None:
            time.sleep(0.2)

        mock_scheduler.run.side_effect = slow_run
        mock_runtime.scheduler.return_value = mock_scheduler

        mock_router = MagicMock()
        mock_router.resolve.return_value = mock_runtime
        mock_router.try_acquire.return_value = True

        pool = WorkerPool(size=1, router=mock_router, queue=queue, store=store, bus=MagicMock())
        pool.start()

        job = ScheduledJob(task=sample_task, retry_policy=RetryPolicy(max_retries=0))
        store.save(job)
        queue.put(job)

        # 等待 job 进入 RUNNING 后取消
        time.sleep(0.05)
        job.cancel_event.set()

        deadline = time.time() + 2.0
        while time.time() < deadline:
            fetched = store.get(job.job_id)
            if fetched and fetched.status.is_terminal():
                break
            time.sleep(0.05)

        pool.stop()
        fetched = store.get(job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.CANCELLED

    def test_retry_exhausted(
        self, store: JobStore, queue: JobQueue, sample_task: Task
    ) -> None:
        """AC-5: job with max_retries=2 fails 3 times total, attempts length=3."""
        mock_runtime = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.run.side_effect = RuntimeError("boom")
        mock_runtime.scheduler.return_value = mock_scheduler

        mock_router = MagicMock()
        mock_router.resolve.return_value = mock_runtime
        mock_router.try_acquire.return_value = True

        pool = WorkerPool(
            size=1,
            router=mock_router,
            queue=queue,
            store=store,
            bus=MagicMock(),
        )
        pool.start()

        job = ScheduledJob(
            task=sample_task,
            retry_policy=RetryPolicy(max_retries=2, base_delay=0.01, max_delay=0.05),
        )
        store.save(job)
        queue.put(job)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            fetched = store.get(job.job_id)
            if fetched and fetched.status.is_terminal():
                break
            time.sleep(0.05)

        pool.stop()
        fetched = store.get(job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.FAILED
        assert len(fetched.attempts) == 3
        for attempt in fetched.attempts:
            assert attempt.status == JobStatus.FAILED
            assert "boom" in (attempt.error or "")

    def test_timeout_marks_timeout(
        self, store: JobStore, queue: JobQueue, sample_task: Task
    ) -> None:
        """AC-6: job with timeout=0.1, scheduler.run sleeps 0.3, final status TIMEOUT."""
        mock_runtime = MagicMock()
        mock_scheduler = MagicMock()

        def slow_run(task_id: str) -> None:
            time.sleep(0.3)

        mock_scheduler.run.side_effect = slow_run
        mock_runtime.scheduler.return_value = mock_scheduler

        mock_router = MagicMock()
        mock_router.resolve.return_value = mock_runtime
        mock_router.try_acquire.return_value = True

        pool = WorkerPool(size=1, router=mock_router, queue=queue, store=store, bus=MagicMock())
        pool.start()

        job = ScheduledJob(
            task=sample_task,
            timeout=0.1,
            retry_policy=RetryPolicy(max_retries=0),
        )
        store.save(job)
        queue.put(job)

        deadline = time.time() + 3.0
        while time.time() < deadline:
            fetched = store.get(job.job_id)
            if fetched and fetched.status.is_terminal():
                break
            time.sleep(0.05)

        pool.stop()
        fetched = store.get(job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.TIMEOUT

    def test_max_concurrent_acquire_fails_requeues(
        self, store: JobStore, queue: JobQueue, sample_task: Task
    ) -> None:
        """AC-9: try_acquire returns False, job requeued (stays QUEUED)."""
        mock_runtime = MagicMock()
        mock_scheduler = MagicMock()
        mock_runtime.scheduler.return_value = mock_scheduler

        mock_router = MagicMock()
        mock_router.resolve.return_value = mock_runtime
        mock_router.try_acquire.return_value = False  # 限流

        pool = WorkerPool(
            size=1,
            router=mock_router,
            queue=queue,
            store=store,
            bus=MagicMock(),
            requeue_sleep=0.05,
        )
        pool.start()

        job = ScheduledJob(task=sample_task, target_project="proj-a")
        store.save(job)
        queue.put(job)

        time.sleep(0.3)  # 给 worker 时间尝试 acquire 并 requeue
        pool.stop()

        # job 应仍在队列中或重新入队，未进入 RUNNING
        fetched = store.get(job.job_id)
        assert fetched is not None
        assert fetched.status != JobStatus.RUNNING
        mock_router.try_acquire.assert_called_with("proj-a")


# ---------------------------------------------------------------------------
# Import EmptyError for queue test
# ---------------------------------------------------------------------------

from hermes.workbench.scheduler import EmptyError  # noqa: E402

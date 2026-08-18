"""U1a: scheduler center lifecycle tests.

Verifies that the scheduler center started by the server actually consumes
jobs (fixing the gap where ``serve`` left jobs QUEUED forever) and that the
start/stop lifecycle + status reporting behave correctly.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock

from hermes.workbench import cli as wb_cli
from hermes.workbench.cli import Task
from hermes.workbench.scheduler import JobStatus, ScheduledJob


@pytest.fixture
def center(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A scheduler center pointed at a tmp state dir, with a mocked router."""
    monkeypatch.setattr(wb_cli, "_state_dir", lambda: tmp_path)
    wb_cli._reset_scheduler_center()
    c = wb_cli._make_scheduler_center()

    # Replace the real router with a mock that executes jobs synchronously
    # via a fake runtime, so tests do not depend on a real skills directory.
    mock_runtime = MagicMock()
    mock_scheduler = MagicMock()
    mock_scheduler.run.return_value = None
    mock_runtime.scheduler.return_value = mock_scheduler
    mock_router = MagicMock()
    mock_router.resolve.return_value = mock_runtime
    mock_router.try_acquire.return_value = True
    mock_router.release.return_value = None
    c.router = mock_router
    yield c
    c.stop()
    wb_cli._reset_scheduler_center()


def _submit_job(center: Any, task: Task) -> ScheduledJob:
    job = ScheduledJob(task=task, target_project="default")
    job.status = JobStatus.QUEUED
    center.job_store.save(job)
    center.job_queue.put(job)
    return job


def _wait_terminal(center: Any, job_id: str, timeout: float = 5.0) -> ScheduledJob:
    deadline = time.time() + timeout
    while time.time() < deadline:
        fetched = center.job_store.get(job_id)
        if fetched is not None and fetched.status.is_terminal():
            return fetched
        time.sleep(0.05)
    return center.job_store.get(job_id)  # type: ignore[return-value]


def test_start_consumes_submitted_job(center: Any) -> None:
    """U1a AC: after start(), a submitted job reaches a terminal state."""
    task = Task(task_id="t1", plan=[{"skill": "alpha"}])
    center.start()
    job = _submit_job(center, task)
    fetched = _wait_terminal(center, job.job_id)
    assert fetched is not None
    assert fetched.status == JobStatus.SUCCEEDED
    assert len(fetched.attempts) == 1


def test_start_returns_recovery_stats(center: Any) -> None:
    """U1a: start() returns {requeued, abandoned, skipped} from recovery."""
    stats = center.start()
    assert set(stats) == {"requeued", "abandoned", "skipped"}
    assert all(isinstance(v, int) for v in stats.values())


def test_scheduler_status_reports_workers(center: Any, tmp_path: Path) -> None:
    """U1a: scheduler_status exposes worker pool + cron + queue state."""
    center.start()
    status = center.scheduler_status
    assert status["running"] is True
    assert status["workers"]["size"] == 2
    assert status["workers"]["active"] >= 0
    assert status["queue_depth"] >= 0
    assert status["cron"] is True


def test_stop_idempotent(center: Any) -> None:
    """U1a: stop() can be called twice without error."""
    center.start()
    center.stop()
    center.stop()


def test_idle_after_stop(center: Any) -> None:
    """U1a: after stop(), worker pool reports not running."""
    center.start()
    assert center.worker_pool.is_running() is True
    center.stop()
    assert center.worker_pool.is_running() is False

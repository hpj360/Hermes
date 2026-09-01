"""Tests for content_team crash recovery integration.

覆盖：
- RecoveryManager 在不同作业状态下的恢复行为（PENDING/QUEUED/RUNNING/终态）
- enabled=False 禁用恢复时的行为
- CONTENT_TEAM_SCHEDULER_RECOVERY 环境变量开关
- init_scheduler_on_startup 创建全部组件并启动工作线程池
- get_scheduler 单例语义
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from hermes.content_team.scheduler import (
    _reset_scheduler,
    get_scheduler,
    init_scheduler_on_startup,
    shutdown_scheduler,
)
from hermes.workbench.cli import Task
from hermes.workbench.recovery import RecoveryManager
from hermes.workbench.scheduler import (
    JobQueue,
    JobStatus,
    JobStore,
    ScheduledJob,
)


# ---------------------------------------------------------------------------
# 辅助函数与 fixtures
# ---------------------------------------------------------------------------


def _make_job(job_id: str, status: JobStatus) -> ScheduledJob:
    """构造指定 id 与状态的 ScheduledJob。"""
    task = Task(task_id=f"task-{job_id}", plan=[{"skill": "echo", "args": ["hi"]}])
    return ScheduledJob(
        task=task,
        job_id=job_id,
        target_project="default",
        status=status,
    )


@pytest.fixture
def reset_scheduler() -> Iterator[None]:
    """单例相关测试前后重置调度器单例，避免线程与状态泄漏。"""
    _reset_scheduler()
    yield
    _reset_scheduler()


# ---------------------------------------------------------------------------
# RecoveryManager 行为测试
# ---------------------------------------------------------------------------


def test_recovery_empty_store_returns_all_zeros(tmp_path: Path) -> None:
    """空存储恢复后应返回全零统计。"""
    store = JobStore(state_dir=tmp_path)
    queue = JobQueue()
    rm = RecoveryManager(store=store, queue=queue, memory=None)

    stats = rm.recover()

    assert stats == {"requeued": 0, "abandoned": 0, "skipped": 0}
    assert queue.size() == 0


def test_recovery_queued_job_gets_reenqueued(tmp_path: Path) -> None:
    """QUEUED 作业应被重新入队。"""
    store = JobStore(state_dir=tmp_path)
    queue = JobQueue()
    queued = _make_job("job-queued", JobStatus.QUEUED)
    store.save(queued)

    rm = RecoveryManager(store=store, queue=queue, memory=None)
    stats = rm.recover()

    assert stats["requeued"] == 1
    assert queue.size() == 1
    dequeued = queue.get(timeout=0.5)
    assert dequeued.job_id == queued.job_id


def test_recovery_running_job_marked_abandoned(tmp_path: Path) -> None:
    """RUNNING 作业应被标记为 ABANDONED。"""
    store = JobStore(state_dir=tmp_path)
    queue = JobQueue()
    running = _make_job("job-running", JobStatus.RUNNING)
    store.save(running)

    rm = RecoveryManager(store=store, queue=queue, memory=None)
    stats = rm.recover()

    assert stats["abandoned"] == 1
    updated = store.get(running.job_id)
    assert updated is not None
    assert updated.status == JobStatus.ABANDONED


def test_recovery_pending_job_gets_skipped(tmp_path: Path) -> None:
    """PENDING 作业应被跳过，状态保持不变。"""
    store = JobStore(state_dir=tmp_path)
    queue = JobQueue()
    pending = _make_job("job-pending", JobStatus.PENDING)
    store.save(pending)

    rm = RecoveryManager(store=store, queue=queue, memory=None)
    stats = rm.recover()

    assert stats == {"requeued": 0, "abandoned": 0, "skipped": 1}
    updated = store.get(pending.job_id)
    assert updated is not None
    assert updated.status == JobStatus.PENDING
    assert queue.size() == 0


def test_recovery_terminal_jobs_get_skipped(tmp_path: Path) -> None:
    """终态作业（SUCCEEDED/FAILED/CANCELLED）应全部被跳过。

    注：JobStatus 中成功态为 SUCCEEDED（任务描述中的 COMPLETED 对应此处）。
    """
    store = JobStore(state_dir=tmp_path)
    queue = JobQueue()
    terminals = [
        _make_job("job-succeeded", JobStatus.SUCCEEDED),
        _make_job("job-failed", JobStatus.FAILED),
        _make_job("job-cancelled", JobStatus.CANCELLED),
    ]
    for j in terminals:
        store.save(j)

    rm = RecoveryManager(store=store, queue=queue, memory=None)
    stats = rm.recover()

    assert stats == {"requeued": 0, "abandoned": 0, "skipped": 3}
    assert queue.size() == 0
    for j in terminals:
        updated = store.get(j.job_id)
        assert updated is not None
        assert updated.status == j.status


def test_recovery_disabled_abandons_queued_and_running(tmp_path: Path) -> None:
    """enabled=False 时 QUEUED 与 RUNNING 被标记 ABANDONED，PENDING 仍跳过。"""
    store = JobStore(state_dir=tmp_path)
    queue = JobQueue()
    pending = _make_job("job-pending", JobStatus.PENDING)
    queued = _make_job("job-queued", JobStatus.QUEUED)
    running = _make_job("job-running", JobStatus.RUNNING)
    for j in (pending, queued, running):
        store.save(j)

    rm = RecoveryManager(store=store, queue=queue, memory=None, enabled=False)
    stats = rm.recover()

    assert stats == {"requeued": 0, "abandoned": 2, "skipped": 1}
    assert store.get(queued.job_id).status == JobStatus.ABANDONED
    assert store.get(running.job_id).status == JobStatus.ABANDONED
    assert store.get(pending.job_id).status == JobStatus.PENDING
    assert queue.size() == 0


# ---------------------------------------------------------------------------
# 单例与启动集成测试
# ---------------------------------------------------------------------------


def test_get_scheduler_returns_same_singleton(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_scheduler: None
) -> None:
    """D2: get_scheduler 返回同一调度中心的同一组组件（门面语义）。"""
    monkeypatch.setattr(
        "hermes.workbench.services._state_dir", lambda: tmp_path / "state"
    )

    first = get_scheduler(state_dir=tmp_path)
    second = get_scheduler()

    # 返回的是门面 dict（每次新构造），但底层组件是同一个共享中心实例。
    assert first is not second
    assert first["store"] is second["store"]
    assert first["queue"] is second["queue"]
    assert first["pool"] is second["pool"]
    assert first["recovery"] is second["recovery"]


def test_init_scheduler_on_startup_creates_all_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_scheduler: None
) -> None:
    """D2: init_scheduler_on_startup 返回共享中心组件并启动工作线程池。"""
    monkeypatch.setattr(
        "hermes.workbench.services._state_dir", lambda: tmp_path / "state"
    )
    # 预先用 tmp_path 构造中心，避免写入项目 data 目录
    get_scheduler(state_dir=tmp_path)

    sched = init_scheduler_on_startup()
    try:
        assert sched["store"] is not None
        assert sched["queue"] is not None
        assert sched["pool"] is not None
        assert sched["recovery"] is not None
        # 工作线程池配置为 2 个 worker
        assert sched["pool"].size == 2
        # start 后应有 2 个工作线程在运行
        assert len(sched["pool"]._workers) == 2  # noqa: SLF001
    finally:
        shutdown_scheduler()


def test_env_var_disables_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_scheduler: None
) -> None:
    """HERMES_SCHEDULER_RECOVERY=off 时共享中心的 RecoveryManager 禁用恢复。"""
    monkeypatch.setattr(
        "hermes.workbench.services._state_dir", lambda: tmp_path / "state"
    )
    monkeypatch.setenv("HERMES_SCHEDULER_RECOVERY", "off")
    # 在构造单例前预置一个 QUEUED 作业
    sched = get_scheduler(state_dir=tmp_path)
    queued = _make_job("job-queued", JobStatus.QUEUED)
    sched["store"].save(queued)

    stats = sched["recovery"].recover()

    assert stats == {"requeued": 0, "abandoned": 1, "skipped": 0}
    updated = sched["store"].get(queued.job_id)
    assert updated is not None
    assert updated.status == JobStatus.ABANDONED

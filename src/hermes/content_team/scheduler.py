"""Content-team scheduler integration.

Wraps hermes workbench scheduler and recovery for content-team use:
- Initializes JobStore, JobQueue, WorkerPool
- Integrates RecoveryManager for crash recovery on startup
- Provides singleton access to scheduler components
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from hermes.content_team.memory import get_memory_service
from hermes.content_team.observability import log_event
from hermes.workbench.recovery import RecoveryManager
from hermes.workbench.scheduler import JobQueue, JobStore, WorkerPool

__all__ = [
    "get_scheduler",
    "init_scheduler_on_startup",
    "shutdown_scheduler",
]


# 存储目录：项目根目录下的 data/content_team_jobs/
# JobStore 会在该目录下创建 jobs.json
_DEFAULT_STATE_DIR = Path(__file__).resolve().parents[3] / "data" / "content_team_jobs"

# 单例实例与保护锁
_SCHEDULER: dict[str, Any] | None = None
_SCHEDULER_LOCK = threading.Lock()

# 环境变量名：控制是否启用崩溃恢复（值为 "off" 时禁用）
_RECOVERY_ENV_VAR = "CONTENT_TEAM_SCHEDULER_RECOVERY"


class _NoopRouter:
    """占位 Router。

    content_team 尚未接入真实的 ProjectRuntime，而 WorkerPool 构造时需要
    一个提供 ``resolve`` / ``try_acquire`` / ``release`` 接口的对象。在
    content_team 真正接入任务执行前使用该占位实现：``resolve`` 抛出明确
    错误，使被消费的作业快速失败而非静默成功。后续接入真实执行链路时，
    将其替换为 ``hermes.workbench.projects.Router`` 即可。
    """

    def resolve(self, project_id: str) -> Any:
        raise RuntimeError(
            "content_team scheduler has no project runtime wired; "
            "job execution is not yet supported"
        )

    def try_acquire(self, project_id: str) -> bool:
        return True

    def release(self, project_id: str) -> None:
        return None


def _recovery_enabled() -> bool:
    """读取 ``CONTENT_TEAM_SCHEDULER_RECOVERY`` 环境变量（默认 "on"）。

    值为 "off"（不区分大小写、忽略首尾空白）时返回 False，表示禁用
    自动恢复，QUEUED 与 RUNNING 作业都会被标记为 ABANDONED。
    """
    raw = os.environ.get(_RECOVERY_ENV_VAR, "on")
    return raw.strip().lower() != "off"


def _build_scheduler(state_dir: Path | str | None = None) -> dict[str, Any]:
    """构造调度器各组件并返回组件字典。"""
    resolved_dir = Path(state_dir) if state_dir is not None else _DEFAULT_STATE_DIR
    store = JobStore(state_dir=resolved_dir)
    queue = JobQueue()
    router = _NoopRouter()
    # 2 个守护线程 worker；WorkerPool.start() 内部以 daemon=True 创建线程
    pool = WorkerPool(size=2, router=router, queue=queue, store=store)

    # 内存服务：best-effort 接入，失败时降级为 None，不阻断恢复流程
    try:
        memory = get_memory_service()
    except Exception:  # noqa: BLE001
        memory = None

    recovery = RecoveryManager(
        store=store,
        queue=queue,
        memory=memory,
        enabled=_recovery_enabled(),
    )
    return {"store": store, "queue": queue, "pool": pool, "recovery": recovery}


def get_scheduler(state_dir: Path | str | None = None) -> dict[str, Any]:
    """获取（或首次初始化）content_team 调度器单例。

    返回包含 ``store`` / ``queue`` / ``pool`` / ``recovery`` 四个组件的
    字典。首次调用时按需构造；后续调用返回同一实例（此时 ``state_dir``
    入参将被忽略）。
    """
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        if _SCHEDULER is None:
            _SCHEDULER = _build_scheduler(state_dir=state_dir)
        return _SCHEDULER


def init_scheduler_on_startup() -> dict[str, Any]:
    """应用启动时执行崩溃恢复并启动工作线程池。

    - 获取调度器单例
    - 调用 ``recovery.recover()`` 并以结构化日志记录恢复统计
    - 启动 WorkerPool（已启动则幂等返回）
    """
    sched = get_scheduler()
    stats = sched["recovery"].recover()
    log_event(
        "scheduler_recovery",
        "crash recovery completed",
        requeued=stats["requeued"],
        abandoned=stats["abandoned"],
        skipped=stats["skipped"],
    )
    sched["pool"].start()
    log_event("scheduler_started", "worker pool started", workers=2)
    return sched


def shutdown_scheduler() -> None:
    """应用关闭时优雅停止工作线程池。"""
    sched = get_scheduler()
    try:
        sched["pool"].stop()
    finally:
        log_event("scheduler_stopped", "worker pool stopped")


def _reset_scheduler() -> None:
    """重置调度器单例（仅供测试使用）。

    会先尝试停止已启动的工作线程池，再清空单例，确保测试间互不干扰。
    """
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        if _SCHEDULER is not None:
            try:
                _SCHEDULER["pool"].stop()
            except Exception:  # noqa: BLE001
                pass
        _SCHEDULER = None

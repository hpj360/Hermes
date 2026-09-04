"""Service factories: dependency wiring for workbench services.

从 workbench/cli.py 拆出的服务装配层（原 1691 行巨型文件的
L304-594）：``_state_dir`` 与全部 ``_make_*`` 工厂、memory 缓存、
SchedulerCenter（Phase 3 调度中心）单例。CLI 命令、HTTP handlers、
content_team 通过 ``hermes.workbench.cli`` 的 re-export 访问这里。

patch 语义（tests 依赖，勿改）：
- 测试 patch ``hermes.workbench.services._state_dir`` 影响本模块内的
  所有工厂（工厂在此命名空间解析 ``_state_dir``）。
- 测试 patch ``cli._make_memory`` / ``cli._make_scheduler_center`` 仍有效：
  调用方（server_routes / cli cmd handlers）经函数级 import 从 cli
  命名空间取绑定，re-export 会被正确替换。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from hermes.config import get_settings
from hermes.skills import skills_dir as _hermes_skills_dir
from hermes.workbench.agent_loop import AgentLoop
from hermes.workbench.memory import MemoryService
from hermes.workbench.skill_runner import SkillRunner
from hermes.workbench.task_runtime import TaskRegistry, TaskScheduler, TaskStore

__all__ = [
    "TaskRegistry",
    "TaskScheduler",
    "TaskStore",
    "_SchedulerCenter",
    "_attach_memory_backend",
    "_best_effort_memory",
    "_make_dag",
    "_make_llm",
    "_make_loop",
    "_make_memory",
    "_make_registry",
    "_make_runner",
    "_make_scheduler",
    "_make_scheduler_center",
    "_make_store",
    "_make_todo_store",
    "_make_notes_dir",
    "_recovery_enabled",
    "_reset_memory_cache",
    "_reset_scheduler_center",
    "_state_dir",
]


def _state_dir() -> Path:
    return get_settings().hermes_state_dir


def _make_runner() -> SkillRunner:
    return SkillRunner(base_dir=_hermes_skills_dir())


_memory_lock: threading.Lock = threading.Lock()
_memory_cache: dict[tuple[str, str, bool], MemoryService] = {}


def _reset_memory_cache() -> None:
    """Drop the cached memory services (used by tests for state isolation)."""
    global _memory_cache
    with _memory_lock:
        for svc in _memory_cache.values():
            svc.stop_sync()
        _memory_cache = {}


def _make_memory() -> MemoryService:
    from hermes.config import get_settings
    from hermes.workbench.memory import EmbeddingClient, MemosConfig

    settings = get_settings()
    # M4: cache the memory service per (state_dir, backend, sync) so long-running
    # `serve` mode reuses one instance and one sync worker instead of leaking a
    # daemon thread per request. Tests isolate via unique tmp state dirs; reset
    # with :func:`_reset_memory_cache` when a forced rebuild is required.
    key = (
        str(_state_dir()),
        settings.hermes_memory_backend.lower(),
        settings.hermes_memory_sync_enabled,
    )
    with _memory_lock:
        cached = _memory_cache.get(key)
        if cached is not None:
            return cached

        embed = EmbeddingClient(
            base_url=settings.ollama_embed_url,
            model=settings.ollama_embed_model,
        )
        memos_cfg = MemosConfig(
            enabled=settings.memos_enabled,
            base_url=settings.memos_base_url,
        )
        svc = MemoryService(
            state_dir=_state_dir(),
            embed_client=embed,
            memos_config=memos_cfg,
        )
        _attach_memory_backend(svc, settings)
        _memory_cache[key] = svc
        return svc


def _attach_memory_backend(svc: MemoryService, settings: Any) -> None:
    """Wire an external memory backend + async sync pipeline onto *svc* (M4).

    Default backend is the local RRF baseline built inside ``MemoryService``;
    only ``mem0`` requires an explicit attachment here. The sync pipeline is
    only started for non-local backends when explicitly enabled.
    """
    name = settings.hermes_memory_backend.lower()
    if name == "mem0":
        from hermes.workbench.mem0_adapter import Mem0Backend, Mem0BackendConfig

        cfg = Mem0BackendConfig(
            llm_model=settings.hermes_mem0_llm_model or settings.hermes_llm_model,
            embed_model=settings.hermes_mem0_embed_model or settings.ollama_embed_model,
            llm_base_url=settings.ollama_base_url,
            embed_base_url=settings.ollama_embed_url,
        )
        svc.set_backend(Mem0Backend(memory=svc, state_dir=_state_dir(), config=cfg))

    if settings.hermes_memory_sync_enabled and name != "local_rrf":
        from hermes.workbench.memory_sync import MemorySyncConfig, MemorySyncService

        sync_cfg = MemorySyncConfig(
            enabled=True,
            batch_size=settings.hermes_memory_sync_batch_size,
        )
        sync = MemorySyncService(
            backend=svc.get_backend(), state_dir=_state_dir(), config=sync_cfg
        )
        svc.set_sync(sync)
        sync.start()


def _make_loop() -> AgentLoop:
    return AgentLoop(runner=_make_runner(), memory=_make_memory())


def _make_store() -> TaskStore:
    return TaskStore(state_dir=_state_dir())


def _make_registry() -> TaskRegistry:
    return TaskRegistry()


def _make_llm() -> Any | None:
    """Build an LLM client from settings, or None when unavailable.

    Silently returns None when the provider is unconfigured so that loop
    mode falls back to the rule-based planner/evaluator without crashing.
    """
    try:
        from hermes.workbench.llm import make_llm_client
        return make_llm_client()
    except Exception:  # noqa: BLE001 — config errors are non-fatal here
        return None


def _make_scheduler() -> TaskScheduler:
    return TaskScheduler(
        store=_make_store(),
        registry=_make_registry(),
        runner=_make_runner(),
        memory=_make_memory(),
        llm=_make_llm(),
    )


def _best_effort_memory() -> Any | None:
    """Build a memory service for recovery audit, or None when unavailable."""
    try:
        return _make_memory()
    except Exception:  # noqa: BLE001 — recovery must not break on memory issues
        return None


def _recovery_enabled() -> bool:
    """Whether crash recovery is enabled (HERMES_SCHEDULER_RECOVERY != 'off')."""
    import os

    raw = os.environ.get("HERMES_SCHEDULER_RECOVERY", "on")
    return raw.strip().lower() != "off"


# ---------------------------------------------------------------------------
# Phase 3 scheduler center (JobStore/Queue/StatusBus/Router/Trigger/DAG)
# ---------------------------------------------------------------------------


class _SchedulerCenter:
    """Bundle of the Phase 3.1-3.6 services that must share in-memory state.

    ``JobQueue`` and ``StatusBus`` are inherently in-memory (priority queue +
    pub/sub), so a single cached instance must back the whole server/CLI run.
    ``JobStore`` / ``ProjectRegistry`` / ``TriggerStore`` re-read from disk on
    first construction but are then cached so concurrent handlers see a
    consistent snapshot.
    """

    __slots__ = (
        "cron_continuity",
        "cron_scheduler",
        "dag",
        "job_queue",
        "job_store",
        "project_registry",
        "recovery",
        "router",
        "status_bus",
        "trigger_store",
        "worker_pool",
    )

    def __init__(self) -> None:
        from hermes.workbench.cron_memory import CronContinuity
        from hermes.workbench.dag import DependencyGraph
        from hermes.workbench.projects import ProjectRegistry, Router
        from hermes.workbench.recovery import RecoveryManager
        from hermes.workbench.scheduler import JobQueue, JobStatus, JobStore, StatusBus, WorkerPool
        from hermes.workbench.triggers import CronScheduler, TriggerStore

        self.job_store = JobStore(state_dir=_state_dir())
        self.job_queue = JobQueue()
        self.status_bus = StatusBus()
        self.project_registry = ProjectRegistry(state_dir=_state_dir())
        self.router = Router(self.project_registry)
        self.trigger_store = TriggerStore(state_dir=_state_dir())

        # Fired jobs must be persisted (so they are visible in /jobs and
        # recoverable on crash) before being handed to the queue.
        def _submit_fired_job(job: Any) -> None:
            job.status = JobStatus.QUEUED
            self.job_store.save(job)
            self.job_queue.put(job)
            self.status_bus.emit(job)

        # P4-1：continuity 触发器派发时注入跨运行记忆（notepad + 上次摘要）。
        self.cron_continuity = CronContinuity(
            state_dir=_state_dir(), memory=_best_effort_memory()
        )
        self.cron_scheduler = CronScheduler(
            self.trigger_store, _submit_fired_job, continuity=self.cron_continuity
        )
        self.dag = DependencyGraph(
            self.job_store, self.job_queue, self.status_bus
        )

        # 调度执行主线（P0 U1a）：serve 模式下必须真正消费 job，否则
        # POST /jobs 的 job 永远停在 QUEUED。WorkerPool 消费队列，
        # RecoveryManager 处理崩溃遗留，on_job_done 接 DAG 级联回调。
        self.worker_pool = WorkerPool(
            size=2,
            router=self.router,
            queue=self.job_queue,
            store=self.job_store,
            bus=self.status_bus,
            on_job_done=self.dag.on_job_done,
        )
        self.recovery = RecoveryManager(
            store=self.job_store,
            queue=self.job_queue,
            memory=_best_effort_memory(),
            enabled=_recovery_enabled(),
        )

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """Run crash recovery, then start the worker pool and cron scheduler.

        Returns the recovery stats ``{requeued, abandoned, skipped}`` so the
        server can surface them. All three steps are idempotent.
        """
        stats = self.recovery.recover()
        self.worker_pool.start()
        self.cron_scheduler.start()
        return stats

    def stop(self) -> None:
        """Stop cron scheduler and worker pool (graceful)."""
        self.cron_scheduler.stop()
        self.worker_pool.stop()

    @property
    def scheduler_status(self) -> dict[str, Any]:
        """Human/API-facing scheduler status (worker active/idle + queue)."""
        return {
            "running": self.worker_pool.is_running() or self.cron_scheduler.is_running(),
            "workers": {
                "active": self.worker_pool.active_count(),
                "idle": max(0, self.worker_pool.size - self.worker_pool.active_count()),
                "size": self.worker_pool.size,
            },
            "queue_depth": self.job_queue.size(),
            "cron": self.cron_scheduler.is_running(),
        }


_center_lock: threading.Lock = threading.Lock()
_center: _SchedulerCenter | None = None


def _make_scheduler_center() -> _SchedulerCenter:
    """Return the cached scheduler center, building it lazily on first call.

    Tests can reset the cache via :func:`_reset_scheduler_center` or monkeypatch
    this function to inject a center pointed at a tmp state dir.
    """
    global _center
    if _center is None:
        with _center_lock:
            if _center is None:
                _center = _SchedulerCenter()
    return _center


def _reset_scheduler_center() -> None:
    """Drop the cached scheduler center (used by tests for state isolation)."""
    global _center
    with _center_lock:
        _center = None


def _make_todo_store() -> Any:
    """Build (or reuse) the TodoStore backed by the shared state dir."""
    from hermes.workbench.todos import TodoStore

    return TodoStore(state_dir=_state_dir())


def _make_notes_dir() -> Any:
    """Resolve the capture notes directory (HERMES_NOTES_DIR)."""
    notes_dir = get_settings().hermes_notes_dir
    if not notes_dir.is_absolute():
        notes_dir = get_settings().hermes_state_dir.parent / notes_dir
    return notes_dir


def _make_dag() -> Any:
    """Return the shared :class:`DependencyGraph` from the scheduler center."""
    return _make_scheduler_center().dag

"""Content-team scheduler integration (D2: converged single scheduler).

Since PRD decision D2, content-team no longer owns a second
``JobStore``/``JobQueue``/``WorkerPool``. This module is a thin facade over
the workbench scheduler center (``hermes.workbench.cli._make_scheduler_center``):

* **One JobStore / JobQueue / WorkerPool / RecoveryManager** — the same center
  the gateway starts, so publish/collect jobs submitted here are persisted to
  the shared ``jobs.db``, recovered on crash, and executed by the gateway
  workers.
* **One Router** — the ``content-team`` project is registered in the center's
  ``ProjectRegistry`` with ``config.executor == "content-team"`` so fired jobs
  targeting ``content-team`` resolve to ``ContentTeamTaskScheduler`` (which
  dispatches publish/collect via ``PublishDispatcher`` / ``MetricsCollector``).
* ``init_scheduler_on_startup`` / ``shutdown_scheduler`` remain idempotent and
  may be called from the gateway lifespan or a legacy content_team app entry.
"""
from __future__ import annotations

import threading
from typing import Any

from hermes.content_team.observability import log_event

__all__ = [
    "get_scheduler",
    "init_scheduler_on_startup",
    "shutdown_scheduler",
    "ensure_content_team_project",
]

# 单例锁（仅保护并发初始化竞争；真正的单例由 workbench 中心管理）
_INIT_LOCK = threading.Lock()
_CONTENT_TEAM_PROJECT_ID = "content-team"


def _center() -> Any:
    """Return the shared workbench scheduler center (the single scheduler)."""
    from hermes.workbench.cli import _make_scheduler_center

    return _make_scheduler_center()


def ensure_content_team_project(center: Any) -> Any:
    """Register the ``content-team`` project in the center's registry (idempotent).

    The project routes to ``ContentTeamTaskScheduler`` (publish/collect)
    instead of the generic skill loop. ``state_dir`` points at the shared
    state dir so memory/task stores stay on the anchored data path.
    """
    from hermes.config import get_settings

    registry = center.project_registry
    if registry.get(_CONTENT_TEAM_PROJECT_ID) is not None:
        return registry.get(_CONTENT_TEAM_PROJECT_ID)
    conn = registry.add(
        name="Content Team",
        project_type="api",
        state_dir=str(get_settings().hermes_state_dir),
        config={"executor": "content-team"},
        max_concurrent=2,
        conn_id=_CONTENT_TEAM_PROJECT_ID,
    )
    log_event("content_team_project_registered", "content-team 项目已注册到调度中心")
    return conn


def get_scheduler(state_dir: object = None) -> dict[str, Any]:
    """Return the shared scheduler components as ``{store, queue, pool, recovery}``.

    ``state_dir`` is ignored (kept for backward compatibility) — D2 requires a
    single store backed by the workbench center.
    """
    with _INIT_LOCK:
        center = _center()
        ensure_content_team_project(center)
        return {
            "store": center.job_store,
            "queue": center.job_queue,
            "pool": center.worker_pool,
            "recovery": center.recovery,
        }


def init_scheduler_on_startup() -> dict[str, Any]:
    """Start the shared scheduler center (recovery + worker pool) if needed.

    Also registers the ``content-team`` project and returns the components
    dict. Idempotent — safe to call from both the gateway lifespan and any
    legacy content_team app entry.
    """
    center = _center()
    stats = center.start()
    ensure_content_team_project(center)
    log_event(
        "scheduler_recovery",
        "crash recovery completed (shared center)",
        requeued=stats["requeued"],
        abandoned=stats["abandoned"],
        skipped=stats["skipped"],
    )
    log_event("scheduler_started", "shared worker pool started", workers=center.worker_pool.size)
    return {
        "store": center.job_store,
        "queue": center.job_queue,
        "pool": center.worker_pool,
        "recovery": center.recovery,
    }


def shutdown_scheduler() -> None:
    """Gracefully stop the shared scheduler center."""
    try:
        center = _center()
        center.stop()
    except Exception:  # noqa: BLE001
        pass
    log_event("scheduler_stopped", "shared worker pool stopped")


def _reset_scheduler() -> None:
    """Reset the workbench center cache (only for tests)."""
    from hermes.workbench import cli as wb_cli

    wb_cli._reset_scheduler_center()

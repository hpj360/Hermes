"""content_team 任务执行运行时（P1-1 修复：接通定时发布/采集链路）。

工作台调度中心的 ``WorkerPool`` 消费 ``ScheduledJob`` 后调用
``runtime.scheduler().run(task.task_id)``。此前 content_team 用
``_NoopRouter``（``resolve`` 直接抛错），导致 cron 触发的发布/采集 job
必然 FAILED。本模块提供一个真实可执行的运行时，把 job 里携带的业务上下
文（``task.goal`` 中的 ``type`` / ``payload``）分发给真实的
``PublishDispatcher`` / ``MetricsCollector``，让定时发布与每日采集真正落地。

职责边界：
- ``ContentTeamTaskScheduler``：duck-type 兼容 ``runtime.scheduler().run(task_id)``，
  但 ``task_id`` 只是索引键；真正的业务参数从 ``task.goal``（``type``/``payload``）
  恢复，避免依赖空的 ``TaskRegistry``。
- 发布/采集为 async 业务；worker 线程通过 ``asyncio.run`` 桥接（每次独立
  event loop，避免跨线程复用 loop 的隐患）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from hermes.content_team.db import AsyncSessionLocal
from hermes.content_team.observability import log_event

__all__ = [
    "ContentTeamTaskScheduler",
    "ContentTeamRuntime",
    "ContentTeamRouter",
    "execute_content_team_task",
]


# ---------------------------------------------------------------------------
# 任务执行（async → sync 桥接）
# ---------------------------------------------------------------------------


async def _run_publish(payload: dict[str, Any]) -> dict[str, Any]:
    """执行一次定时发布：把 SCHEDULED 任务真正分发到平台（fan-out）。"""
    from hermes.content_team.publish.dispatcher import (
        PublishDispatcher,
    )

    content_id = payload.get("content_id")
    platform = payload.get("platform")
    account_ids = payload.get("platform_account_ids") or []

    if not content_id:
        return {"ok": False, "error": "publish payload missing content_id"}

    async with AsyncSessionLocal() as session:
        dispatcher = PublishDispatcher(db_session=session)
        # 定时发布语义：按平台找到该内容已 SCHEDULED 的发布任务并执行。
        # 优先使用显式账号列表；否则按平台解析全部账号。
        if not account_ids:
            from hermes.content_team.models.platform import Platform

            try:
                platform_enum = Platform(platform) if platform else None
            except ValueError:
                platform_enum = None
            if platform_enum is not None:
                # fan-out 到该平台下的所有启用账号
                from hermes.content_team.models.platform import PlatformAccount
                from sqlalchemy import select

                rows = await session.execute(
                    select(PlatformAccount.id).where(
                        PlatformAccount.platform == platform_enum,
                        PlatformAccount.status == "active",
                    )
                )
                account_ids = [r[0] for r in rows.all()]

        if not account_ids:
            return {"ok": False, "error": "no platform accounts to publish to"}

        from uuid import UUID

        try:
            content_uuid = UUID(str(content_id))
        except ValueError:
            return {"ok": False, "error": f"invalid content_id: {content_id!r}"}

        tasks = await dispatcher.dispatch(
            content_id=content_uuid,
            platform_accounts=account_ids,
        )
        return {
            "ok": True,
            "published": len(tasks),
            "statuses": [t.status.value for t in tasks],
        }


async def _run_collect(payload: dict[str, Any]) -> dict[str, Any]:
    """执行一次指标采集（每日采集触发器）。"""
    from hermes.content_team.analytics.collector import MetricsCollector

    async with AsyncSessionLocal() as session:
        collector = MetricsCollector(db_session=session)
        collected = await collector.collect_all()
        return {"ok": True, "collected": collected}


def execute_content_team_task(task: Any) -> dict[str, Any]:
    """按 task.goal 的 type 分发执行 content_team 业务，返回结果字典。

    任何异常都被捕获并转化为 ``{"ok": False, "error": ...}``，让 worker 的
    重试/失败记账逻辑接管，而不是让 worker 线程崩溃。
    """
    goal = getattr(task, "goal", None) or {}
    if not isinstance(goal, dict):
        goal = {}
    task_type = str(goal.get("type", "") or "")
    raw_payload = goal.get("payload")
    payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}

    coro: Any
    if task_type == "publish":
        coro = _run_publish(payload)
    elif task_type == "collect":
        coro = _run_collect(payload)
    else:
        return {"ok": False, "error": f"unknown content_team task type: {task_type!r}"}

    try:
        return asyncio.run(coro)
    except Exception as exc:  # noqa: BLE001 — worker 记账依赖结构化错误，不在此崩溃
        log_event("content_team_task_failed", "定时任务执行失败", error=str(exc))
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 运行时 / Router（duck-type 兼容 WorkerPool 的调用约定）
# ---------------------------------------------------------------------------


class _TaskRegistryAdapter:
    """最小登记表：提供 ``register``，兼容 WorkerPool 的注册调用约定。"""

    def __init__(self) -> None:
        self._tasks: dict[str, Any] = {}

    def register(self, task: Any) -> Any:
        self._tasks[getattr(task, "task_id", "") or ""] = task
        return task

    def get(self, task_id: str) -> Any | None:
        return self._tasks.get(task_id)


class ContentTeamTaskScheduler:
    """兼容 ``runtime.scheduler()`` 与 ``WorkerPool`` 调用约定的执行器。

    ``WorkerPool._run_with_retries`` 会先把 ``job.task`` 注册进 ``registry``，
    再调用 ``run(task_id)``。本类用 ``registry`` 保存 ``task_id → task`` 映射，
    从 ``task.goal`` 恢复业务上下文（``type``/``payload``）并分发给真实的
    ``PublishDispatcher`` / ``MetricsCollector``。
    """

    def __init__(self) -> None:
        self.registry = _TaskRegistryAdapter()

    def run(self, task_id: str) -> dict[str, Any]:
        """执行任务；task 从 ``registry[task_id]`` 解析。

        当业务结果 ``ok=False`` 时抛 :class:`RuntimeError`，让 worker 的失败
        记账与重试逻辑接管，而不是把失败静默记为 SUCCEEDED。
        """
        task = self.registry.get(task_id)
        if task is None:
            raise RuntimeError(f"task {task_id!r} not resolvable")
        result = execute_content_team_task(task)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "content_team task failed")
        return result


class ContentTeamRuntime:
    """提供 ``.scheduler()`` 的运行时对象。"""

    def scheduler(self) -> ContentTeamTaskScheduler:
        return ContentTeamTaskScheduler()


class ContentTeamRouter:
    """Duck-type Router：``resolve`` 返回 ContentTeamRuntime。

    ``try_acquire`` / ``release`` 恒真/空操作：content_team 是单业务，不设
    跨项目并发上限。
    """

    def resolve(self, project_id: str) -> ContentTeamRuntime:
        return ContentTeamRuntime()

    def try_acquire(self, project_id: str) -> bool:
        return True

    def release(self, project_id: str) -> None:
        return None

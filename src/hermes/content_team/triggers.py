"""Content-team Cron trigger integration.

Registers content-specific Cron triggers:
- Daily data collection (default: 0 9 * * *)
- Scheduled publishing (custom cron per publish task)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from hermes.content_team.observability import log_event
from hermes.workbench.scheduler import ScheduledJob
from hermes.workbench.triggers import CronScheduler, Trigger, TriggerStore

__all__ = [
    "get_trigger_store",
    "register_daily_collection_trigger",
    "register_publish_trigger",
    "list_triggers",
    "enable_trigger",
    "disable_trigger",
    "delete_trigger",
    "init_cron_scheduler",
    "shutdown_cron_scheduler",
]

# 存储目录：项目根目录下的 data/content_team_triggers/
# TriggerStore 会在该目录内创建 triggers.json 持久化文件
_STORAGE_DIR = Path(__file__).resolve().parents[3] / "data" / "content_team_triggers"

# 单例 TriggerStore
_trigger_store: TriggerStore | None = None

# 单例 CronScheduler 守护线程
_cron_scheduler: CronScheduler | None = None


def get_trigger_store() -> TriggerStore:
    """获取（或首次初始化）content_team 的单例 TriggerStore。

    存储目录为 ``data/content_team_triggers/``，触发器持久化文件为该
    目录下的 ``triggers.json``。目录不存在时自动创建。
    """
    global _trigger_store
    if _trigger_store is None:
        _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        _trigger_store = TriggerStore(state_dir=_STORAGE_DIR)
    return _trigger_store


# ---------------------------------------------------------------------------
# 触发器注册
# ---------------------------------------------------------------------------


def register_daily_collection_trigger(cron_expr: str = "0 9 * * *") -> str:
    """注册"每日数据采集"Cron 触发器。

    :param cron_expr: 5 字段 cron 表达式，默认每天 09:00
    :returns: 新建触发器的 trigger_id
    """
    store = get_trigger_store()
    trigger = Trigger(
        job_template={
            "type": "data_collection",
            "payload": {"action": "collect_metrics"},
        },
        trigger_type="cron",
        config={"cron": cron_expr},
    )
    store.save(trigger)
    log_event(
        "trigger_registered",
        "注册每日数据采集触发器",
        trigger_id=trigger.trigger_id,
        cron=cron_expr,
        type="data_collection",
    )
    return trigger.trigger_id


def register_publish_trigger(cron_expr: str, content_id: Any, platform: str) -> str:
    """注册"定时发布"Cron 触发器。

    :param cron_expr: 5 字段 cron 表达式
    :param content_id: 待发布内容 ID（会被转为字符串存入 payload）
    :param platform: 目标发布平台
    :returns: 新建触发器的 trigger_id
    """
    store = get_trigger_store()
    trigger = Trigger(
        job_template={
            "type": "publish",
            "payload": {
                "content_id": str(content_id),
                "platform": platform,
            },
        },
        trigger_type="cron",
        config={"cron": cron_expr},
    )
    store.save(trigger)
    log_event(
        "trigger_registered",
        "注册定时发布触发器",
        trigger_id=trigger.trigger_id,
        cron=cron_expr,
        type="publish",
        content_id=str(content_id),
        platform=platform,
    )
    return trigger.trigger_id


# ---------------------------------------------------------------------------
# 触发器管理
# ---------------------------------------------------------------------------


def list_triggers() -> list[Trigger]:
    """列出所有已注册的触发器。"""
    return get_trigger_store().list()


def enable_trigger(trigger_id: str) -> bool:
    """启用指定触发器。

    :returns: 操作是否成功（触发器不存在时返回 False）
    """
    return get_trigger_store().update_enabled(trigger_id, True)


def disable_trigger(trigger_id: str) -> bool:
    """禁用指定触发器。

    :returns: 操作是否成功（触发器不存在时返回 False）
    """
    return get_trigger_store().update_enabled(trigger_id, False)


def delete_trigger(trigger_id: str) -> bool:
    """删除指定触发器。

    :returns: 操作是否成功（触发器不存在时返回 False）
    """
    return get_trigger_store().delete(trigger_id)


# ---------------------------------------------------------------------------
# CronScheduler 守护线程
# ---------------------------------------------------------------------------


def _get_submit_callback() -> Callable[[ScheduledJob], None]:
    """获取提交回调：优先使用 content_team.scheduler 的 JobQueue.put。

    ``hermes.content_team.scheduler`` 可能尚未实现，此时回退为 no-op 回调，
    保证 CronScheduler 守护线程仍可启动并扫描触发器（仅不实际入队）。
    """
    try:
        from hermes.content_team.scheduler import get_scheduler  # type: ignore[import-not-found]
    except ImportError:
        get_scheduler = None

    if get_scheduler is not None:
        try:
            components = get_scheduler()
            # 兼容对象（.queue）与字典（["queue"]）两种返回形式
            queue = getattr(components, "queue", None)
            if queue is None and isinstance(components, dict):
                queue = components.get("queue")
            if queue is not None and hasattr(queue, "put"):
                return queue.put  # type: ignore[no-any-return]
        except Exception:
            pass  # 回退到 no-op

    def _noop_submit(job: ScheduledJob) -> None:
        log_event(
            "cron_job_noop_submit",
            "content_team.scheduler 不可用，跳过任务提交",
            job_id=job.job_id,
        )

    return _noop_submit


def init_cron_scheduler() -> CronScheduler:
    """初始化 CronScheduler 守护线程。

    - 从 :func:`get_trigger_store` 取触发器存储
    - 从 ``content_team.scheduler`` 取 JobQueue 作为提交回调（不可用时回退 no-op）
    - ``scan_interval=60`` 秒
    - 启动守护线程并记录 ``cron_scheduler_started`` 事件

    幂等：重复调用返回已运行的 CronScheduler 实例。
    :returns: 已启动的 CronScheduler 实例
    """
    global _cron_scheduler
    if _cron_scheduler is not None and _cron_scheduler.is_running():
        return _cron_scheduler
    store = get_trigger_store()
    submit_callback = _get_submit_callback()
    _cron_scheduler = CronScheduler(
        store=store,
        submit_callback=submit_callback,
        scan_interval=60,
    )
    _cron_scheduler.start()
    log_event(
        "cron_scheduler_started",
        "Cron 调度守护线程已启动",
        scan_interval=60,
    )
    return _cron_scheduler


def shutdown_cron_scheduler() -> None:
    """停止 CronScheduler 守护线程。"""
    global _cron_scheduler
    if _cron_scheduler is None:
        return
    _cron_scheduler.stop()
    log_event("cron_scheduler_stopped", "Cron 调度守护线程已停止")
    _cron_scheduler = None

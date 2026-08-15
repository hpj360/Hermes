"""Publish dispatcher - orchestrates multi-platform publishing using fan-out pattern.

发布调度器：将一条内容以 fan-out 方式分发到多个平台账号。

- 立即发布：对每个账号创建任务并同步调用适配器 ``publish``，根据结果更新状态。
- 定时发布：将任务状态置为 ``SCHEDULED``，并通过 ``register_publish_trigger``
  注册 Cron 触发器，由调度器在到点时触发实际发布。
- 重试与状态检查：支持对失败任务重试，以及通过适配器主动查询平台端状态。
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hermes.content_team.models.content import Content
from hermes.content_team.models.platform import Platform, PlatformAccount
from hermes.content_team.models.publish import PublishStatus, PublishTask
from hermes.content_team.observability import log_event
from hermes.content_team.publish.adapters.base import BaseAdapter, PublishResult
from hermes.content_team.publish.adapters.bilibili import BilibiliAdapter
from hermes.content_team.publish.adapters.douyin import DouyinAdapter
from hermes.content_team.publish.adapters.wechat import WeChatOfficialAdapter
from hermes.content_team.publish.adapters.wechat_video import WeChatVideoAdapter
from hermes.content_team.publish.adapters.xiaohongshu import XiaohongshuAdapter
from hermes.content_team.triggers import delete_trigger, register_publish_trigger
from hermes.workbench.triggers import CronScheduler


def _datetime_to_cron(dt: datetime) -> str:
    """将 ``datetime`` 转换为 5 字段 cron 表达式（匹配具体分钟）。"""
    # 确保 dt 带时区时使用 UTC 分量
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return f"{dt.minute} {dt.hour} {dt.day} {dt.month} *"


class PublishDispatcher:
    """发布调度器。

    通过 ``dispatch`` 方法将内容分发到多个平台账号（fan-out），通过
    ``get_adapter`` 工厂方法按平台选择适配器，并提供 ``check_task_status``
    与 ``retry_task`` 用于状态检查和失败重试。
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self.db = db_session

    # ------------------------------------------------------------------
    # 适配器工厂
    # ------------------------------------------------------------------

    def get_adapter(
        self, platform: Platform, account: PlatformAccount
    ) -> BaseAdapter:
        """根据平台返回对应的适配器实例。"""
        if platform == Platform.WECHAT_OFFICIAL:
            return WeChatOfficialAdapter(account)
        if platform == Platform.WECHAT_VIDEO:
            return WeChatVideoAdapter(account)
        if platform == Platform.DOUYIN:
            return DouyinAdapter(account)
        if platform == Platform.XIAOHONGSHU:
            return XiaohongshuAdapter(account)
        if platform == Platform.BILIBILI:
            return BilibiliAdapter(account)
        raise ValueError(f"暂不支持的平台: {platform}")

    # ------------------------------------------------------------------
    # 发布分发
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        content_id: UUID,
        platform_accounts: list[UUID],
        scheduled_at: datetime | None = None,
    ) -> list[PublishTask]:
        """将内容分发到多个平台账号。

        - ``scheduled_at`` 非空时：任务状态为 ``SCHEDULED``，并注册 Cron 触发器。
        - ``scheduled_at`` 为空时：立即调用适配器发布并更新状态。

        :returns: 创建的全部 ``PublishTask`` 列表
        :raises ValueError: 内容或账号不存在时
        """
        # 加载内容
        content = await self.db.get(Content, content_id)
        if content is None:
            raise ValueError(f"内容不存在: {content_id}")

        tasks: list[PublishTask] = []

        # P1-8：定时发布任务写入数据库、Cron 触发器写入独立 JSON 存储，二者
        # 非同一事务。预先校验 cron 表达式合法，并记录已注册的 trigger_id，
        # 以便后续账号失败时可回滚已注册的触发器，避免产生孤儿触发器。
        registered_trigger_ids: list[str] = []
        if scheduled_at is not None:
            cron_expr = _datetime_to_cron(scheduled_at)
            try:
                CronScheduler._matches_cron(cron_expr, datetime.now(timezone.utc))
            except Exception as exc:  # noqa: BLE001 — 非法 cron 应在登记前拒绝
                raise ValueError(f"非法定时时间，无法生成 cron 表达式: {exc}") from exc

        for account_id in platform_accounts:
            account = await self.db.get(PlatformAccount, account_id)
            if account is None:
                # 回滚已注册的触发器（补偿语义：不留下孤儿 trigger）。
                for tid in registered_trigger_ids:
                    try:
                        delete_trigger(tid)
                    except Exception:  # noqa: BLE001
                        pass
                raise ValueError(f"平台账号不存在: {account_id}")

            task = PublishTask(
                content_id=content_id,
                platform=account.platform,
                account_id=account_id,
                status=PublishStatus.PENDING,
            )

            if scheduled_at is not None:
                # 定时发布：置为 SCHEDULED 并注册 Cron 触发器
                task.scheduled_at = scheduled_at
                task.status = PublishStatus.SCHEDULED
                cron_expr = _datetime_to_cron(scheduled_at)
                try:
                    trigger_id = register_publish_trigger(
                        cron_expr,
                        str(content_id),
                        account.platform.value,
                    )
                    registered_trigger_ids.append(trigger_id)
                except Exception as exc:  # noqa: BLE001
                    # 注册失败：回滚已注册的触发器，避免部分成功的孤儿 trigger。
                    for tid in registered_trigger_ids:
                        try:
                            delete_trigger(tid)
                        except Exception:  # noqa: BLE001
                            pass
                    raise ValueError(
                        f"注册定时发布触发器失败: {exc}"
                    ) from exc
                log_event(
                    "publish_task_scheduled",
                    "发布任务已调度",
                    task_id=str(task.id) if task.id else None,
                    content_id=str(content_id),
                    platform=account.platform.value,
                    scheduled_at=scheduled_at.isoformat(),
                    trigger_id=trigger_id,
                )
            else:
                # 立即发布：调用适配器执行
                task.status = PublishStatus.IN_PROGRESS
                self.db.add(task)
                await self.db.flush()  # 确保 task.id 已生成

                adapter = self.get_adapter(account.platform, account)
                result = await adapter.publish(content)
                self._apply_result(task, result)

                log_event(
                    "publish_task_executed",
                    "发布任务已执行",
                    task_id=str(task.id),
                    content_id=str(content_id),
                    platform=account.platform.value,
                    status=task.status.value,
                )

            self.db.add(task)
            tasks.append(task)

        await self.db.commit()
        for task in tasks:
            await self.db.refresh(task)

        return tasks

    # ------------------------------------------------------------------
    # 状态检查
    # ------------------------------------------------------------------

    async def check_task_status(self, task_id: UUID) -> PublishTask:
        """主动检查任务在平台端的最新状态并更新。

        :raises ValueError: 任务或关联账号不存在时
        """
        task = await self.db.get(PublishTask, task_id)
        if task is None:
            raise ValueError(f"发布任务不存在: {task_id}")

        account = await self.db.get(PlatformAccount, task.account_id)
        if account is None:
            raise ValueError(f"平台账号不存在: {task.account_id}")

        adapter = self.get_adapter(task.platform, account)
        result = await adapter.check_status(task)
        self._apply_result(task, result)

        await self.db.commit()
        await self.db.refresh(task)
        return task

    # ------------------------------------------------------------------
    # 失败重试
    # ------------------------------------------------------------------

    async def retry_task(self, task_id: UUID) -> PublishTask:
        """重试失败的发布任务。

        仅允许对 ``FAILED`` 或 ``PARTIAL_SUCCESS`` 状态的任务进行重试。

        :raises ValueError: 任务不存在或状态不允许重试时
        """
        task = await self.db.get(PublishTask, task_id)
        if task is None:
            raise ValueError(f"发布任务不存在: {task_id}")

        if task.status not in (PublishStatus.FAILED, PublishStatus.PARTIAL_SUCCESS):
            raise ValueError(f"当前状态不允许重试: {task.status.value}")

        account = await self.db.get(PlatformAccount, task.account_id)
        if account is None:
            raise ValueError(f"平台账号不存在: {task.account_id}")

        content = await self.db.get(Content, task.content_id)
        if content is None:
            raise ValueError(f"内容不存在: {task.content_id}")

        # 重置状态并重新发布
        task.status = PublishStatus.IN_PROGRESS
        task.error_message = None

        adapter = self.get_adapter(task.platform, account)
        result = await adapter.publish(content)
        self._apply_result(task, result)

        log_event(
            "publish_task_retried",
            "发布任务已重试",
            task_id=str(task.id),
            status=task.status.value,
        )

        await self.db.commit()
        await self.db.refresh(task)
        return task

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_result(task: PublishTask, result: PublishResult) -> None:
        """将适配器返回的 ``PublishResult`` 应用到 ``PublishTask``。"""
        if result.success and result.error is None:
            # 完全成功
            task.status = PublishStatus.SUCCESS
            task.external_url = result.external_url
            task.error_message = None
            task.published_at = datetime.now(timezone.utc)
        elif result.success and result.error is not None:
            # 半自动模式：需要人工完成
            task.status = PublishStatus.PARTIAL_SUCCESS
            task.external_url = result.external_url
            task.error_message = result.error
            task.published_at = datetime.now(timezone.utc)
        else:
            # 发布失败
            task.status = PublishStatus.FAILED
            task.error_message = result.error or "发布失败"

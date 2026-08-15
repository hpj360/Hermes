"""数据采集服务 - 按计划从平台 API 拉取指标。

``MetricsCollector`` 提供单任务采集、批量采集以及按内容采集三种入口。
优先通过 :class:`MetricsAdapterRegistry` 中注册的真实平台适配器拉取指标；
当平台未注册适配器、适配器返回 ``None``（缺凭证/网络失败）时，回退到
基于 ``random`` 的可复现模拟（固定种子），保证无凭证环境仍可运行。
"""
from __future__ import annotations

import random
import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.content_team.analytics.adapters import (
    MetricsAdapterRegistry,
    MetricsSnapshot,
)
from hermes.content_team.models.content import Content
from hermes.content_team.models.metrics import ContentMetric
from hermes.content_team.models.platform import Platform
from hermes.content_team.models.publish import PublishStatus, PublishTask
from hermes.content_team.observability import log_event

# 固定随机种子，保证模拟指标在测试中可复现
_RANDOM_SEED = 42
# 各平台的模拟参数：(views_min, views_max, engagement_ratio)
# engagement_ratio 表示 likes + comments + shares 相对 views 的整体互动率
_PLATFORM_SIM_PARAMS: dict[Platform, tuple[int, int, float]] = {
    Platform.WECHAT_OFFICIAL: (100, 10_000, 0.05),
    Platform.WECHAT_VIDEO: (500, 50_000, 0.08),
    Platform.DOUYIN: (1_000, 100_000, 0.10),
    Platform.XIAOHONGSHU: (200, 20_000, 0.12),
    Platform.BILIBILI: (300, 30_000, 0.06),
}

# 互动率在 likes / comments / shares 之间的拆分比例
# likes : comments : shares = 0.7 : 0.2 : 0.1
_LIKES_SHARE = 0.7
_COMMENTS_SHARE = 0.2
_SHARES_SHARE = 0.1

# 粉丝增减的模拟范围
_FOLLOWERS_GAINED_MAX = 200
_FOLLOWERS_LOST_MAX = 50


def _simulate_metrics_for_platform(
    platform: Platform, rng: random.Random
) -> dict[str, int | float]:
    """根据平台特定的范围与互动率模拟一条指标快照。

    :param platform: 目标平台
    :param rng: 已种子化的 random.Random 实例
    :returns: 包含 views/likes/comments/shares/followers_gained/
              followers_lost/engagement_rate 的字典
    """
    views_min, views_max, engagement_ratio = _PLATFORM_SIM_PARAMS[platform]
    views = rng.randint(views_min, views_max)
    # 总互动量 = views * engagement_ratio，再拆分到 likes/comments/shares
    total_engagement = int(views * engagement_ratio)
    likes = int(total_engagement * _LIKES_SHARE)
    comments = int(total_engagement * _COMMENTS_SHARE)
    shares = total_engagement - likes - comments
    followers_gained = rng.randint(0, _FOLLOWERS_GAINED_MAX)
    followers_lost = rng.randint(0, _FOLLOWERS_LOST_MAX)
    engagement_rate = ContentMetric.compute_engagement_rate(
        views, likes, comments, shares
    )
    return {
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "followers_gained": followers_gained,
        "followers_lost": followers_lost,
        "engagement_rate": engagement_rate,
    }


class MetricsCollector:
    """指标采集器。

    通过数据库会话拉取已成功发布的任务，并为其生成模拟指标快照。
    实际接入平台 API 时，将 ``_simulate_metrics_for_platform`` 替换为
    对应适配器的真实调用即可。
    """

    def __init__(
        self,
        db_session: AsyncSession,
        adapters: MetricsAdapterRegistry | None = None,
    ) -> None:
        self.db_session = db_session
        # 每个 collector 实例独立维护一个种子化的 RNG，避免全局状态污染
        self._rng = random.Random(_RANDOM_SEED)
        self._adapters = adapters or MetricsAdapterRegistry()

    async def _fetch_metrics(
        self, task: PublishTask, account: Any
    ) -> MetricsSnapshot | None:
        """Try a real adapter; return None when unavailable (fall back to sim)."""
        adapter = self._adapters.get(task.platform)
        if adapter is None:
            return None
        try:
            return await adapter.fetch_metrics(account, task.external_url)
        except Exception:  # noqa: BLE001 — real API failure must not break collection
            log_event(
                "metrics_adapter_failed",
                "真实指标适配器调用失败，回退模拟",
                platform=task.platform.value,
            )
            return None

    def _snapshot_to_dict(self, snap: MetricsSnapshot) -> dict[str, int | float]:
        engagement_rate = snap.engagement_rate
        if engagement_rate < 0:
            engagement_rate = ContentMetric.compute_engagement_rate(
                snap.views, snap.likes, snap.comments, snap.shares
            )
        return {
            "views": snap.views,
            "likes": snap.likes,
            "comments": snap.comments,
            "shares": snap.shares,
            "followers_gained": snap.followers_gained,
            "followers_lost": snap.followers_lost,
            "engagement_rate": engagement_rate,
        }

    async def collect_single(
        self, publish_task_id: uuid.UUID
    ) -> ContentMetric | None:
        """采集单个发布任务对应内容的当日指标快照。

        :param publish_task_id: 发布任务 ID
        :returns: 新建的 ``ContentMetric``；任务或内容不存在时返回 None
        """
        task = await self.db_session.get(PublishTask, publish_task_id)
        if task is None:
            log_event(
                "metrics_collect_skipped",
                "发布任务不存在，跳过采集",
                publish_task_id=str(publish_task_id),
            )
            return None

        content = await self.db_session.get(Content, task.content_id)
        if content is None:
            log_event(
                "metrics_collect_skipped",
                "内容不存在，跳过采集",
                publish_task_id=str(publish_task_id),
                content_id=str(task.content_id),
            )
            return None

        # 1. 尝试真实平台适配器；2. 回退到模拟。
        from hermes.content_team.models.platform import PlatformAccount

        account = await self.db_session.get(PlatformAccount, task.account_id)
        snapshot = await self._fetch_metrics(task, account)
        if snapshot is not None:
            metrics_data = self._snapshot_to_dict(snapshot)
            source = "adapter"
        else:
            metrics_data = _simulate_metrics_for_platform(task.platform, self._rng)
            source = "simulation"
        snapshot_date = date.today()

        # 提前缓存日志所需字段，避免 commit/rollback 后访问已过期的属性
        content_id_value = task.content_id
        platform_value = task.platform

        metric = ContentMetric(
            content_id=content_id_value,
            publish_task_id=task.id,
            platform=platform_value,
            date=snapshot_date,
            source=source,
            **metrics_data,
        )
        self.db_session.add(metric)
        try:
            await self.db_session.commit()
        except IntegrityError:
            # 同一 content_id + platform + date 已存在快照，回滚并跳过
            await self.db_session.rollback()
            log_event(
                "metrics_collect_skipped",
                "指标快照已存在，跳过重复采集",
                publish_task_id=str(publish_task_id),
                content_id=str(content_id_value),
                platform=platform_value.value,
                date=snapshot_date.isoformat(),
            )
            return None
        await self.db_session.refresh(metric)

        log_event(
            "metrics_collected",
            "指标采集完成",
            metric_id=str(metric.id),
            publish_task_id=str(publish_task_id),
            content_id=str(metric.content_id),
            platform=metric.platform.value,
            date=metric.date.isoformat(),
            views=metric.views,
            likes=metric.likes,
            comments=metric.comments,
            shares=metric.shares,
            engagement_rate=metric.engagement_rate,
            source=source,
        )
        return metric

    async def collect_all(self) -> int:
        """采集所有成功发布任务的指标快照。

        :returns: 实际新增的指标条数
        """
        stmt = select(PublishTask).where(
            PublishTask.status.in_(
                [PublishStatus.SUCCESS, PublishStatus.PARTIAL_SUCCESS]
            )
        )
        result = await self.db_session.execute(stmt)
        tasks = list(result.scalars().all())

        collected = 0
        for task in tasks:
            metric = await self.collect_single(task.id)
            if metric is not None:
                collected += 1

        log_event(
            "metrics_collect_all",
            "批量指标采集完成",
            total_tasks=len(tasks),
            collected=collected,
        )
        return collected

    async def collect_by_content(
        self, content_id: uuid.UUID
    ) -> list[ContentMetric]:
        """采集指定内容下所有成功发布任务的指标快照。

        :param content_id: 内容 ID
        :returns: 新增的 ``ContentMetric`` 列表（已存在快照的任务会被跳过）
        """
        stmt = select(PublishTask).where(
            PublishTask.content_id == content_id,
            PublishTask.status.in_(
                [PublishStatus.SUCCESS, PublishStatus.PARTIAL_SUCCESS]
            ),
        )
        result = await self.db_session.execute(stmt)
        tasks = list(result.scalars().all())

        metrics: list[ContentMetric] = []
        for task in tasks:
            metric = await self.collect_single(task.id)
            if metric is not None:
                metrics.append(metric)

        log_event(
            "metrics_collect_by_content",
            "按内容采集指标完成",
            content_id=str(content_id),
            total_tasks=len(tasks),
            collected=len(metrics),
        )
        return metrics

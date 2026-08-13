"""数据分析 API：指标查询、聚合摘要与手动采集。

端点：
- ``GET /api/analytics``                - 列表查询（支持 content_id/platform/日期范围过滤）
- ``GET /api/analytics/summary``        - 全局聚合摘要（支持日期范围过滤）
- ``GET /api/analytics/content/{id}``   - 单内容跨平台指标
- ``GET /api/analytics/content/{id}/summary`` - 单内容聚合摘要
- ``POST /api/analytics/collect``       - 手动触发批量采集
- ``POST /api/analytics/collect/{task_id}`` - 手动采集单个发布任务
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from hermes.content_team.analytics.collector import MetricsCollector
from hermes.content_team.db import get_db
from hermes.content_team.models.metrics import ContentMetric
from hermes.content_team.models.platform import Platform

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class MetricResponse(BaseModel):
    """单条指标快照响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content_id: UUID
    publish_task_id: UUID | None = None
    platform: Platform
    date: date
    views: int
    likes: int
    comments: int
    shares: int
    followers_gained: int
    followers_lost: int
    engagement_rate: float
    created_at: datetime


class PlatformBreakdown(BaseModel):
    """单平台的聚合指标。"""

    views: int
    likes: int
    comments: int
    shares: int
    followers_gained: int
    followers_lost: int
    engagement_rate: float
    count: int


class MetricsSummary(BaseModel):
    """指标聚合摘要。"""

    content_id: UUID | None = None
    total_views: int
    total_likes: int
    total_comments: int
    total_shares: int
    total_followers_gained: int
    avg_engagement_rate: float
    by_platform: dict[str, PlatformBreakdown]


class MetricsFilter(BaseModel):
    """指标过滤条件（所有字段可选）。"""

    content_id: UUID | None = None
    platform: Platform | None = None
    start_date: date | None = None
    end_date: date | None = None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _apply_filters(
    stmt: Select[Any],
    content_id: UUID | None,
    platform: Platform | None,
    start_date: date | None,
    end_date: date | None,
) -> Select[Any]:
    """在查询语句上叠加过滤条件。"""
    if content_id is not None:
        stmt = stmt.where(ContentMetric.content_id == content_id)
    if platform is not None:
        stmt = stmt.where(ContentMetric.platform == platform)
    if start_date is not None:
        stmt = stmt.where(ContentMetric.date >= start_date)
    if end_date is not None:
        stmt = stmt.where(ContentMetric.date <= end_date)
    return stmt


async def _build_summary(
    db: AsyncSession,
    *,
    content_id: UUID | None,
    platform: Platform | None,
    start_date: date | None,
    end_date: date | None,
) -> MetricsSummary:
    """根据过滤条件构建聚合摘要。"""
    # 总体聚合
    total_stmt = _apply_filters(
        select(
            func.coalesce(func.sum(ContentMetric.views), 0).label("total_views"),
            func.coalesce(func.sum(ContentMetric.likes), 0).label("total_likes"),
            func.coalesce(func.sum(ContentMetric.comments), 0).label(
                "total_comments"
            ),
            func.coalesce(func.sum(ContentMetric.shares), 0).label("total_shares"),
            func.coalesce(func.sum(ContentMetric.followers_gained), 0).label(
                "total_followers_gained"
            ),
            func.coalesce(func.avg(ContentMetric.engagement_rate), 0.0).label(
                "avg_engagement_rate"
            ),
        ),
        content_id,
        platform,
        start_date,
        end_date,
    )
    total_result = await db.execute(total_stmt)
    total_row = total_result.one()

    # 按平台聚合
    platform_stmt = _apply_filters(
        select(
            ContentMetric.platform,
            func.coalesce(func.sum(ContentMetric.views), 0).label("views"),
            func.coalesce(func.sum(ContentMetric.likes), 0).label("likes"),
            func.coalesce(func.sum(ContentMetric.comments), 0).label("comments"),
            func.coalesce(func.sum(ContentMetric.shares), 0).label("shares"),
            func.coalesce(func.sum(ContentMetric.followers_gained), 0).label(
                "followers_gained"
            ),
            func.coalesce(func.sum(ContentMetric.followers_lost), 0).label(
                "followers_lost"
            ),
            func.coalesce(func.avg(ContentMetric.engagement_rate), 0.0).label(
                "engagement_rate"
            ),
            func.count(ContentMetric.id).label("count"),
        ).group_by(ContentMetric.platform),
        content_id,
        platform,
        start_date,
        end_date,
    )
    platform_result = await db.execute(platform_stmt)
    by_platform: dict[str, PlatformBreakdown] = {}
    for row in platform_result.all():
        by_platform[row.platform.value] = PlatformBreakdown(
            views=row.views,
            likes=row.likes,
            comments=row.comments,
            shares=row.shares,
            followers_gained=row.followers_gained,
            followers_lost=row.followers_lost,
            engagement_rate=row.engagement_rate,
            count=int(getattr(row, "count")),
        )

    return MetricsSummary(
        content_id=content_id,
        total_views=total_row.total_views,
        total_likes=total_row.total_likes,
        total_comments=total_row.total_comments,
        total_shares=total_row.total_shares,
        total_followers_gained=total_row.total_followers_gained,
        avg_engagement_rate=total_row.avg_engagement_rate,
        by_platform=by_platform,
    )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("", response_model=list[MetricResponse])
async def list_metrics(
    content_id: UUID | None = None,
    platform: Platform | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[ContentMetric]:
    """列出指标快照，支持按内容/平台/日期范围过滤。"""
    stmt = _apply_filters(
        select(ContentMetric), content_id, platform, start_date, end_date
    ).order_by(ContentMetric.date.desc(), ContentMetric.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/summary", response_model=MetricsSummary)
async def get_metrics_summary(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> MetricsSummary:
    """获取全局聚合摘要（可按日期范围过滤）。"""
    return await _build_summary(
        db,
        content_id=None,
        platform=None,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/content/{content_id}", response_model=list[MetricResponse])
async def get_content_metrics(
    content_id: UUID, db: AsyncSession = Depends(get_db)
) -> list[ContentMetric]:
    """获取指定内容在所有平台上的指标快照。"""
    stmt = (
        select(ContentMetric)
        .where(ContentMetric.content_id == content_id)
        .order_by(ContentMetric.date.desc(), ContentMetric.platform.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/content/{content_id}/summary", response_model=MetricsSummary)
async def get_content_summary(
    content_id: UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> MetricsSummary:
    """获取指定内容的聚合摘要。"""
    return await _build_summary(
        db,
        content_id=content_id,
        platform=None,
        start_date=start_date,
        end_date=end_date,
    )


@router.post("/collect", response_model=dict)
async def trigger_collect_all(
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """手动触发批量指标采集，返回采集统计。"""
    collector = MetricsCollector(db_session=db)
    collected = await collector.collect_all()
    return {"collected": collected}


@router.post("/collect/{publish_task_id}", response_model=MetricResponse)
async def trigger_collect_single(
    publish_task_id: UUID, db: AsyncSession = Depends(get_db)
) -> ContentMetric:
    """手动采集单个发布任务的指标快照。"""
    collector = MetricsCollector(db_session=db)
    metric = await collector.collect_single(publish_task_id)
    if metric is None:
        raise HTTPException(
            status_code=404,
            detail="Publish task not found or metric snapshot already exists",
        )
    return metric

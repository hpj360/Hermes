"""趋势数据 API：爆款笔记查询 + 热榜查询 + 一键导入选题。"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.content_team.db import get_db
from hermes.content_team.models.topic import Topic
from hermes.content_team.trend_sources import (
    SUPPORTED_TREND_PLATFORMS,
    TrendSourceNotConfigured,
    collect_topic_suggestions,
    get_trend_provider,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class HotNoteResponse(BaseModel):
    """爆款笔记响应体。"""

    title: str
    platform: str
    likes: int
    collects: int
    comments: int
    shares: int
    engagement: int
    author_fans: int | None = None
    url: str = ""
    category: str = ""
    published_at: str = ""
    source: str


class HotNoteListResponse(BaseModel):
    """爆款笔记列表响应体。"""

    platform: str
    provider: str
    keyword: str | None = None
    total: int
    notes: list[HotNoteResponse]


class HotListItemResponse(BaseModel):
    """热榜条目响应体。"""

    rank: int
    title: str
    platform: str
    heat: int
    tag: str
    url: str
    source: str


class HotListResponse(BaseModel):
    """热榜响应体。"""

    platform: str
    provider: str
    total: int
    items: list[HotListItemResponse]


class TrendImportRequest(BaseModel):
    """爆款导入选题请求体。"""

    platform: str = Field(default="XIAOHONGSHU")
    keyword: str | None = None
    limit: int = Field(default=20, ge=1, le=50)
    min_engagement: int = Field(default=500, ge=0)
    max_fans: int | None = Field(default=None, ge=0)


class TopicSuggestionResponse(BaseModel):
    """导入的选题响应体（精简）。"""

    id: str
    title: str
    description: str
    keywords: list[str]
    target_platforms: list[str]


class TrendImportResponse(BaseModel):
    """爆款导入结果。"""

    imported: int
    skipped_duplicates: int
    provider: str
    topics: list[TopicSuggestionResponse]


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


def _check_platform(platform: str) -> None:
    if platform not in SUPPORTED_TREND_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的趋势平台: {platform}，可用: {SUPPORTED_TREND_PLATFORMS}",
        )


@router.get("/hot-notes", response_model=HotNoteListResponse)
async def get_hot_notes(
    platform: str = "XIAOHONGSHU",
    keyword: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> HotNoteListResponse:
    """查询平台爆款笔记（数据源：红狐Hub，未配置时回退 fixture 样例）。"""
    _check_platform(platform)
    try:
        provider = get_trend_provider(platform)
        notes = await provider.fetch_hot_notes(keyword=keyword, limit=limit)
    except TrendSourceNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return HotNoteListResponse(
        platform=platform,
        provider=provider.name,
        keyword=keyword,
        total=len(notes),
        notes=[
            HotNoteResponse(
                title=n.title,
                platform=n.platform,
                likes=n.likes,
                collects=n.collects,
                comments=n.comments,
                shares=n.shares,
                engagement=n.engagement,
                author_fans=n.author_fans,
                url=n.url,
                category=n.category,
                published_at=n.published_at,
                source=n.source,
            )
            for n in notes
        ],
    )


@router.get("/hot-list", response_model=HotListResponse)
async def get_hot_list(
    platform: str = "DOUYIN",
    limit: int = Query(default=50, ge=1, le=50),
) -> HotListResponse:
    """查询平台热榜（数据源：红狐Hub，未配置时回退 fixture 样例）。"""
    _check_platform(platform)
    try:
        provider = get_trend_provider(platform)
        items = await provider.fetch_hot_list(limit=limit)
    except TrendSourceNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return HotListResponse(
        platform=platform,
        provider=provider.name,
        total=len(items),
        items=[HotListItemResponse(**asdict(i)) for i in items],
    )


@router.post("/import", response_model=TrendImportResponse)
async def import_trend_topics(
    payload: TrendImportRequest,
    db: AsyncSession = Depends(get_db),
) -> TrendImportResponse:
    """拉取爆款笔记并批量导入选题库（按标题去重）。

    数据驱动选题（Phase 1）：查询 → 过滤 → 去重 → 建 Topic（PENDING）。
    """
    _check_platform(payload.platform)

    # 已有选题标题，用于去重
    result = await db.execute(select(Topic.title))
    existing_titles = {t for (t,) in result.all()}

    try:
        rows, provider_name = await collect_topic_suggestions(
            payload.platform,
            keyword=payload.keyword,
            limit=payload.limit,
            min_engagement=payload.min_engagement,
            max_fans=payload.max_fans,
        )
    except TrendSourceNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # 再次按已入库标题过滤
    from hermes.content_team.trend_sources import _normalize_title

    existing_norm = {_normalize_title(t) for t in existing_titles}
    topics: list[Topic] = []
    skipped = 0
    for row in rows:
        if _normalize_title(row["title"]) in existing_norm:
            skipped += 1
            continue
        topic = Topic(status="PENDING", **row)
        db.add(topic)
        topics.append(topic)
    if topics:
        await db.commit()
        for t in topics:
            await db.refresh(t)

    return TrendImportResponse(
        imported=len(topics),
        skipped_duplicates=skipped,
        provider=provider_name,
        topics=[
            TopicSuggestionResponse(
                id=str(t.id),
                title=t.title,
                description=t.description,
                keywords=t.keywords,
                target_platforms=t.target_platforms,
            )
            for t in topics
        ],
    )

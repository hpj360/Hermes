"""选题 API：CRUD + 评分 + 领取。"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.content_team.db import get_db
from hermes.content_team.models.topic import Topic, TopicScore, TopicStatus

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TopicCreate(BaseModel):
    """创建选题请求体。"""

    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    priority: int = Field(default=3, ge=1, le=5)
    target_platforms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    status: TopicStatus = TopicStatus.PENDING


class TopicUpdate(BaseModel):
    """更新选题请求体，所有字段可选。"""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    priority: int | None = Field(None, ge=1, le=5)
    status: TopicStatus | None = None
    target_platforms: list[str] | None = None
    keywords: list[str] | None = None
    assigned_to: UUID | None = None


class TopicResponse(BaseModel):
    """选题响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    priority: int
    status: TopicStatus
    target_platforms: list[str]
    keywords: list[str]
    assigned_to: UUID | None = None
    created_at: datetime
    updated_at: datetime


class TopicImportRequest(BaseModel):
    """选题库导入请求体：原始 markdown 文本。"""

    markdown: str = Field(..., min_length=1)
    default_platform: str = "XIAOHONGSHU"


class TopicImportResult(BaseModel):
    """选题库导入结果。"""

    imported: int
    topics: list[TopicResponse]


class TopicScoreRequest(BaseModel):
    """选题评分请求体。"""

    heat: float = Field(..., ge=0.0, le=1.0)
    expertise: float = Field(..., ge=0.0, le=1.0)
    timeliness: float = Field(..., ge=0.0, le=1.0)


class TopicScoreResponse(BaseModel):
    """选题评分响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic_id: UUID
    heat: float
    expertise: float
    timeliness: float
    total: float
    created_at: datetime


class ClaimRequest(BaseModel):
    """领取选题请求体。"""

    assigned_to: UUID


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("", response_model=TopicResponse, status_code=201)
async def create_topic(
    payload: TopicCreate, db: AsyncSession = Depends(get_db)
) -> Topic:
    """创建选题。"""
    topic = Topic(**payload.model_dump())
    db.add(topic)
    await db.commit()
    await db.refresh(topic)
    return topic


@router.post("/import", response_model=TopicImportResult)
async def import_topic_library(
    payload: TopicImportRequest, db: AsyncSession = Depends(get_db)
) -> TopicImportResult:
    """批量导入选题库 markdown（IT-2：选题库结构化导入）。

    解析 ``content-creation/01-前30天选题库.md`` 格式的选题库文档，
    每篇创建一条选题（标题/内容大纲/关键词/目标平台），返回导入统计。
    """
    from hermes.content_team.topic_import import parse_topic_library

    parsed = parse_topic_library(payload.markdown)
    topics: list[Topic] = []
    for item in parsed:
        data = item.to_topic_input(default_platform=payload.default_platform)
        topic = Topic(**data, status=TopicStatus.PENDING)
        db.add(topic)
        topics.append(topic)
    await db.commit()
    for topic in topics:
        await db.refresh(topic)
    return TopicImportResult(imported=len(topics), topics=topics)


@router.get("", response_model=list[TopicResponse])
async def list_topics(
    status: TopicStatus | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[Topic]:
    """列出所有选题，支持按状态过滤。"""
    stmt = select(Topic)
    if status is not None:
        stmt = stmt.where(Topic.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic(
    topic_id: UUID, db: AsyncSession = Depends(get_db)
) -> Topic:
    """获取单个选题。"""
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.put("/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: UUID,
    payload: TopicUpdate,
    db: AsyncSession = Depends(get_db),
) -> Topic:
    """更新选题。"""
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(topic, key, value)
    await db.commit()
    await db.refresh(topic)
    return topic


@router.delete("/{topic_id}", status_code=204)
async def delete_topic(
    topic_id: UUID, db: AsyncSession = Depends(get_db)
) -> None:
    """删除选题。"""
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    await db.delete(topic)
    await db.commit()


@router.post("/{topic_id}/score", response_model=TopicScoreResponse)
async def score_topic(
    topic_id: UUID,
    payload: TopicScoreRequest,
    db: AsyncSession = Depends(get_db),
) -> TopicScore:
    """创建或更新选题评分（upsert 语义：每个选题仅保留一条评分）。"""
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    total = TopicScore.compute_total(
        payload.heat, payload.expertise, payload.timeliness
    )
    # 查找已有评分
    stmt = select(TopicScore).where(TopicScore.topic_id == topic_id)
    result = await db.execute(stmt)
    score = result.scalars().first()

    if score is None:
        score = TopicScore(
            topic_id=topic_id,
            heat=payload.heat,
            expertise=payload.expertise,
            timeliness=payload.timeliness,
            total=total,
        )
        db.add(score)
    else:
        score.heat = payload.heat
        score.expertise = payload.expertise
        score.timeliness = payload.timeliness
        score.total = total

    await db.commit()
    await db.refresh(score)
    return score


@router.post("/{topic_id}/claim", response_model=TopicResponse)
async def claim_topic(
    topic_id: UUID,
    payload: ClaimRequest,
    db: AsyncSession = Depends(get_db),
) -> Topic:
    """领取选题，设置 assigned_to。"""
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    topic.assigned_to = payload.assigned_to
    await db.commit()
    await db.refresh(topic)
    return topic

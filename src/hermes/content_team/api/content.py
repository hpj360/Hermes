"""内容 API：CRUD + 版本管理 + 基于选题创建内容。"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.content_team.db import get_db
from hermes.content_team.models.content import (
    Content,
    ContentStatus,
    ContentVersion,
)
from hermes.content_team.models.topic import Topic

router = APIRouter()
topics_content_router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ContentCreate(BaseModel):
    """创建内容请求体。"""

    title: str = Field(..., min_length=1, max_length=255)
    body: str = ""
    topic_id: UUID | None = None
    content_type: str = Field(default="article", max_length=50)
    author_id: UUID | None = None


class ContentUpdate(BaseModel):
    """更新内容请求体，所有字段可选。

    当 ``title`` 或 ``body`` 变更时会自动创建新版本快照。
    """

    title: str | None = Field(None, min_length=1, max_length=255)
    body: str | None = None
    content_type: str | None = Field(None, max_length=50)
    status: ContentStatus | None = None


class ContentResponse(BaseModel):
    """内容响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic_id: UUID | None = None
    title: str
    body: str
    content_type: str
    status: ContentStatus
    author_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ContentVersionResponse(BaseModel):
    """内容版本响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content_id: UUID
    version_number: int
    title: str
    body: str
    created_at: datetime
    created_by: UUID | None = None


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _create_version(
    db: AsyncSession,
    content: Content,
    *,
    version_number: int | None = None,
) -> ContentVersion:
    """为指定内容创建版本快照，存储当前标题与正文的快照值。

    ``version_number`` 为 None 时自动取最大版本号 + 1。
    """
    if version_number is None:
        # 查询当前最大版本号
        stmt = select(func.max(ContentVersion.version_number)).where(
            ContentVersion.content_id == content.id
        )
        result = await db.execute(stmt)
        current_max = result.scalar()
        version_number = (current_max or 0) + 1

    version = ContentVersion(
        content_id=content.id,
        version_number=version_number,
        title=content.title,
        body=content.body,
        created_by=content.author_id,
    )
    db.add(version)
    return version


# ---------------------------------------------------------------------------
# 内容 CRUD 路由
# ---------------------------------------------------------------------------


@router.post("", response_model=ContentResponse, status_code=201)
async def create_content(
    payload: ContentCreate, db: AsyncSession = Depends(get_db)
) -> Content:
    """创建内容，并自动生成版本号为 1 的首个版本快照。"""
    content = Content(**payload.model_dump())
    db.add(content)
    await db.flush()  # 确保 content.id 已生成
    await _create_version(db, content, version_number=1)
    await db.commit()
    await db.refresh(content)
    return content


@router.get("", response_model=list[ContentResponse])
async def list_content(
    status: ContentStatus | None = None,
    topic_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[Content]:
    """列出所有内容，支持按状态或选题 ID 过滤。"""
    stmt = select(Content)
    if status is not None:
        stmt = stmt.where(Content.status == status)
    if topic_id is not None:
        stmt = stmt.where(Content.topic_id == topic_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: UUID, db: AsyncSession = Depends(get_db)
) -> Content:
    """获取单个内容。"""
    content = await db.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return content


@router.put("/{content_id}", response_model=ContentResponse)
async def update_content(
    content_id: UUID,
    payload: ContentUpdate,
    db: AsyncSession = Depends(get_db),
) -> Content:
    """更新内容。当 ``title`` 或 ``body`` 发生变化时自动创建新版本快照。"""
    content = await db.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    data = payload.model_dump(exclude_unset=True)
    # 判断标题或正文是否变更，决定是否生成新版本
    title_changed = "title" in data and data["title"] != content.title
    body_changed = "body" in data and data["body"] != content.body
    needs_new_version = title_changed or body_changed

    for key, value in data.items():
        setattr(content, key, value)

    if needs_new_version:
        await _create_version(db, content)

    await db.commit()
    await db.refresh(content)
    return content


@router.delete("/{content_id}", status_code=204)
async def delete_content(
    content_id: UUID, db: AsyncSession = Depends(get_db)
) -> None:
    """删除内容（级联删除所有版本）。"""
    content = await db.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    await db.delete(content)
    await db.commit()


@router.get(
    "/{content_id}/versions", response_model=list[ContentVersionResponse]
)
async def list_content_versions(
    content_id: UUID, db: AsyncSession = Depends(get_db)
) -> list[ContentVersion]:
    """列出指定内容的所有版本，按版本号升序返回。"""
    content = await db.get(Content, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    stmt = (
        select(ContentVersion)
        .where(ContentVersion.content_id == content_id)
        .order_by(ContentVersion.version_number.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# 基于选题创建内容
# ---------------------------------------------------------------------------


@topics_content_router.post(
    "/{topic_id}/content", response_model=ContentResponse, status_code=201
)
async def create_content_from_topic(
    topic_id: UUID,
    payload: ContentCreate,
    db: AsyncSession = Depends(get_db),
) -> Content:
    """基于选题创建内容，自动设置 ``topic_id`` 为 URL 中的选题 ID。"""
    topic = await db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")

    # 强制覆盖 topic_id 为 URL 中的选题 ID
    data = payload.model_dump()
    data["topic_id"] = topic_id
    content = Content(**data)
    db.add(content)
    await db.flush()
    await _create_version(db, content, version_number=1)
    await db.commit()
    await db.refresh(content)
    return content

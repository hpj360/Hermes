"""发布与分发 API：平台账号管理 + 发布任务分发/查询/重试。"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.content_team.db import get_db
from hermes.content_team.models.platform import Platform, PlatformAccount
from hermes.content_team.models.publish import PublishStatus, PublishTask
from hermes.content_team.publish.dispatcher import PublishDispatcher

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PlatformAccountCreate(BaseModel):
    """创建平台账号请求体。"""

    platform: Platform
    display_name: str = Field(..., min_length=1, max_length=255)
    account_id: str | None = Field(None, max_length=255)
    auth_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None


class PlatformAccountResponse(BaseModel):
    """平台账号响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: Platform
    display_name: str
    account_id: str | None = None
    auth_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: datetime | None = None
    status: str
    metadata_: str | None = None
    created_at: datetime
    updated_at: datetime


class PublishRequest(BaseModel):
    """发布请求体：将内容分发到多个平台账号。"""

    content_id: UUID
    platform_account_ids: list[UUID] = Field(..., min_length=1)
    scheduled_at: datetime | None = None


class PublishTaskResponse(BaseModel):
    """发布任务响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content_id: UUID
    platform: Platform
    account_id: UUID
    status: PublishStatus
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    external_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class PublishResultResponse(BaseModel):
    """发布结果响应体（精简视图）。"""

    task_id: UUID
    status: PublishStatus
    external_url: str | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# 平台账号路由
# ---------------------------------------------------------------------------


@router.post(
    "/accounts",
    response_model=PlatformAccountResponse,
    status_code=201,
)
async def create_account(
    payload: PlatformAccountCreate,
    db: AsyncSession = Depends(get_db),
) -> PlatformAccount:
    """创建平台账号。"""
    account = PlatformAccount(**payload.model_dump())
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.get("/accounts", response_model=list[PlatformAccountResponse])
async def list_accounts(
    platform: Platform | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[PlatformAccount]:
    """列出所有平台账号，支持按平台过滤。"""
    stmt = select(PlatformAccount)
    if platform is not None:
        stmt = stmt.where(PlatformAccount.platform == platform)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: UUID, db: AsyncSession = Depends(get_db)
) -> None:
    """删除平台账号。"""
    account = await db.get(PlatformAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    await db.delete(account)
    await db.commit()


# ---------------------------------------------------------------------------
# 发布任务路由
# ---------------------------------------------------------------------------


@router.post("/publish", response_model=list[PublishTaskResponse])
async def dispatch_publish(
    payload: PublishRequest,
    db: AsyncSession = Depends(get_db),
) -> list[PublishTask]:
    """将内容分发到多个平台账号（fan-out）。"""
    dispatcher = PublishDispatcher(db_session=db)
    try:
        tasks = await dispatcher.dispatch(
            content_id=payload.content_id,
            platform_accounts=payload.platform_account_ids,
            scheduled_at=payload.scheduled_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return tasks


@router.get("/publish/{task_id}", response_model=PublishTaskResponse)
async def get_publish_task(
    task_id: UUID, db: AsyncSession = Depends(get_db)
) -> PublishTask:
    """获取单个发布任务。"""
    task = await db.get(PublishTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Publish task not found")
    return task


@router.get("/publish", response_model=list[PublishTaskResponse])
async def list_publish_tasks(
    content_id: UUID | None = None,
    status: PublishStatus | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[PublishTask]:
    """列出发布任务，支持按 content_id 和 status 过滤。"""
    stmt = select(PublishTask)
    if content_id is not None:
        stmt = stmt.where(PublishTask.content_id == content_id)
    if status is not None:
        stmt = stmt.where(PublishTask.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/publish/{task_id}/retry",
    response_model=PublishResultResponse,
)
async def retry_publish_task(
    task_id: UUID, db: AsyncSession = Depends(get_db)
) -> PublishResultResponse:
    """重试失败的发布任务。"""
    dispatcher = PublishDispatcher(db_session=db)
    try:
        task = await dispatcher.retry_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PublishResultResponse(
        task_id=task.id,
        status=task.status,
        external_url=task.external_url,
        error_message=task.error_message,
    )

"""发布与分发 API：平台账号管理 + 发布任务分发/查询/重试。"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.content_team.compliance import (
    ComplianceBlockedError,
    check_compliance,
)
from hermes.content_team.db import get_db
from hermes.content_team.models.platform import Platform, PlatformAccount
from hermes.content_team.models.publish import PublishStatus, PublishTask
from hermes.content_team.observability import log_event
from hermes.content_team.publish.dispatcher import PublishDispatcher

router = APIRouter()


def _require_compliance_approval(force: bool, supplied: str | None) -> None:
    """Require a separate approval secret for red-line bypasses in production."""
    if not force:
        return
    from hermes.config import get_settings

    settings = get_settings()
    expected = settings.compliance_approval_token
    if expected:
        import secrets

        if supplied is None or not secrets.compare_digest(supplied, expected):
            raise HTTPException(status_code=403, detail="compliance approval required")
        log_event("compliance_force_approved", "Red-line publish bypass approved")
        return
    if settings.hermes_api_token:
        raise HTTPException(status_code=503, detail="compliance approval is not configured")


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
    """平台账号响应体（凭据脱敏：不回传 token 明文）。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: Platform
    display_name: str
    account_id: str | None = None
    has_auth_token: bool = False
    has_refresh_token: bool = False
    token_expires_at: datetime | None = None
    status: str
    metadata_: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_account(cls, account: PlatformAccount) -> "PlatformAccountResponse":
        """Build a token-masked response from a ``PlatformAccount`` ORM object.

        Never serializes ``auth_token`` / ``refresh_token`` values; presence is
        reported as booleans so clients know whether a token is configured
        without exposing it.
        """
        return cls(
            id=account.id,
            platform=account.platform,
            display_name=account.display_name,
            account_id=account.account_id,
            has_auth_token=account.auth_token is not None,
            has_refresh_token=account.refresh_token is not None,
            token_expires_at=account.token_expires_at,
            status=account.status,
            metadata_=account.metadata_,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )


class PublishRequest(BaseModel):
    """发布请求体：将内容分发到多个平台账号。"""

    content_id: UUID
    platform_account_ids: list[UUID] = Field(..., min_length=1)
    scheduled_at: datetime | None = None
    force_compliance: bool = False


class ComplianceCheckRequest(BaseModel):
    """合规预检请求体：直接传标题与正文，无需入库。"""

    title: str = Field(..., min_length=1)
    body: str = ""


class ComplianceHitResponse(BaseModel):
    """合规规则命中项。"""

    rule_id: str
    rule_name: str
    severity: str
    keyword: str
    source: str
    position: int


class ComplianceReportResponse(BaseModel):
    """合规检查报告。"""

    passed: bool
    blocking: list[ComplianceHitResponse]
    warnings: list[ComplianceHitResponse]
    summary: str


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


class PublishConfirmRequest(BaseModel):
    """半自动发布确认请求体：人工发布完成后回填真实链接。"""

    external_url: str = Field(..., min_length=1, max_length=2048)


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
) -> PlatformAccountResponse:
    """创建平台账号（响应不回传 token 明文）。"""
    account = PlatformAccount(**payload.model_dump())
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return PlatformAccountResponse.from_account(account)


@router.get("/accounts", response_model=list[PlatformAccountResponse])
async def list_accounts(
    platform: Platform | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[PlatformAccountResponse]:
    """列出所有平台账号，支持按平台过滤（凭据脱敏）。"""
    stmt = select(PlatformAccount)
    if platform is not None:
        stmt = stmt.where(PlatformAccount.platform == platform)
    result = await db.execute(stmt)
    return [PlatformAccountResponse.from_account(a) for a in result.scalars().all()]


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
    compliance_approval: str | None = Header(
        default=None, alias="X-Hermes-Compliance-Approval"
    ),
) -> list[PublishTask]:
    """将内容分发到多个平台账号（fan-out）。

    内容命中合规红线时默认被拦截（422），可传 ``force_compliance=true``
    人工确认后强制发布。
    """
    _require_compliance_approval(payload.force_compliance, compliance_approval)
    dispatcher = PublishDispatcher(db_session=db)
    try:
        tasks = await dispatcher.dispatch(
            content_id=payload.content_id,
            platform_accounts=payload.platform_account_ids,
            scheduled_at=payload.scheduled_at,
            force_compliance=payload.force_compliance,
        )
    except ComplianceBlockedError as exc:
        raise HTTPException(status_code=422, detail=exc.report.summary())
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
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    force_compliance: bool = False,
    compliance_approval: str | None = Header(
        default=None, alias="X-Hermes-Compliance-Approval"
    ),
) -> PublishResultResponse:
    """重试失败的发布任务。

    ``force_compliance=true`` 可人工确认强制发布合规红线内容。
    """
    _require_compliance_approval(force_compliance, compliance_approval)
    dispatcher = PublishDispatcher(db_session=db)
    try:
        task = await dispatcher.retry_task(task_id, force_compliance=force_compliance)
    except ComplianceBlockedError as exc:
        raise HTTPException(status_code=422, detail=exc.report.summary())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return PublishResultResponse(
        task_id=task.id,
        status=task.status,
        external_url=task.external_url,
        error_message=task.error_message,
    )


@router.post(
    "/publish/{task_id}/confirm",
    response_model=PublishResultResponse,
)
async def confirm_publish_task(
    task_id: UUID,
    payload: PublishConfirmRequest,
    db: AsyncSession = Depends(get_db),
) -> PublishResultResponse:
    """人工确认半自动发布：回填真实发布链接并置为成功。

    半自动平台（抖音/小红书/B站/视频号）分发后任务停在
    ``PARTIAL_SUCCESS``，人工在平台侧发布完成后调用本端点把真实链接
    写回任务，回采器即可据此拉取真实指标。
    """
    task = await db.get(PublishTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Publish task not found")
    if task.status != PublishStatus.PARTIAL_SUCCESS:
        raise HTTPException(
            status_code=400,
            detail=f"仅 PARTIAL_SUCCESS 任务可确认，当前状态: {task.status.value}",
        )
    task.external_url = payload.external_url
    task.error_message = None
    task.status = PublishStatus.SUCCESS
    if task.published_at is None:
        task.published_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(task)
    return PublishResultResponse(
        task_id=task.id,
        status=task.status,
        external_url=task.external_url,
        error_message=task.error_message,
    )


# ---------------------------------------------------------------------------
# 合规检查单（IT-2）
# ---------------------------------------------------------------------------


@router.post("/compliance/check", response_model=ComplianceReportResponse)
async def compliance_check(
    payload: ComplianceCheckRequest,
) -> ComplianceReportResponse:
    """发布前合规预检：对标题与正文做红线扫描，返回报告。

    不写入数据库，纯只读扫描，用于内容创作/发布前自查。
    """
    report = check_compliance(payload.title, payload.body)
    return ComplianceReportResponse(
        passed=report.passed,
        blocking=[
            ComplianceHitResponse(
                rule_id=h.rule_id,
                rule_name=h.rule_name,
                severity=h.severity,
                keyword=h.keyword,
                source=h.source,
                position=h.position,
            )
            for h in report.blocking
        ],
        warnings=[
            ComplianceHitResponse(
                rule_id=h.rule_id,
                rule_name=h.rule_name,
                severity=h.severity,
                keyword=h.keyword,
                source=h.source,
                position=h.position,
            )
            for h in report.warnings
        ],
        summary=report.summary(),
    )

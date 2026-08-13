"""发布任务数据模型。

每条 ``PublishTask`` 记录一次"将内容发布到某平台账号"的尝试，
涵盖待发布、进行中、成功、部分成功（半自动）、失败、取消、已调度等状态。
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hermes.content_team.db import GUID, Base
from hermes.content_team.models.platform import Platform


class PublishStatus(str, enum.Enum):
    """发布任务状态枚举。"""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SCHEDULED = "SCHEDULED"


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class PublishTask(Base):
    """发布任务模型。

    将一条内容（``content_id``）发布到指定平台账号（``account_id``）的
    一次任务记录。调度发布时 ``status`` 为 ``SCHEDULED``，立即发布时
    依次流转为 ``IN_PROGRESS`` → ``SUCCESS`` / ``PARTIAL_SUCCESS`` / ``FAILED``。
    """

    __tablename__ = "publish_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("contents.id"), nullable=False
    )
    platform: Mapped[Platform] = mapped_column(
        sa.Enum(Platform), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("platform_accounts.id"), nullable=False
    )
    status: Mapped[PublishStatus] = mapped_column(
        sa.Enum(PublishStatus), nullable=False, default=PublishStatus.PENDING
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    external_url: Mapped[Optional[str]] = mapped_column(
        sa.String(2048), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

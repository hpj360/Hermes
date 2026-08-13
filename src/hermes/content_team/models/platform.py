"""平台账号数据模型。

管理各内容发布平台（微信公众号、微信视频号、抖音、小红书、B站）的
账号凭证与状态。每个 ``PlatformAccount`` 记录对应一个外部平台账号，
供 ``PublishDispatcher`` 在分发发布任务时引用。
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hermes.content_team.db import GUID, Base


class Platform(str, enum.Enum):
    """支持的内容发布平台枚举。"""

    WECHAT_OFFICIAL = "WECHAT_OFFICIAL"
    WECHAT_VIDEO = "WECHAT_VIDEO"
    DOUYIN = "DOUYIN"
    XIAOHONGSHU = "XIAOHONGSHU"
    BILIBILI = "BILIBILI"


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class PlatformAccount(Base):
    """平台账号模型。

    存储外部平台账号的认证信息与状态。``auth_token`` / ``refresh_token``
    在生产环境中应加密存储，此处以 Text 列保存占位。
    ``metadata_`` 列以 JSON 字符串保存平台特有的额外数据。
    """

    __tablename__ = "platform_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    platform: Mapped[Platform] = mapped_column(
        sa.Enum(Platform), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    account_id: Mapped[Optional[str]] = mapped_column(
        sa.String(255), nullable=True
    )
    auth_token: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    refresh_token: Mapped[Optional[str]] = mapped_column(
        sa.Text, nullable=True
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, default="active"
    )
    # metadata 是 SQLAlchemy 声明基类的保留属性，故使用 metadata_
    metadata_: Mapped[Optional[str]] = mapped_column(
        "metadata", sa.Text, nullable=True
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

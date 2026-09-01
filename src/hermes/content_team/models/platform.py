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

from hermes.content_team.crypto import decrypt, encrypt
from hermes.content_team.db import GUID, Base


class EncryptedText(sa.TypeDecorator[str]):
    """Symmetric at-rest encryption for token-like columns.

    Encrypts on bind (write) and decrypts on result (read) using
    :mod:`hermes.content_team.crypto`. When ``HERMES_SECRET_KEY`` is unset,
    values pass through unchanged (dev mode). Legacy plaintext values decrypt
    to None and fall back to the raw value, so existing rows keep working.
    """

    impl = sa.Text
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> object:
        if value is None:
            return None
        # Lazy import keeps the settings lookup test-patchable and decoupled.
        from hermes.content_team.crypto import get_secret

        secret = get_secret()
        if not secret:
            return value
        return encrypt(secret, str(value))

    def process_result_value(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        from hermes.content_team.crypto import get_secret

        secret = get_secret()
        if not secret:
            return value
        decrypted = decrypt(secret, str(value))
        if decrypted is None:
            # Legacy plaintext row (or tampered blob) — return as-is.
            return value
        return decrypted


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
    经 :class:`EncryptedText` 在落盘前对称加密（密钥来自 ``HERMES_SECRET_KEY``），
    读取时自动解密；未配置密钥时透传（dev 模式）。
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
        EncryptedText, nullable=True
    )
    refresh_token: Mapped[Optional[str]] = mapped_column(
        EncryptedText, nullable=True
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

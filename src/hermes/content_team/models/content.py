"""内容与内容版本数据模型。"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hermes.content_team.db import GUID, Base


class ContentStatus(str, enum.Enum):
    """内容状态枚举。"""

    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class Content(Base):
    """内容模型。"""

    __tablename__ = "contents"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    topic_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("topics.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    content_type: Mapped[str] = mapped_column(
        sa.String(50), nullable=False, default="article"
    )
    status: Mapped[ContentStatus] = mapped_column(
        sa.Enum(ContentStatus), nullable=False, default=ContentStatus.DRAFT
    )
    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), nullable=True
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

    versions: Mapped[list[ContentVersion]] = relationship(
        back_populates="content", cascade="all, delete-orphan"
    )


class ContentVersion(Base):
    """内容版本快照模型。

    每次内容标题或正文变更都会生成一条版本记录，存储变更后的快照值。
    """

    __tablename__ = "content_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("contents.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), nullable=True
    )

    content: Mapped[Content] = relationship(back_populates="versions")

"""选题与选题评分数据模型。"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hermes.content_team.db import GUID, Base


class TopicStatus(str, enum.Enum):
    """选题状态枚举。"""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class Topic(Base):
    """选题模型。"""

    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=3)
    status: Mapped[TopicStatus] = mapped_column(
        sa.Enum(TopicStatus), nullable=False, default=TopicStatus.PENDING
    )
    target_platforms: Mapped[list[str]] = mapped_column(
        sa.JSON, nullable=False, default=list
    )
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(
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

    scores: Mapped[list[TopicScore]] = relationship(
        back_populates="topic", cascade="all, delete-orphan"
    )


class TopicScore(Base):
    """选题评分模型。

    ``total`` 为加权计算结果：heat * 0.4 + expertise * 0.3 + timeliness * 0.3。
    """

    __tablename__ = "topic_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("topics.id"), nullable=False
    )
    heat: Mapped[float] = mapped_column(sa.Float, nullable=False)
    expertise: Mapped[float] = mapped_column(sa.Float, nullable=False)
    timeliness: Mapped[float] = mapped_column(sa.Float, nullable=False)
    total: Mapped[float] = mapped_column(sa.Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )

    topic: Mapped[Topic] = relationship(back_populates="scores")

    # 评分权重常量
    WEIGHT_HEAT: float = 0.4
    WEIGHT_EXPERTISE: float = 0.3
    WEIGHT_TIMELINESS: float = 0.3

    @staticmethod
    def compute_total(heat: float, expertise: float, timeliness: float) -> float:
        """根据热度、擅长度、时效性计算综合得分。"""
        return (
            heat * TopicScore.WEIGHT_HEAT
            + expertise * TopicScore.WEIGHT_EXPERTISE
            + timeliness * TopicScore.WEIGHT_TIMELINESS
        )

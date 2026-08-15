"""内容指标数据模型。

``ContentMetric`` 记录某条内容在指定平台某日的指标快照（浏览、点赞、
评论、分享、粉丝增减等）。同一内容 + 平台 + 日期的组合唯一，避免重复
采集产生重复快照。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hermes.content_team.db import GUID, Base
from hermes.content_team.models.platform import Platform


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class ContentMetric(Base):
    """内容指标快照模型。

    每条记录对应"某内容 + 某平台 + 某日期"的指标快照。
    ``engagement_rate`` 为互动率，计算公式为
    ``(likes + comments + shares) / max(views, 1)``。
    """

    __tablename__ = "content_metrics"
    # 同一内容 + 平台 + 日期的快照唯一，避免重复采集
    __table_args__ = (
        sa.UniqueConstraint(
            "content_id",
            "platform",
            "date",
            name="uq_content_metric_content_platform_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("contents.id"), nullable=False, index=True
    )
    publish_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        sa.ForeignKey("publish_tasks.id"), nullable=True
    )
    platform: Mapped[Platform] = mapped_column(
        sa.Enum(Platform), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    views: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0
    )
    shares: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    followers_gained: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0
    )
    followers_lost: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, default=0
    )
    engagement_rate: Mapped[float] = mapped_column(
        sa.Float, nullable=False, default=0.0
    )
    # P1-7：指标来源标注。"adapter"=真实平台回采，"simulation"=固定种子模拟。
    # 落库而非仅写日志，使用户/API/仪表盘能区分真实数据与模拟数据。
    source: Mapped[str] = mapped_column(
        sa.String(20), nullable=False, default="simulation"
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )

    @staticmethod
    def compute_engagement_rate(
        views: int, likes: int, comments: int, shares: int
    ) -> float:
        """计算互动率：``(likes + comments + shares) / max(views, 1)``。"""
        return (likes + comments + shares) / max(views, 1)

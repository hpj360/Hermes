"""团队成员数据模型。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hermes.content_team.db import GUID, Base


def _utcnow() -> datetime:
    """返回带时区的当前 UTC 时间。"""
    return datetime.now(timezone.utc)


class TeamMember(Base):
    """团队成员模型。"""

    __tablename__ = "team_members"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="member")
    created_at: Mapped[Optional[datetime]] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )

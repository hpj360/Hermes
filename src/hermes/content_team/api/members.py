"""团队成员 API：创建 + 列表。"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hermes.content_team.db import get_db
from hermes.content_team.models.member import TeamMember

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class MemberCreate(BaseModel):
    """创建成员请求体。"""

    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., max_length=255)
    role: str = "member"


class MemberResponse(BaseModel):
    """成员响应体。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    role: str
    created_at: datetime


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("", response_model=MemberResponse, status_code=201)
async def create_member(
    payload: MemberCreate, db: AsyncSession = Depends(get_db)
) -> TeamMember:
    """创建团队成员。"""
    member = TeamMember(**payload.model_dump())
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@router.get("", response_model=list[MemberResponse])
async def list_members(
    db: AsyncSession = Depends(get_db),
) -> list[TeamMember]:
    """列出所有团队成员。"""
    result = await db.execute(select(TeamMember))
    return list(result.scalars().all())

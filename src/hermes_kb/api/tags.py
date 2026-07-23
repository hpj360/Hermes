"""标签与分类端点（M2-06）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from hermes_kb.api.deps import require_auth
from hermes_kb.database import get_session
from hermes_kb.models import PRESET_CATEGORIES, Document, DocumentTag, Tag

router = APIRouter(prefix="/api", tags=["tags"])


# M2-06：标签创建
class TagCreateReq(BaseModel):
    name: str = Field(..., max_length=32)
    color: str = Field(default="#6b7280", max_length=16)


@router.get("/tags", dependencies=[Depends(require_auth)])
async def list_tags() -> dict[str, Any]:
    with get_session() as session:
        tags = session.exec(select(Tag).order_by(Tag.name)).all()
        # 统计每个 tag 关联文档数
        counts: dict[int, int] = {}
        for t in tags:
            cnt = len(
                session.exec(
                    select(DocumentTag).where(DocumentTag.tag_id == t.id)
                ).all()
            )
            counts[t.id or 0] = cnt
        return {
            "total": len(tags),
            "items": [
                {
                    "id": t.id,
                    "name": t.name,
                    "color": t.color,
                    "doc_count": counts.get(t.id or 0, 0),
                }
                for t in tags
            ],
        }


@router.post("/tags", dependencies=[Depends(require_auth)])
async def create_tag(req: TagCreateReq) -> dict[str, Any]:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名不能为空")
    with get_session() as session:
        existing = session.exec(
            select(Tag).where(Tag.name == name)
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="标签已存在")
        tag = Tag(name=name, color=req.color)
        session.add(tag)
        session.commit()
        session.refresh(tag)
        return {"id": tag.id, "name": tag.name, "color": tag.color}


@router.delete("/tags/{tag_id}", dependencies=[Depends(require_auth)])
async def delete_tag(tag_id: int) -> dict[str, Any]:
    with get_session() as session:
        tag = session.get(Tag, tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail="标签不存在")
        session.delete(tag)
        session.commit()
        return {"id": tag_id, "status": "deleted"}


@router.get("/categories", dependencies=[Depends(require_auth)])
async def list_categories() -> dict[str, Any]:
    """M2-06：列出预设分类 + 已使用分类的文档数。"""
    with get_session() as session:
        # 统计每个 category 的文档数
        rows = session.exec(
            select(Document.category).where(Document.category != "")
        ).all()
        counts: dict[str, int] = {}
        for c in rows:
            counts[c] = counts.get(c, 0) + 1
        items = [
            {"name": c, "doc_count": counts.get(c, 0)}
            for c in PRESET_CATEGORIES
        ]
        # 追加未在预设内但已使用的分类
        for c, n in counts.items():
            if c not in PRESET_CATEGORIES:
                items.append({"name": c, "doc_count": n})
        return {"total": len(items), "items": items}

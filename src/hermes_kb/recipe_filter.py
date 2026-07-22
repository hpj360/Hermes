"""配方筛选/审核/隐藏（B5 数据源治理）。"""
from __future__ import annotations

from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document


def filter_recipes(
    source: str | None = None,
    verified: bool | None = None,
    hidden: bool | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """筛选配方列表。"""
    with get_session() as session:
        stmt = select(Document).where(Document.category == "recipe")
        if source is not None:
            stmt = stmt.where(Document.source == source)
        if verified is not None:
            stmt = stmt.where(Document.verified == verified)
        if hidden is not None:
            stmt = stmt.where(Document.hidden == hidden)
        if status is not None:
            stmt = stmt.where(Document.status == status)
        stmt = stmt.limit(limit)
        docs = session.exec(stmt).all()
        return [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "source": d.source,
                "source_id": d.source_id,
                "verified": d.verified,
                "season": d.season,
                "hidden": d.hidden,
                "status": d.status,
                "image_url": d.image_url,
            }
            for d in docs
        ]


def verify_recipe(doc_id: str) -> bool:
    """审核通过配方（verified=True, status=published）。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc:
            return False
        doc.verified = True
        doc.status = "published"
        session.add(doc)
        session.commit()
        return True


def hide_recipe(doc_id: str, hidden: bool = True) -> bool:
    """隐藏/取消隐藏配方。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc:
            return False
        doc.hidden = hidden
        session.add(doc)
        session.commit()
        return True

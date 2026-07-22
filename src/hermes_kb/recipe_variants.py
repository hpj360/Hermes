"""配方变体关联管理（M4.3）。"""
from __future__ import annotations

from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document, RecipeVariant


def create_variant_link(
    base_doc_id: str, variant_doc_id: str, variant_note: str = ""
) -> bool:
    """创建变体关联（已存在则返回 False）。"""
    with get_session() as session:
        # 检查是否已存在
        existing = session.exec(
            select(RecipeVariant).where(
                RecipeVariant.base_doc_id == base_doc_id,
                RecipeVariant.variant_doc_id == variant_doc_id,
            )
        ).first()
        if existing:
            return False

        # 检查两个 doc 是否存在
        base_doc = session.get(Document, base_doc_id)
        variant_doc = session.get(Document, variant_doc_id)
        if not base_doc or not variant_doc:
            return False

        link = RecipeVariant(
            base_doc_id=base_doc_id,
            variant_doc_id=variant_doc_id,
            variant_note=variant_note,
        )
        session.add(link)
        session.commit()
        return True


def get_variants(base_doc_id: str) -> list[dict[str, Any]]:
    """查询某配方的所有变体。"""
    with get_session() as session:
        links = session.exec(
            select(RecipeVariant).where(
                RecipeVariant.base_doc_id == base_doc_id
            )
        ).all()
        result = []
        for link in links:
            variant_doc = session.get(Document, link.variant_doc_id)
            result.append(
                {
                    "variant_doc_id": link.variant_doc_id,
                    "variant_title": variant_doc.title if variant_doc else "(已删除)",
                    "variant_note": link.variant_note,
                    "created_at": link.created_at.isoformat()
                    if link.created_at
                    else None,
                }
            )
        return result


def get_base_recipe(variant_doc_id: str) -> dict[str, Any] | None:
    """查询变体的原配方。"""
    with get_session() as session:
        link = session.exec(
            select(RecipeVariant).where(
                RecipeVariant.variant_doc_id == variant_doc_id
            )
        ).first()
        if not link:
            return None
        base_doc = session.get(Document, link.base_doc_id)
        return {
            "base_doc_id": link.base_doc_id,
            "base_title": base_doc.title if base_doc else "(已删除)",
            "variant_note": link.variant_note,
        }

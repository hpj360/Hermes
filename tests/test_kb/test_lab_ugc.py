"""M4.3 UGC 调酒研究室测试。"""
from __future__ import annotations

import pytest
from sqlmodel import select


def test_recipe_variant_model(tmp_db):
    """RecipeVariant 表可创建并写入。"""
    from hermes_kb.models import RecipeVariant
    from hermes_kb.database import get_session

    with get_session() as session:
        v = RecipeVariant(
            base_doc_id="doc_base001",
            variant_doc_id="doc_variant001",
            variant_note="辛辣版，增加苦精",
        )
        session.add(v)
        session.commit()
        session.refresh(v)
        assert v.id is not None
        assert v.base_doc_id == "doc_base001"
        assert v.variant_doc_id == "doc_variant001"
        assert v.variant_note == "辛辣版，增加苦精"
        assert v.created_at is not None

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


def test_create_ugc_recipe(tmp_db):
    """创建 UGC 配方（draft 状态）。"""
    from hermes_kb.recipe_crud import create_recipe

    result = create_recipe(
        title="我的特调",
        ingredients=["金酒", "柠檬汁", "蜂蜜"],
        content="# 我的特调\n\n## 配方\n- 金酒 50ml\n- 柠檬汁 20ml\n- 蜂蜜 15ml",
        base_spirit="gin",
        difficulty="easy",
        season="spring",
    )
    assert result["doc_id"] is not None
    assert result["status"] == "draft"

    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    with get_session() as session:
        doc = session.get(Document, result["doc_id"])
        assert doc.title == "我的特调"
        assert doc.category == "recipe"
        assert doc.source == "ugc"
        assert doc.verified is False
        assert doc.status == "draft"
        assert doc.season == "spring"


def test_submit_recipe(tmp_db):
    """提交审核（draft → pending）。"""
    from hermes_kb.recipe_crud import create_recipe, submit_recipe
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    created = create_recipe(
        title="待审核配方",
        ingredients=["金酒"],
        content="# 待审核\n\n## 配方\n- 金酒 50ml",
        base_spirit="gin",
        difficulty="easy",
    )
    doc_id = created["doc_id"]

    ok = submit_recipe(doc_id)
    assert ok is True

    with get_session() as session:
        doc = session.get(Document, doc_id)
        assert doc.status == "pending"


def test_approve_recipe(tmp_db):
    """审核通过（pending → published, verified=True）。"""
    from hermes_kb.recipe_crud import create_recipe, submit_recipe, approve_recipe
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    created = create_recipe(
        title="将通过",
        ingredients=["金酒"],
        content="# 将通过\n\n## 配方\n- 金酒 50ml",
        base_spirit="gin",
        difficulty="easy",
    )
    submit_recipe(created["doc_id"])

    ok = approve_recipe(created["doc_id"])
    assert ok is True

    with get_session() as session:
        doc = session.get(Document, created["doc_id"])
        assert doc.status == "published"
        assert doc.verified is True


def test_reject_recipe(tmp_db):
    """审核驳回（pending → rejected）。"""
    from hermes_kb.recipe_crud import create_recipe, submit_recipe, reject_recipe
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    created = create_recipe(
        title="将驳回",
        ingredients=["金酒"],
        content="# 将驳回\n\n## 配方\n- 金酒 50ml",
        base_spirit="gin",
        difficulty="easy",
    )
    submit_recipe(created["doc_id"])

    ok = reject_recipe(created["doc_id"], reason="材料比例不合理")
    assert ok is True

    with get_session() as session:
        doc = session.get(Document, created["doc_id"])
        assert doc.status == "rejected"
        assert doc.verified is False


def test_update_recipe(tmp_db):
    """编辑配方（仅 draft 状态可编辑）。"""
    from hermes_kb.recipe_crud import create_recipe, update_recipe, submit_recipe
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    created = create_recipe(
        title="原配方",
        ingredients=["金酒"],
        content="# 原配方\n\n## 配方\n- 金酒 50ml",
        base_spirit="gin",
        difficulty="easy",
    )
    # draft 状态可编辑
    ok = update_recipe(
        created["doc_id"],
        title="改后配方",
        ingredients=["金酒", "柠檬汁"],
        content="# 改后配方\n\n## 配方\n- 金酒 50ml\n- 柠檬汁 20ml",
    )
    assert ok is True

    with get_session() as session:
        doc = session.get(Document, created["doc_id"])
        assert doc.title == "改后配方"

    # pending 状态不可编辑
    submit_recipe(created["doc_id"])
    ok2 = update_recipe(
        created["doc_id"],
        title="再改",
        ingredients=["金酒"],
        content="# 再改",
    )
    assert ok2 is False

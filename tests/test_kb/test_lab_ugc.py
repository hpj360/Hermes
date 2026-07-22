"""M4.3 UGC 调酒研究室测试。"""
from __future__ import annotations

import pytest
from sqlmodel import select


def test_recipe_variant_model(tmp_db):
    """RecipeVariant 表可创建并写入（FK 约束要求 doc 必须存在）。"""
    from hermes_kb.models import Document, RecipeVariant
    from hermes_kb.database import get_session

    with get_session() as session:
        # FK 约束要求 base/variant doc 必须先存在
        base_doc = Document(title="原版", content="内容")
        variant_doc = Document(title="变体", content="内容")
        session.add(base_doc)
        session.add(variant_doc)
        session.commit()
        session.refresh(base_doc)
        session.refresh(variant_doc)

        v = RecipeVariant(
            base_doc_id=base_doc.doc_id,
            variant_doc_id=variant_doc.doc_id,
            variant_note="辛辣版，增加苦精",
        )
        session.add(v)
        session.commit()
        session.refresh(v)
        assert v.id is not None
        assert v.base_doc_id == base_doc.doc_id
        assert v.variant_doc_id == variant_doc.doc_id
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


@pytest.fixture
def base_and_variant(tmp_db):
    """创建一个原配方和一个变体。"""
    from hermes_kb.recipe_crud import create_recipe

    base = create_recipe(
        title="原版马天尼",
        ingredients=["金酒", "味美思", "橄榄"],
        content="# 原版马天尼\n\n## 配方\n- 金酒 60ml\n- 味美思 10ml\n- 橄榄 1颗",
        base_spirit="gin",
        difficulty="easy",
    )
    variant = create_recipe(
        title="辛辣马天尼",
        ingredients=["金酒", "味美思", "苦精"],
        content="# 辛辣马天尼\n\n## 配方\n- 金酒 60ml\n- 味美思 10ml\n- 苦精 2滴",
        base_spirit="gin",
        difficulty="medium",
    )
    return base, variant


def test_create_variant_link(base_and_variant):
    """创建变体关联。"""
    from hermes_kb.recipe_variants import create_variant_link, get_variants

    base, variant = base_and_variant
    ok = create_variant_link(
        base_doc_id=base["doc_id"],
        variant_doc_id=variant["doc_id"],
        variant_note="增加苦精的辛辣版",
    )
    assert ok is True

    variants = get_variants(base["doc_id"])
    assert len(variants) == 1
    assert variants[0]["variant_doc_id"] == variant["doc_id"]
    assert variants[0]["variant_note"] == "增加苦精的辛辣版"
    assert variants[0]["variant_title"] == "辛辣马天尼"


def test_get_base_recipe(base_and_variant):
    """查询变体的原配方。"""
    from hermes_kb.recipe_variants import create_variant_link, get_base_recipe

    base, variant = base_and_variant
    create_variant_link(base["doc_id"], variant["doc_id"], "测试")

    base_info = get_base_recipe(variant["doc_id"])
    assert base_info is not None
    assert base_info["base_doc_id"] == base["doc_id"]
    assert base_info["base_title"] == "原版马天尼"


def test_create_variant_duplicate(base_and_variant):
    """重复创建变体关联返回 False。"""
    from hermes_kb.recipe_variants import create_variant_link

    base, variant = base_and_variant
    create_variant_link(base["doc_id"], variant["doc_id"], "第一次")
    ok = create_variant_link(base["doc_id"], variant["doc_id"], "第二次")
    assert ok is False


def test_api_create_recipe(client):
    """POST /api/lab/recipes 创建 UGC 配方。"""
    resp = client.post("/api/lab/recipes", json={
        "title": "API 特调",
        "ingredients": ["金酒", "柠檬汁"],
        "content": "# API 特调\n\n## 配方\n- 金酒 50ml\n- 柠檬汁 20ml",
        "base_spirit": "gin",
        "difficulty": "easy",
        "season": "summer",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "draft"
    assert data["doc_id"] is not None


def test_api_recipe_lifecycle(client):
    """UGC 配方完整生命周期：创建→提交→通过。"""
    # 创建
    created = client.post("/api/lab/recipes", json={
        "title": "生命周期测试",
        "ingredients": ["金酒"],
        "content": "# 生命周期测试\n\n## 配方\n- 金酒 50ml",
        "base_spirit": "gin",
        "difficulty": "easy",
    }).json()
    doc_id = created["doc_id"]

    # 提交
    resp = client.post(f"/api/lab/recipes/{doc_id}/submit")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    # 通过
    resp = client.post(f"/api/lab/recipes/{doc_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_api_recipe_reject(client):
    """POST /api/lab/recipes/{doc_id}/reject 审核驳回。"""
    created = client.post("/api/lab/recipes", json={
        "title": "将被驳回",
        "ingredients": ["金酒"],
        "content": "# 将被驳回",
        "base_spirit": "gin",
        "difficulty": "easy",
    }).json()
    client.post(f"/api/lab/recipes/{created['doc_id']}/submit")

    resp = client.post(
        f"/api/lab/recipes/{created['doc_id']}/reject",
        json={"reason": "配方不完整"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_api_recipe_variants(client, base_and_variant):
    """GET /api/lab/recipes/{doc_id}/variants 查看变体。"""
    from hermes_kb.recipe_variants import create_variant_link

    base, variant = base_and_variant
    create_variant_link(base["doc_id"], variant["doc_id"], "测试变体")

    resp = client.get(f"/api/lab/recipes/{base['doc_id']}/variants")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["variant_title"] == "辛辣马天尼"


def test_api_pending_recipes(client, base_and_variant):
    """GET /api/lab/recipes?status=pending 查看待审核。"""
    from hermes_kb.recipe_crud import submit_recipe

    base, _ = base_and_variant
    submit_recipe(base["doc_id"])

    resp = client.get("/api/lab/recipes", params={"status": "pending"})
    assert resp.status_code == 200
    data = resp.json()
    assert any(i["title"] == "原版马天尼" for i in data["items"])


def test_recipe_variant_cascade_on_delete(base_and_variant):
    """P0-2: 删除 base 配方后，RecipeVariant 关联应级联删除（不留孤儿）。"""
    from hermes_kb.recipe_variants import create_variant_link
    from hermes_kb.models import Document, RecipeVariant
    from hermes_kb.database import get_session

    base, variant = base_and_variant
    create_variant_link(base["doc_id"], variant["doc_id"], "测试级联")

    with get_session() as session:
        # 确认关联已建立
        links_before = session.exec(
            select(RecipeVariant).where(RecipeVariant.base_doc_id == base["doc_id"])
        ).all()
        assert len(links_before) == 1

        # 删除 base Document
        doc = session.get(Document, base["doc_id"])
        session.delete(doc)
        session.commit()

        # RecipeVariant 应被级联删除（不留孤儿）
        links_after = session.exec(
            select(RecipeVariant).where(RecipeVariant.base_doc_id == base["doc_id"])
        ).all()
        assert len(links_after) == 0


def test_recipe_variant_cascade_on_delete_variant(base_and_variant):
    """P0-2: 删除 variant 配方后，RecipeVariant 关联也应级联删除。"""
    from hermes_kb.recipe_variants import create_variant_link
    from hermes_kb.models import Document, RecipeVariant
    from hermes_kb.database import get_session

    base, variant = base_and_variant
    create_variant_link(base["doc_id"], variant["doc_id"], "测试级联")

    with get_session() as session:
        links_before = session.exec(
            select(RecipeVariant).where(RecipeVariant.variant_doc_id == variant["doc_id"])
        ).all()
        assert len(links_before) == 1

        # 删除 variant Document
        doc = session.get(Document, variant["doc_id"])
        session.delete(doc)
        session.commit()

        # RecipeVariant 应被级联删除
        links_after = session.exec(
            select(RecipeVariant).where(RecipeVariant.variant_doc_id == variant["doc_id"])
        ).all()
        assert len(links_after) == 0

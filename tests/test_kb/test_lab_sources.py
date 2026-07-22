"""M4.2 L3 外部数据源测试（B1+B5）。"""
from __future__ import annotations

import pytest
from sqlmodel import select


def test_document_new_fields():
    """B1: Document 支持 8 个新字段且有默认值。"""
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    with get_session() as session:
        doc = Document(title="测试配方", category="recipe")
        session.add(doc)
        session.commit()
        session.refresh(doc)
        assert doc.source == "local"
        assert doc.source_id is None
        assert doc.verified is True
        assert doc.season is None
        assert doc.hidden is False
        assert doc.status == "published"
        assert doc.image_url is None
        assert doc.meta == "{}"


def test_document_with_external_source():
    """B1: Document 可标记为外部数据源 + 图片 URL + metadata。"""
    from hermes_kb.models import Document
    from hermes_kb.database import get_session
    import json

    with get_session() as session:
        doc = Document(
            title="Mojito (TCTDB)",
            category="recipe",
            source="thecocktaildb",
            source_id="11000",
            verified=False,
            season="summer",
            status="pending",
            image_url="https://www.thecocktaildb.com/images/media/drink/metwpp1504642957.jpg",
            meta=json.dumps({"ingredients": ["朗姆酒", "青柠汁", "糖浆", "薄荷叶", "苏打水"], "category": "cocktail"}),
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        assert doc.source == "thecocktaildb"
        assert doc.source_id == "11000"
        assert doc.verified is False
        assert doc.season == "summer"
        assert doc.status == "pending"
        assert doc.image_url.startswith("https://")
        meta = json.loads(doc.meta)
        assert "ingredients" in meta
        assert "朗姆酒" in meta["ingredients"]


@pytest.fixture
def external_recipes():
    """导入几款外部数据源配方用于筛选测试。"""
    from hermes_kb.models import Document
    from hermes_kb.database import get_session
    from hermes_kb.rag import ImportService

    importer = ImportService()
    recipes = [
        {"title": "Mojito (TCTDB)", "source": "thecocktaildb", "source_id": "11000", "verified": False},
        {"title": "Negroni (TCTDB)", "source": "thecocktaildb", "source_id": "11001", "verified": False},
        {"title": "Margarita (TCTDB)", "source": "thecocktaildb", "source_id": "11002", "verified": True},
    ]
    for r in recipes:
        result = importer.import_text(
            content=f"<!-- ingredients: 金酒 -->\n# {r['title']}",
            title=r["title"],
        )
        doc_id = result["doc_id"] if isinstance(result, dict) else result
        with get_session() as session:
            doc = session.get(Document, doc_id)
            doc.category = "recipe"
            doc.source = r["source"]
            doc.source_id = r["source_id"]
            doc.verified = r["verified"]
            session.add(doc)
            session.commit()
    return importer


def test_filter_recipes_by_source(external_recipes):
    """B5: 按数据源筛选配方。"""
    from hermes_kb.recipe_filter import filter_recipes

    result = filter_recipes(source="thecocktaildb")
    assert len(result) == 3
    assert all(r["source"] == "thecocktaildb" for r in result)


def test_filter_recipes_by_verified(external_recipes):
    """B5: 按审核状态筛选。"""
    from hermes_kb.recipe_filter import filter_recipes

    unverified = filter_recipes(verified=False)
    assert len(unverified) == 2
    assert all(not r["verified"] for r in unverified)

    verified = filter_recipes(verified=True)
    assert len(verified) == 1
    assert verified[0]["title"] == "Margarita (TCTDB)"


def test_verify_recipe(external_recipes):
    """B5: 审核通过配方。"""
    from hermes_kb.recipe_filter import verify_recipe
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    with get_session() as session:
        doc = session.exec(
            select(Document).where(Document.title == "Mojito (TCTDB)")
        ).first()
        doc_id = doc.doc_id

    verify_recipe(doc_id)

    with get_session() as session:
        doc = session.get(Document, doc_id)
        assert doc.verified is True
        assert doc.status == "published"


def test_hide_recipe(external_recipes):
    """B5: 隐藏配方。"""
    from hermes_kb.recipe_filter import hide_recipe
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    with get_session() as session:
        doc = session.exec(
            select(Document).where(Document.title == "Negroni (TCTDB)")
        ).first()
        doc_id = doc.doc_id

    hide_recipe(doc_id, hidden=True)

    with get_session() as session:
        doc = session.get(Document, doc_id)
        assert doc.hidden is True

    hide_recipe(doc_id, hidden=False)
    with get_session() as session:
        doc = session.get(Document, doc_id)
        assert doc.hidden is False


def test_match_excludes_unverified(external_recipes):
    """B5: 匹配排除 verified=false 的配方。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒"})
    all_titles = [r["title"] for r in result["full_match"]] + [
        r["title"] for r in result["partial_match"]
    ]
    # Margarita (TCTDB) verified=True 应出现，其他两个 verified=False 不出现
    assert "Margarita (TCTDB)" in all_titles
    assert "Mojito (TCTDB)" not in all_titles
    assert "Negroni (TCTDB)" not in all_titles


def test_match_excludes_hidden(external_recipes):
    """B5: 匹配排除 hidden=true 的配方。"""
    from hermes_kb.recipe_match import match_recipes
    from hermes_kb.recipe_filter import hide_recipe
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    # 先隐藏 Margarita
    with get_session() as session:
        doc = session.exec(
            select(Document).where(Document.title == "Margarita (TCTDB)")
        ).first()
        doc_id = doc.doc_id
    hide_recipe(doc_id, hidden=True)

    result = match_recipes({"金酒"})
    all_titles = [r["title"] for r in result["full_match"]] + [
        r["title"] for r in result["partial_match"]
    ]
    assert "Margarita (TCTDB)" not in all_titles

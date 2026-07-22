"""M4.1 自动运营层测试：每日推荐 + 缺材料统计 + 运营看板。"""
from __future__ import annotations

import pytest
from sqlmodel import select


def test_missing_ingredient_stats_model(tmp_db):
    """MissingIngredientStats 表可创建并写入。"""
    from hermes_kb.models import MissingIngredientStats
    from hermes_kb.database import get_session

    with get_session() as session:
        stat = MissingIngredientStats(
            canonical="君度", missing_count=5
        )
        session.add(stat)
        session.commit()
        session.refresh(stat)
        assert stat.canonical == "君度"
        assert stat.missing_count == 5
        assert stat.last_missing_at is None


def test_seed_recipes_have_season():
    """每款种子配方都有 season 标签。"""
    from hermes_kb.seed_recipes import SEED_RECIPES

    valid_seasons = {"spring", "summer", "autumn", "winter"}
    for recipe in SEED_RECIPES:
        assert "season" in recipe, f"配方 {recipe['title']} 缺 season 字段"
        assert recipe["season"] in valid_seasons, (
            f"配方 {recipe['title']} 的 season={recipe['season']} 不合法"
        )


def test_seed_recipes_season_distribution():
    """季节标签至少覆盖 3 个季节（避免全挤一季）。"""
    from hermes_kb.seed_recipes import SEED_RECIPES

    seasons = {r["season"] for r in SEED_RECIPES}
    assert len(seasons) >= 3, f"季节覆盖不足: {seasons}"


@pytest.fixture
def seeded_recipes_ops(tmp_db):
    """导入种子配方（含 season）用于运营层测试。"""
    from hermes_kb.rag import ImportService
    from hermes_kb.seed_recipes import SEED_RECIPES
    from hermes_kb.database import get_session
    from hermes_kb.models import Document
    from sqlmodel import select

    importer = ImportService()
    for recipe in SEED_RECIPES:
        importer.import_text(
            content=recipe["content"],
            title=recipe["title"],
            source_type="seed",
            file_type="md",
        )
        with get_session() as session:
            doc = session.exec(
                select(Document).where(Document.title == recipe["title"])
            ).first()
            if doc:
                doc.category = "recipe"
                session.add(doc)
                session.commit()
    return importer


def test_daily_recipe_returns_one(seeded_recipes_ops):
    """每日推荐返回一款配方。"""
    from hermes_kb.daily_recipe import daily_recipe

    result = daily_recipe()
    assert result is not None
    assert "title" in result
    assert "doc_id" in result
    assert "reason" in result
    assert result["reason"] in ["season", "hot", "random"]


def test_daily_recipe_stable_per_day(seeded_recipes_ops):
    """同一天多次调用返回同一款。"""
    from hermes_kb.daily_recipe import daily_recipe

    r1 = daily_recipe()
    r2 = daily_recipe()
    assert r1["doc_id"] == r2["doc_id"]


def test_daily_recipe_reason_format(seeded_recipes_ops):
    """reason 字段格式正确。"""
    from hermes_kb.daily_recipe import daily_recipe

    result = daily_recipe()
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0

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


def test_missing_stats_increment(seeded_recipes_ops):
    """记录缺失材料计数。"""
    from hermes_kb.missing_stats import increment_missing, get_missing_stats

    increment_missing("君度")
    increment_missing("君度")
    increment_missing("金巴利")

    stat = get_missing_stats("君度")
    assert stat is not None
    assert stat["missing_count"] == 2
    assert stat["last_missing_at"] is not None


def test_missing_stats_top(seeded_recipes_ops):
    """缺失材料排行。"""
    from hermes_kb.missing_stats import increment_missing, get_top_missing

    for _ in range(5):
        increment_missing("君度")
    for _ in range(3):
        increment_missing("金巴利")
    for _ in range(1):
        increment_missing("苦精")

    top = get_top_missing(limit=3)
    assert len(top) == 3
    assert top[0]["canonical"] == "君度"
    assert top[0]["missing_count"] == 5
    assert top[1]["canonical"] == "金巴利"
    assert top[2]["canonical"] == "苦精"


def test_match_records_missing(seeded_recipes_ops):
    """match_recipes 调用后缺失材料被统计。"""
    from hermes_kb.recipe_match import match_recipes
    from hermes_kb.missing_stats import get_missing_stats

    # 白色佳人需要金酒+君度+柠檬汁，只给金酒+柠檬汁 → 缺君度
    match_recipes({"金酒", "柠檬汁"})
    stat = get_missing_stats("君度")
    assert stat is not None
    assert stat["missing_count"] >= 1


def test_lab_dashboard_aggregation(seeded_recipes_ops):
    """运营看板返回完整指标。"""
    from hermes_kb.lab_dashboard import get_lab_dashboard
    from hermes_kb.recipe_match import match_recipes

    # 制造一些匹配和缺失数据
    match_recipes({"金酒", "味美思", "橄榄"})
    match_recipes({"金酒", "柠檬汁"})

    dashboard = get_lab_dashboard()
    assert "recipe_count" in dashboard
    assert "weekly_match_count" in dashboard
    assert "top_recipe" in dashboard
    assert "top_missing" in dashboard
    assert "substitute_coverage" in dashboard
    assert "user_substitute_count" in dashboard
    assert "daily_recipe" in dashboard
    assert "season_coverage" in dashboard

    assert dashboard["recipe_count"] >= 8
    assert isinstance(dashboard["substitute_coverage"], (int, float))
    assert 0 <= dashboard["substitute_coverage"] <= 1

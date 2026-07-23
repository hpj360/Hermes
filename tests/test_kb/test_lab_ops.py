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


def test_daily_recipe_returns_one(seeded_recipes):
    """每日推荐返回一款配方。"""
    from hermes_kb.daily_recipe import daily_recipe

    result = daily_recipe()
    assert result is not None
    assert "title" in result
    assert "doc_id" in result
    assert "reason" in result
    assert result["reason"] in ["season", "hot", "random"]


def test_daily_recipe_stable_per_day(seeded_recipes):
    """同一天多次调用返回同一款。"""
    from hermes_kb.daily_recipe import daily_recipe

    r1 = daily_recipe()
    r2 = daily_recipe()
    assert r1["doc_id"] == r2["doc_id"]


def test_daily_recipe_reason_format(seeded_recipes):
    """reason 字段格式正确。"""
    from hermes_kb.daily_recipe import daily_recipe

    result = daily_recipe()
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0


def test_missing_stats_increment(seeded_recipes):
    """记录缺失材料计数。"""
    from hermes_kb.missing_stats import increment_missing, get_missing_stats

    increment_missing("君度")
    increment_missing("君度")
    increment_missing("金巴利")

    stat = get_missing_stats("君度")
    assert stat is not None
    assert stat["missing_count"] == 2
    assert stat["last_missing_at"] is not None


def test_missing_stats_top(seeded_recipes):
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


def test_match_records_missing(seeded_recipes):
    """match_recipes 调用后缺失材料被统计（A3-3: 通过 _pending_stats 异步批量写入）。"""
    from hermes_kb.recipe_match import match_recipes
    from hermes_kb.missing_stats import batch_increment_missing, get_missing_stats

    # 白色佳人需要金酒+君度+柠檬汁，只给金酒+柠檬汁 → 缺君度
    result = match_recipes({"金酒", "柠檬汁"})
    # A3-3: match_recipes 不再同步写统计，由调用方应用 _pending_stats（端点走 BackgroundTasks）
    pending = result["_pending_stats"]
    if pending.get("missing_ingredients"):
        batch_increment_missing(pending["missing_ingredients"])
    stat = get_missing_stats("君度")
    assert stat is not None
    assert stat["missing_count"] >= 1


def test_lab_dashboard_aggregation(seeded_recipes):
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


def test_api_lab_daily(seeded_recipes, client):
    """GET /api/lab/daily 返回每日推荐。"""
    resp = client.get("/api/lab/daily")
    assert resp.status_code == 200
    data = resp.json()
    assert "title" in data
    assert "doc_id" in data
    assert data["reason"] in ["season", "hot", "random"]


def test_api_lab_missing_stats(seeded_recipes, client):
    """GET /api/lab/missing-stats 返回缺失排行。"""
    # 先制造缺失数据
    client.get("/api/lab/match", params={"ingredients": "金酒,柠檬汁"})

    resp = client.get("/api/lab/missing-stats", params={"limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) > 0
    assert "canonical" in data["items"][0]
    assert "missing_count" in data["items"][0]


def test_api_lab_substitute_save(seeded_recipes, client):
    """POST /api/lab/substitute 保存用户自定义替代。"""
    resp = client.post(
        "/api/lab/substitute",
        json={"canonical": "君度", "substitute": "自制橙皮酒"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    from hermes_kb.substitutes import get_substitutes
    assert "自制橙皮酒" in get_substitutes("君度")


def test_api_lab_dashboard(seeded_recipes, client):
    """GET /api/lab/dashboard 返回运营看板。"""
    resp = client.get("/api/lab/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recipe_count"] >= 8
    assert "substitute_coverage" in data
    assert "daily_recipe" in data


def test_weekly_match_count_semantics(seeded_recipes):
    """A4-1: weekly_match_count 应为本周新增匹配数，不是累计值。"""
    from hermes_kb.recipe_stats import increment_match_count
    from hermes_kb.lab_dashboard import get_lab_dashboard
    from hermes_kb.database import get_session
    from hermes_kb.models import Document
    from sqlmodel import select

    # seeded_recipes 是 ImportService，从 DB 取前 2 个 recipe 的 doc_id
    with get_session() as session:
        docs = session.exec(
            select(Document).where(Document.category == "recipe").limit(2)
        ).all()
    doc_ids = [d.doc_id for d in docs]
    assert len(doc_ids) >= 2, "种子配方不足 2 个，无法完成测试"

    # 第一周：配方 A 匹配 5 次，配方 B 匹配 3 次
    for _ in range(5):
        increment_match_count(doc_ids[0])
    for _ in range(3):
        increment_match_count(doc_ids[1])

    dash = get_lab_dashboard()
    # weekly_match_count 应是 8（5+3），不是累计
    assert dash["weekly_match_count"] == 8
    # total_match_count 应等于 weekly（因为还没重置过）
    assert dash["total_match_count"] == 8

    # 模拟周切换：重置 weekly
    from hermes_kb.recipe_stats import reset_weekly_stats
    reset_weekly_stats()

    dash = get_lab_dashboard()
    # 重置后 weekly 应为 0
    assert dash["weekly_match_count"] == 0
    # total 仍保留 8（累计）
    assert dash["total_match_count"] == 8

    # 第二周：配方 A 再匹配 2 次
    for _ in range(2):
        increment_match_count(doc_ids[0])

    dash = get_lab_dashboard()
    # weekly 应是 2（新周新增）
    assert dash["weekly_match_count"] == 2
    # total 应是 10（5+3+2）
    assert dash["total_match_count"] == 10

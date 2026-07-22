"""鸡尾酒实验室测试：数据模型 + 匹配算法 + API + 统计。"""
from __future__ import annotations

import pytest
from sqlmodel import select


def test_recipe_stats_model(tmp_db):
    """RecipeStats 表可创建并写入。"""
    from hermes_kb.models import RecipeStats
    from hermes_kb.database import get_session

    with get_session() as session:
        stat = RecipeStats(doc_id="recipe-martini", match_count=5, view_count=12)
        session.add(stat)
        session.commit()
        session.refresh(stat)
        assert stat.doc_id == "recipe-martini"
        assert stat.match_count == 5
        assert stat.view_count == 12
        assert stat.last_matched_at is None


def test_ingredient_substitute_model(tmp_db):
    """IngredientSubstitute 表可创建并写入。"""
    from hermes_kb.models import IngredientSubstitute
    from hermes_kb.database import get_session

    with get_session() as session:
        sub = IngredientSubstitute(
            canonical="君度", substitute="橙味力娇酒", source="preset"
        )
        session.add(sub)
        session.commit()
        session.refresh(sub)
        assert sub.id is not None
        assert sub.canonical == "君度"
        assert sub.source == "preset"


def test_ingredient_registry_canonical():
    """材料注册表能通过别名归一化到标准名。"""
    from hermes_kb.ingredients import canonicalize, INGREDIENT_REGISTRY

    assert canonicalize("gin") == "金酒"
    assert canonicalize("Gin") == "金酒"
    assert canonicalize("dry gin") == "金酒"
    assert canonicalize("杜松子酒") == "金酒"
    assert canonicalize("gordon's") == "金酒"
    # 未知材料返回原值
    assert canonicalize("未知材料") == "未知材料"


def test_ingredient_registry_category():
    """材料能正确分类。"""
    from hermes_kb.ingredients import get_category, INGREDIENT_REGISTRY

    assert get_category("金酒") == "base_spirit"
    assert get_category("味美思") == "modifier"
    assert get_category("柠檬汁") == "juice"
    assert get_category("橄榄") == "garnish"


def test_ingredient_registry_list_by_category():
    """能按分类列出所有材料。"""
    from hermes_kb.ingredients import list_by_category

    base_spirits = list_by_category("base_spirit")
    assert "金酒" in base_spirits
    assert "威士忌" in base_spirits
    assert len(base_spirits) >= 6  # 六大基酒


def test_ingredient_registry_all_canonical():
    """所有标准名都能被列出。"""
    from hermes_kb.ingredients import all_canonical

    names = all_canonical()
    assert "金酒" in names
    assert "君度" in names
    assert "柠檬汁" in names


def test_substitutes_preset():
    """L1 预置替代关系可查询。"""
    from hermes_kb.substitutes import get_substitutes_preset

    subs = get_substitutes_preset("君度")
    assert "橙味力娇酒" in subs
    assert "干库拉索" in subs


def test_substitutes_merged_with_user(tmp_db):
    """L1 预置 + L2 用户自定义能合并查询。"""
    from hermes_kb.substitutes import get_substitutes, add_user_substitute
    from hermes_kb.database import get_session
    from hermes_kb.models import IngredientSubstitute

    preset_subs = get_substitutes("君度")
    assert "橙味力娇酒" in preset_subs

    add_user_substitute("君度", "自制橙皮酒")
    merged = get_substitutes("君度")
    assert "橙味力娇酒" in merged
    assert "自制橙皮酒" in merged


def test_substitutes_remove_user(tmp_db):
    """可删除用户自定义替代（不影响预置）。"""
    from hermes_kb.substitutes import (
        add_user_substitute,
        remove_user_substitute,
        get_substitutes,
    )

    add_user_substitute("君度", "临时替代")
    assert "临时替代" in get_substitutes("君度")

    remove_user_substitute("君度", "临时替代")
    assert "临时替代" not in get_substitutes("君度")
    assert "橙味力娇酒" in get_substitutes("君度")


def test_seed_recipes_structure():
    """种子配方数据结构完整。"""
    from hermes_kb.seed_recipes import SEED_RECIPES

    assert len(SEED_RECIPES) >= 8

    recipe = SEED_RECIPES[0]
    assert "title" in recipe
    assert "content" in recipe
    assert "base_spirit" in recipe
    assert "difficulty" in recipe
    assert "ingredients" in recipe
    assert isinstance(recipe["ingredients"], list)
    assert len(recipe["ingredients"]) > 0


def test_seed_recipes_martini():
    """马天尼配方内容正确。"""
    from hermes_kb.seed_recipes import SEED_RECIPES

    martini = next(r for r in SEED_RECIPES if "马天尼" in r["title"])
    assert "金酒" in martini["ingredients"]
    assert "味美思" in martini["ingredients"]
    assert martini["base_spirit"] == "gin"
    assert martini["difficulty"] == "easy"


def test_seed_recipes_all_ingredients_canonical():
    """所有配方的材料都是标准名（在注册表中）。"""
    from hermes_kb.seed_recipes import SEED_RECIPES
    from hermes_kb.ingredients import all_canonical

    valid_names = set(all_canonical())
    for recipe in SEED_RECIPES:
        for ing in recipe["ingredients"]:
            assert ing in valid_names, (
                f"配方 {recipe['title']} 的材料 {ing} 不在注册表中"
            )


@pytest.fixture
def seeded_recipes(tmp_db):
    """导入种子配方的 ImportService。"""
    from hermes_kb.rag import ImportService
    from hermes_kb.seed_recipes import SEED_RECIPES

    importer = ImportService()
    for recipe in SEED_RECIPES:
        importer.import_text(
            content=recipe["content"],
            title=recipe["title"],
            source_type="seed",
            file_type="md",
        )
        # 设置 category=recipe
        from hermes_kb.database import get_session
        from hermes_kb.models import Document
        from sqlmodel import select

        with get_session() as session:
            doc = session.exec(
                select(Document).where(Document.title == recipe["title"])
            ).first()
            if doc:
                doc.category = "recipe"
                session.add(doc)
                session.commit()
    return importer


def test_match_full(seeded_recipes):
    """材料齐全的配方进 full_match。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒", "味美思", "橄榄"})
    titles = [r["title"] for r in result["full_match"]]
    assert "马天尼 Martini" in titles


def test_match_partial(seeded_recipes):
    """缺 1-2 种材料的配方进 partial_match。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒", "柠檬汁"})
    partial_titles = [r["title"] for r in result["partial_match"]]
    assert "白色佳人 White Lady" in partial_titles
    white_lady = next(r for r in result["partial_match"] if "白色佳人" in r["title"])
    assert "君度" in white_lady["missing"]


def test_match_substitute_resolves(seeded_recipes):
    """有替代品时，缺的材料算"不缺"。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"龙舌兰", "橙味力娇酒", "青柠汁"})
    titles = [r["title"] for r in result["full_match"]]
    assert "玛格丽特 Margarita" in titles


def test_match_skip_three_plus_missing(seeded_recipes):
    """缺 3+ 种材料的配方不返回。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒"})
    all_titles = [r["title"] for r in result["full_match"]] + [
        r["title"] for r in result["partial_match"]
    ]
    assert "莫吉托 Mojito" not in all_titles


def test_match_empty_input(seeded_recipes):
    """空材料集合返回空结果。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes(set())
    assert result["full_match"] == []
    assert result["partial_match"] == []


def test_stats_increment_match(seeded_recipes):
    """匹配命中时 match_count +1。"""
    from hermes_kb.recipe_stats import increment_match_count, get_stats
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒", "味美思", "橄榄"})
    martini = next(r for r in result["full_match"] if "马天尼" in r["title"])
    doc_id = martini["doc_id"]

    increment_match_count(doc_id)
    increment_match_count(doc_id)
    stat = get_stats(doc_id)
    assert stat is not None
    assert stat["match_count"] == 2
    assert stat["last_matched_at"] is not None


def test_stats_increment_view(seeded_recipes):
    """查看详情时 view_count +1。"""
    from hermes_kb.recipe_stats import increment_view_count, get_stats

    from hermes_kb.rag import ImportService

    importer = ImportService()
    result = importer.import_text(
        content="# 测试配方\n金酒 60ml", title="测试配方", source_type="test"
    )
    doc_id = result["doc_id"]

    increment_view_count(doc_id)
    stat = get_stats(doc_id)
    assert stat["view_count"] == 1


def test_stats_hot_recipes(seeded_recipes):
    """热门配方按 match_count 降序。"""
    from hermes_kb.recipe_stats import increment_match_count, get_hot_recipes
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒", "味美思", "橄榄"})
    martini = next(r for r in result["full_match"] if "马天尼" in r["title"])
    for _ in range(3):
        increment_match_count(martini["doc_id"])

    result = match_recipes({"金酒", "金巴利", "味美思"})
    negroni = next(r for r in result["full_match"] if "尼格罗尼" in r["title"])
    increment_match_count(negroni["doc_id"])

    hot = get_hot_recipes(limit=10, days=30)
    assert len(hot) >= 2
    assert hot[0]["match_count"] >= 3


def test_api_lab_match(seeded_recipes, client):
    """GET /api/lab/match 返回匹配结果。"""
    resp = client.get("/api/lab/match", params={"ingredients": "金酒,味美思,橄榄"})
    assert resp.status_code == 200
    data = resp.json()
    assert "full_match" in data
    assert "partial_match" in data
    titles = [r["title"] for r in data["full_match"]]
    assert "马天尼 Martini" in titles


def test_api_lab_match_empty(client):
    """空材料返回空结果。"""
    resp = client.get("/api/lab/match", params={"ingredients": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["full_match"] == []
    assert data["partial_match"] == []


def test_api_lab_match_increments_stats(seeded_recipes, client):
    """匹配 API 调用后统计计数增加。"""
    resp = client.get(
        "/api/lab/match", params={"ingredients": "金酒,味美思,橄榄"}
    )
    assert resp.status_code == 200
    martini = next(
        r for r in resp.json()["full_match"] if "马天尼" in r["title"]
    )
    doc_id = martini["doc_id"]

    from hermes_kb.recipe_stats import get_stats

    stat = get_stats(doc_id)
    assert stat is not None
    assert stat["match_count"] >= 1


def test_api_lab_hot(seeded_recipes, client):
    """GET /api/lab/hot 返回热门配方。"""
    for _ in range(3):
        client.get(
            "/api/lab/match", params={"ingredients": "金酒,味美思,橄榄"}
        )

    resp = client.get("/api/lab/hot", params={"limit": 10, "days": 30})
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) > 0
    assert data["items"][0]["match_count"] >= 3


def test_api_lab_view(seeded_recipes, client):
    """POST /api/lab/view/{doc_id} 增加查看计数。"""
    from hermes_kb.recipe_match import match_recipes

    result = match_recipes({"金酒", "味美思", "橄榄"})
    doc_id = result["full_match"][0]["doc_id"]

    resp = client.post(f"/api/lab/view/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    from hermes_kb.recipe_stats import get_stats

    stat = get_stats(doc_id)
    assert stat["view_count"] == 1


def test_api_seed_recipes(client):
    """POST /api/seed/recipes 导入 IBA 配方种子。"""
    resp = client.post("/api/seed/recipes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["seeded"] == 8
    assert data["failed"] == 0
    from hermes_kb.database import get_session
    from hermes_kb.models import Document
    from sqlmodel import select

    with get_session() as session:
        recipes = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        assert len(recipes) == 8
        titles = [d.title for d in recipes]
        assert "马天尼 Martini" in titles


def test_api_seed_recipes_idempotent(client):
    """重复导入不会产生重复配方。"""
    client.post("/api/seed/recipes")
    resp = client.post("/api/seed/recipes")
    assert resp.status_code == 200
    from hermes_kb.database import get_session
    from hermes_kb.models import Document
    from sqlmodel import select

    with get_session() as session:
        count = len(
            session.exec(
                select(Document).where(Document.category == "recipe")
            ).all()
        )
        assert count == 8

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

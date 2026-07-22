"""配方匹配算法。

输入：用户已有的材料集合（标准名）
输出：分两组返回
- full_match: 缺 0 种（含替代命中）
- partial_match: 缺 1-2 种
- 缺 3+ 种不返回

排序规则：
- full_match 按材料命中数降序
- partial_match 按缺少数升序

装饰类材料（garnish）视为可选，不参与缺少数判定。
"""
from __future__ import annotations

from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.ingredients import get_category
from hermes_kb.models import Chunk, Document
from hermes_kb.substitutes import get_substitutes


def _load_recipes() -> list[dict[str, Any]]:
    """从知识库加载所有 category=recipe 的配方文档。"""
    recipes: list[dict[str, Any]] = []
    with get_session() as session:
        docs = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        for doc in docs:
            first_chunk = session.exec(
                select(Chunk)
                .where(Chunk.doc_id == doc.doc_id)
                .order_by(Chunk.idx)
            ).first()
            recipes.append(
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "chunk_rowid": first_chunk.id if first_chunk else None,
                    "content": doc.content or "",
                }
            )
    return recipes


def _extract_ingredients_from_seed(title: str) -> set[str]:
    """从种子配方标题反查材料。"""
    from hermes_kb.seed_recipes import SEED_RECIPES

    for recipe in SEED_RECIPES:
        if recipe["title"] == title:
            return set(recipe["ingredients"])
    return set()


def _parse_ingredients_from_content(content: str) -> set[str]:
    """从配方内容解析材料（基于材料注册表匹配）。"""
    from hermes_kb.ingredients import all_canonical

    found: set[str] = set()
    for name in all_canonical():
        if name in content:
            found.add(name)
    return found


def _get_recipe_ingredients(recipe: dict[str, Any]) -> set[str]:
    """获取配方的材料集合（优先种子映射，回退内容解析）。"""
    ingredients = _extract_ingredients_from_seed(recipe["title"])
    if ingredients:
        return ingredients
    return _parse_ingredients_from_content(recipe["content"])


def _is_required(ingredient: str) -> bool:
    """装饰类材料（garnish）视为可选，不参与缺少数判定。"""
    return get_category(ingredient) != "garnish"


def _resolve_missing(
    missing: set[str], user_ingredients: set[str]
) -> list[str]:
    """检查缺失材料是否有用户已有的替代品。"""
    truly_missing: list[str] = []
    for m in missing:
        subs = set(get_substitutes(m))
        if subs & user_ingredients:
            continue
        truly_missing.append(m)
    return truly_missing


def match_recipes(
    user_ingredients: set[str], limit: int = 20
) -> dict[str, list[dict[str, Any]]]:
    """材料集合 → 配方匹配，分两组返回。"""
    if not user_ingredients:
        return {"full_match": [], "partial_match": []}

    from hermes_kb.seed_recipes import SEED_RECIPES

    seed_meta: dict[str, dict] = {}
    for r in SEED_RECIPES:
        seed_meta[r["title"]] = r

    recipes = _load_recipes()
    full_match: list[dict[str, Any]] = []
    partial_match: list[dict[str, Any]] = []

    for recipe in recipes:
        title = recipe["title"]
        meta = seed_meta.get(title, {})
        recipe_ingredients = (
            set(meta.get("ingredients", [])) or _get_recipe_ingredients(recipe)
        )
        if not recipe_ingredients:
            continue

        # 装饰类材料视为可选：仅统计必选材料的缺失
        required = {ing for ing in recipe_ingredients if _is_required(ing)}
        missing = required - user_ingredients
        truly_missing = _resolve_missing(missing, user_ingredients)

        ingredient_details = []
        for ing in sorted(recipe_ingredients):
            have = ing in user_ingredients
            detail: dict[str, Any] = {"name": ing, "have": have}
            if not have:
                subs = get_substitutes(ing)
                if subs:
                    detail["substitutes"] = subs
            ingredient_details.append(detail)

        base = {
            "title": title,
            "doc_id": recipe["doc_id"],
            "chunk_rowid": recipe["chunk_rowid"],
            "ingredients": ingredient_details,
            "base_spirit": meta.get("base_spirit", ""),
            "difficulty": meta.get("difficulty", ""),
        }

        if len(truly_missing) == 0:
            base["match_count"] = len(recipe_ingredients & user_ingredients)
            full_match.append(base)
        elif len(truly_missing) <= 2:
            base["missing"] = truly_missing
            base["missing_count"] = len(truly_missing)
            partial_match.append(base)

    full_match.sort(key=lambda x: x.get("match_count", 0), reverse=True)
    partial_match.sort(key=lambda x: x.get("missing_count", 0))

    return {
        "full_match": full_match[:limit],
        "partial_match": partial_match[:limit],
    }

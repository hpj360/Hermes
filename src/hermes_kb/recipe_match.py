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

A3-2: 批量化 N+1（batch_first_chunks）。
A3-3: match_recipes 不再同步写统计，改为返回 _pending_stats 内部字段，
      由端点用 BackgroundTasks 调用批量函数异步写入。
A4-2: 材料解析优先用 content 开头的 frontmatter 注释，回退 seed_meta，
      再回退改进的 _parse_ingredients_from_content（位置感知，避免裸子串误匹配）。
"""
from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from hermes_kb.database import get_session
from hermes_kb.ingredients import get_category
from hermes_kb.models import Chunk, Document
from hermes_kb.substitutes import get_substitutes

# A4-2: frontmatter 注释格式 `<!-- ingredients: a|b|c -->`
_FRONTMATTER_PATTERN = re.compile(r"<!--\s*ingredients:\s*([^>]+?)\s*-->")


def batch_first_chunks(
    doc_ids: list[str], session: Session | None = None
) -> dict[str, Chunk]:
    """批量获取多个 doc 的第一个 chunk（消除 N+1，A3-2）。

    一次 `WHERE doc_id IN (...) ORDER BY doc_id, idx` 取所有相关 chunk，
    再按 doc_id 保留 idx 最小者。返回 {doc_id: Chunk} 映射。

    传入 session 时复用该 session（不再新开），便于调用方在同一事务内
    完成 docs + chunks 两次查询且只计一次 get_session。
    """
    if not doc_ids:
        return {}

    def _collect(sess: Session) -> dict[str, Chunk]:
        rows = sess.exec(
            select(Chunk)
            .where(Chunk.doc_id.in_(doc_ids))
            .order_by(Chunk.doc_id, Chunk.idx)
        ).all()
        result: dict[str, Chunk] = {}
        for chunk in rows:
            if chunk.doc_id not in result:
                result[chunk.doc_id] = chunk
        return result

    if session is not None:
        return _collect(session)
    with get_session() as sess:
        return _collect(sess)


def _load_recipes() -> list[dict[str, Any]]:
    """从知识库加载所有 category=recipe 的配方文档（批量化 + 过滤，A3-2 + B5）。

    单次 session 内完成 docs 查询 + first_chunk 批量查询，消除 N+1。
    B5: 仅加载 verified=True 且 hidden=False 的配方，外部数据源同步默认
    不进实验室匹配，需审核通过后才可见。
    """
    with get_session() as session:
        docs = session.exec(
            select(Document).where(
                Document.category == "recipe",
                Document.verified == True,  # noqa: E712
                Document.hidden == False,  # noqa: E712
            )
        ).all()
        doc_ids = [d.doc_id for d in docs]
        first_chunks = batch_first_chunks(doc_ids, session=session)
    return [
        {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "chunk_rowid": first_chunks[doc.doc_id].id if doc.doc_id in first_chunks else None,
            "content": doc.content or "",
        }
        for doc in docs
    ]


def _extract_ingredients_from_seed(title: str) -> set[str]:
    """从种子配方标题反查材料（A4-2: 已降级为回退路径，优先用 frontmatter）。"""
    from hermes_kb.seed_recipes import SEED_RECIPES

    for recipe in SEED_RECIPES:
        if recipe["title"] == title:
            return set(recipe["ingredients"])
    return set()


def _parse_ingredients_from_frontmatter(content: str) -> set[str]:
    """从 content 开头的 HTML 注释解析材料列表（A4-2）。

    格式：`<!-- ingredients: 材料1|材料2|材料3 -->`。仅搜前 500 字符，
    无注释返回空集合。
    """
    if not content:
        return set()
    match = _FRONTMATTER_PATTERN.search(content[:500])
    if not match:
        return set()
    raw = match.group(1)
    return {x.strip() for x in raw.split("|") if x.strip()}


def _parse_ingredients_from_content(content: str) -> set[str]:
    """从配方内容解析材料（改进版，A4-2：位置感知，避免裸子串误匹配）。

    先用裸子串找出所有出现的标准名，再过滤掉「同位置起点存在更长候选」
    的命中。例如 content 含「柠檬汁」时，若「柠檬」也是标准名，则「柠檬」
    不会被单独匹配（它只是更长候选「柠檬汁」的前缀）。
    """
    from hermes_kb.ingredients import all_canonical

    if not content:
        return set()

    matches: list[tuple[str, int]] = []
    for name in all_canonical():
        start = 0
        while True:
            idx = content.find(name, start)
            if idx == -1:
                break
            matches.append((name, idx))
            start = idx + 1  # 允许重叠查找，捕获多次出现

    found: set[str] = set()
    for name, pos in matches:
        # 若同一位置存在更长的候选材料，则当前 name 是其前缀子串，跳过
        shadowed = any(
            other != name and opos == pos and len(other) > len(name)
            for other, opos in matches
        )
        if not shadowed:
            found.add(name)
    return found


def _get_recipe_ingredients(recipe: dict[str, Any]) -> set[str]:
    """获取配方的材料集合（A4-2: 优先 frontmatter，回退 seed_meta，再回退内容解析）。"""
    # 1. 优先从 frontmatter 解析
    ings = _parse_ingredients_from_frontmatter(recipe.get("content", ""))
    if ings:
        return ings
    # 2. 回退到 seed_meta（保留兼容，title 反查）
    ingredients = _extract_ingredients_from_seed(recipe.get("title", ""))
    if ingredients:
        return ingredients
    # 3. 最后回退到改进版内容解析
    return _parse_ingredients_from_content(recipe.get("content", ""))


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
    """材料集合 → 配方匹配，分两组返回（A3-3：统计异步化）。

    不再同步写统计；命中/缺失信息收集到返回结果的 `_pending_stats` 内部字段，
    由调用方（端点）用 BackgroundTasks 批量写入。
    """
    if not user_ingredients:
        return {
            "full_match": [],
            "partial_match": [],
            "_pending_stats": {"matched_doc_ids": [], "missing_ingredients": []},
        }

    from hermes_kb.seed_recipes import SEED_RECIPES

    # seed_meta 仅用于补充 base_spirit / difficulty（A4-2: 材料改由 _get_recipe_ingredients 决定）
    seed_meta: dict[str, dict] = {}
    for r in SEED_RECIPES:
        seed_meta[r["title"]] = r

    recipes = _load_recipes()
    full_match: list[dict[str, Any]] = []
    partial_match: list[dict[str, Any]] = []
    pending_matched_doc_ids: list[str] = []
    pending_missing_ingredients: list[str] = []

    for recipe in recipes:
        title = recipe["title"]
        meta = seed_meta.get(title, {})
        recipe_ingredients = _get_recipe_ingredients(recipe)
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
            pending_matched_doc_ids.append(recipe["doc_id"])
        elif len(truly_missing) <= 2:
            base["missing"] = truly_missing
            base["missing_count"] = len(truly_missing)
            # A3-3: 不再同步写统计，收集到 _pending_stats 供端点后台批量写入
            pending_missing_ingredients.extend(truly_missing)
            partial_match.append(base)

    full_match.sort(key=lambda x: x.get("match_count", 0), reverse=True)
    partial_match.sort(key=lambda x: x.get("missing_count", 0))

    return {
        "full_match": full_match[:limit],
        "partial_match": partial_match[:limit],
        "_pending_stats": {
            "matched_doc_ids": pending_matched_doc_ids,
            "missing_ingredients": pending_missing_ingredients,
        },
    }

"""每日推荐算法（M4.1）。

权重：季节 60% + 热门 30% + 随机 10%
稳定性：同一天返回同一款（用日期作随机种子）

A3-2: _seasonal_pool 与随机分支改用 batch_first_chunks 批量获取 first_chunk，
      消除每 doc 单独查 chunk 的 N+1。
"""
from __future__ import annotations

import random
from datetime import date, datetime, timezone
from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document
from hermes_kb.recipe_match import batch_first_chunks
from hermes_kb.recipe_stats import get_hot_recipes
from hermes_kb.seed_recipes import SEED_RECIPES


def _today_utc() -> date:
    """统一的 UTC 当前日期（替代 date.today() 的本地时区依赖）。

    跨时区部署（Docker 默认 UTC vs 北京时间）下保证"换日"时机一致，
    也让 daily_recipe 的随机种子可预测、可重复。
    """
    return datetime.now(timezone.utc).date()


def _current_season() -> str:
    """根据当前月份返回季节。"""
    month = _today_utc().month
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def _seasonal_pool(season: str) -> list[dict[str, Any]]:
    """获取某季节的配方池（从种子数据 + 知识库，批量化 A3-2）。"""
    seed_season: dict[str, str] = {r["title"]: r.get("season", "") for r in SEED_RECIPES}

    with get_session() as session:
        docs = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        # 先筛出当季节的 doc（基于 seed season 标签）
        seasonal_docs = [d for d in docs if seed_season.get(d.title, "") == season]

    if not seasonal_docs:
        return []

    # 批量取 first_chunk（A3-2，消除 N+1）
    doc_ids = [d.doc_id for d in seasonal_docs]
    first_chunks = batch_first_chunks(doc_ids)
    recipes: list[dict[str, Any]] = []
    for doc in seasonal_docs:
        meta = next((r for r in SEED_RECIPES if r["title"] == doc.title), {})
        first_chunk = first_chunks.get(doc.doc_id)
        recipes.append(
            {
                "title": doc.title,
                "doc_id": doc.doc_id,
                "chunk_rowid": first_chunk.id if first_chunk else None,
                "base_spirit": meta.get("base_spirit", ""),
                "difficulty": meta.get("difficulty", ""),
            }
        )
    return recipes


def daily_recipe() -> dict[str, Any] | None:
    """每日推荐：季节 60% + 热门 30% + 随机 10%。

    Returns:
        {title, doc_id, chunk_rowid, reason, base_spirit, difficulty}
        reason: "season" | "hot" | "random"
        若知识库无配方返回 None。
    """
    today_seed = int(_today_utc().toordinal())
    rng = random.Random(today_seed)

    roll = rng.random()
    season = _current_season()

    # 60% 季节池
    if roll < 0.6:
        pool = _seasonal_pool(season)
        if pool:
            choice = rng.choice(pool)
            choice["reason"] = "season"
            return choice

    # 30% 热门池
    if roll < 0.9:
        hot = get_hot_recipes(limit=10, days=30)
        if hot:
            choice = rng.choice(hot)
            return {
                "title": choice["title"],
                "doc_id": choice["doc_id"],
                "chunk_rowid": choice.get("chunk_rowid"),
                "reason": "hot",
                "base_spirit": "",
                "difficulty": "",
            }

    # 10% 全库随机（批量化 A3-2）
    with get_session() as session:
        docs = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        if not docs:
            return None
        doc = rng.choice(docs)

    # 批量取 first_chunk（A3-2，这里仅取单个 doc，但仍走批量工具统一路径）
    first_chunks = batch_first_chunks([doc.doc_id])
    first_chunk = first_chunks.get(doc.doc_id)
    meta = next((r for r in SEED_RECIPES if r["title"] == doc.title), {})
    return {
        "title": doc.title,
        "doc_id": doc.doc_id,
        "chunk_rowid": first_chunk.id if first_chunk else None,
        "reason": "random",
        "base_spirit": meta.get("base_spirit", ""),
        "difficulty": meta.get("difficulty", ""),
    }

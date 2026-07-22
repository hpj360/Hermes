"""每日推荐算法（M4.1）。

权重：季节 60% + 热门 30% + 随机 10%
稳定性：同一天返回同一款（用日期作随机种子）
"""
from __future__ import annotations

import random
from datetime import date
from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Chunk, Document
from hermes_kb.recipe_stats import get_hot_recipes
from hermes_kb.seed_recipes import SEED_RECIPES


def _current_season() -> str:
    """根据当前月份返回季节。"""
    month = date.today().month
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def _seasonal_pool(season: str) -> list[dict[str, Any]]:
    """获取某季节的配方池（从种子数据 + 知识库）。"""
    seed_season: dict[str, str] = {r["title"]: r.get("season", "") for r in SEED_RECIPES}

    recipes: list[dict[str, Any]] = []
    with get_session() as session:
        docs = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        for doc in docs:
            doc_season = seed_season.get(doc.title, "")
            if doc_season == season:
                first_chunk = session.exec(
                    select(Chunk)
                    .where(Chunk.doc_id == doc.doc_id)
                    .order_by(Chunk.idx)
                ).first()
                meta = next((r for r in SEED_RECIPES if r["title"] == doc.title), {})
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
    today_seed = int(date.today().toordinal())
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

    # 10% 全库随机
    with get_session() as session:
        docs = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        if not docs:
            return None
        doc = rng.choice(docs)
        first_chunk = session.exec(
            select(Chunk)
            .where(Chunk.doc_id == doc.doc_id)
            .order_by(Chunk.idx)
        ).first()
        meta = next((r for r in SEED_RECIPES if r["title"] == doc.title), {})
        return {
            "title": doc.title,
            "doc_id": doc.doc_id,
            "chunk_rowid": first_chunk.id if first_chunk else None,
            "reason": "random",
            "base_spirit": meta.get("base_spirit", ""),
            "difficulty": meta.get("difficulty", ""),
        }

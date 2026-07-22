"""配方使用统计（M3 运营层）。

统计时机：
- 匹配命中：/api/lab/match 返回时对 full_match + partial_match 配方 match_count +1
- 查看详情：用户点引用跳转时 view_count +1
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document, RecipeStats, Chunk


def increment_match_count(doc_id: str) -> None:
    """匹配命中时 match_count +1，weekly_match_count +1，更新 last_matched_at。"""
    with get_session() as session:
        stat = session.get(RecipeStats, doc_id)
        now = datetime.now(timezone.utc)
        if stat:
            stat.match_count += 1
            stat.weekly_match_count += 1
            stat.last_matched_at = now
        else:
            stat = RecipeStats(
                doc_id=doc_id,
                match_count=1,
                weekly_match_count=1,
                last_matched_at=now,
            )
        session.add(stat)
        session.commit()


def increment_view_count(doc_id: str) -> None:
    """查看详情时 view_count +1，更新 last_viewed_at。"""
    with get_session() as session:
        stat = session.get(RecipeStats, doc_id)
        now = datetime.now(timezone.utc)
        if stat:
            stat.view_count += 1
            stat.last_viewed_at = now
        else:
            stat = RecipeStats(
                doc_id=doc_id, view_count=1, last_viewed_at=now
            )
        session.add(stat)
        session.commit()


def get_stats(doc_id: str) -> dict[str, Any] | None:
    """查询单个配方的统计数据。"""
    with get_session() as session:
        stat = session.get(RecipeStats, doc_id)
        if not stat:
            return None
        return {
            "doc_id": stat.doc_id,
            "match_count": stat.match_count,
            "view_count": stat.view_count,
            "last_matched_at": stat.last_matched_at.isoformat()
            if stat.last_matched_at
            else None,
            "last_viewed_at": stat.last_viewed_at.isoformat()
            if stat.last_viewed_at
            else None,
        }


def get_hot_recipes(limit: int = 3, days: int = 30) -> list[dict[str, Any]]:
    """获取热门配方（按 match_count 降序，限时间范围）。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with get_session() as session:
        rows = session.exec(
            select(RecipeStats, Document)
            .join(Document, RecipeStats.doc_id == Document.doc_id)
            .where(RecipeStats.match_count > 0)
            .where(RecipeStats.last_matched_at >= cutoff)
            .order_by(RecipeStats.match_count.desc())
            .limit(limit)
        ).all()
        results: list[dict[str, Any]] = []
        for stat, doc in rows:
            first_chunk = session.exec(
                select(Chunk)
                .where(Chunk.doc_id == doc.doc_id)
                .order_by(Chunk.idx)
            ).first()
            results.append(
                {
                    "title": doc.title,
                    "doc_id": doc.doc_id,
                    "chunk_rowid": first_chunk.id if first_chunk else None,
                    "match_count": stat.match_count,
                    "last_matched_at": stat.last_matched_at.isoformat()
                    if stat.last_matched_at
                    else None,
                }
            )
        return results


def reset_weekly_stats() -> None:
    """重置所有 RecipeStats 的 weekly_match_count 为 0。

    供定时任务调用（每周一 0 点）。累计 match_count 保留不变。
    """
    with get_session() as session:
        rows = session.exec(select(RecipeStats)).all()
        for stat in rows:
            stat.weekly_match_count = 0
        session.commit()

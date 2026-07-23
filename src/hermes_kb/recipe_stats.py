"""配方使用统计（M3 运营层）。

统计时机：
- 匹配命中：/api/lab/match 返回时对 full_match + partial_match 配方 match_count +1
- 查看详情：用户点引用跳转时 view_count +1
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text as sa_text
from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document, RecipeStats


def increment_match_count(doc_id: str) -> None:
    """匹配命中时 match_count +1，weekly_match_count +1，更新 last_matched_at。

    P2-1: 用原子 SQL upsert（INSERT ... ON CONFLICT DO UPDATE）消除
    读-改-写竞态，避免并发下 lost-update。
    """
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.execute(
            sa_text(
                "INSERT INTO recipestats "
                "(doc_id, match_count, view_count, weekly_match_count, last_matched_at) "
                "VALUES (:did, 1, 0, 1, :now) "
                "ON CONFLICT(doc_id) DO UPDATE SET "
                "match_count = match_count + 1, "
                "weekly_match_count = weekly_match_count + 1, "
                "last_matched_at = :now"
            ),
            {"did": doc_id, "now": now},
        )
        session.commit()


def increment_view_count(doc_id: str) -> None:
    """查看详情时 view_count +1，更新 last_viewed_at。

    P2-1: 原子 SQL upsert。
    """
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.execute(
            sa_text(
                "INSERT INTO recipestats "
                "(doc_id, match_count, view_count, weekly_match_count, last_viewed_at) "
                "VALUES (:did, 0, 1, 0, :now) "
                "ON CONFLICT(doc_id) DO UPDATE SET "
                "view_count = view_count + 1, "
                "last_viewed_at = :now"
            ),
            {"did": doc_id, "now": now},
        )
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
    """获取热门配方（按 match_count 降序，限时间范围，批量化 A3-2）。

    单次 session 完成 join 查询；first_chunk 通过 batch_first_chunks 批量
    获取（消除每 (stat, doc) 单独查 first_chunk 的 N+1）。
    """
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

    if not rows:
        return []

    # 批量取 first_chunk（A3-2，消除 N+1）
    from hermes_kb.recipe_match import batch_first_chunks

    doc_ids = [doc.doc_id for _, doc in rows]
    first_chunks = batch_first_chunks(doc_ids)
    results: list[dict[str, Any]] = []
    for stat, doc in rows:
        first_chunk = first_chunks.get(doc.doc_id)
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


def batch_increment_match_counts(doc_ids: list[str]) -> None:
    """批量累加 match_count 和 weekly_match_count（A3-3）。

    P2-1: 用原子 SQL upsert（INSERT ... ON CONFLICT DO UPDATE SET col = col + excluded.col），
    单次事务完成，消除读-改-写竞态。同一 doc_id 出现 N 次则 +N（Counter 聚合）。
    供端点 BackgroundTasks 调用。
    """
    if not doc_ids:
        return
    from collections import Counter

    counts = Counter(doc_ids)
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.execute(
            sa_text(
                "INSERT INTO recipestats "
                "(doc_id, match_count, view_count, weekly_match_count, last_matched_at) "
                "VALUES (:did, :cnt, 0, :cnt, :now) "
                "ON CONFLICT(doc_id) DO UPDATE SET "
                "match_count = match_count + :cnt, "
                "weekly_match_count = weekly_match_count + :cnt, "
                "last_matched_at = :now"
            ),
            [
                {"did": did, "cnt": cnt, "now": now}
                for did, cnt in counts.items()
            ],
        )
        session.commit()

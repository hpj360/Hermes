"""缺材料统计（M4.1 反馈循环）。

统计时机：match_recipes 返回 partial_match 时，对每个 missing 材料计数 +1。
用途：反向优化替代关系表，高频缺失材料提示运营补充替代。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import MissingIngredientStats


def increment_missing(canonical: str) -> None:
    """缺失材料计数 +1。"""
    with get_session() as session:
        stat = session.get(MissingIngredientStats, canonical)
        now = datetime.now(timezone.utc)
        if stat:
            stat.missing_count += 1
            stat.last_missing_at = now
        else:
            stat = MissingIngredientStats(
                canonical=canonical, missing_count=1, last_missing_at=now
            )
        session.add(stat)
        session.commit()


def get_missing_stats(canonical: str) -> dict[str, Any] | None:
    """查询单个材料的缺失统计。"""
    with get_session() as session:
        stat = session.get(MissingIngredientStats, canonical)
        if not stat:
            return None
        return {
            "canonical": stat.canonical,
            "missing_count": stat.missing_count,
            "last_missing_at": stat.last_missing_at.isoformat()
            if stat.last_missing_at
            else None,
        }


def get_top_missing(limit: int = 10) -> list[dict[str, Any]]:
    """缺失材料排行（按 missing_count 降序）。"""
    with get_session() as session:
        rows = session.exec(
            select(MissingIngredientStats)
            .where(MissingIngredientStats.missing_count > 0)
            .order_by(MissingIngredientStats.missing_count.desc())
            .limit(limit)
        ).all()
        return [
            {
                "canonical": r.canonical,
                "missing_count": r.missing_count,
                "last_missing_at": r.last_missing_at.isoformat()
                if r.last_missing_at
                else None,
            }
            for r in rows
        ]


def batch_increment_missing(canonicals: list[str]) -> None:
    """批量累加 missing_count（A3-3）。

    单次事务完成，替代循环调 increment_missing。保留旧语义：同一 canonical
    在 canonicals 中出现 N 次则 +N（用 Counter 聚合，避免对同一主键多次
    INSERT 触发 UNIQUE 约束）。供端点 BackgroundTasks 调用。
    """
    if not canonicals:
        return
    from collections import Counter

    counts = Counter(canonicals)
    now = datetime.now(timezone.utc)
    with get_session() as session:
        existing = session.exec(
            select(MissingIngredientStats).where(
                MissingIngredientStats.canonical.in_(list(counts.keys()))
            )
        ).all()
        existing_map = {s.canonical: s for s in existing}
        for stat in existing:
            stat.missing_count += counts[stat.canonical]
            stat.last_missing_at = now
            session.add(stat)
        for name, cnt in counts.items():
            if name not in existing_map:
                session.add(
                    MissingIngredientStats(
                        canonical=name, missing_count=cnt, last_missing_at=now
                    )
                )
        session.commit()

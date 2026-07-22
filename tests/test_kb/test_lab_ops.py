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

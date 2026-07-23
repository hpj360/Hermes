"""IngredientSubstitute 并发写入测试（H3）。

验证 UniqueConstraint(canonical, substitute) 在并发写入下的防重 + 并发安全行为。

设计要点：
- SQLite WAL 模式 + busy_timeout=5000 串行化写入，IntegrityError 兜底并发竞态
- test 1：相同对并发插入，UniqueConstraint 保证最终仅 1 条
- test 2：不同对并发插入，全部成功
- test 3：sync_bar_assistant_substitutes 并发调用，不报错且无重复
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import IngredientSubstitute


def _insert_substitute_directly(canonical: str, substitute: str) -> bool:
    """直接插入一条替代关系，返回是否成功。

    IntegrityError（UniqueConstraint 冲突）和 OperationalError（database is locked）
    均视为失败 —— 这是并发写入下的预期行为。
    """
    try:
        with get_session() as session:
            session.add(
                IngredientSubstitute(
                    canonical=canonical, substitute=substitute, source="user"
                )
            )
            session.commit()
        return True
    except (IntegrityError, OperationalError):
        return False


def test_concurrent_insert_no_duplicates(tmp_db):
    """1. 10 个线程并发插入相同 (canonical, substitute) → 最终只有 1 条记录。

    UniqueConstraint 防重：首个线程插入成功，其余收到 IntegrityError。
    """
    canonical = "测试基酒H3"
    substitute = "测试替代H3"

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(_insert_substitute_directly, canonical, substitute)
            for _ in range(10)
        ]
        results = [f.result() for f in as_completed(futures)]

    # 至少 1 个成功（首个拿到写锁的线程）
    assert sum(results) >= 1, "至少应有一个线程成功插入"
    # UniqueConstraint 生效：不可能是全部 10 个都成功
    assert sum(results) < 10, "UniqueConstraint 未生效：全部线程都成功插入"

    # 最终表中该 (canonical, substitute) 只有 1 条记录
    with get_session() as session:
        rows = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.canonical == canonical,
                IngredientSubstitute.substitute == substitute,
            )
        ).all()
        assert len(rows) == 1, (
            f"期望 1 条记录，实际 {len(rows)} 条（UniqueConstraint 防重失效）"
        )


def test_concurrent_insert_different_pairs(tmp_db):
    """2. 10 个线程并发插入不同 (canonical, substitute) → 全部成功写入。"""
    pairs = [(f"基酒H3_{i}", f"替代H3_{i}") for i in range(10)]

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(_insert_substitute_directly, c, s)
            for c, s in pairs
        ]
        results = [f.result() for f in as_completed(futures)]

    # 全部成功（不同对之间无 UniqueConstraint 冲突）
    assert all(results), f"部分线程失败：{results}"
    assert sum(results) == 10

    # 表中有 10 条记录
    with get_session() as session:
        rows = session.exec(select(IngredientSubstitute)).all()
        assert len(rows) == 10, f"期望 10 条记录，实际 {len(rows)} 条"

        # 每条记录的 (canonical, substitute) 对唯一
        pair_set = {(r.canonical, r.substitute) for r in rows}
        assert len(pair_set) == 10, "存在重复的 (canonical, substitute) 对"


def test_bar_assistant_sync_concurrent(tmp_db):
    """3. 并发调用 sync_bar_assistant_substitutes 两次（相同数据）→ 不报错且最终无重复。"""
    from hermes_kb.bar_assistant_sync import sync_bar_assistant_substitutes

    data = [
        {"canonical": "金酒", "substitute": "伏特加"},
        {"canonical": "威士忌", "substitute": "波本"},
        {"canonical": "朗姆酒", "substitute": "黑朗姆酒"},
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(sync_bar_assistant_substitutes, data)
        f2 = executor.submit(sync_bar_assistant_substitutes, data)
        r1 = f1.result()
        r2 = f2.result()

    # 不报错（返回 dict 而非抛异常）
    assert isinstance(r1, dict), f"调用 1 抛异常或返回非 dict: {r1}"
    assert isinstance(r2, dict), f"调用 2 抛异常或返回非 dict: {r2}"

    # 总导入数 = 3（每条数据只成功导入一次，UniqueConstraint 防重）
    total_imported = r1["imported"] + r2["imported"]
    assert total_imported == 3, (
        f"期望总导入 3 条，实际 {total_imported}（r1={r1}, r2={r2}）"
    )

    # 最终无重复：3 条唯一记录
    with get_session() as session:
        rows = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.source == "bar_assistant"
            )
        ).all()
        assert len(rows) == 3, f"期望 3 条记录，实际 {len(rows)} 条"

        # (canonical, substitute) 对无重复
        pairs = [(r.canonical, r.substitute) for r in rows]
        assert len(set(pairs)) == 3, f"存在重复对: {pairs}"

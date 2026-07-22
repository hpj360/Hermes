"""三层替代关系表（L1 预置 + L2 用户自定义 + L3 预留）。

- L1: 预置 IBA 替代关系（本文件常量）
- L2: 用户自定义（持久化到 SQLite ingredient_substitutes 表）
- L3: 外部同步（M4 远期，接口预留）
"""
from __future__ import annotations

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import IngredientSubstitute

# L1: 预置 IBA 替代关系
SUBSTITUTES_PRESET: dict[str, list[str]] = {
    "君度": ["干库拉索", "橙味力娇酒"],
    "青柠汁": ["柠檬汁"],
    "糖浆": ["蜂蜜糖浆", "白糖水"],
    "汤力水": ["苏打水"],
    "金巴利": ["Aperol"],
    "樱桃": ["酒渍樱桃"],
    "苦精": ["橙味苦精"],
    "蔓越莓汁": ["红莓汁"],
}


def get_substitutes_preset(canonical: str) -> list[str]:
    """查询 L1 预置替代关系。"""
    return SUBSTITUTES_PRESET.get(canonical, [])


def get_substitutes(canonical: str) -> list[str]:
    """合并查询 L1 + L2 替代关系。"""
    result = list(get_substitutes_preset(canonical))
    with get_session() as session:
        rows = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.canonical == canonical
            )
        ).all()
        for row in rows:
            if row.substitute not in result:
                result.append(row.substitute)
    return result


def add_user_substitute(canonical: str, substitute: str) -> None:
    """添加 L2 用户自定义替代关系。"""
    canonical = canonical.strip()
    substitute = substitute.strip()
    if not canonical or not substitute:
        return
    with get_session() as session:
        existing = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.canonical == canonical,
                IngredientSubstitute.substitute == substitute,
            )
        ).first()
        if existing:
            return
        session.add(
            IngredientSubstitute(
                canonical=canonical, substitute=substitute, source="user"
            )
        )
        session.commit()


def remove_user_substitute(canonical: str, substitute: str) -> None:
    """删除 L2 用户自定义替代（仅删 source='user'）。"""
    with get_session() as session:
        rows = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.canonical == canonical,
                IngredientSubstitute.substitute == substitute,
                IngredientSubstitute.source == "user",
            )
        ).all()
        for row in rows:
            session.delete(row)
        session.commit()


def list_all_substitutes() -> dict[str, list[str]]:
    """列出所有材料的替代关系（L1+L2 合并）。用于运营看板覆盖率统计。"""
    all_subs: dict[str, set[str]] = {}
    for canon, subs in SUBSTITUTES_PRESET.items():
        all_subs.setdefault(canon, set()).update(subs)
    with get_session() as session:
        rows = session.exec(select(IngredientSubstitute)).all()
        for row in rows:
            all_subs.setdefault(row.canonical, set()).add(row.substitute)
    return {k: sorted(v) for k, v in all_subs.items()}

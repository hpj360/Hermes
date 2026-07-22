"""三层替代关系表（L1 预置 + L2 用户自定义 + L3 预留）。

- L1: 预置 IBA 替代关系（本文件常量）
- L2: 用户自定义（持久化到 SQLite ingredient_substitutes 表）
- L3: 外部同步（M4 远期，接口预留）
"""
from __future__ import annotations

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import IngredientSubstitute

# L1: 预置替代关系（扩充版，B4：基于 bar-assistant 开源数据集）
SUBSTITUTES_PRESET: dict[str, list[str]] = {
    # === 基酒互替 ===
    "金酒": ["伏特加", "杜松子酒"],
    "伏特加": ["金酒"],
    "威士忌": ["波本", "黑麦威士忌", "苏格兰威士忌"],
    "朗姆酒": ["黑朗姆酒", "白朗姆酒", "陈年朗姆酒"],
    "龙舌兰": ["梅斯卡尔"],
    "白兰地": ["干邑", "雅文邑"],
    # === 辅料 ===
    "味美思": ["干味美思", "甜味美思"],
    "干味美思": ["味美思"],
    "甜味美思": ["味美思"],
    "君度": ["干库拉索", "橙味力娇酒", "triple sec"],
    "金巴利": ["Aperol", "Campari"],
    "苦精": ["橙味苦精", "安高天娜苦精"],
    "糖浆": ["蜂蜜糖浆", "白糖水", "龙舌兰糖浆"],
    "蜂蜜糖浆": ["糖浆", "蜂蜜"],
    "汤力水": ["苏打水"],
    "苏打水": ["汤力水", "气泡水"],
    "干库拉索": ["君度", "橙味力娇酒"],
    "橙味力娇酒": ["君度", "干库拉索"],
    "咖啡利口酒": ["甘露咖啡利口酒", "Kahlua"],
    "甘露咖啡利口酒": ["咖啡利口酒"],
    "椰子利口酒": ["马利宝"],
    "杏仁糖浆": ["Orgeat", "杏仁糖浆"],
    "黑莓利口酒": ["Creme de Mure"],
    "薄荷利口酒": ["绿薄荷利口酒", "Creme de Menthe"],
    # === 果汁 ===
    "青柠汁": ["柠檬汁"],
    "柠檬汁": ["青柠汁"],
    "橙汁": ["血橙汁", "橘子汁"],
    "蔓越莓汁": ["红莓汁"],
    "菠萝汁": ["芒果汁"],
    "番茄汁": ["蔬菜汁"],
    "葡萄柚汁": ["西柚汁"],
    # === 装饰 ===
    "樱桃": ["酒渍樱桃", "蜜饯樱桃"],
    "橄榄": ["珍珠洋葱"],
    "薄荷叶": ["薄荷枝"],
    "柠檬片": ["青柠片"],
    "青柠片": ["柠檬片"],
    "橙皮": ["柠檬皮", "西柚皮"],
    "柠檬皮": ["橙皮"],
    # === 其他 ===
    "蛋白": ["鹰嘴豆水"],
    "奶油": ["椰奶", "淡奶"],
    "姜汁啤酒": ["姜汁汽水"],
    "姜汁汽水": ["姜汁啤酒"],
    "红葡萄酒": ["白葡萄酒"],
    "白葡萄酒": ["红葡萄酒"],
    "香槟": ["起泡酒", "Prosecco"],
    "起泡酒": ["香槟", "Prosecco"],
    "咖啡": ["浓缩咖啡"],
    "牛奶": ["燕麦奶", "杏仁奶"],
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

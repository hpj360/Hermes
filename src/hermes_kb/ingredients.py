"""材料注册表 + 别名归一化。

4 大类：
- base_spirit 基酒（金酒/威士忌/朗姆/龙舌兰/白兰地/伏特加）
- modifier 辅料（味美思/苦精/糖浆/君度/利口酒/汤力水/苏打水）
- juice 果汁（柠檬汁/青柠汁/橙汁/蔓越莓汁/菠萝汁）
- garnish 装饰（橄榄/柠檬片/薄荷叶/樱桃/橙皮）
"""
from __future__ import annotations

INGREDIENT_REGISTRY: dict[str, dict] = {
    # === 基酒 ===
    "gin": {
        "canonical": "金酒",
        "aliases": ["gin", "dry gin", "london dry", "杜松子酒", "gordon's", "gordon"],
        "category": "base_spirit",
    },
    "whiskey": {
        "canonical": "威士忌",
        "aliases": ["whiskey", "whisky", "scotch", "bourbon", "rye", "威士忌"],
        "category": "base_spirit",
    },
    "rum": {
        "canonical": "朗姆酒",
        "aliases": ["rum", "white rum", "dark rum", "朗姆", "朗姆酒"],
        "category": "base_spirit",
    },
    "tequila": {
        "canonical": "龙舌兰",
        "aliases": ["tequila", "龙舌兰"],
        "category": "base_spirit",
    },
    "brandy": {
        "canonical": "白兰地",
        "aliases": ["brandy", "cognac", "白兰地", "干邑"],
        "category": "base_spirit",
    },
    "vodka": {
        "canonical": "伏特加",
        "aliases": ["vodka", "伏特加"],
        "category": "base_spirit",
    },
    # === 辅料 ===
    "vermouth": {
        "canonical": "味美思",
        "aliases": ["vermouth", "dry vermouth", "sweet vermouth", "味美思", "苦艾酒"],
        "category": "modifier",
    },
    "campari": {
        "canonical": "金巴利",
        "aliases": ["campari", "金巴利"],
        "category": "modifier",
    },
    "sugar_syrup": {
        "canonical": "糖浆",
        "aliases": ["sugar syrup", "simple syrup", "syrup", "糖浆", "糖水"],
        "category": "modifier",
    },
    "cointreau": {
        "canonical": "君度",
        "aliases": ["cointreau", "triple sec", "橙味力娇酒", "君度"],
        "category": "modifier",
    },
    "angostura": {
        "canonical": "苦精",
        "aliases": ["angostura", "bitters", "苦精", "安高天娜"],
        "category": "modifier",
    },
    "tonic": {
        "canonical": "汤力水",
        "aliases": ["tonic", "tonic water", "汤力水"],
        "category": "modifier",
    },
    "soda": {
        "canonical": "苏打水",
        "aliases": ["soda", "soda water", "苏打水", "气泡水"],
        "category": "modifier",
    },
    "cola": {
        "canonical": "可乐",
        "aliases": ["cola", "coke", "可乐"],
        "category": "modifier",
    },
    "ginger_beer": {
        "canonical": "姜啤",
        "aliases": ["ginger beer", "姜啤"],
        "category": "modifier",
    },
    # === 果汁 ===
    "lemon_juice": {
        "canonical": "柠檬汁",
        "aliases": ["lemon juice", "柠檬汁"],
        "category": "juice",
    },
    "lime_juice": {
        "canonical": "青柠汁",
        "aliases": ["lime juice", "青柠汁", "莱姆汁"],
        "category": "juice",
    },
    "orange_juice": {
        "canonical": "橙汁",
        "aliases": ["orange juice", "橙汁", "橘子汁"],
        "category": "juice",
    },
    "cranberry_juice": {
        "canonical": "蔓越莓汁",
        "aliases": ["cranberry juice", "蔓越莓汁"],
        "category": "juice",
    },
    "pineapple_juice": {
        "canonical": "菠萝汁",
        "aliases": ["pineapple juice", "菠萝汁"],
        "category": "juice",
    },
    "tomato_juice": {
        "canonical": "番茄汁",
        "aliases": ["tomato juice", "番茄汁"],
        "category": "juice",
    },
    # === 装饰 ===
    "olive": {
        "canonical": "橄榄",
        "aliases": ["olive", "橄榄"],
        "category": "garnish",
    },
    "lemon_slice": {
        "canonical": "柠檬片",
        "aliases": ["lemon slice", "lemon", "柠檬片", "柠檬"],
        "category": "garnish",
    },
    "mint": {
        "canonical": "薄荷叶",
        "aliases": ["mint", "mint leaves", "薄荷叶", "薄荷"],
        "category": "garnish",
    },
    "cherry": {
        "canonical": "樱桃",
        "aliases": ["cherry", "maraschino cherry", "樱桃"],
        "category": "garnish",
    },
    "orange_peel": {
        "canonical": "橙皮",
        "aliases": ["orange peel", "橙皮"],
        "category": "garnish",
    },
}

# 反向索引：alias(小写) → canonical
_ALIAS_INDEX: dict[str, str] = {}
for _key, _info in INGREDIENT_REGISTRY.items():
    _canon = _info["canonical"]
    # 标准名本身也加入索引
    _ALIAS_INDEX[_canon.lower()] = _canon
    for _alias in _info["aliases"]:
        _ALIAS_INDEX[_alias.lower()] = _canon


def canonicalize(name: str) -> str:
    """将别名归一化为标准名。未知材料返回原值。"""
    if not name:
        return name
    return _ALIAS_INDEX.get(name.strip().lower(), name.strip())


def get_category(canonical: str) -> str | None:
    """根据标准名获取分类。"""
    for _info in INGREDIENT_REGISTRY.values():
        if _info["canonical"] == canonical:
            return _info["category"]
    return None


def list_by_category(category: str) -> list[str]:
    """列出某分类下所有材料标准名。"""
    return [
        info["canonical"]
        for info in INGREDIENT_REGISTRY.values()
        if info["category"] == category
    ]


def all_canonical() -> list[str]:
    """列出所有材料标准名。"""
    return [info["canonical"] for info in INGREDIENT_REGISTRY.values()]

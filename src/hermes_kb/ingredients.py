"""材料注册表 + 别名归一化。

类别：
- base_spirit 基酒（金酒/威士忌/朗姆/龙舌兰/白兰地/伏特加 等）
- modifier 辅料（味美思/苦精/糖浆/君度/利口酒/汤力水/苏打水 等）
- juice 果汁（柠檬汁/青柠汁/橙汁/蔓越莓汁/菠萝汁）
- wine 葡萄酒与起泡酒（香槟/普罗塞克/红葡萄酒/波特酒）
- garnish 装饰（橄榄/柠檬片/薄荷叶/樱桃/橙皮）

每条材料携带：
- canonical: 中文标准名
- aliases: 英文 + 中文同义词列表
- category: 上述分类之一
- abv: 酒精度小数（0.0-1.0），非酒精材料为 0.0
- brands: 常见品牌列表（可为空）
"""
from __future__ import annotations

INGREDIENT_REGISTRY: dict[str, dict] = {
    # === 基酒 ===
    "gin": {
        "canonical": "金酒",
        "aliases": ["gin", "dry gin", "london dry", "杜松子酒", "gordon's", "gordon"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": ["Gordon's", "Tanqueray", "Beefeater", "Bombay"],
    },
    "whiskey": {
        "canonical": "威士忌",
        "aliases": ["whiskey", "whisky", "威士忌"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": ["Johnnie Walker", "Glenfiddich", "Jim Beam", "Macallan"],
    },
    "rum": {
        "canonical": "朗姆酒",
        "aliases": ["rum", "朗姆", "朗姆酒"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": ["Bacardi", "Havana Club", "Captain Morgan"],
    },
    "tequila": {
        "canonical": "龙舌兰",
        "aliases": ["tequila", "龙舌兰"],
        "category": "base_spirit",
        "abv": 0.38,
        "brands": ["Patrón", "Jose Cuervo", "Don Julio"],
    },
    "brandy": {
        "canonical": "白兰地",
        "aliases": ["brandy", "白兰地", "干邑"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": ["Hennessy", "Rémy Martin", "Martell"],
    },
    "vodka": {
        "canonical": "伏特加",
        "aliases": ["vodka", "伏特加"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": ["Absolut", "Grey Goose", "Smirnoff", "Stolichnaya"],
    },
    # === 辅料 ===
    "vermouth": {
        "canonical": "味美思",
        "aliases": ["vermouth", "dry vermouth", "sweet vermouth", "味美思", "苦艾酒"],
        "category": "modifier",
        "abv": 0.18,
        "brands": ["Martini", "Noilly Prat", "Cinzano"],
    },
    "campari": {
        "canonical": "金巴利",
        "aliases": ["campari", "金巴利"],
        "category": "modifier",
        "abv": 0.25,
        "brands": ["Campari"],
    },
    "sugar_syrup": {
        "canonical": "糖浆",
        "aliases": ["sugar syrup", "simple syrup", "syrup", "糖浆", "糖水"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "cointreau": {
        "canonical": "君度",
        "aliases": ["cointreau", "橙味力娇酒", "君度"],
        "category": "modifier",
        "abv": 0.40,
        "brands": ["Cointreau"],
    },
    "angostura": {
        "canonical": "苦精",
        "aliases": ["angostura", "bitters", "苦精", "安高天娜"],
        "category": "modifier",
        "abv": 0.44,
        "brands": ["Angostura"],
    },
    "tonic": {
        "canonical": "汤力水",
        "aliases": ["tonic", "tonic water", "汤力水"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "soda": {
        "canonical": "苏打水",
        "aliases": ["soda", "soda water", "苏打水", "气泡水"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "cola": {
        "canonical": "可乐",
        "aliases": ["cola", "coke", "可乐"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "ginger_beer": {
        "canonical": "姜啤",
        "aliases": ["ginger beer", "姜啤"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    # === 果汁 ===
    "lemon_juice": {
        "canonical": "柠檬汁",
        "aliases": ["lemon juice", "柠檬汁"],
        "category": "juice",
        "abv": 0.0,
        "brands": [],
    },
    "lime_juice": {
        "canonical": "青柠汁",
        "aliases": ["lime juice", "青柠汁", "莱姆汁"],
        "category": "juice",
        "abv": 0.0,
        "brands": [],
    },
    "orange_juice": {
        "canonical": "橙汁",
        "aliases": ["orange juice", "橙汁", "橘子汁"],
        "category": "juice",
        "abv": 0.0,
        "brands": [],
    },
    "cranberry_juice": {
        "canonical": "蔓越莓汁",
        "aliases": ["cranberry juice", "蔓越莓汁"],
        "category": "juice",
        "abv": 0.0,
        "brands": [],
    },
    "pineapple_juice": {
        "canonical": "菠萝汁",
        "aliases": ["pineapple juice", "菠萝汁"],
        "category": "juice",
        "abv": 0.0,
        "brands": [],
    },
    "tomato_juice": {
        "canonical": "番茄汁",
        "aliases": ["tomato juice", "番茄汁"],
        "category": "juice",
        "abv": 0.0,
        "brands": [],
    },
    # === 装饰 ===
    "olive": {
        "canonical": "橄榄",
        "aliases": ["olive", "橄榄"],
        "category": "garnish",
        "abv": 0.0,
        "brands": [],
    },
    "lemon_slice": {
        "canonical": "柠檬片",
        "aliases": ["lemon slice", "lemon", "柠檬片", "柠檬"],
        "category": "garnish",
        "abv": 0.0,
        "brands": [],
    },
    "mint": {
        "canonical": "薄荷叶",
        "aliases": ["mint", "mint leaves", "薄荷叶", "薄荷"],
        "category": "garnish",
        "abv": 0.0,
        "brands": [],
    },
    "cherry": {
        "canonical": "樱桃",
        "aliases": ["cherry", "maraschino cherry", "樱桃"],
        "category": "garnish",
        "abv": 0.0,
        "brands": [],
    },
    "orange_peel": {
        "canonical": "橙皮",
        "aliases": ["orange peel", "橙皮"],
        "category": "garnish",
        "abv": 0.0,
        "brands": [],
    },
    # === 扩展：烈酒类 ===
    "absinthe": {
        "canonical": "苦艾烈酒",
        "aliases": ["absinthe", "绿魔", "苦艾烈酒"],
        "category": "base_spirit",
        "abv": 0.55,
        "brands": [],
    },
    "bourbon": {
        "canonical": "波本威士忌",
        "aliases": ["bourbon", "bourbon whiskey", "波本", "波本威士忌"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": [],
    },
    "cognac": {
        "canonical": "干邑白兰地",
        "aliases": ["cognac", "cognac brandy", "干邑白兰地", "法国白兰地"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": [],
    },
    "irish_whiskey": {
        "canonical": "爱尔兰威士忌",
        "aliases": ["irish whiskey", "爱尔兰威士忌"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": [],
    },
    "rye_whiskey": {
        "canonical": "黑麦威士忌",
        "aliases": ["rye", "rye whiskey", "rye whisky", "黑麦威士忌"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": [],
    },
    "scotch": {
        "canonical": "苏格兰威士忌",
        "aliases": ["scotch", "scotch whisky", "scottish whisky", "苏格兰威士忌"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": [],
    },
    "pisco": {
        "canonical": "皮斯科",
        "aliases": ["pisco", "皮斯科", "秘鲁烈酒"],
        "category": "base_spirit",
        "abv": 0.38,
        "brands": [],
    },
    "aquavit": {
        "canonical": "阿夸维特",
        "aliases": ["aquavit", "akvavit", "阿夸维特"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": [],
    },
    "dark_rum": {
        "canonical": "黑朗姆酒",
        "aliases": ["dark rum", "黑朗姆", "黑朗姆酒", "dark rum liqueur"],
        "category": "base_spirit",
        "abv": 0.43,
        "brands": [],
    },
    "white_rum": {
        "canonical": "白朗姆酒",
        "aliases": ["white rum", "白朗姆", "白朗姆酒", "light rum"],
        "category": "base_spirit",
        "abv": 0.40,
        "brands": [],
    },
    "aged_rum": {
        "canonical": "陈年朗姆酒",
        "aliases": ["aged rum", "anejo rum", "陈年朗姆酒"],
        "category": "base_spirit",
        "abv": 0.43,
        "brands": [],
    },
    # === 扩展：利口酒类 ===
    "amaretto": {
        "canonical": "苦杏仁酒",
        "aliases": ["amaretto", "苦杏仁酒", "杏仁力娇酒"],
        "category": "modifier",
        "abv": 0.28,
        "brands": ["Disaronno"],
    },
    "baileys": {
        "canonical": "百利甜酒",
        "aliases": ["baileys", "irish cream", "百利甜酒", "百利"],
        "category": "modifier",
        "abv": 0.17,
        "brands": ["Baileys"],
    },
    "chambord": {
        "canonical": "香波力娇酒",
        "aliases": ["chambord", "香波力娇酒", "chambord liqueur"],
        "category": "modifier",
        "abv": 0.16,
        "brands": [],
    },
    "coffee_liqueur": {
        "canonical": "咖啡力娇酒",
        "aliases": ["coffee liqueur", "咖啡力娇酒", "咖啡酒"],
        "category": "modifier",
        "abv": 0.20,
        "brands": ["Kahlúa", "Tia Maria"],
    },
    "grand_marnier": {
        "canonical": "柑曼怡",
        "aliases": ["grand marnier", "柑曼怡", "grand marnier liqueur"],
        "category": "modifier",
        "abv": 0.40,
        "brands": [],
    },
    "galliano": {
        "canonical": "加利亚诺",
        "aliases": ["galliano", "加利亚诺", "galliano liqueur"],
        "category": "modifier",
        "abv": 0.30,
        "brands": [],
    },
    "midori": {
        "canonical": "蜜瓜力娇酒",
        "aliases": ["midori", "蜜瓜力娇酒", "melon liqueur"],
        "category": "modifier",
        "abv": 0.20,
        "brands": [],
    },
    "blue_curacao": {
        "canonical": "蓝柑香酒",
        "aliases": ["blue curacao", "blue curaçao", "蓝柑香酒", "蓝橙力娇酒"],
        "category": "modifier",
        "abv": 0.21,
        "brands": [],
    },
    "creme_de_cacao": {
        "canonical": "可可力娇酒",
        "aliases": ["creme de cacao", "crème de cacao", "可可力娇酒", "可可甜酒"],
        "category": "modifier",
        "abv": 0.25,
        "brands": [],
    },
    "creme_de_cassis": {
        "canonical": "黑加仑力娇酒",
        "aliases": ["creme de cassis", "crème de cassis", "黑加仑力娇酒", "黑醋栗酒"],
        "category": "modifier",
        "abv": 0.20,
        "brands": [],
    },
    "creme_de_menthe": {
        "canonical": "薄荷力娇酒",
        "aliases": ["creme de menthe", "crème de menthe", "薄荷力娇酒", "薄荷甜酒"],
        "category": "modifier",
        "abv": 0.25,
        "brands": [],
    },
    "triple_sec": {
        "canonical": "白橙力娇酒",
        "aliases": ["triple sec", "triple sec liqueur", "白橙力娇酒", "三秒酒"],
        "category": "modifier",
        "abv": 0.30,
        "brands": [],
    },
    "peach_schnapps": {
        "canonical": "蜜桃香甜酒",
        "aliases": ["peach schnapps", "蜜桃香甜酒", "peach liqueur"],
        "category": "modifier",
        "abv": 0.20,
        "brands": [],
    },
    "apricot_brandy": {
        "canonical": "杏子白兰地",
        "aliases": ["apricot brandy", "杏子白兰地", "apricot liqueur"],
        "category": "modifier",
        "abv": 0.30,
        "brands": [],
    },
    "maraschino_liqueur": {
        "canonical": "樱桃力娇酒",
        "aliases": ["maraschino liqueur", "maraschino", "樱桃力娇酒"],
        "category": "modifier",
        "abv": 0.32,
        "brands": [],
    },
    # === 扩展：葡萄酒 / 起泡酒 ===
    "champagne": {
        "canonical": "香槟",
        "aliases": ["champagne", "香槟", "champagne wine"],
        "category": "wine",
        "abv": 0.12,
        "brands": [],
    },
    "prosecco": {
        "canonical": "普罗塞克",
        "aliases": ["prosecco", "普罗塞克", "起泡酒"],
        "category": "wine",
        "abv": 0.11,
        "brands": [],
    },
    "red_wine": {
        "canonical": "红葡萄酒",
        "aliases": ["red wine", "红葡萄酒", "红酒"],
        "category": "wine",
        "abv": 0.13,
        "brands": [],
    },
    "port_wine": {
        "canonical": "波特酒",
        "aliases": ["port wine", "port", "波特酒", "portwine"],
        "category": "wine",
        "abv": 0.20,
        "brands": [],
    },
    # === 扩展：其他辅料 ===
    "dry_vermouth": {
        "canonical": "干味美思",
        "aliases": ["extra dry vermouth", "干味美思"],
        "category": "modifier",
        "abv": 0.18,
        "brands": [],
    },
    "sweet_vermouth": {
        "canonical": "甜味美思",
        "aliases": ["sweet vermouth rouge", "甜味美思"],
        "category": "modifier",
        "abv": 0.20,
        "brands": [],
    },
    "orange_bitters": {
        "canonical": "橙味苦精",
        "aliases": ["orange bitters", "橙味苦精"],
        "category": "modifier",
        "abv": 0.28,
        "brands": [],
    },
    "egg_white": {
        "canonical": "蛋清",
        "aliases": ["egg white", "蛋清", "蛋白"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "cream": {
        "canonical": "奶油",
        "aliases": ["cream", "奶油", "鲜奶油"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "espresso": {
        "canonical": "浓缩咖啡",
        "aliases": ["espresso", "浓缩咖啡", "espresso coffee"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "grenadine": {
        "canonical": "红石榴糖浆",
        "aliases": ["grenadine", "红石榴糖浆", "石榴糖浆"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "honey_syrup": {
        "canonical": "蜂蜜糖浆",
        "aliases": ["honey syrup", "蜂蜜糖浆", "蜜糖浆"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "agave_syrup": {
        "canonical": "龙舌兰糖浆",
        "aliases": ["agave syrup", "agave nectar", "龙舌兰糖浆"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
    },
    "coconut_cream": {
        "canonical": "椰奶油",
        "aliases": ["coconut cream", "椰奶油", "椰浆"],
        "category": "modifier",
        "abv": 0.0,
        "brands": [],
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


def get_abv(canonical: str) -> float:
    """根据标准名获取 ABV（0.0-1.0）。未知材料返回 0.0。"""
    for _info in INGREDIENT_REGISTRY.values():
        if _info["canonical"] == canonical:
            return _info.get("abv", 0.0)
    return 0.0


def get_brands(canonical: str) -> list[str]:
    """根据标准名获取常见品牌列表。未知材料返回空列表。"""
    for _info in INGREDIENT_REGISTRY.values():
        if _info["canonical"] == canonical:
            return list(_info.get("brands", []))
    return []

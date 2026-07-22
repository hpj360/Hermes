"""TheCocktailDB 数据源同步器（B2）。

免费开源 API：https://www.thecocktaildb.com/api.php
测试 Key "1" 可用，生产环境建议购买 Premium Key（$10 终身）。

增强点（B2）：
- 全量拉取（遍历 a-z + 0-9 首字母）
- 保存图片 URL（strDrinkThumb → Document.image_url）
- 归一化失败保留英文原名（不丢弃）
- 材料名映射表 80+
"""
from __future__ import annotations

from typing import Any

import httpx
from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.ingredients import canonicalize
from hermes_kb.models import Document
from hermes_kb.rag import ImportService

# TheCocktailDB 英文材料名 → 中文标准名映射（80+）
_INGREDIENT_OVERRIDES: dict[str, str] = {
    # 基酒
    "light rum": "朗姆酒",
    "dark rum": "朗姆酒",
    "white rum": "朗姆酒",
    "spiced rum": "朗姆酒",
    "bacardi": "朗姆酒",
    "gin": "金酒",
    "vodka": "伏特加",
    "tequila": "龙舌兰",
    "whiskey": "威士忌",
    "whisky": "威士忌",
    "bourbon": "威士忌",
    "scotch": "威士忌",
    "irish whiskey": "威士忌",
    "blended whiskey": "威士忌",
    "brandy": "白兰地",
    "cognac": "白兰地",
    "armagnac": "白兰地",
    # 辅料
    "vermouth": "味美思",
    "sweet vermouth": "味美思",
    "dry vermouth": "味美思",
    "rosso vermouth": "味美思",
    "campari": "金巴利",
    "aperol": "Aperol",
    "triple sec": "君度",
    "cointreau": "君度",
    "grand marnier": "君度",
    "blue curacao": "蓝橙力娇酒",
    "cherry liqueur": "樱桃利口酒",
    "maraschino liqueur": "樱桃利口酒",
    "coffee liqueur": "咖啡利口酒",
    "kahlua": "甘露咖啡利口酒",
    "tia maria": "咖啡利口酒",
    "amaretto": "杏仁利口酒",
    "baileys": "百利甜",
    "irish cream": "百利甜",
    "creme de cacao": "可可利口酒",
    "creme de menthe": "薄荷利口酒",
    "green creme de menthe": "薄荷利口酒",
    "white creme de menthe": "薄荷利口酒",
    "creme de cassis": "黑加仑利口酒",
    "creme de mure": "黑莓利口酒",
    "midori": "哈密瓜利口酒",
    "malibu": "椰子利口酒",
    "coconut liqueur": "椰子利口酒",
    "drambuie": "威士忌利口酒",
    "benedictine": "本笃利口酒",
    "chartreuse": "查特酒",
    "green chartreuse": "查特酒",
    "yellow chartreuse": "查特酒",
    "galliano": "加利亚诺",
    "sambuca": "桑布卡",
    "ouzo": "茴香酒",
    "absinthe": "苦艾酒",
    "pernod": "茴香酒",
    "ricard": "茴香酒",
    "angostura bitters": "苦精",
    "orange bitters": "橙味苦精",
    "peychaud's bitters": "苦精",
    "bitters": "苦精",
    # 糖浆
    "sugar syrup": "糖浆",
    "simple syrup": "糖浆",
    "grenadine": "石榴糖浆",
    "honey syrup": "蜂蜜糖浆",
    "agave syrup": "龙舌兰糖浆",
    "orgeat": "杏仁糖浆",
    "almond syrup": "杏仁糖浆",
    # 碳酸饮料
    "soda water": "苏打水",
    "club soda": "苏打水",
    "carbonated water": "苏打水",
    "tonic water": "汤力水",
    "ginger beer": "姜汁啤酒",
    "ginger ale": "姜汁汽水",
    "cola": "可乐",
    "lemon-lime soda": "雪碧",
    "7-up": "雪碧",
    "sprite": "雪碧",
    "red bull": "能量饮料",
    # 果汁
    "lime juice": "青柠汁",
    "lime": "青柠汁",
    "lemon juice": "柠檬汁",
    "lemon": "柠檬汁",
    "orange juice": "橙汁",
    "cranberry juice": "蔓越莓汁",
    "pineapple juice": "菠萝汁",
    "grapefruit juice": "葡萄柚汁",
    "tomato juice": "番茄汁",
    "pomegranate juice": "石榴汁",
    "apple juice": "苹果汁",
    # 装饰
    "mint": "薄荷叶",
    "mint leaves": "薄荷叶",
    "olive": "橄榄",
    "cocktail onion": "珍珠洋葱",
    "cherry": "樱桃",
    "maraschino cherry": "樱桃",
    "orange": "橙皮",
    "orange peel": "橙皮",
    "lemon peel": "柠檬皮",
    "lemon twist": "柠檬皮",
    "lime peel": "青柠皮",
    "lime wedge": "青柠片",
    "lemon wedge": "柠檬片",
    "orange slice": "橙片",
    "pineapple": "菠萝",
    # 其他
    "sugar": "糖浆",
    "cream": "奶油",
    "heavy cream": "奶油",
    "milk": "牛奶",
    "coconut milk": "椰奶",
    "coconut cream": "椰浆",
    "egg white": "蛋白",
    "egg": "鸡蛋",
    "whole egg": "鸡蛋",
    "honey": "蜂蜜",
    "coffee": "咖啡",
    "espresso": "浓缩咖啡",
    "hot coffee": "咖啡",
    "chocolate": "巧克力",
    "chocolate syrup": "巧克力糖浆",
    "cocoa powder": "可可粉",
    "nutmeg": "肉豆蔻",
    "cinnamon": "肉桂",
    "salt": "盐",
    "black pepper": "黑胡椒",
    "tabasco": "辣椒酱",
    "worcestershire sauce": "伍斯特酱",
    "wine": "葡萄酒",
    "red wine": "红葡萄酒",
    "white wine": "白葡萄酒",
    "port wine": "波特酒",
    "sherry": "雪莉酒",
    "champagne": "香槟",
    "prosecco": "起泡酒",
    "sparkling wine": "起泡酒",
    "beer": "啤酒",
    "stout": "黑啤",
    "ale": "艾尔",
}

API_BASE = "https://www.thecocktaildb.com/api/json/v1/1"
API_KEY = "1"  # 测试 Key，免费


def normalize_ingredient(en_name: str) -> str | None:
    """英文材料名 → 中文标准名。

    先查 _INGREDIENT_OVERRIDES，再查 ingredients.canonicalize。
    返回 None 表示无法归一化。

    注意：canonicalize 在未命中时返回原值（保留大小写、仅 strip），
    故此处用大小写不敏感比较判定是否命中，避免把未知材料误判为已归一化。
    """
    if not en_name:
        return None
    key = en_name.strip().lower()
    if not key:
        return None
    if key in _INGREDIENT_OVERRIDES:
        return _INGREDIENT_OVERRIDES[key]
    result = canonicalize(en_name)
    # canonicalize 未命中时返回 strip 后的原值；命中时返回中文标准名。
    if result and result.strip().lower() != key:
        return result
    return None


def parse_recipe(api_data: dict[str, Any]) -> dict[str, Any]:
    """解析 TheCocktailDB 单条 API 响应为配方 dict。"""
    source_id = api_data.get("idDrink", "")
    title = api_data.get("strDrink", "")
    instructions = api_data.get("strInstructions", "")
    image_url = api_data.get("strDrinkThumb") or None

    ingredients: list[str] = []
    measures: list[str] = []
    unknown: list[str] = []

    for i in range(1, 16):
        ing = api_data.get(f"strIngredient{i}")
        measure = api_data.get(f"strMeasure{i}", "")
        if not ing:
            break
        normalized = normalize_ingredient(ing)
        if normalized:
            ingredients.append(normalized)
            measures.append(measure.strip())
        else:
            # B2: 归一化失败保留英文原名
            ingredients.append(ing.strip())
            measures.append(measure.strip())
            unknown.append(ing.strip())

    # 构建 content Markdown（含 frontmatter 标注 ingredients）
    ing_str = "|".join(ingredients)
    content_lines = [f"<!-- ingredients: {ing_str} -->", f"# {title}\n\n## 配方"]
    for ing, measure in zip(ingredients, measures):
        line = f"- {ing}"
        if measure:
            line += f" {measure}"
        content_lines.append(line)
    content_lines.append(f"\n## 步骤\n{instructions or '见原文'}")
    if image_url:
        content_lines.append(f"\n![{title}]({image_url})")
    if unknown:
        content_lines.append(f"\n## 未归一化材料\n{', '.join(unknown)}")
    content = "\n".join(content_lines)

    return {
        "title": title,
        "source_id": source_id,
        "ingredients": ingredients,
        "content": content,
        "source": "thecocktaildb",
        "verified": False,
        "image_url": image_url,
        "unknown_ingredients": unknown,
    }


def sync_thecocktaildb(
    limit: int = 50,
    letters: str = "abcdefghijklmnopqrstuvwxyz0123456789",
) -> dict[str, Any]:
    """从 TheCocktailDB 全量同步配方。

    Args:
        limit: 每个字母最多拉取条数
        letters: 遍历的首字母集合（默认 a-z + 0-9）

    Returns:
        {imported, skipped, failed, unknown_ingredients}
    """
    imported = 0
    skipped = 0
    failed = 0
    all_unknown: list[str] = []
    importer = ImportService()

    for letter in letters:
        url = f"{API_BASE}/search.php?f={letter}"
        try:
            resp = httpx.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            failed += 1
            continue

        drinks = data.get("drinks") or []
        for drink in drinks[:limit]:
            try:
                recipe = parse_recipe(drink)
                all_unknown.extend(recipe.pop("unknown_ingredients", []))

                # 去重：source + source_id
                with get_session() as session:
                    existing = session.exec(
                        select(Document).where(
                            Document.source == "thecocktaildb",
                            Document.source_id == recipe["source_id"],
                        )
                    ).first()
                    if existing:
                        skipped += 1
                        continue

                # 导入
                result = importer.import_text(
                    content=recipe["content"],
                    title=recipe["title"],
                )
                doc_id = result.get("doc_id") if isinstance(result, dict) else result
                if doc_id:
                    with get_session() as session:
                        doc = session.get(Document, doc_id)
                        if doc:
                            doc.category = "recipe"
                            doc.source = "thecocktaildb"
                            doc.source_id = recipe["source_id"]
                            doc.verified = False
                            doc.image_url = recipe.get("image_url")
                            session.add(doc)
                            session.commit()
                    imported += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "unknown_ingredients": list(set(all_unknown)),
    }

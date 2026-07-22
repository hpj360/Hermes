"""IBA 官方配方数据集导入器（B3）。

数据源：lmc2179/iba_dataset_json GitHub 仓库
- recipes.json：IBA 全部配方（~100 款），单位 cl
- ingredients_strength.json：每种成分 ABV 映射

IBA 金标准配方 verified=True，直接进实验室匹配。
单位转换：cl → ml（1cl = 10ml）。
"""
from __future__ import annotations

from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document
from hermes_kb.rag import ImportService

# IBA dataset 仓库 URL
IBA_REPO = "lmc2179/iba_dataset_json"
IBA_RAW_BASE = f"https://raw.githubusercontent.com/{IBA_REPO}/master"


def _normalize_ingredient(en_name: str) -> tuple[str, bool]:
    """英文材料名 → 中文标准名。

    复用 ingredients 模块的别名索引（与种子配方共享归一化口径）。

    Returns:
        (normalized_name, is_unknown)
    """
    if not en_name:
        return ("", True)
    stripped = en_name.strip()
    key = stripped.lower()
    try:
        from hermes_kb.ingredients import _ALIAS_INDEX

        if key in _ALIAS_INDEX:
            return (_ALIAS_INDEX[key], False)
    except ImportError:
        pass
    # 未命中别名表，保留原名并标记为未知
    return (stripped, True)


def parse_iba_recipe(raw: dict[str, Any]) -> dict[str, Any]:
    """解析 IBA dataset 单条配方。

    IBA dataset 格式：
    {
        "name": "MOJITO",
        "ingredients": [{"name": "white rum", "quantity": 4.5}, ...],
        "type": "Contemporary Classics"
    }
    quantity 单位为 cl，需转 ml。
    """
    title = raw.get("name", "").strip()
    category_official = raw.get("type", "")
    raw_ingredients = raw.get("ingredients", [])

    ingredients: list[str] = []
    measures: list[str] = []
    unknown: list[str] = []

    for ing in raw_ingredients:
        en_name = ing.get("name", "").strip()
        quantity = ing.get("quantity")
        normalized, is_unknown = _normalize_ingredient(en_name)
        # _normalize_ingredient 对未知材料返回原名（非空），故 normalized 恒非空
        ingredients.append(normalized if normalized else en_name)
        if is_unknown and en_name:
            unknown.append(en_name)
        # cl → ml 转换
        if quantity is not None:
            measures.append(f"{float(quantity) * 10:.0f}ml")
        else:
            measures.append("适量")

    # 构建 content（含 frontmatter，供 recipe_match 优先解析）
    ing_str = "|".join(ingredients)
    content_lines = [f"<!-- ingredients: {ing_str} -->", f"# {title}\n\n## 配方"]
    for ing, measure in zip(ingredients, measures):
        content_lines.append(f"- {ing} {measure}")
    content_lines.append(f"\n## 分类\n{category_official}")
    if unknown:
        content_lines.append(f"\n## 未归一化材料\n{', '.join(unknown)}")
    content = "\n".join(content_lines)

    return {
        "title": title,
        "ingredients": ingredients,
        "content": content,
        "source": "iba",
        "verified": True,
        "category_official": category_official,
        "unknown_ingredients": unknown,
    }


def _is_duplicate(title: str) -> bool:
    """检查是否与已有配方重复（含模糊匹配）。

    匹配逻辑：
    1. 精确匹配 source="iba" 的 title（幂等去重）
    2. 模糊匹配已有 recipe（title 互相包含，用于与种子配方去重）
    """
    if not title:
        return False
    title_lower = title.lower()
    with get_session() as session:
        # 精确匹配 IBA 配方
        existing = session.exec(
            select(Document).where(
                Document.source == "iba",
                Document.title == title,
            )
        ).first()
        if existing:
            return True
        # 模糊匹配已有配方（title 互相包含）
        docs = session.exec(
            select(Document).where(Document.category == "recipe")
        ).all()
        for doc in docs:
            doc_title_lower = doc.title.lower()
            if not doc_title_lower:
                continue
            if title_lower in doc_title_lower or doc_title_lower in title_lower:
                return True
    return False


def sync_iba_dataset(data: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """从 IBA dataset 导入配方。

    Args:
        data: IBA 配方列表。若为 None，尝试从 GitHub 拉取。

    Returns:
        {imported, skipped, failed, unknown_ingredients}
    """
    if data is None:
        data = _fetch_remote_data()

    if not data:
        return {"imported": 0, "skipped": 0, "failed": 0, "unknown_ingredients": []}

    imported = 0
    skipped = 0
    failed = 0
    all_unknown: list[str] = []
    importer = ImportService()

    for raw in data:
        try:
            recipe = parse_iba_recipe(raw)
            all_unknown.extend(recipe.pop("unknown_ingredients", []))

            # 去重
            if _is_duplicate(recipe["title"]):
                skipped += 1
                continue

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
                        doc.source = "iba"
                        doc.verified = True  # IBA 金标准
                        doc.status = "published"
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


def _fetch_remote_data() -> list[dict[str, Any]]:
    """从 GitHub 拉取 IBA dataset。

    若网络不可用，返回空列表。
    """
    try:
        import httpx

        url = f"{IBA_RAW_BASE}/recipes.json"
        resp = httpx.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []

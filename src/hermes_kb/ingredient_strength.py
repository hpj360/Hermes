"""材料强度与营养计算模块（G2）。

数据源：
- ingredients.py 的 ABV 注册表（本地权威）
- IBA ingredients_strength.json（远程校验补充）
- 卡路里公式：Volume(ml) × ABV × 0.789(酒精密度) × 7(kcal/g) = 纯酒精卡路里

参考公式来源：basicfreetools.com Alcohol Calorie Calculator
"""
from __future__ import annotations

import httpx

from hermes_kb import ingredients

# IBA ingredients_strength.json 远程地址
IBA_STRENGTH_URL = (
    "https://raw.githubusercontent.com/lmc2179/iba_dataset_json/"
    "master/ingredients_strength.json"
)

# 无体积时的估算假设（ml）：按材料分类给默认体积
# 烈酒 45ml，利口酒 15ml，果汁 30ml，糖浆 10ml，装饰 0ml
_VOLUME_BY_CATEGORY = {
    "base_spirit": 45.0,
    "juice": 30.0,
    "garnish": 0.0,
    "wine": 90.0,
}


def get_ingredient_abv(name: str) -> float:
    """通过 ingredients.canonicalize 归一化后查 ABV，未知返回 0.0。"""
    canonical = ingredients.canonicalize(name)
    return ingredients.get_abv(canonical)


def calculate_cocktail_abv(ingredients_list: list[tuple[str, float]]) -> float:
    """加权平均 ABV。

    Args:
        ingredients_list: [(材料名, 体积ml), ...]

    Returns:
        0.0-1.0 的小数；总体积为 0 时返回 0.0。
    """
    total_volume = sum(vol for _, vol in ingredients_list)
    if total_volume <= 0:
        return 0.0
    weighted = sum(get_ingredient_abv(name) * vol for name, vol in ingredients_list)
    return weighted / total_volume


def calculate_alcohol_calories(volume_ml: float, abv: float) -> float:
    """纯酒精卡路里：volume_ml × abv × 0.789 × 7。"""
    return volume_ml * abv * 0.789 * 7


def _estimate_volume(canonical: str) -> float:
    """根据材料分类估算单次用量（ml）。"""
    category = ingredients.get_category(canonical)
    if category == "modifier":
        # 利口酒（含酒精）15ml，糖浆/无酒精辅料 10ml
        return 15.0 if ingredients.get_abv(canonical) > 0 else 10.0
    return _VOLUME_BY_CATEGORY.get(category, 15.0)


def estimate_recipe_stats(ingredient_names: list[str]) -> dict:
    """无体积时的配方强度估算。

    假设：烈酒 45ml，利口酒 15ml，果汁 30ml，糖浆 10ml，装饰 0ml。

    Returns:
        {"estimated_abv": float, "estimated_calories": float, "total_volume_ml": float}
    """
    total_volume = 0.0
    weighted_abv = 0.0
    total_calories = 0.0

    for name in ingredient_names:
        canonical = ingredients.canonicalize(name)
        abv = ingredients.get_abv(canonical)
        vol = _estimate_volume(canonical)
        total_volume += vol
        weighted_abv += abv * vol
        total_calories += calculate_alcohol_calories(vol, abv)

    estimated_abv = weighted_abv / total_volume if total_volume > 0 else 0.0
    return {
        "estimated_abv": estimated_abv,
        "estimated_calories": total_calories,
        "total_volume_ml": total_volume,
    }


def fetch_iba_strength_data() -> dict[str, float]:
    """从 IBA GitHub 拉取 ingredients_strength.json。

    Returns:
        {材料英文名: ABV小数}；网络失败返回空 dict。
    """
    try:
        resp = httpx.get(IBA_STRENGTH_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError, OSError):
        return {}

    result: dict[str, float] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            try:
                result[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    return result

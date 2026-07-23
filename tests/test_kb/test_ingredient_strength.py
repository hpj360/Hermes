"""材料强度与营养计算模块测试（G2）。"""
from __future__ import annotations

import pytest


def test_get_ingredient_abv():
    """G2: 已知材料返回正确 ABV，未知返回 0.0。"""
    from hermes_kb.ingredient_strength import get_ingredient_abv

    assert get_ingredient_abv("gin") == pytest.approx(0.40)
    assert get_ingredient_abv("Gordon's") == pytest.approx(0.40)  # 别名归一化
    assert get_ingredient_abv("vermouth") == pytest.approx(0.18)
    assert get_ingredient_abv("angostura") == pytest.approx(0.44)
    assert get_ingredient_abv("lemon juice") == pytest.approx(0.0)
    # 未知材料
    assert get_ingredient_abv("某种神秘液体") == pytest.approx(0.0)
    assert get_ingredient_abv("") == pytest.approx(0.0)


def test_calculate_cocktail_abv():
    """G2: 加权平均 ABV（45ml gin 0.40 + 15ml vermouth 0.18 = 0.345）。"""
    from hermes_kb.ingredient_strength import calculate_cocktail_abv

    abv = calculate_cocktail_abv([("gin", 45.0), ("vermouth", 15.0)])
    # (0.40*45 + 0.18*15) / 60 = 20.7/60 = 0.345
    assert abv == pytest.approx(0.345)
    # 含非酒精材料稀释
    abv2 = calculate_cocktail_abv([("gin", 45.0), ("tonic", 90.0)])
    # (0.40*45 + 0*90) / 135 = 18/135 ≈ 0.1333
    assert abv2 == pytest.approx(0.1333, abs=1e-3)
    # 空输入 / 零体积
    assert calculate_cocktail_abv([]) == pytest.approx(0.0)
    assert calculate_cocktail_abv([("gin", 0.0)]) == pytest.approx(0.0)


def test_calculate_alcohol_calories():
    """G2: 纯酒精卡路里公式（100ml × 0.40 × 0.789 × 7 = 220.92 kcal）。"""
    from hermes_kb.ingredient_strength import calculate_alcohol_calories

    kcal = calculate_alcohol_calories(100.0, 0.40)
    assert kcal == pytest.approx(220.92)
    # 非酒精材料卡路里为 0
    assert calculate_alcohol_calories(200.0, 0.0) == pytest.approx(0.0)
    # 零体积
    assert calculate_alcohol_calories(0.0, 0.40) == pytest.approx(0.0)


def test_estimate_recipe_stats():
    """G2: 无体积估算返回三字段，ABV 在合理范围。"""
    from hermes_kb.ingredient_strength import estimate_recipe_stats

    stats = estimate_recipe_stats(["gin", "vermouth", "lemon juice"])
    assert set(stats.keys()) == {"estimated_abv", "estimated_calories", "total_volume_ml"}
    # ABV 合理范围
    assert 0.0 <= stats["estimated_abv"] <= 1.0
    assert stats["total_volume_ml"] > 0
    assert stats["estimated_calories"] >= 0
    # 全装饰（零体积）应安全返回 0 ABV
    stats2 = estimate_recipe_stats(["mint", "olive"])
    assert stats2["estimated_abv"] == pytest.approx(0.0)
    assert stats2["total_volume_ml"] == pytest.approx(0.0)


def test_fetch_iba_strength_data_network_fail(monkeypatch):
    """G2: httpx 失败时返回空 dict。"""
    from hermes_kb import ingredient_strength
    import httpx

    def fake_get(*args, **kwargs):
        raise httpx.HTTPError("network down")

    monkeypatch.setattr(ingredient_strength.httpx, "get", fake_get)
    result = ingredient_strength.fetch_iba_strength_data()
    assert result == {}

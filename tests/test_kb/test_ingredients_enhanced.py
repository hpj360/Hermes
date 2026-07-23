"""增强版材料注册表测试（G1：ABV + 品牌字段 + 扩展材料）。"""
from __future__ import annotations

import pytest


def test_get_abv():
    """G1: 根据标准名获取 ABV，未知返回 0.0。"""
    from hermes_kb.ingredients import get_abv

    assert get_abv("金酒") == pytest.approx(0.40)
    assert get_abv("威士忌") == pytest.approx(0.40)
    assert get_abv("味美思") == pytest.approx(0.18)
    assert get_abv("苦精") == pytest.approx(0.44)
    assert get_abv("糖浆") == pytest.approx(0.0)
    assert get_abv("柠檬汁") == pytest.approx(0.0)
    # 未知材料
    assert get_abv("不存在的材料") == pytest.approx(0.0)
    assert get_abv("") == pytest.approx(0.0)


def test_get_brands():
    """G1: 已知材料返回品牌列表，未知返回空。"""
    from hermes_kb.ingredients import get_brands

    gin_brands = get_brands("金酒")
    assert isinstance(gin_brands, list)
    assert "Gordon's" in gin_brands
    assert "Tanqueray" in gin_brands
    # campari 只有一个品牌
    assert get_brands("金巴利") == ["Campari"]
    # 非酒精材料品牌为空列表
    assert get_brands("柠檬汁") == []
    # 未知材料
    assert get_brands("不存在的材料") == []
    # 返回的列表不应是内部引用（避免外部篡改注册表）
    brands = get_brands("金酒")
    brands.append("HACK")
    assert "HACK" not in get_brands("金酒")


def test_new_ingredients_coverage():
    """G1: 新增材料都能通过 canonicalize 查到。"""
    from hermes_kb.ingredients import canonicalize

    new_canonicals = [
        # 烈酒类
        "苦艾烈酒", "波本威士忌", "干邑白兰地", "爱尔兰威士忌", "黑麦威士忌",
        "苏格兰威士忌", "皮斯科", "阿夸维特", "黑朗姆酒", "白朗姆酒", "陈年朗姆酒",
        # 利口酒类
        "苦杏仁酒", "百利甜酒", "香波力娇酒", "咖啡力娇酒", "柑曼怡", "加利亚诺",
        "蜜瓜力娇酒", "蓝柑香酒", "可可力娇酒", "黑加仑力娇酒", "薄荷力娇酒",
        "白橙力娇酒", "蜜桃香甜酒", "杏子白兰地", "樱桃力娇酒",
        # 葡萄酒/起泡酒
        "香槟", "普罗塞克", "红葡萄酒", "波特酒",
        # 其他
        "干味美思", "甜味美思", "橙味苦精", "蛋清", "奶油", "浓缩咖啡",
        "红石榴糖浆", "蜂蜜糖浆", "龙舌兰糖浆", "椰奶油",
    ]
    for canonical in new_canonicals:
        assert canonicalize(canonical) == canonical, f"新增材料未被注册: {canonical}"

    # 部分新材料的英文别名也可归一化
    assert canonicalize("amaretto") == "苦杏仁酒"
    assert canonicalize("irish cream") == "百利甜酒"
    assert canonicalize("grand marnier") == "柑曼怡"
    assert canonicalize("blue curacao") == "蓝柑香酒"
    assert canonicalize("champagne") == "香槟"
    assert canonicalize("red wine") == "红葡萄酒"


def test_new_ingredients_have_abv_and_brands():
    """G1: 新增材料条目均含 abv 与 brands 字段。"""
    from hermes_kb.ingredients import INGREDIENT_REGISTRY, get_abv, get_brands

    # 抽检若干新材料具备 ABV 与品牌字段
    assert get_abv("苦艾烈酒") == pytest.approx(0.55)
    assert get_abv("咖啡力娇酒") == pytest.approx(0.20)
    assert get_brands("苦杏仁酒") == ["Disaronno"]
    assert get_brands("咖啡力娇酒") == ["Kahlúa", "Tia Maria"]
    assert get_brands("百利甜酒") == ["Baileys"]

    # 全注册表每条都应有 abv(float) 与 brands(list)
    for info in INGREDIENT_REGISTRY.values():
        assert "abv" in info, f"{info['canonical']} 缺 abv"
        assert isinstance(info["abv"], float)
        assert 0.0 <= info["abv"] <= 1.0
        assert "brands" in info, f"{info['canonical']} 缺 brands"
        assert isinstance(info["brands"], list)


def test_backward_compatible():
    """G1: 原有函数行为不变（具体烈酒英文别名已解冲突，归一化到具体条目）。"""
    from hermes_kb.ingredients import (
        all_canonical,
        canonicalize,
        get_category,
        list_by_category,
        INGREDIENT_REGISTRY,
    )

    # canonicalize 核心映射保持
    assert canonicalize("gin") == "金酒"
    assert canonicalize("Gordon's") == "金酒"
    assert canonicalize("whiskey") == "威士忌"
    assert canonicalize("whisky") == "威士忌"
    assert canonicalize("rum") == "朗姆酒"
    assert canonicalize("vermouth") == "味美思"
    assert canonicalize("苦艾酒") == "味美思"
    # P2-A 修复：具体烈酒英文别名归一化到具体条目（不再被通用别名遮蔽）
    assert canonicalize("bourbon") == "波本威士忌"
    assert canonicalize("scotch") == "苏格兰威士忌"
    assert canonicalize("rye") == "黑麦威士忌"
    assert canonicalize("cognac") == "干邑白兰地"
    assert canonicalize("white rum") == "白朗姆酒"
    assert canonicalize("dark rum") == "黑朗姆酒"
    assert canonicalize("triple sec") == "白橙力娇酒"
    # 未知材料返回原值
    assert canonicalize("某未知材料") == "某未知材料"
    assert canonicalize("") == ""

    # get_category
    assert get_category("金酒") == "base_spirit"
    assert get_category("柠檬汁") == "juice"
    assert get_category("橄榄") == "garnish"
    assert get_category("不存在") is None

    # list_by_category：原 5 种装饰不变
    garnishes = list_by_category("garnish")
    assert garnishes == ["橄榄", "柠檬片", "薄荷叶", "樱桃", "橙皮"]
    # 原有基酒 6 种仍在
    spirits = list_by_category("base_spirit")
    for s in ["金酒", "威士忌", "朗姆酒", "龙舌兰", "白兰地", "伏特加"]:
        assert s in spirits

    # all_canonical：含原有材料，且因扩展而增长
    all_names = all_canonical()
    for n in ["金酒", "威士忌", "朗姆酒", "味美思", "柠檬汁", "橄榄"]:
        assert n in all_names
    assert len(all_names) >= 26
    # 去重（标准名唯一）
    assert len(all_names) == len(set(all_names))
    # 注册表条目数与 all_canonical 一致
    assert len(all_names) == len(INGREDIENT_REGISTRY)


def test_specific_spirit_abv_resolution():
    """P2-A: 具体烈酒英文别名归一化后查到正确的 ABV（不再用通用条目 ABV）。"""
    from hermes_kb.ingredient_strength import get_ingredient_abv

    # dark rum 应查到黑朗姆酒 ABV 0.43，而非朗姆酒 0.40
    assert get_ingredient_abv("dark rum") == 0.43
    # white rum 查到白朗姆酒 0.40
    assert get_ingredient_abv("white rum") == 0.40
    # triple sec 查到白橙力娇酒 0.30，而非君度 0.40
    assert get_ingredient_abv("triple sec") == 0.30
    # 通用 rum 仍查到朗姆酒 0.40
    assert get_ingredient_abv("rum") == 0.40

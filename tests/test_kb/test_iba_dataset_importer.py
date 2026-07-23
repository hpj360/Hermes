"""IBA dataset importer 测试（B3）。"""
from __future__ import annotations

import pytest
from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document


def test_parse_iba_recipe_basic():
    """B3: 解析 IBA dataset 单条配方。"""
    from hermes_kb.iba_dataset_importer import parse_iba_recipe

    raw = {
        "name": "MOJITO",
        "ingredients": [
            {"name": "white rum", "quantity": 4.5},
            {"name": "lime juice", "quantity": 2.0},
            {"name": "sugar syrup", "quantity": 1.5},
            {"name": "soda water", "quantity": None},
            {"name": "mint", "quantity": None},
        ],
        "type": "Contemporary Classics",
    }
    recipe = parse_iba_recipe(raw)
    assert recipe["title"] == "MOJITO"
    assert recipe["source"] == "iba"
    assert recipe["verified"] is True
    assert "朗姆酒" in recipe["ingredients"]
    assert "青柠汁" in recipe["ingredients"]
    assert recipe["category_official"] == "Contemporary Classics"
    # content 应含 frontmatter
    assert "<!-- ingredients:" in recipe["content"]


def test_parse_iba_recipe_unit_conversion():
    """B3: cl → ml 单位转换。"""
    from hermes_kb.iba_dataset_importer import parse_iba_recipe

    raw = {
        "name": "TEST",
        "ingredients": [
            {"name": "gin", "quantity": 6.0},
        ],
        "type": "Test",
    }
    recipe = parse_iba_recipe(raw)
    # 6cl → 60ml
    assert "60ml" in recipe["content"]


def test_parse_iba_recipe_unknown_ingredient():
    """B3: 未归一化材料保留英文原名。"""
    from hermes_kb.iba_dataset_importer import parse_iba_recipe

    raw = {
        "name": "SPECIAL",
        "ingredients": [
            {"name": "gin", "quantity": 4.5},
            {"name": "some rare liqueur", "quantity": 1.0},
        ],
        "type": "Special",
    }
    recipe = parse_iba_recipe(raw)
    assert "金酒" in recipe["ingredients"]
    # 未归一化的应在 unknown_ingredients
    assert "some rare liqueur" in recipe["unknown_ingredients"]


def test_sync_iba_dataset_with_mock_data():
    """B3: 用 mock 数据导入 IBA 配方。"""
    from hermes_kb.iba_dataset_importer import sync_iba_dataset

    mock_data = [
        {
            "name": "NEGRONI",
            "ingredients": [
                {"name": "gin", "quantity": 3.0},
                {"name": "campari", "quantity": 3.0},
                {"name": "sweet vermouth", "quantity": 3.0},
            ],
            "type": "Contemporary Classics",
        },
        {
            "name": "OLD FASHIONED",
            "ingredients": [
                {"name": "bourbon", "quantity": 6.0},
                {"name": "sugar", "quantity": None},
                {"name": "angostura bitters", "quantity": None},
            ],
            "type": "The Unforgettables",
        },
    ]

    result = sync_iba_dataset(data=mock_data)
    assert result["imported"] == 2
    assert result["skipped"] == 0

    # 验证导入
    with get_session() as session:
        docs = session.exec(
            select(Document).where(Document.source == "iba")
        ).all()
        assert len(docs) == 2
        titles = {d.title for d in docs}
        assert "NEGRONI" in titles
        assert "OLD FASHIONED" in titles
        # verified 应为 True（IBA 金标准）
        assert all(d.verified for d in docs)

    # 再次同步应去重
    result2 = sync_iba_dataset(data=mock_data)
    assert result2["imported"] == 0
    assert result2["skipped"] == 2


def test_sync_iba_dataset_dedup_with_seed():
    """B3: 与种子配方去重（按 title 模糊匹配）。"""
    from hermes_kb.iba_dataset_importer import sync_iba_dataset
    from hermes_kb.seed_recipes import SEED_RECIPES
    from hermes_kb.rag import ImportService
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    # 先播种种子（含 莫吉托 Mojito）。seed_recipes 模块未提供 seed_all，
    # 这里复用 ImportService + SEED_RECIPES 内联播种（与 /api/seed/recipes 同逻辑）。
    importer = ImportService()
    for recipe in SEED_RECIPES:
        result = importer.import_text(
            content=recipe["content"],
            title=recipe["title"],
            source_type="seed",
            file_type="md",
        )
        doc_id = result.get("doc_id") if isinstance(result, dict) else result
        if doc_id:
            with get_session() as session:
                doc = session.get(Document, doc_id)
                if doc:
                    doc.category = "recipe"
                    session.add(doc)
                    session.commit()

    mock_data = [
        {
            "name": "Mojito",  # 与种子 "莫吉托 Mojito" 模糊匹配
            "ingredients": [
                {"name": "white rum", "quantity": 4.5},
                {"name": "lime juice", "quantity": 2.0},
            ],
            "type": "Contemporary Classics",
        },
        {
            "name": "DAIQUIRI",  # 新配方
            "ingredients": [
                {"name": "white rum", "quantity": 4.5},
                {"name": "lime juice", "quantity": 2.0},
                {"name": "sugar syrup", "quantity": 1.5},
            ],
            "type": "Contemporary Classics",
        },
    ]

    result = sync_iba_dataset(data=mock_data)
    # Mojito 应被去重（与种子模糊匹配）
    # DAIQUIRI 应导入
    # 注意：模糊匹配逻辑可能是 title 包含关系或相似度
    assert result["imported"] >= 1
    assert result["skipped"] >= 1


def test_sync_iba_dataset_empty_data():
    """B3: 空数据应返回空结果。"""
    from hermes_kb.iba_dataset_importer import sync_iba_dataset

    result = sync_iba_dataset(data=[])
    assert result["imported"] == 0
    assert result["skipped"] == 0


def test_diff_iba_official_basic():
    """G3: 用 mock local + official data 测试 diff 逻辑。"""
    from hermes_kb.iba_dataset_importer import diff_iba_official

    local_data = [
        {"title": "Negroni"},
        {"title": "Mojito"},
        {"title": "Old Fashioned"},
    ]
    official_data = [
        {"name": "Negroni", "ingredients": [], "type": "The Unforgettables"},
        {"name": "Mojito", "ingredients": [], "type": "Contemporary Classics"},
        {"name": "Daiquiri", "ingredients": [], "type": "Contemporary Classics"},
    ]

    result = diff_iba_official(local_data=local_data, official_data=official_data)

    assert result["local_count"] == 3
    assert result["official_count"] == 3
    # 两边都有的
    assert result["matched"] == ["mojito", "negroni"]
    # 官方有但本地没有
    assert result["missing_locally"] == ["daiquiri"]
    # 本地有但官方没有
    assert result["extra_locally"] == ["old fashioned"]


def test_diff_iba_official_network_fail(monkeypatch):
    """G3: 网络失败时返回结构正确（official_count=0, missing_locally=[]）。"""
    from hermes_kb import iba_dataset_importer

    # 模拟远程拉取失败（返回空列表）
    monkeypatch.setattr(iba_dataset_importer, "_fetch_remote_data", lambda: [])

    local_data = [{"title": "Negroni"}, {"title": "Mojito"}]
    result = iba_dataset_importer.diff_iba_official(
        local_data=local_data, official_data=None
    )

    # 结构完整
    assert set(result.keys()) == {
        "local_count",
        "official_count",
        "missing_locally",
        "extra_locally",
        "matched",
    }
    assert result["official_count"] == 0
    assert result["missing_locally"] == []
    assert result["local_count"] == 2
    # 本地全部算作 extra
    assert sorted(result["extra_locally"]) == ["mojito", "negroni"]
    assert result["matched"] == []

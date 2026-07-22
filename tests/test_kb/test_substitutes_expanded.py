"""替代材料扩充测试（B4）。"""
from __future__ import annotations


def test_substitutes_preset_expanded():
    """B4: SUBSTITUTES_PRESET 应扩充到 40+ 条。"""
    from hermes_kb.substitutes import SUBSTITUTES_PRESET

    assert len(SUBSTITUTES_PRESET) >= 40, (
        f"expected >= 40 presets, got {len(SUBSTITUTES_PRESET)}"
    )


def test_substitutes_preset_covers_common_ingredients():
    """B4: 应覆盖常见鸡尾酒材料的替代关系。"""
    from hermes_kb.substitutes import SUBSTITUTES_PRESET

    # 基酒替代
    assert "金酒" in SUBSTITUTES_PRESET
    assert "伏特加" in SUBSTITUTES_PRESET
    assert "威士忌" in SUBSTITUTES_PRESET
    assert "朗姆酒" in SUBSTITUTES_PRESET
    assert "龙舌兰" in SUBSTITUTES_PRESET
    # 辅料替代
    assert "味美思" in SUBSTITUTES_PRESET
    assert "苦精" in SUBSTITUTES_PRESET
    # 果汁替代
    assert "柠檬汁" in SUBSTITUTES_PRESET
    assert "橙汁" in SUBSTITUTES_PRESET


def test_substitutes_preset_values_are_lists():
    """B4: 每个替代值应为 list[str]。"""
    from hermes_kb.substitutes import SUBSTITUTES_PRESET

    for canonical, subs in SUBSTITUTES_PRESET.items():
        assert isinstance(subs, list), f"{canonical} substitutes not list"
        assert len(subs) > 0, f"{canonical} has empty substitutes"
        for s in subs:
            assert isinstance(s, str), f"{canonical} substitute {s} not str"


def test_bar_assistant_sync_module_exists():
    """B4: bar_assistant_sync 模块应存在。"""
    from hermes_kb.bar_assistant_sync import sync_bar_assistant_substitutes

    assert callable(sync_bar_assistant_substitutes)


def test_bar_assistant_sync_with_mock_data(monkeypatch):
    """B4: bar-assistant 同步应能处理 mock 数据并导入。"""
    from hermes_kb.bar_assistant_sync import sync_bar_assistant_substitutes
    from hermes_kb.models import IngredientSubstitute
    from hermes_kb.database import get_session
    from sqlmodel import select

    # Mock bar-assistant 数据（模拟从仓库拉取的替代关系）
    mock_data = [
        {"canonical": "金酒", "substitute": "伏特加"},
        {"canonical": "威士忌", "substitute": "波本"},
        {"canonical": "橙汁", "substitute": "芒果汁"},
    ]

    result = sync_bar_assistant_substitutes(data=mock_data)
    assert result["imported"] == 3
    assert result["skipped"] == 0

    # 验证导入
    with get_session() as session:
        rows = session.exec(
            select(IngredientSubstitute).where(
                IngredientSubstitute.source == "bar_assistant"
            )
        ).all()
        assert len(rows) >= 3
        canon_set = {r.canonical for r in rows}
        assert "金酒" in canon_set
        assert "威士忌" in canon_set

    # 再次同步应去重
    result2 = sync_bar_assistant_substitutes(data=mock_data)
    assert result2["imported"] == 0
    assert result2["skipped"] == 3


def test_bar_assistant_sync_no_data():
    """B4: 无数据时应返回空结果。"""
    from hermes_kb.bar_assistant_sync import sync_bar_assistant_substitutes

    result = sync_bar_assistant_substitutes(data=[])
    assert result["imported"] == 0
    assert result["skipped"] == 0

"""趋势数据源 + 平台词包单元测试（Phase 1/2 数据驱动选题）。"""
from __future__ import annotations

import pytest

from hermes.content_team.compliance import (
    check_compliance,
    load_platform_rules,
)
from hermes.content_team.trend_sources import (
    FixtureTrendProvider,
    HonghuTrendProvider,
    HotNote,
    TrendSourceNotConfigured,
    hot_notes_to_topic_inputs,
)


@pytest.fixture
def provider() -> FixtureTrendProvider:
    return FixtureTrendProvider()


@pytest.mark.asyncio
async def test_fixture_provider_returns_notes(provider):
    notes = await provider.fetch_hot_notes()
    assert len(notes) >= 5
    assert all(n.platform == "XIAOHONGSHU" for n in notes)
    assert all(n.source == "fixture" for n in notes)


@pytest.mark.asyncio
async def test_fixture_provider_keyword_filter(provider):
    notes = await provider.fetch_hot_notes(keyword="居家调酒")
    assert all("居家调酒" in n.title or "居家调酒" in n.category for n in notes)


@pytest.mark.asyncio
async def test_fixture_provider_hotlist(provider):
    items = await provider.fetch_hot_list()
    assert len(items) >= 5
    ranks = [i.rank for i in items]
    assert ranks == sorted(ranks)
    assert all(i.platform == "DOUYIN" for i in items)


def test_honghu_not_configured_raises(monkeypatch):
    monkeypatch.delenv("HERMES_HONGHU_BASE_URL", raising=False)
    monkeypatch.delenv("HERMES_HONGHU_API_KEY", raising=False)
    with pytest.raises(TrendSourceNotConfigured):
        HonghuTrendProvider.from_env()


def test_honghu_configured_from_env(monkeypatch):
    monkeypatch.setenv("HERMES_HONGHU_BASE_URL", "https://api.example.com/")
    monkeypatch.setenv("HERMES_HONGHU_API_KEY", "sk-test")
    p = HonghuTrendProvider.from_env()
    assert p.base_url == "https://api.example.com"
    assert p.name == "honghu"


def test_hot_notes_to_topic_inputs_filter_and_dedup():
    notes = [
        HotNote(title="酒A", platform="XIAOHONGSHU", likes=800, source="fixture"),
        HotNote(
            title="酒B", platform="XIAOHONGSHU", likes=100, source="fixture"
        ),  # 互动不足
        HotNote(
            title="酒A ", platform="XIAOHONGSHU", likes=900, source="fixture"
        ),  # 归一化后重复
        HotNote(
            title="大号爆款",
            platform="XIAOHONGSHU",
            likes=5000,
            author_fans=100000,
            source="fixture",
        ),
    ]
    rows = hot_notes_to_topic_inputs(
        notes, min_engagement=500, max_fans=5000
    )
    titles = [r["title"] for r in rows]
    assert titles == ["酒A"]  # 低互动剔除、重复去重、大号被 max_fans 过滤
    row = rows[0]
    assert row["target_platforms"] == ["XIAOHONGSHU"]
    assert "爆款参考" in row["description"]


def test_hot_notes_to_topic_inputs_exclude_existing():
    notes = [
        HotNote(title="已有选题", platform="XIAOHONGSHU", likes=800, source="fixture"),
        HotNote(title="新选题", platform="XIAOHONGSHU", likes=800, source="fixture"),
    ]
    rows = hot_notes_to_topic_inputs(notes, exclude_titles={"已有选题"})
    assert [r["title"] for r in rows] == ["新选题"]


def test_hot_notes_sorted_by_engagement_desc():
    notes = [
        HotNote(title="低", platform="XIAOHONGSHU", likes=100, source="fixture"),
        HotNote(title="高", platform="XIAOHONGSHU", likes=900, source="fixture"),
    ]
    rows = hot_notes_to_topic_inputs(notes, min_engagement=50)
    assert [r["title"] for r in rows] == ["高", "低"]


# ---------------------------------------------------------------------------
# 平台词包
# ---------------------------------------------------------------------------


def test_load_platform_rules_all_packs():
    for platform in ("xiaohongshu", "douyin", "wechat_official"):
        rules = load_platform_rules(platform)
        assert rules, f"{platform} 词包不应为空"
        assert all(r.keywords for r in rules)


def test_load_platform_rules_missing_pack_returns_empty():
    assert load_platform_rules("nonexistent_platform") == ()


def test_load_platform_rules_case_insensitive():
    assert load_platform_rules("XIAOHONGSHU") == load_platform_rules("xiaohongshu")


def test_check_compliance_platform_pack_adds_hits():
    # "全网最低" 在 douyin 词包（BLOCK），基础规则不含
    report = check_compliance("全网最低的威士忌", "正文", platform="DOUYIN")
    assert report.passed is False
    assert any(h.rule_id == "dy_price_absolute" for h in report.blocking)

    # 不带 platform 时不加载词包
    report_base = check_compliance("全网最低的威士忌", "正文")
    assert report_base.passed is True


def test_check_compliance_xhs_pack_warn():
    report = check_compliance(
        "好喝的酒", "价格私聊我，保证不上头", platform="XIAOHONGSHU"
    )
    assert report.passed is True  # 均为 WARN
    rule_ids = {h.rule_id for h in report.warnings}
    assert {"xhs_offsite_deal", "xhs_effect_promise"} <= rule_ids


def test_check_compliance_base_rules_still_apply_with_platform():
    # 基础规则（未成年人）+ 平台词包同时生效
    report = check_compliance(
        "未成年人也能喝的酒", "全网最低价", platform="DOUYIN"
    )
    rule_ids = {h.rule_id for h in report.blocking}
    assert "minors" in rule_ids
    assert "dy_price_absolute" in rule_ids

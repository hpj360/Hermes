"""创作 SOP 化单元测试（IT-2：builder + checker）。"""
from __future__ import annotations

import uuid

from hermes.content_team.models.content import Content
from hermes.content_team.models.platform import Platform
from hermes.content_team.models.topic import Topic
from hermes.content_team.sop import (
    PLATFORM_BODY_LIMIT,
    PLATFORM_TITLE_LIMIT,
    _hashtag_variants,
    _mechanism_candidates,
    build_draft,
    check_content,
)


def _make_topic(
    title="金汤力入门",
    description="开头：今天分享一款最简单的居家调酒\n- 金酒 50ml\n- 汤力水 150ml\n- 柠檬一片\n结尾：关注我，一起喝好酒",
    keywords=("金汤力", "居家调酒", "调酒入门"),
) -> Topic:
    return Topic(
        id=uuid.uuid4(),
        title=title,
        description=description,
        keywords=list(keywords),
        target_platforms=["XIAOHONGSHU"],
    )


def test_platform_limits_match_adapters():
    """平台长度限制与各适配器一致。"""
    assert PLATFORM_TITLE_LIMIT[Platform.XIAOHONGSHU] == 20
    assert PLATFORM_TITLE_LIMIT[Platform.WECHAT_OFFICIAL] == 64
    assert PLATFORM_TITLE_LIMIT[Platform.DOUYIN] == 55
    assert PLATFORM_TITLE_LIMIT[Platform.BILIBILI] == 80
    assert PLATFORM_BODY_LIMIT[Platform.XIAOHONGSHU] == 1000
    assert PLATFORM_BODY_LIMIT[Platform.WECHAT_OFFICIAL] == 20000


def test_build_draft_returns_title_candidates():
    topic = _make_topic()
    draft = build_draft(topic, Platform.XIAOHONGSHU)
    assert len(draft.title_candidates) >= 1
    assert len(draft.title_candidates) <= 6
    assert draft.title == draft.title_candidates[0]


def test_build_draft_respects_title_limit():
    topic = _make_topic()
    draft = build_draft(topic, Platform.XIAOHONGSHU)
    for c in draft.title_candidates:
        assert len(c) <= 20


def test_build_draft_body_has_structure():
    topic = _make_topic()
    draft = build_draft(topic, Platform.XIAOHONGSHU)
    assert draft.body != ""
    # 至少两段
    paragraphs = [p for p in draft.body.split("\n\n") if p.strip()]
    assert len(paragraphs) >= 2
    # 包含结尾互动引导
    assert "评论" in draft.body or "👇" in draft.body


def test_build_draft_includes_keywords():
    topic = _make_topic()
    draft = build_draft(topic, Platform.XIAOHONGSHU)
    # 至少一个关键词出现在正文或标题中
    found = any(kw in draft.body or kw in draft.title for kw in topic.keywords)
    assert found


def test_build_draft_hashtags_from_keywords():
    topic = _make_topic()
    draft = build_draft(topic, Platform.XIAOHONGSHU)
    assert len(draft.hashtags) >= len(topic.keywords)


def test_hashtag_variants():
    tags = _hashtag_variants(["居家调酒", "微醺 日常"])
    assert "居家调酒" in tags
    assert "微醺 日常" in tags
    assert "微醺日常" in tags  # 去空格变体


def test_check_content_clean_passes():
    topic = _make_topic()
    content = Content(title="金汤力入门", body="今天分享一款最简单的居家调酒\n\n金酒 50ml、汤力水 150ml\n\n关注我一起喝好酒\n\n#金汤力 #居家调酒 #调酒入门")
    result = check_content(content, Platform.XIAOHONGSHU, topic)
    assert result.passed is True
    assert result.blocking == []
    assert result.compliance_passed is True


def test_check_content_platform_limit_blocked():
    content = Content(title="x" * 21, body="正文\n\n#标签1 #标签2 #标签3")
    result = check_content(content, Platform.XIAOHONGSHU)
    assert result.passed is False
    assert any("标题超过" in e for e in result.blocking)


def test_check_content_compliance_blocked():
    content = Content(title="未成年人饮酒指南", body="正文内容\n\n#标签1 #标签2 #标签3")
    result = check_content(content, Platform.XIAOHONGSHU)
    assert result.passed is False
    assert result.compliance_passed is False
    assert any("合规红线" in b for b in result.blocking)


def test_check_content_sop_warnings():
    # 过短正文 + 缺标签 → SOP 警告
    content = Content(title="短", body="只有开头没有结尾")
    result = check_content(content, Platform.XIAOHONGSHU)
    assert len(result.sop_warnings) > 0


def test_check_content_keyword_coverage():
    topic = _make_topic()
    content = Content(title="无关标题", body="正文内容不涉及关键词\n\n#标签1 #标签2 #标签3")
    result = check_content(content, Platform.XIAOHONGSHU, topic)
    assert result.keyword_coverage == {
        "金汤力": False,
        "居家调酒": False,
        "调酒入门": False,
    }


def test_check_content_keyword_coverage_hit():
    topic = _make_topic()
    content = Content(title="金汤力入门", body="分享居家调酒\n\n#金汤力 #居家调酒 #调酒入门")
    result = check_content(content, Platform.XIAOHONGSHU, topic)
    assert all(result.keyword_coverage.values())


# ---------------------------------------------------------------------------
# SOP Builder v2：标题机制库 + 去 AI 味检查
# ---------------------------------------------------------------------------


def test_build_draft_title_mechanisms_detailed():
    """候选标题带机制标注，且多机制覆盖。"""
    from hermes.content_team.sop import TITLE_MECHANISMS

    topic = _make_topic()
    draft = build_draft(topic, Platform.XIAOHONGSHU)
    assert draft.title_candidates_detailed
    mechs = {c["mechanism"] for c in draft.title_candidates_detailed}
    assert mechs <= {m.mech_id for m in TITLE_MECHANISMS}
    assert len(mechs) == len(draft.title_candidates_detailed)  # 机制互不重复
    for c in draft.title_candidates_detailed:
        assert c["mechanism_name"]
        assert c["note"]


def test_build_draft_mechanisms_respect_title_limit():
    topic = _make_topic(title="超长金汤力入门教程标题需要被正确截断保持合规")
    draft = build_draft(topic, Platform.XIAOHONGSHU)
    for c in draft.title_candidates:
        assert len(c) <= 20


def test_title_mechanism_templates_fill_placeholders():
    """机制模板用 base/kw 占位填充，不残留花括号。"""
    for t, _ in _mechanism_candidates(_make_topic(), 80):
        assert "{" not in t and "}" not in t


def test_check_ai_flavor_detects_template_language():
    content = Content(
        title="金汤力",
        body="首先，加冰。其次，倒酒。最后，搅拌。总而言之，很棒。\n\n#金汤力 #居家调酒 #调酒入门",
    )
    result = check_content(content, Platform.XIAOHONGSHU)
    joined = "\n".join(result.sop_warnings)
    assert "首先" in joined
    assert "其次" in joined
    assert any("总而言之" in w or "总的来说" in w for w in result.sop_warnings)


def test_check_ai_flavor_detects_emoji_flood():
    body = "😀" * 8 + "\n\n#金汤力 #居家调酒 #调酒入门"
    content = Content(title="金汤力", body=body)
    result = check_content(content, Platform.XIAOHONGSHU, None)
    assert any("emoji 堆砌" in w for w in result.sop_warnings)


def test_check_ai_flavor_clean_body_no_warning():
    content = Content(
        title="金汤力入门",
        body="今天来一杯金汤力，做法很简单。\n\n金酒加汤力水，挤片柠檬。\n\n#金汤力 #居家调酒 #调酒入门",
    )
    result = check_content(content, Platform.XIAOHONGSHU)
    flavor = [w for w in result.sop_warnings if "AI腔" in w or "emoji" in w]
    assert flavor == []


def test_check_content_applies_platform_word_pack():
    """SOP Checker 的合规检查按平台加载词包（DOUYIN 价格绝对化）。"""
    content = Content(
        title="全网最低的威士忌",
        body="正文\n\n#金汤力 #居家调酒 #调酒入门",
    )
    result = check_content(content, Platform.DOUYIN)
    assert result.compliance_passed is False
    assert any(
        h.rule_id == "dy_price_absolute" for h in result.compliance.blocking
    )
    # 换平台后同内容不再命中该词包规则
    result_xhs = check_content(
        Content(
            title="全网最低的威士忌",
            body="正文\n\n#金汤力 #居家调酒 #调酒入门",
        ),
        Platform.XIAOHONGSHU,
    )
    assert result_xhs.compliance_passed is True

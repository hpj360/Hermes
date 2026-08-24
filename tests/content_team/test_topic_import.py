"""选题库解析器单元测试（IT-2）。"""

from __future__ import annotations

from hermes.content_team.topic_import import parse_topic_library

SAMPLE = """# 前30天选题库（15篇，直接用）

> 原则：前15篇全部围绕「居家调酒+酒类推荐」，极致垂直

---

## 第1篇（启动篇）：人设建立
**标题方向**：
- 《30岁北漂回成都，我决定在家开个小酒吧》
- 《一个数据产品经理的家里，居然藏了这么多酒》

**内容方向**：
- 开头：拍你家酒柜/酒的全景图
- 结尾：欢迎关注，一起喝好酒

**关键词**：居家调酒、在家喝酒、微醺日常

---

## 第2篇（金汤力入门）：你的拿手酒
**标题方向**：
- 《我心中永远的第一：在家3分钟调一杯完美金汤力》

**内容方向**：
- 原料：金酒、汤力水、柠檬、冰块
- 步骤：加冰→倒金酒→加汤力水→挤柠檬

**关键词**：金汤力、居家调酒、调酒入门

---

## 话题标签库（每篇选5-8个搭配用）
```
#居家调酒 #微醺 #在家喝酒
```
"""


def test_parses_topic_sections():
    topics = parse_topic_library(SAMPLE)
    assert len(topics) == 2
    assert topics[0].section_label == "第1篇"
    assert topics[0].topic_title == "人设建立"


def test_parses_titles_and_content():
    topics = parse_topic_library(SAMPLE)
    t = topics[0]
    assert t.titles == [
        "《30岁北漂回成都，我决定在家开个小酒吧》",
        "《一个数据产品经理的家里，居然藏了这么多酒》",
    ]
    assert t.content == [
        "开头：拍你家酒柜/酒的全景图",
        "结尾：欢迎关注，一起喝好酒",
    ]


def test_parses_keywords():
    topics = parse_topic_library(SAMPLE)
    assert topics[0].keywords == ["居家调酒", "在家喝酒", "微醺日常"]
    assert topics[1].keywords == ["金汤力", "居家调酒", "调酒入门"]


def test_skips_tag_library_section():
    topics = parse_topic_library(SAMPLE)
    assert all("话题标签" not in t.topic_title for t in topics)


def test_to_topic_input_default_platform():
    topics = parse_topic_library(SAMPLE)
    data = topics[0].to_topic_input()
    assert data["title"] == "30岁北漂回成都，我决定在家开个小酒吧"
    assert data["target_platforms"] == ["XIAOHONGSHU"]
    assert data["keywords"] == ["居家调酒", "在家喝酒", "微醺日常"]
    assert data["description"].startswith("- 开头：拍你家酒柜")


def test_to_topic_input_fallback_when_no_titles():
    topics = parse_topic_library(
        "## 第3篇：无标题候选\n**内容方向**：\n- 只有大纲\n"
    )
    data = topics[0].to_topic_input(default_platform="DOUYIN")
    assert data["title"] == "无标题候选"
    assert data["target_platforms"] == ["DOUYIN"]


def test_handles_empty_input():
    assert parse_topic_library("") == []
    assert parse_topic_library("只有说明文字，没有选题") == []

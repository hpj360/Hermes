"""选题库 markdown 解析器（IT-2：选题库结构化导入）。

解析 ``content-creation/01-前30天选题库.md`` 这类「前 N 天选题库」文档，
把每篇（``## 第N篇...`` 小节）解析为结构化选题输入，供导入选题池使用。

文档结构约定（与选题库模板一致）：
- ``## 第N篇（可选标签）：主题``   → 选题分组标题
- ``**标题方向**：``                → 标题候选列表（- 开头）
- ``**内容方向**：``                → 内容大纲列表（- 开头）
- ``**关键词**：``                  → 关键词（顿号/逗号分隔）

解析对格式容忍：字段缺失时取空值，不抛异常；只解析含 ``标题方向``
的"内容篇"，跳过话题标签库等非选题小节。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["ParsedTopic", "parse_topic_library"]

# 小节标题：## 第1篇（启动篇）：人设建立 / ## 第1篇：人设建立 / ## 第2篇（金汤力入门）：你的拿手酒
_SECTION_RE = re.compile(r"^##\s*(第\s*\d+\s*篇)[：:（(]*(.*?)[）)]*$")
_FIELD_RE = re.compile(r"^\*\*(标题方向|内容方向|关键词)\*\*[：:]\s*(.*)$")
_TITLE_LINE_RE = re.compile(r"^[-*]\s*(.+)$")


def _extract_section_title(raw: str) -> str:
    """从小节标题提取主题，取最后一个（）：之后的文本。

    - ``第1篇（启动篇）：人设建立`` → ``人设建立``
    - ``第2篇：金汤力入门`` → ``金汤力入门``
    - ``第3篇 金酒推荐`` → ``金酒推荐``
    """
    # 取最后一个）：或：之后的内容
    for sep in ("）：", "):", "：", ":"):
        idx = raw.rfind(sep)
        if idx != -1:
            return raw[idx + len(sep) :].strip()
    return raw.strip()


@dataclass
class ParsedTopic:
    """从选题库文档解析出的一篇选题（结构化）。"""

    section_label: str  # "第1篇"
    topic_title: str  # 小节主题（如 "人设建立"）
    titles: list[str] = field(default_factory=list)  # 标题方向候选
    content: list[str] = field(default_factory=list)  # 内容方向大纲
    keywords: list[str] = field(default_factory=list)

    def to_topic_input(self, *, default_platform: str = "XIAOHONGSHU") -> dict[str, Any]:
        """转换为 ``TopicCreate`` 兼容的输入字典。

        - title：取首个标题候选（去书名号）；无候选时用小节主题兜底。
        - description：内容大纲逐条合并；无大纲时用小节主题。
        - target_platforms：默认小红书（冷启动主阵地），可覆盖。
        - keywords：解析出的关键词。
        """
        title = self.titles[0] if self.titles else self.topic_title
        title = title.strip("《》 ")
        description = "\n".join(f"- {c}" for c in self.content) or self.topic_title
        return {
            "title": title or self.topic_title,
            "description": description,
            "target_platforms": [default_platform],
            "keywords": self.keywords,
        }


def _split_keywords(text: str) -> list[str]:
    """按顿号/逗号/分号拆分关键词，去空白与空项。"""
    parts = re.split(r"[、，,;；]", text)
    return [p.strip() for p in parts if p.strip()]


def parse_topic_library(markdown: str) -> list[ParsedTopic]:
    """解析选题库 markdown 文本，返回结构化选题列表。"""
    topics: list[ParsedTopic] = []
    current: ParsedTopic | None = None
    field_name: str | None = None

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        section_match = _SECTION_RE.match(line.strip())
        if section_match:
            # 完成上一篇
            if current is not None:
                topics.append(current)
            label = section_match.group(1)
            current = ParsedTopic(
                section_label=label,
                topic_title=_extract_section_title(section_match.group(2)),
            )
            field_name = None
            continue

        # 任意 ## 二级标题（如"话题标签库"）都终止当前选题收集
        if line.strip().startswith("## ") and current is not None:
            topics.append(current)
            current = None
            field_name = None
            continue

        field_match = _FIELD_RE.match(line.strip())
        if field_match:
            field_name = field_match.group(1)
            inline = field_match.group(2).strip()
            # current 可能仍为 None（字段行出现在首个小节标题之前）：
            # 按"解析容忍、不抛异常"的模块约定跳过无归属字段。
            if field_name == "关键词" and inline and current is not None:
                current.keywords.extend(_split_keywords(inline))
            continue

        if current is None:
            continue  # 前置说明行，忽略

        if field_name == "关键词" and not line.startswith(("-", "*")):
            current.keywords.extend(_split_keywords(line))
            continue

        if field_name in ("标题方向", "内容方向"):
            title_line = _TITLE_LINE_RE.match(line.strip())
            if title_line:
                item = title_line.group(1).strip()
                if field_name == "标题方向":
                    current.titles.append(item)
                else:
                    current.content.append(item)

    if current is not None:
        topics.append(current)
    return topics

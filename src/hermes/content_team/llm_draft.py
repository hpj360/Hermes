"""LLM 驱动的平台化草稿生成（真实创作路径）。

在模板 SOP（:func:`hermes.content_team.sop.build_draft`）之上提供"真实 AI
创作"通道：调用 Hermes LLM 层，按目标平台（小红书/抖音等）的长度限制与文风
生成标题、正文与话题标签。

设计原则：
1. **可用性优先**：任何失败（未配置 LLM、网络错误、JSON 解析失败、字段缺失）
   都回退到模板草稿，绝不因 LLM 不可用而让创作链路中断。
2. **零硬依赖**：LLM 客户端经 :func:`make_llm_client` 惰性获取，且可注入
   （测试用 fake client，无需网络）。
3. **平台规范内收**：标题/正文按平台上限截断，避免生成超限内容。
"""
from __future__ import annotations

from typing import Any

from hermes.content_team.models.platform import Platform
from hermes.content_team.models.topic import Topic
from hermes.content_team.sop import (
    PLATFORM_BODY_LIMIT,
    PLATFORM_TITLE_LIMIT,
    Draft,
    build_draft,
)

__all__ = ["generate_llm_draft", "LLM_DRAFT_MAX_TOKENS"]

# 生成草稿的 token 上限（约 600-900 中文字，足够一条社媒内容）
LLM_DRAFT_MAX_TOKENS = 1600

_SYSTEM_PROMPT = (
    "你是资深中文社媒内容创作者，擅长小红书与抖音平台的文案创作。"
    "严格遵守平台规范，只输出 JSON，不要输出任何解释文字。"
)

_PLATFORM_STYLE: dict[Platform, str] = {
    Platform.XIAOHONGSHU: (
        "小红书图文：口语化、有亲和力，适度使用 emoji；开头一句话钩子，"
        "正文分点讲清卖点/体验，结尾引导互动（点赞/收藏/评论）。"
    ),
    Platform.DOUYIN: (
        "抖音短视频口播文案：前 3 秒必须抓人，节奏明快，句子短、口语化，"
        "结尾给出互动引导。"
    ),
}


def _default_client() -> Any | None:
    """Build the default LLM client, or None when unavailable."""
    try:
        from hermes.workbench.llm import make_llm_client

        return make_llm_client()
    except Exception:  # noqa: BLE001 — 创作链路必须可降级
        return None


def _build_prompt(
    topic: Topic, platform: Platform, title_limit: int, body_limit: int
) -> str:
    """Build the user prompt describing the topic and platform constraints."""
    style = _PLATFORM_STYLE.get(platform, "通用中文社媒文案。")
    keywords = "、".join(topic.keywords or []) or "（无）"
    description = (topic.description or "").strip() or "（无）"
    return (
        f"请为「{platform.value}」平台创作一条内容。\n"
        f"平台风格要求：{style}\n"
        f"选题标题：{topic.title}\n"
        f"内容方向：{description}\n"
        f"关键词（尽量自然融入）：{keywords}\n\n"
        f"硬性约束：标题不超过 {title_limit} 个字符；正文不超过 {body_limit} 个字符。\n"
        "请严格输出如下 JSON（不要 markdown 代码块、不要多余文字）：\n"
        '{"title": "标题", "body": "正文（含换行用 \\n）", '
        '"hashtags": ["话题1", "话题2", "话题3"]}\n'
    )


def _normalize_hashtags(raw: Any) -> list[str]:
    """Clean model-provided hashtags: strip leading '#', drop empties, dedupe."""
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    tags: list[str] = []
    for item in raw:
        tag = str(item).strip().lstrip("#").strip()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def _dedupe(items: list[str]) -> list[str]:
    """Return *items* with duplicates/empties removed, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = (item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def generate_llm_draft(
    topic: Topic,
    platform: Platform = Platform.XIAOHONGSHU,
    *,
    llm_client: Any | None = None,
    max_tokens: int = LLM_DRAFT_MAX_TOKENS,
) -> Draft:
    """生成平台化草稿；LLM 不可用时回退模板草稿。

    :param topic: 选题（提供标题/描述/关键词）
    :param platform: 目标平台（决定文风与长度上限）
    :param llm_client: 可注入的 LLM 客户端（测试用）；None 走默认工厂
    :param max_tokens: 生成 token 上限
    """
    title_limit = PLATFORM_TITLE_LIMIT.get(platform, 20)
    body_limit = PLATFORM_BODY_LIMIT.get(platform, 1000)

    client = llm_client or _default_client()
    if client is None:
        return build_draft(topic, platform)

    try:
        from hermes.workbench.llm import LlmMessage, _extract_json

        resp = client.chat(
            [
                LlmMessage(role="system", content=_SYSTEM_PROMPT),
                LlmMessage(
                    role="user",
                    content=_build_prompt(topic, platform, title_limit, body_limit),
                ),
            ],
            max_tokens=max_tokens,
        )
        data = _extract_json(resp.content or "")
    except Exception:  # noqa: BLE001 — 任何失败都回退模板
        return build_draft(topic, platform)

    title = str(data.get("title", "")).strip()
    body = str(data.get("body", "")).strip()
    if not title or not body:
        return build_draft(topic, platform)

    title = _truncate(title, title_limit)
    body = _truncate(body, body_limit, ellipsis=False)

    template = build_draft(topic, platform)
    hashtags = _normalize_hashtags(data.get("hashtags"))
    return Draft(
        title=title,
        title_candidates=_dedupe([title, *template.title_candidates])[:3],
        body=body,
        hashtags=hashtags or template.hashtags,
        platform=platform.value,
        title_limit=title_limit,
        body_limit=body_limit,
        source="llm",
    )


def _truncate(text: str, limit: int, ellipsis: bool = True) -> str:
    """Truncate *text* to *limit* characters (CJK counts as one)."""
    if len(text) <= limit:
        return text
    if ellipsis and limit > 3:
        return text[: limit - 1] + "…"
    return text[:limit]

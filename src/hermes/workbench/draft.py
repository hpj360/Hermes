"""Platform-optimized LLM draft generation (generic workbench capability).

Given a topic (title / description / keywords) and a target platform, produce a
ready-to-edit draft — title candidates, body and hashtags — constrained to the
platform's length limits. Uses the configured LLM; **degrades to a deterministic
template** when the LLM is unavailable, so creation never blocks.

Kept in ``hermes.workbench`` (not any vertical) so it has no dependency on a
specific 内容 workflow and can be reused by content_team or the CLI. Zero extra
deps (stdlib only); the LLM client is injectable for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PLATFORM_BODY_LIMIT",
    "PLATFORM_TITLE_LIMIT",
    "Draft",
    "generate_draft",
]

# Platform length limits (characters). Keys are uppercase platform names so this
# module stays independent of any vertical's Platform enum.
PLATFORM_TITLE_LIMIT: dict[str, int] = {
    "XIAOHONGSHU": 20,
    "DOUYIN": 55,
    "WECHAT_OFFICIAL": 64,
    "WECHAT_VIDEO": 64,
    "BILIBILI": 80,
}
PLATFORM_BODY_LIMIT: dict[str, int] = {
    "XIAOHONGSHU": 1000,
    "DOUYIN": 5000,
    "WECHAT_OFFICIAL": 20000,
    "WECHAT_VIDEO": 20000,
    "BILIBILI": 2000,
}

_MAX_TOKENS = 1600

_SYSTEM_PROMPT = (
    "你是资深中文社媒内容创作者，擅长小红书与抖音平台的文案创作。"
    "严格遵守平台规范，只输出 JSON，不要输出任何解释文字。"
)

_PLATFORM_STYLE: dict[str, str] = {
    "XIAOHONGSHU": (
        "小红书图文：口语化、有亲和力，适度使用 emoji；开头一句话钩子，"
        "正文分点讲清卖点/体验，结尾引导互动。"
    ),
    "DOUYIN": (
        "抖音短视频口播文案：前 3 秒必须抓人，节奏明快，句子短、口语化，"
        "结尾给出互动引导。"
    ),
}


@dataclass
class Draft:
    """A generated draft (not persisted; caller edits/creates the record)."""

    title: str
    title_candidates: list[str] = field(default_factory=list)
    body: str = ""
    hashtags: list[str] = field(default_factory=list)
    platform: str = "XIAOHONGSHU"
    title_limit: int = 20
    body_limit: int = 1000
    source: str = "template"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "title_candidates": list(self.title_candidates),
            "body": self.body,
            "hashtags": list(self.hashtags),
            "platform": self.platform,
            "title_limit": self.title_limit,
            "body_limit": self.body_limit,
            "source": self.source,
        }


def _truncate(text: str, limit: int, ellipsis: bool = True) -> str:
    if len(text) <= limit:
        return text
    if ellipsis and limit > 3:
        return text[: limit - 1] + "…"
    return text[:limit]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = (item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _default_client() -> Any | None:
    try:
        from hermes.workbench.llm import make_llm_client

        return make_llm_client()
    except Exception:  # noqa: BLE001 — creation must be able to degrade
        return None


def _template_draft(
    title: str,
    description: str,
    keywords: list[str],
    platform: str,
    title_limit: int,
    body_limit: int,
) -> Draft:
    """Deterministic fallback draft (no LLM)."""
    first_kw = keywords[0] if keywords else ""
    base = title.strip() or (first_kw or "未命名内容")
    candidates = _dedupe(
        [
            _truncate(base, title_limit),
            _truncate(f"{first_kw}｜{base}" if first_kw else base, title_limit),
        ]
    )
    lines: list[str] = []
    desc = (description or "").strip()
    if desc:
        lines.append(desc)
        lines.append("")
    if keywords:
        lines.append("关键词：" + "、".join(keywords))
        lines.append("")
    lines.append("你最喜欢哪一种？评论区告诉我 👇")
    body = _truncate("\n".join(lines).strip(), body_limit, ellipsis=False)
    return Draft(
        title=candidates[0],
        title_candidates=candidates[:3],
        body=body,
        hashtags=list(keywords),
        platform=platform,
        title_limit=title_limit,
        body_limit=body_limit,
        source="template",
    )


def _build_prompt(
    title: str,
    description: str,
    keywords: list[str],
    platform: str,
    title_limit: int,
    body_limit: int,
) -> str:
    style = _PLATFORM_STYLE.get(platform, "通用中文社媒文案。")
    kw = "、".join(keywords) or "（无）"
    desc = (description or "").strip() or "（无）"
    return (
        f"请为「{platform}」平台创作一条内容。\n"
        f"平台风格要求：{style}\n"
        f"选题标题：{title}\n"
        f"内容方向：{desc}\n"
        f"关键词（尽量自然融入）：{kw}\n\n"
        f"硬性约束：标题不超过 {title_limit} 个字符；正文不超过 {body_limit} 个字符。\n"
        "请严格输出如下 JSON（不要 markdown 代码块、不要多余文字）：\n"
        '{"title": "标题", "body": "正文（换行用 \\n）", '
        '"hashtags": ["话题1", "话题2", "话题3"]}\n'
    )


def _normalize_hashtags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return _dedupe([str(t).lstrip("#") for t in raw])


def generate_draft(
    title: str,
    description: str = "",
    keywords: list[str] | None = None,
    platform: str = "XIAOHONGSHU",
    *,
    llm_client: Any | None = None,
    max_tokens: int = _MAX_TOKENS,
) -> Draft:
    """Generate a platform-optimized draft; falls back to a template.

    :param title: topic title
    :param description: content direction / talking points
    :param keywords: keywords to weave in / derive hashtags from
    :param platform: target platform (uppercase name; controls limits & style)
    :param llm_client: optional injected LLM client (tests); None → default
    """
    platform = (platform or "XIAOHONGSHU").upper()
    kws = [k.strip() for k in (keywords or []) if k and k.strip()]
    title_limit = PLATFORM_TITLE_LIMIT.get(platform, 20)
    body_limit = PLATFORM_BODY_LIMIT.get(platform, 1000)

    client = llm_client or _default_client()
    if client is None:
        return _template_draft(title, description, kws, platform, title_limit, body_limit)

    try:
        from hermes.workbench.llm import LlmMessage, _extract_json

        resp = client.chat(
            [
                LlmMessage(role="system", content=_SYSTEM_PROMPT),
                LlmMessage(
                    role="user",
                    content=_build_prompt(
                        title, description, kws, platform, title_limit, body_limit
                    ),
                ),
            ],
            max_tokens=max_tokens,
        )
        data = _extract_json(resp.content or "")
    except Exception:  # noqa: BLE001
        return _template_draft(title, description, kws, platform, title_limit, body_limit)

    out_title = str(data.get("title", "")).strip()
    out_body = str(data.get("body", "")).strip()
    if not out_title or not out_body:
        return _template_draft(title, description, kws, platform, title_limit, body_limit)

    out_title = _truncate(out_title, title_limit)
    out_body = _truncate(out_body, body_limit, ellipsis=False)
    hashtags = _normalize_hashtags(data.get("hashtags")) or kws
    return Draft(
        title=out_title,
        title_candidates=_dedupe([out_title, title])[:3],
        body=out_body,
        hashtags=hashtags,
        platform=platform,
        title_limit=title_limit,
        body_limit=body_limit,
        source="llm",
    )

"""外部趋势数据源（数据驱动选题 · Phase 1）。

Provider 协议 + 两个实现：

- ``HonghuTrendProvider``：红狐Hub HTTP API。需配置 ``HERMES_HONGHU_BASE_URL``
  与 ``HERMES_HONGHU_API_KEY``；未配置时显式抛 ``TrendSourceNotConfigured``。
  接口路径模板可配置（``HERMES_HONGHU_NOTES_PATH`` / ``HERMES_HONGHU_HOTLIST_PATH``），
  默认值需在拿到红狐Hub真实 API 契约后核对调整。
- ``FixtureTrendProvider``：离线确定性数据（开发/测试/演示），数据为虚构样例。

以及爆款笔记 → 选题导入的转换逻辑（去重、互动量过滤、低粉爆款筛选）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from hermes.content_team.observability import log_event

SUPPORTED_TREND_PLATFORMS = ("XIAOHONGSHU", "DOUYIN")


class TrendSourceNotConfigured(Exception):
    """趋势数据源未配置（缺 API Key / Base URL）。"""


@dataclass(frozen=True)
class HotNote:
    """一条爆款笔记样本。"""

    title: str
    platform: str
    likes: int = 0
    collects: int = 0
    comments: int = 0
    shares: int = 0
    author_fans: int | None = None
    url: str = ""
    category: str = ""
    published_at: str = ""
    source: str = "fixture"

    @property
    def engagement(self) -> int:
        """总互动量（点赞+收藏+评论+分享）。"""
        return self.likes + self.collects + self.comments + self.shares


@dataclass(frozen=True)
class HotListItem:
    """热榜条目（如抖音热榜）。"""

    rank: int
    title: str
    platform: str
    heat: int = 0
    tag: str = ""
    url: str = ""
    source: str = "fixture"


# ---------------------------------------------------------------------------
# Provider 协议与实现
# ---------------------------------------------------------------------------


class TrendProvider(Protocol):
    """趋势数据源协议。"""

    name: str

    async def fetch_hot_notes(
        self, keyword: str | None = None, limit: int = 20
    ) -> list[HotNote]: ...

    async def fetch_hot_list(self, limit: int = 50) -> list[HotListItem]: ...


class FixtureTrendProvider:
    """离线确定性数据源（开发/测试/演示，数据为虚构样例）。"""

    name = "fixture"

    _NOTES: tuple[HotNote, ...] = (
        HotNote(
            title="出租屋也能调出酒吧味的3杯酒",
            platform="XIAOHONGSHU",
            likes=820, collects=540, comments=96, shares=44,
            author_fans=1200, category="居家调酒",
        ),
        HotNote(
            title="第一次买金酒别踩这4个坑",
            platform="XIAOHONGSHU",
            likes=610, collects=720, comments=58, shares=30,
            author_fans=800, category="酒类推荐",
        ),
        HotNote(
            title="3块钱成本的自制莫吉托，同事喝完要配方",
            platform="XIAOHONGSHU",
            likes=1500, collects=980, comments=210, shares=120,
            author_fans=3500, category="居家调酒",
        ),
        HotNote(
            title="威士忌入门：先搞懂这3个产区再花钱",
            platform="XIAOHONGSHU",
            likes=430, collects=660, comments=75, shares=28,
            author_fans=2400, category="酒类推荐",
        ),
        HotNote(
            title="微醺不胖人的低卡调酒公式",
            platform="XIAOHONGSHU",
            likes=980, collects=1300, comments=140, shares=90,
            author_fans=2800, category="低卡微醺",
        ),
        HotNote(
            title="人均50的清吧平替：我家阳台小酒馆",
            platform="XIAOHONGSHU",
            likes=2100, collects=870, comments=320, shares=150,
            author_fans=4800, category="居家调酒",
        ),
    )

    _HOTLIST: tuple[HotListItem, ...] = (
        HotListItem(rank=1, title="夏日冰饮挑战赛", platform="DOUYIN", heat=9820000, tag="热"),
        HotListItem(rank=2, title="便利店调酒新喝法", platform="DOUYIN", heat=6510000, tag="上升"),
        HotListItem(rank=3, title="夜市美食地图", platform="DOUYIN", heat=5240000, tag="热"),
        HotListItem(rank=4, title="微醺时刻氛围感", platform="DOUYIN", heat=3180000, tag="荐"),
        HotListItem(rank=5, title="独居生活治愈日常", platform="DOUYIN", heat=2760000, tag="热"),
    )

    async def fetch_hot_notes(
        self, keyword: str | None = None, limit: int = 20
    ) -> list[HotNote]:
        notes = list(self._NOTES)
        if keyword:
            kw = keyword.strip()
            notes = [
                n for n in notes
                if kw in n.title or kw in n.category
            ] or notes  # 无命中时返回全量，保证可用性
        return notes[:limit]

    async def fetch_hot_list(self, limit: int = 50) -> list[HotListItem]:
        return list(self._HOTLIST)[:limit]


class HonghuTrendProvider:
    """红狐Hub HTTP 数据源（需配置 API Key）。

    环境变量：
    - ``HERMES_HONGHU_BASE_URL``：服务基址，如 ``https://api.honghu.example``
    - ``HERMES_HONGHU_API_KEY``：Bearer Token
    - ``HERMES_HONGHU_NOTES_PATH``：爆款笔记接口路径（默认 ``/v1/xhs/hot-notes``）
    - ``HERMES_HONGHU_HOTLIST_PATH``：热榜接口路径（默认 ``/v1/douyin/hot-list``）

    注意：默认路径为占位约定，接入前必须按红狐Hub真实契约核对调整。
    """

    name = "honghu"

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @classmethod
    def from_env(cls) -> "HonghuTrendProvider":
        base = os.getenv("HERMES_HONGHU_BASE_URL", "").strip()
        key = os.getenv("HERMES_HONGHU_API_KEY", "").strip()
        if not base or not key:
            raise TrendSourceNotConfigured(
                "红狐Hub 数据源未配置：需要 HERMES_HONGHU_BASE_URL 与 "
                "HERMES_HONGHU_API_KEY 环境变量"
            )
        return cls(base, key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def fetch_hot_notes(
        self, keyword: str | None = None, limit: int = 20
    ) -> list[HotNote]:
        path = os.getenv("HERMES_HONGHU_NOTES_PATH", "/v1/xhs/hot-notes")
        params: dict[str, Any] = {"limit": limit}
        if keyword:
            params["keyword"] = keyword
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            payload = resp.json()
        items = payload.get("notes") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("红狐Hub 返回格式不符：缺少 notes 列表")
        return [_parse_note(i, "honghu") for i in items][:limit]

    async def fetch_hot_list(self, limit: int = 50) -> list[HotListItem]:
        path = os.getenv("HERMES_HONGHU_HOTLIST_PATH", "/v1/douyin/hot-list")
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                params={"limit": limit},
            )
            resp.raise_for_status()
            payload = resp.json()
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("红狐Hub 返回格式不符：缺少 items 列表")
        return [_parse_hotlist_item(i, "honghu") for i in items][:limit]


def _parse_note(item: dict[str, Any], source: str) -> HotNote:
    """把 Provider 返回的字典解析为 HotNote（宽松字段映射）。"""
    metrics = item.get("metrics") or {}
    return HotNote(
        title=str(item.get("title") or item.get("note_title") or "").strip(),
        platform=str(item.get("platform") or "XIAOHONGSHU"),
        likes=int(metrics.get("likes") or item.get("likes") or 0),
        collects=int(metrics.get("collects") or item.get("collects") or 0),
        comments=int(metrics.get("comments") or item.get("comments") or 0),
        shares=int(metrics.get("shares") or item.get("shares") or 0),
        author_fans=item.get("author_fans"),
        url=str(item.get("url") or item.get("note_url") or ""),
        category=str(item.get("category") or item.get("tag") or ""),
        published_at=str(item.get("published_at") or ""),
        source=source,
    )


def _parse_hotlist_item(item: dict[str, Any], source: str) -> HotListItem:
    return HotListItem(
        rank=int(item.get("rank") or item.get("position") or 0),
        title=str(item.get("title") or item.get("topic") or "").strip(),
        platform=str(item.get("platform") or "DOUYIN"),
        heat=int(item.get("heat") or item.get("heat_value") or 0),
        tag=str(item.get("tag") or ""),
        url=str(item.get("url") or ""),
        source=source,
    )


def get_trend_provider(platform: str) -> TrendProvider:
    """按优先级返回数据源：红狐Hub 已配置则用之，否则回退 fixture。"""
    try:
        return HonghuTrendProvider.from_env()
    except TrendSourceNotConfigured:
        return FixtureTrendProvider()


# ---------------------------------------------------------------------------
# 爆款笔记 → 选题转换
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """标题归一化（去空白/全半角差异），用于去重。"""
    return _WS_RE.sub("", title).lower()


def hot_notes_to_topic_inputs(
    notes: list[HotNote],
    *,
    min_engagement: int = 500,
    max_fans: int | None = None,
    exclude_titles: set[str] | None = None,
) -> list[dict[str, Any]]:
    """把爆款笔记转换为选题创建载荷（Topic API 兼容格式）。

    - 过滤：总互动量低于 ``min_engagement`` 的剔除；
      ``max_fans`` 非空时仅保留粉丝量不超过该值的笔记（低粉爆款模式）。
    - 去重：按归一化标题，且跳过 ``exclude_titles`` 中已存在的标题。
    - 排序：互动量降序。
    """
    exclude = {_normalize_title(t) for t in (exclude_titles or set())}
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []

    for note in notes:
        if note.engagement < min_engagement:
            continue
        if max_fans is not None and note.author_fans is not None:
            if note.author_fans > max_fans:
                continue
        key = _normalize_title(note.title)
        if not key or key in seen or key in exclude:
            continue
        seen.add(key)
        keywords = [w for w in (note.category, note.platform) if w]
        rows.append(
            {
                "title": note.title[:255],
                "description": (
                    f"爆款参考（{note.source}）：赞{note.likes} 藏{note.collects} "
                    f"评{note.comments} 传{note.shares}"
                    + (f"；粉丝{note.author_fans}" if note.author_fans is not None else "")
                    + (f"；来源 {note.url}" if note.url else "")
                ),
                "priority": 3,
                "target_platforms": [note.platform],
                "keywords": keywords,
            }
        )

    rows.sort(
        key=lambda r: next(
            (n.engagement for n in notes if n.title == r["title"]), 0
        ),
        reverse=True,
    )
    return rows


async def collect_topic_suggestions(
    platform: str,
    keyword: str | None = None,
    limit: int = 20,
    min_engagement: int = 500,
    max_fans: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """拉取爆款并转换为选题建议，返回 (rows, provider_name)。"""
    provider = get_trend_provider(platform)
    notes = await provider.fetch_hot_notes(keyword=keyword, limit=limit)
    rows = hot_notes_to_topic_inputs(
        notes, min_engagement=min_engagement, max_fans=max_fans
    )
    log_event(
        "trend_suggestions_collected",
        "爆款选题建议已生成",
        platform=platform,
        provider=provider.name,
        notes=len(notes),
        suggestions=len(rows),
    )
    return rows, provider.name

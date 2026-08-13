"""Content-team memory integration.

Wraps hermes workbench MemoryService for content-team specific use cases:
- L1 facts: topic preferences, platform settings
- L2 episodes: topic creation, scoring, publishing events
- L3 profile: user content expertise and preferences
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes.workbench.memory import Episode, MemoryService, make_episode


# 存储目录：项目根目录下的 data/content_team_memory/
_STORAGE_DIR = Path(__file__).resolve().parents[3] / "data" / "content_team_memory"

# 单例 MemoryService 实例
_memory_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    """获取（或首次初始化）content_team 的单例 MemoryService。

    存储位置为 data/content_team_memory/，目录不存在时自动创建。
    """
    global _memory_service
    if _memory_service is None:
        _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        _memory_service = MemoryService(state_dir=_STORAGE_DIR)
    return _memory_service


# ---------------------------------------------------------------------------
# L2 — 事件记录
# ---------------------------------------------------------------------------


def record_topic_created(
    topic_id: str,
    title: str,
    platforms: list[str],
    author: str,
    service: MemoryService | None = None,
) -> Episode:
    """记录"选题创建"事件到 L2 episodes。"""
    svc = service or get_memory_service()
    episode = make_episode(
        kind="topic_created",
        summary=f"选题创建: {title}",
        details={
            "topic_id": topic_id,
            "title": title,
            "platforms": platforms,
            "author": author,
        },
    )
    svc.record_episode(episode)
    return episode


def record_topic_scored(
    topic_id: str,
    scores: dict[str, Any],
    scorer: str,
    service: MemoryService | None = None,
) -> Episode:
    """记录"选题评分"事件到 L2 episodes。"""
    svc = service or get_memory_service()
    episode = make_episode(
        kind="topic_scored",
        summary=f"选题评分: {topic_id}",
        details={
            "topic_id": topic_id,
            "scores": scores,
            "scorer": scorer,
        },
    )
    svc.record_episode(episode)
    return episode


def record_content_published(
    content_id: str,
    topic_id: str,
    platform: str,
    status: str,
    service: MemoryService | None = None,
) -> Episode:
    """记录"内容发布"事件到 L2 episodes。"""
    svc = service or get_memory_service()
    episode = make_episode(
        kind="content_published",
        summary=f"内容发布: {content_id} -> {platform}",
        details={
            "content_id": content_id,
            "topic_id": topic_id,
            "platform": platform,
            "status": status,
        },
    )
    svc.record_episode(episode)
    return episode


# ---------------------------------------------------------------------------
# L1 — 选题偏好
# ---------------------------------------------------------------------------

_TOPIC_PREF_PREFIX = "topic_pref_"


def save_topic_preference(
    key: str,
    value: Any,
    service: MemoryService | None = None,
) -> None:
    """将选题偏好保存到 L1 facts（键名自动加 topic_pref_ 前缀）。"""
    svc = service or get_memory_service()
    svc.remember_fact(_TOPIC_PREF_PREFIX + key, value)


def get_topic_preference(
    key: str,
    default: Any = None,
    service: MemoryService | None = None,
) -> Any:
    """从 L1 facts 读取选题偏好；不存在时返回 default。"""
    svc = service or get_memory_service()
    fact = svc.get_fact(_TOPIC_PREF_PREFIX + key)
    if fact is None:
        return default
    return fact["value"]


# ---------------------------------------------------------------------------
# L3 — 用户画像
# ---------------------------------------------------------------------------


def update_user_profile(
    updates: dict[str, Any],
    service: MemoryService | None = None,
) -> dict[str, Any]:
    """更新用户画像，将 updates 合并到现有画像中。

    优先委托给 hermes.profile（通过 MemoryService 的 profile saver）；
    若委托失败则回退到 L1 facts 的 "user_profile" 键存储。
    """
    svc = service or get_memory_service()
    try:
        profile = svc.get_user_profile()
        if not isinstance(profile, dict):
            profile = {}
        profile.update(updates)
        svc.save_user_profile(profile)
        return profile
    except Exception:
        # 回退到 L1 facts 存储
        existing = svc.get_fact("user_profile")
        profile = existing["value"] if existing else {}
        if not isinstance(profile, dict):
            profile = {}
        profile.update(updates)
        svc.remember_fact("user_profile", profile)
        return profile


# ---------------------------------------------------------------------------
# L2 — 查询
# ---------------------------------------------------------------------------


def get_recent_episodes(
    kind: str | None = None,
    limit: int = 20,
    service: MemoryService | None = None,
) -> list[Episode]:
    """获取最近的 L2 episodes，可按 kind 过滤，默认返回 20 条。"""
    svc = service or get_memory_service()
    return svc.list_episodes(kind=kind, limit=limit)


def search_episodes(
    query: str,
    limit: int = 10,
    service: MemoryService | None = None,
) -> list[tuple[Episode, float]]:
    """基于 TF-IDF + 余弦相似度搜索 L2 episodes，返回 (episode, score) 元组列表。"""
    svc = service or get_memory_service()
    return svc.search_episodes(query, limit=limit)

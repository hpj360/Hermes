"""Tests for hermes.content_team.memory integration.

每个测试都创建独立的 MemoryService 实例（指向 tmp_path 临时目录），
确保测试之间互不干扰。
"""

from __future__ import annotations

from pathlib import Path

from hermes.content_team import memory as ct_memory
from hermes.workbench.memory import MemoryService


def _make_service(tmp_path: Path) -> MemoryService:
    """创建指向临时目录的 MemoryService 实例，用于测试隔离。"""
    return MemoryService(state_dir=tmp_path / "ct_state")


# ---------------------------------------------------------------------------
# L1 facts — 选题偏好读写
# ---------------------------------------------------------------------------


def test_save_and_get_topic_preference(tmp_path: Path) -> None:
    """save_topic_preference 写入后 get_topic_preference 应读回相同值。"""
    svc = _make_service(tmp_path)
    ct_memory.save_topic_preference("tone", "幽默风趣", service=svc)
    assert ct_memory.get_topic_preference("tone", service=svc) == "幽默风趣"


def test_get_topic_preference_returns_default_when_missing(tmp_path: Path) -> None:
    """不存在的偏好键应返回 default 值。"""
    svc = _make_service(tmp_path)
    assert ct_memory.get_topic_preference("missing", default="默认值", service=svc) == "默认值"


def test_topic_preference_stored_with_prefix(tmp_path: Path) -> None:
    """偏好应存储在 topic_pref_ 前缀键下。"""
    svc = _make_service(tmp_path)
    ct_memory.save_topic_preference("platform", "抖音", service=svc)
    fact = svc.get_fact("topic_pref_platform")
    assert fact is not None
    assert fact["value"] == "抖音"
    # 原始键不应存在
    assert svc.get_fact("platform") is None


def test_topic_preference_overwrites(tmp_path: Path) -> None:
    """相同键的偏好应覆盖旧值。"""
    svc = _make_service(tmp_path)
    ct_memory.save_topic_preference("style", "干货", service=svc)
    ct_memory.save_topic_preference("style", "故事", service=svc)
    assert ct_memory.get_topic_preference("style", service=svc) == "故事"


# ---------------------------------------------------------------------------
# L2 episodes — 事件记录
# ---------------------------------------------------------------------------


def test_record_topic_created_creates_episode(tmp_path: Path) -> None:
    """record_topic_created 应在 L2 创建 kind=topic_created 的事件。"""
    svc = _make_service(tmp_path)
    ep = ct_memory.record_topic_created(
        topic_id="t1",
        title="如何入门 Python",
        platforms=["抖音", "小红书"],
        author="Alice",
        service=svc,
    )
    assert ep.kind == "topic_created"
    episodes = svc.list_episodes(kind="topic_created")
    assert len(episodes) == 1
    assert episodes[0].id == ep.id
    assert episodes[0].details["topic_id"] == "t1"
    assert episodes[0].details["title"] == "如何入门 Python"
    assert episodes[0].details["platforms"] == ["抖音", "小红书"]
    assert episodes[0].details["author"] == "Alice"


def test_record_topic_scored_creates_episode(tmp_path: Path) -> None:
    """record_topic_scored 应在 L2 创建 kind=topic_scored 的事件。"""
    svc = _make_service(tmp_path)
    ep = ct_memory.record_topic_scored(
        topic_id="t1",
        scores={"heat": 8.5, "feasibility": 7.0},
        scorer="llm-judge",
        service=svc,
    )
    assert ep.kind == "topic_scored"
    episodes = svc.list_episodes(kind="topic_scored")
    assert len(episodes) == 1
    assert episodes[0].details["topic_id"] == "t1"
    assert episodes[0].details["scores"] == {"heat": 8.5, "feasibility": 7.0}
    assert episodes[0].details["scorer"] == "llm-judge"


def test_record_content_published_creates_episode(tmp_path: Path) -> None:
    """record_content_published 应在 L2 创建 kind=content_published 的事件。"""
    svc = _make_service(tmp_path)
    ep = ct_memory.record_content_published(
        content_id="c1",
        topic_id="t1",
        platform="抖音",
        status="published",
        service=svc,
    )
    assert ep.kind == "content_published"
    episodes = svc.list_episodes(kind="content_published")
    assert len(episodes) == 1
    assert episodes[0].details["content_id"] == "c1"
    assert episodes[0].details["topic_id"] == "t1"
    assert episodes[0].details["platform"] == "抖音"
    assert episodes[0].details["status"] == "published"


# ---------------------------------------------------------------------------
# L2 episodes — 搜索
# ---------------------------------------------------------------------------


def test_search_episodes_returns_relevant(tmp_path: Path) -> None:
    """search_episodes 应基于 TF-IDF 返回相关事件。"""
    svc = _make_service(tmp_path)
    ct_memory.record_topic_created(
        topic_id="t1",
        title="Python 入门教程",
        platforms=["抖音"],
        author="Alice",
        service=svc,
    )
    ct_memory.record_topic_created(
        topic_id="t2",
        title="JavaScript 前端开发",
        platforms=["小红书"],
        author="Bob",
        service=svc,
    )
    results = ct_memory.search_episodes("Python", service=svc)
    assert len(results) >= 1
    # 最相关的结果应包含 Python
    top_ep = results[0][0]
    assert "Python" in top_ep.summary or "Python" in str(top_ep.details)
    # JavaScript 事件不应出现在结果中
    for ep, _ in results:
        assert "JavaScript" not in ep.summary


def test_search_episodes_empty_when_no_match(tmp_path: Path) -> None:
    """无匹配时搜索应返回空列表。"""
    svc = _make_service(tmp_path)
    ct_memory.record_topic_created(
        topic_id="t1",
        title="Python 入门",
        platforms=["抖音"],
        author="Alice",
        service=svc,
    )
    results = ct_memory.search_episodes("量子物理", service=svc)
    assert results == []


def test_search_episodes_scores_positive(tmp_path: Path) -> None:
    """搜索结果的相似度分数应为正数。"""
    svc = _make_service(tmp_path)
    ct_memory.record_topic_created(
        topic_id="t1",
        title="Python 教程",
        platforms=["抖音"],
        author="Alice",
        service=svc,
    )
    results = ct_memory.search_episodes("Python", service=svc)
    for _ep, score in results:
        assert score > 0.0


# ---------------------------------------------------------------------------
# L2 episodes — 最近事件过滤
# ---------------------------------------------------------------------------


def test_get_recent_episodes_filter_by_kind(tmp_path: Path) -> None:
    """get_recent_episodes 应能按 kind 过滤。"""
    svc = _make_service(tmp_path)
    ct_memory.record_topic_created("t1", "选题A", ["抖音"], "Alice", service=svc)
    ct_memory.record_topic_scored("t1", {"heat": 9}, "judge", service=svc)
    ct_memory.record_topic_created("t2", "选题B", ["小红书"], "Bob", service=svc)

    created = ct_memory.get_recent_episodes(kind="topic_created", service=svc)
    assert len(created) == 2
    assert all(e.kind == "topic_created" for e in created)

    scored = ct_memory.get_recent_episodes(kind="topic_scored", service=svc)
    assert len(scored) == 1
    assert scored[0].kind == "topic_scored"


def test_get_recent_episodes_respects_limit(tmp_path: Path) -> None:
    """get_recent_episodes 应遵守 limit 参数。"""
    svc = _make_service(tmp_path)
    for i in range(5):
        ct_memory.record_topic_created(f"t{i}", f"选题{i}", ["抖音"], "Alice", service=svc)
    episodes = ct_memory.get_recent_episodes(kind="topic_created", limit=2, service=svc)
    assert len(episodes) == 2


def test_get_recent_episodes_returns_newest_first(tmp_path: Path) -> None:
    """get_recent_episodes 应按最新优先返回。"""
    svc = _make_service(tmp_path)
    ct_memory.record_topic_created("t1", "第一个", ["抖音"], "Alice", service=svc)
    ct_memory.record_topic_created("t2", "第二个", ["抖音"], "Alice", service=svc)
    ct_memory.record_topic_created("t3", "第三个", ["抖音"], "Alice", service=svc)
    episodes = ct_memory.get_recent_episodes(kind="topic_created", service=svc)
    titles = [e.details["title"] for e in episodes]
    assert titles == ["第三个", "第二个", "第一个"]


def test_get_recent_episodes_no_kind_returns_all(tmp_path: Path) -> None:
    """不指定 kind 时应返回所有类型的事件。"""
    svc = _make_service(tmp_path)
    ct_memory.record_topic_created("t1", "选题A", ["抖音"], "Alice", service=svc)
    ct_memory.record_topic_scored("t1", {"heat": 9}, "judge", service=svc)
    episodes = ct_memory.get_recent_episodes(service=svc)
    assert len(episodes) == 2


# ---------------------------------------------------------------------------
# L3 — 用户画像
# ---------------------------------------------------------------------------


def test_update_user_profile_delegates_to_saver(tmp_path: Path) -> None:
    """update_user_profile 应通过 profile_saver 委托保存。"""
    saved: list[dict] = []
    svc = MemoryService(
        state_dir=tmp_path / "ct_state",
        profile_loader=lambda: {"version": 4, "basic_info": {"name": "Alice"}},
        profile_saver=saved.append,
    )
    result = ct_memory.update_user_profile(
        {"content_creation": {"status": "active"}}, service=svc
    )
    # 应合并到已有画像
    assert result["basic_info"]["name"] == "Alice"
    assert result["content_creation"]["status"] == "active"
    # saver 应被调用一次
    assert len(saved) == 1
    assert saved[0]["content_creation"]["status"] == "active"
    assert saved[0]["basic_info"]["name"] == "Alice"


def test_update_user_profile_falls_back_to_l1(tmp_path: Path) -> None:
    """当 profile 保存失败时，应回退到 L1 facts 的 user_profile 键。"""

    def _failing_saver(profile: dict) -> None:
        raise RuntimeError("save failed")

    svc = MemoryService(
        state_dir=tmp_path / "ct_state",
        profile_loader=lambda: {"version": 4},
        profile_saver=_failing_saver,
    )
    result = ct_memory.update_user_profile({"expertise": "Python"}, service=svc)
    assert result["expertise"] == "Python"
    # 应存储在 L1 facts 的 user_profile 键下
    fact = svc.get_fact("user_profile")
    assert fact is not None
    assert fact["value"]["expertise"] == "Python"

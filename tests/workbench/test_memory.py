"""Tests for hermes.workbench.memory.MemoryService (L1/L2/L3)."""

from __future__ import annotations

import time as _time
from pathlib import Path

from hermes.workbench.memory import (
    Episode,
    MemoryService,
    make_episode,
)


def _make_service(tmp_path: Path) -> MemoryService:
    return MemoryService(state_dir=tmp_path / "state")


# ---------------------------------------------------------------------------
# Episode factory
# ---------------------------------------------------------------------------


def test_make_episode_generates_id_and_timestamp() -> None:
    ep = make_episode("loop", "ran a plan", {"steps": 2})
    assert isinstance(ep, Episode)
    assert ep.kind == "loop"
    assert ep.summary == "ran a plan"
    assert ep.details == {"steps": 2}
    assert isinstance(ep.id, str) and len(ep.id) > 0
    assert ep.created_at > 0


def test_make_episode_default_details_empty() -> None:
    ep = make_episode("note", "hi")
    assert ep.details == {}


def test_make_episode_ids_unique() -> None:
    a = make_episode("k", "a")
    b = make_episode("k", "b")
    assert a.id != b.id


# ---------------------------------------------------------------------------
# L1 facts
# ---------------------------------------------------------------------------


def test_remember_and_get_fact(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.remember_fact("color", "blue")
    fact = svc.get_fact("color")
    assert fact == {"key": "color", "value": "blue"}


def test_get_fact_missing_returns_none(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    assert svc.get_fact("nope") is None


def test_remember_fact_overwrites(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.remember_fact("k", 1)
    svc.remember_fact("k", 2)
    assert svc.get_fact("k") == {"key": "k", "value": 2}


def test_list_facts_empty(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    assert svc.list_facts() == []


def test_list_facts_returns_all(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.remember_fact("a", 1)
    svc.remember_fact("b", 2)
    facts = {f["key"]: f["value"] for f in svc.list_facts()}
    assert facts == {"a": 1, "b": 2}


def test_forget_fact_returns_true_when_present(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.remember_fact("k", "v")
    assert svc.forget_fact("k") is True
    assert svc.get_fact("k") is None


def test_forget_fact_returns_false_when_missing(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    assert svc.forget_fact("k") is False


def test_facts_persist_across_instances(tmp_path: Path) -> None:
    svc1 = _make_service(tmp_path)
    svc1.remember_fact("persisted", True)
    svc2 = _make_service(tmp_path)
    assert svc2.get_fact("persisted") == {"key": "persisted", "value": True}


def test_facts_survive_corrupt_file(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "facts.json").write_text("{ broken", encoding="utf-8")
    svc = MemoryService(state_dir=state)
    # Corrupt facts.json should be treated as empty
    assert svc.list_facts() == []


# ---------------------------------------------------------------------------
# L1 facts — TTL
# ---------------------------------------------------------------------------


def test_fact_ttl_expires(tmp_path: Path, monkeypatch) -> None:
    """A fact with TTL is purged after the TTL elapses."""
    import hermes.workbench.memory as mem

    base = _time.time()
    monkeypatch.setattr(mem.time, "time", lambda: base)
    svc = _make_service(tmp_path)
    svc.remember_fact("temp", "secret", ttl=10)
    assert svc.get_fact("temp") is not None
    # Advance past TTL
    monkeypatch.setattr(mem.time, "time", lambda: base + 11)
    assert svc.get_fact("temp") is None


def test_fact_ttl_not_yet_expired(tmp_path: Path, monkeypatch) -> None:
    """A fact with TTL is still readable before expiry."""
    import hermes.workbench.memory as mem

    base = _time.time()
    monkeypatch.setattr(mem.time, "time", lambda: base)
    svc = _make_service(tmp_path)
    svc.remember_fact("temp", "value", ttl=100)
    monkeypatch.setattr(mem.time, "time", lambda: base + 50)
    assert svc.get_fact("temp") == {"key": "temp", "value": "value"}


def test_fact_ttl_purged_from_list(tmp_path: Path, monkeypatch) -> None:
    """Expired facts are excluded from list_facts."""
    import hermes.workbench.memory as mem

    base = _time.time()
    monkeypatch.setattr(mem.time, "time", lambda: base)
    svc = _make_service(tmp_path)
    svc.remember_fact("permanent", "keep")
    svc.remember_fact("temp", "gone", ttl=5)
    monkeypatch.setattr(mem.time, "time", lambda: base + 6)
    facts = {f["key"]: f["value"] for f in svc.list_facts()}
    assert facts == {"permanent": "keep"}


def test_fact_without_ttl_persists(tmp_path: Path) -> None:
    """Facts without TTL are never purged."""
    svc = _make_service(tmp_path)
    svc.remember_fact("stable", "val")
    assert svc.get_fact("stable") == {"key": "stable", "value": "val"}


def test_forget_fact_clears_ttl(tmp_path: Path) -> None:
    """Forgetting a fact also removes its TTL entry."""
    svc = _make_service(tmp_path)
    svc.remember_fact("temp", "v", ttl=60)
    assert svc._fact_ttls_path.exists()
    svc.forget_fact("temp")
    # TTL file should not contain the key
    import json
    ttls = json.loads(svc._fact_ttls_path.read_text())
    assert "temp" not in ttls


# ---------------------------------------------------------------------------
# L2 episodes
# ---------------------------------------------------------------------------


def test_record_and_list_episode(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    ep = make_episode("loop", "ran plan")
    svc.record_episode(ep)
    items = svc.list_episodes()
    assert len(items) == 1
    assert items[0].id == ep.id
    assert items[0].kind == "loop"
    assert items[0].summary == "ran plan"


def test_list_episodes_empty(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    assert svc.list_episodes() == []


def test_list_episodes_filter_by_kind(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("loop", "a"))
    svc.record_episode(make_episode("note", "b"))
    svc.record_episode(make_episode("loop", "c"))
    loops = svc.list_episodes(kind="loop")
    assert len(loops) == 2
    assert all(e.kind == "loop" for e in loops)


def test_list_episodes_returns_newest_first(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("k", "first"))
    svc.record_episode(make_episode("k", "second"))
    svc.record_episode(make_episode("k", "third"))
    items = svc.list_episodes()
    assert [e.summary for e in items] == ["third", "second", "first"]


def test_list_episodes_limit(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    for i in range(10):
        svc.record_episode(make_episode("k", f"ep{i}"))
    items = svc.list_episodes(limit=3)
    assert len(items) == 3
    # Newest first → last three recorded
    assert [e.summary for e in items] == ["ep9", "ep8", "ep7"]


def test_list_episodes_limit_zero_returns_empty(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("k", "x"))
    assert svc.list_episodes(limit=0) == []


# ---------------------------------------------------------------------------
# L2 episodes — search
# ---------------------------------------------------------------------------


def test_search_episodes_returns_relevant(tmp_path: Path) -> None:
    """Search returns episodes matching the query, ranked by relevance."""
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("note", "deploy python service to production"))
    svc.record_episode(make_episode("note", "fix javascript bug in frontend"))
    svc.record_episode(make_episode("note", "write python unit tests"))
    results = svc.search_episodes("python", limit=10)
    summaries = [ep.summary for ep, _ in results]
    # Both python episodes should be in results
    assert "deploy python service to production" in summaries
    assert "write python unit tests" in summaries
    # The javascript episode should NOT be in results
    assert "fix javascript bug in frontend" not in summaries


def test_search_episodes_empty_query_returns_empty(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("k", "hello world"))
    assert svc.search_episodes("") == []
    assert svc.search_episodes("   ") == []


def test_search_episodes_no_episodes_returns_empty(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    assert svc.search_episodes("anything") == []


def test_search_episodes_filter_by_kind(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("loop", "deploy python app"))
    svc.record_episode(make_episode("note", "deploy python service"))
    results = svc.search_episodes("python", kind="loop")
    assert len(results) == 1
    assert results[0][0].kind == "loop"


def test_search_episodes_respects_limit(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    for i in range(10):
        svc.record_episode(make_episode("k", f"python task number {i}"))
    results = svc.search_episodes("python", limit=3)
    assert len(results) <= 3


def test_search_episodes_scores_positive(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("k", "deploy python service"))
    svc.record_episode(make_episode("k", "fix javascript bug"))
    results = svc.search_episodes("python")
    for _ep, score in results:
        assert score > 0.0


# ---------------------------------------------------------------------------
# L3 profile
# ---------------------------------------------------------------------------


def test_get_user_profile_uses_injected_loader(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def loader() -> dict[str, object]:
        captured["called"] = True
        return {"version": 4, "basic_info": {"name": "Zoe"}}

    svc = MemoryService(state_dir=tmp_path / "state", profile_loader=loader)
    profile = svc.get_user_profile()
    assert profile == {"version": 4, "basic_info": {"name": "Zoe"}}
    assert captured.get("called") is True


def test_save_user_profile_uses_injected_saver(tmp_path: Path) -> None:
    saved: list[dict[str, object]] = []

    def saver(profile: dict[str, object]) -> None:
        saved.append(profile)

    svc = MemoryService(state_dir=tmp_path / "state", profile_saver=saver)
    svc.save_user_profile({"version": 4})
    assert saved == [{"version": 4}]


def test_get_user_profile_falls_back_to_hermes_profile(tmp_path: Path, tmp_state_dir: Path) -> None:
    svc = _make_service(tmp_state_dir)
    profile = svc.get_user_profile()
    assert isinstance(profile, dict)
    assert "basic_info" in profile


# ---------------------------------------------------------------------------
# P11: TTL cleanup, RRF search, profile learning, compaction
# ---------------------------------------------------------------------------


def test_cleanup_expired_facts_removes_past_ttl(tmp_path: Path) -> None:
    """cleanup_expired_facts should purge facts whose TTL has elapsed."""
    svc = _make_service(tmp_path)
    svc.remember_fact("temp", "gone", ttl=-1.0)  # already expired
    svc.remember_fact("perm", "stays", ttl=3600.0)
    removed = svc.cleanup_expired_facts()
    assert removed == 1
    assert svc.get_fact("temp") is None
    assert svc.get_fact("perm") is not None


def test_cleanup_expired_facts_zero_when_none_expired(tmp_path: Path) -> None:
    """cleanup_expired_facts should return 0 when no facts are expired."""
    svc = _make_service(tmp_path)
    svc.remember_fact("perm", "stays", ttl=3600.0)
    removed = svc.cleanup_expired_facts()
    assert removed == 0


def test_cleanup_expired_facts_zero_when_no_ttls(tmp_path: Path) -> None:
    """cleanup_expired_facts should return 0 when no TTLs are set."""
    svc = _make_service(tmp_path)
    svc.remember_fact("a", 1)  # no TTL
    removed = svc.cleanup_expired_facts()
    assert removed == 0


def test_search_episodes_rrf_fuses_substring_and_tfidf(tmp_path: Path) -> None:
    """RRF should return episodes matching either substring or TF-IDF."""
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("note", "deploy python service to production"))
    svc.record_episode(make_episode("note", "fix javascript bug in frontend"))
    svc.record_episode(make_episode("note", "write python unit tests"))
    results = svc.search_episodes_rrf("python", limit=10)
    summaries = [ep.summary for ep, _ in results]
    # Both python episodes should appear
    assert "deploy python service to production" in summaries
    assert "write python unit tests" in summaries
    # Scores should be positive
    for _ep, score in results:
        assert score > 0.0


def test_search_episodes_rrf_exact_match_ranks_higher(tmp_path: Path) -> None:
    """An episode matching both signals should score higher than one matching one."""
    svc = _make_service(tmp_path)
    # "python deploy" matches substring "python" and TF-IDF "python"
    svc.record_episode(make_episode("k", "python deploy fast"))
    # "ruby deploy" matches TF-IDF "deploy" only (no "python" substring)
    svc.record_episode(make_episode("k", "ruby deploy fast"))
    results = svc.search_episodes_rrf("python", limit=10)
    assert len(results) >= 1
    # The python episode should be first (matched both signals)
    assert "python" in results[0][0].summary


def test_search_episodes_rrf_empty_query_returns_empty(tmp_path: Path) -> None:
    """RRF should return [] for an empty query."""
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("k", "hello world"))
    assert svc.search_episodes_rrf("") == []


def test_search_episodes_rrf_no_episodes_returns_empty(tmp_path: Path) -> None:
    """RRF should return [] when there are no episodes."""
    svc = _make_service(tmp_path)
    assert svc.search_episodes_rrf("anything") == []


def test_learn_profile_from_episodes_extracts_skills(tmp_path: Path) -> None:
    """learn_profile_from_episodes should report most-used skills."""
    saved: list[dict] = []
    svc = MemoryService(
        state_dir=tmp_path / "state",
        profile_loader=lambda: {"version": 4},
        profile_saver=saved.append,
    )
    svc.record_episode(make_episode("loop", "ran deploy", {"skill": "deploy"}))
    svc.record_episode(make_episode("loop", "ran test", {"skill": "test"}))
    svc.record_episode(make_episode("loop", "ran deploy again", {"skill": "deploy"}))
    insights = svc.learn_profile_from_episodes()
    skill_names = [s["skill"] for s in insights["top_skills"]]
    assert "deploy" in skill_names
    assert "test" in skill_names
    # deploy should have count 2
    deploy = next(s for s in insights["top_skills"] if s["skill"] == "deploy")
    assert deploy["count"] == 2
    # Profile should have been saved with the insights
    assert len(saved) == 1
    assert "learned" in saved[0]


def test_learn_profile_from_episodes_counts_kinds(tmp_path: Path) -> None:
    """learn_profile_from_episodes should report most frequent kinds."""
    svc = MemoryService(
        state_dir=tmp_path / "state",
        profile_loader=lambda: {},
        profile_saver=lambda p: None,
    )
    svc.record_episode(make_episode("loop", "a"))
    svc.record_episode(make_episode("loop", "b"))
    svc.record_episode(make_episode("note", "c"))
    insights = svc.learn_profile_from_episodes()
    kinds = {k["kind"]: k["count"] for k in insights["top_kinds"]}
    assert kinds["loop"] == 2
    assert kinds["note"] == 1


def test_compact_episodes_noop_when_under_threshold(tmp_path: Path) -> None:
    """compact_episodes should be a no-op when episodes <= keep_recent."""
    svc = _make_service(tmp_path)
    for i in range(5):
        svc.record_episode(make_episode("k", f"ep {i}"))
    result = svc.compact_episodes(keep_recent=10)
    assert result["removed"] == 0
    assert result["summaries_added"] == 0
    # All 5 episodes should still be present
    assert len(svc.list_episodes()) == 5


def test_compact_episodes_aggregates_old_episodes(tmp_path: Path) -> None:
    """compact_episodes should replace old episodes with per-kind summaries."""
    svc = _make_service(tmp_path)
    # Record 10 episodes; keep only the 4 most recent
    for i in range(10):
        svc.record_episode(make_episode("loop", f"old ep {i}", {"i": i}))
    result = svc.compact_episodes(keep_recent=4)
    assert result["removed"] == 6
    assert result["summaries_added"] == 1  # one summary for "loop" kind
    remaining = svc.list_episodes()
    # 4 recent + 1 summary = 5 total
    assert len(remaining) == 5
    # The summary should be the oldest (created_at smallest)
    summary = [ep for ep in remaining if ep.kind == "loop_summary"]
    assert len(summary) == 1
    assert summary[0].details["count"] == 6
    assert summary[0].details["compacted"] is True


def test_compact_episodes_preserves_recent_intact(tmp_path: Path) -> None:
    """compact_episodes should not alter the recent episodes."""
    svc = _make_service(tmp_path)
    for i in range(8):
        svc.record_episode(make_episode("k", f"ep {i}", {"idx": i}))
    before = svc.list_episodes(limit=4)
    svc.compact_episodes(keep_recent=4)
    after = svc.list_episodes(limit=4)
    # The 4 most recent summaries should be unchanged
    before_summaries = [ep.summary for ep in before]
    after_summaries = [ep.summary for ep in after]
    assert before_summaries == after_summaries

"""Tests for the M4 memory backend protocol and fusion (P1-3 / P1-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes.workbench.memory import (
    Episode,
    MemoryService,
    make_episode,
)
from hermes.workbench.memory_backend import LocalRRFBackend


class FakeBackend:
    """Minimal in-memory backend for testing fusion/consistency.

    ``boost`` lists episode ids that ``search`` returns (scored 1.0) regardless
    of query, so tests can verify the backend signal influences RRF ranking.
    """

    def __init__(self, boost: list[str] | None = None) -> None:
        self._index: dict[str, Episode] = {}
        self._boost = list(boost or [])
        self._healthy = True
        self.deleted: list[str] = []

    def search(
        self, query: str, limit: int = 10, kind: str | None = None
    ) -> list[tuple[Episode, float]]:
        out: list[tuple[Episode, float]] = []
        for eid in self._boost:
            ep = self._index.get(eid)
            if ep is not None and (kind is None or ep.kind == kind):
                out.append((ep, 1.0))
        return out[:limit]

    def index_episode(self, episode: Episode) -> None:
        self._index[episode.id] = episode

    def delete_episode(self, episode_id: str) -> None:
        self._index.pop(episode_id, None)
        self.deleted.append(episode_id)

    def rebuild(self, episodes: list[Episode]) -> None:
        self._index = {ep.id: ep for ep in episodes}

    def indexed_ids(self) -> set[str]:
        return set(self._index.keys())

    def health(self) -> bool:
        return self._healthy


def _make_service(tmp_path: Path, backend: Any = None) -> MemoryService:
    svc = MemoryService(state_dir=tmp_path / "state")
    if backend is not None:
        svc.set_backend(backend)
    return svc


# ---------------------------------------------------------------------------
# LocalRRFBackend
# ---------------------------------------------------------------------------


def test_local_backend_delegates_search(tmp_path: Path) -> None:
    svc = MemoryService(state_dir=tmp_path / "state")
    backend = LocalRRFBackend(svc)
    svc.record_episode(make_episode("note", "deploy python service"))
    results = backend.search("python", limit=10)
    assert any("python" in ep.summary for ep, _ in results)


def test_local_backend_noop_index_delete_rebuild(tmp_path: Path) -> None:
    svc = MemoryService(state_dir=tmp_path / "state")
    backend = LocalRRFBackend(svc)
    ep = make_episode("k", "hello")
    backend.index_episode(ep)  # no-op, must not raise
    backend.delete_episode(ep.id)  # no-op
    backend.rebuild([ep])  # no-op


def test_local_backend_indexed_ids_reflects_all_episodes(tmp_path: Path) -> None:
    svc = MemoryService(state_dir=tmp_path / "state")
    backend = LocalRRFBackend(svc)
    svc.record_episode(make_episode("k", "a"))
    svc.record_episode(make_episode("k", "b"))
    assert backend.indexed_ids() == {ep.id for ep in svc.list_episodes()}


def test_local_backend_health_true(tmp_path: Path) -> None:
    svc = MemoryService(state_dir=tmp_path / "state")
    assert LocalRRFBackend(svc).health() is True


# ---------------------------------------------------------------------------
# Backend fusion (signal 5)
# ---------------------------------------------------------------------------


def test_memory_service_default_backend_is_local(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    assert isinstance(svc.get_backend(), LocalRRFBackend)


def test_backend_signal_surfaces_semantic_matches(tmp_path: Path) -> None:
    """A backend semantic match with no local keyword overlap still surfaces."""
    svc = _make_service(tmp_path)
    fake = FakeBackend()
    svc.set_backend(fake)

    nn_id: str | None = None
    for summary in ("deploy python service", "write python tests", "neural network training"):
        ep = make_episode("note", summary)
        svc.record_episode(ep)
        fake.index_episode(ep)
        if "neural" in summary:
            nn_id = ep.id

    assert nn_id is not None
    fake._boost = [nn_id]  # backend returns the neural episode for a "python" query
    results = svc.search_episodes_rrf("python", limit=10)
    summaries = [ep.summary for ep, _ in results]
    assert "neural network training" in summaries


def test_backend_weight_can_promote(tmp_path: Path) -> None:
    """A high backend weight promotes a backend-only match above local matches."""
    svc = _make_service(tmp_path)
    fake = FakeBackend()
    svc.set_backend(fake)

    js_id: str | None = None
    for summary in ("deploy python service", "fix javascript bug", "write python tests"):
        ep = make_episode("note", summary)
        svc.record_episode(ep)
        fake.index_episode(ep)
        if "javascript" in summary:
            js_id = ep.id

    assert js_id is not None
    fake._boost = [js_id]
    results = svc.search_episodes_rrf("python", limit=10, backend_weight=100.0)
    assert results[0][0].summary == "fix javascript bug"


def test_unhealthy_backend_degrades_to_local(tmp_path: Path) -> None:
    """A backend reporting health() == False must not affect RRF results."""
    svc = _make_service(tmp_path)
    fake = FakeBackend()
    fake._healthy = False
    svc.set_backend(fake)
    svc.record_episode(make_episode("note", "deploy python service"))
    results = svc.search_episodes_rrf("python", limit=10)
    assert [ep.summary for ep, _ in results] == ["deploy python service"]


# ---------------------------------------------------------------------------
# Consistency: one-way projection on compaction / archive
# ---------------------------------------------------------------------------


def test_compact_deletes_removed_from_backend(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    fake = FakeBackend()
    svc.set_backend(fake)
    ids: list[str] = []
    for i in range(10):
        ep = make_episode("loop", f"old ep {i}")
        svc.record_episode(ep)
        fake.index_episode(ep)
        ids.append(ep.id)

    svc.compact_episodes(keep_recent=4)

    # The 6 oldest originals must be removed from the backend index.
    removed = set(ids[:-4])
    assert removed & fake.indexed_ids() == set()
    # The 4 most recent remain indexed.
    assert set(ids[-4:]) <= fake.indexed_ids()


def test_archive_deletes_archived_from_backend(tmp_path: Path) -> None:
    import time as _time

    svc = _make_service(tmp_path)
    fake = FakeBackend()
    svc.set_backend(fake)
    now = _time.time()
    old = Episode(
        id="old-1", kind="loop", summary="old", details={}, created_at=now - 60 * 86400.0
    )
    recent = Episode(id="new-1", kind="loop", summary="new", details={}, created_at=now)
    svc.record_episode(old)
    svc.record_episode(recent)
    fake.index_episode(old)
    fake.index_episode(recent)

    svc.archive_episodes(older_than_days=30.0)

    assert "old-1" not in fake.indexed_ids()
    assert "new-1" in fake.indexed_ids()


# ---------------------------------------------------------------------------
# Audit / rebuild
# ---------------------------------------------------------------------------


def test_memory_audit_reports_orphans_and_stale(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    fake = FakeBackend()
    svc.set_backend(fake)
    ep = make_episode("k", "hello")
    svc.record_episode(ep)
    # backend has a stale entry for an episode no longer in the log
    fake.index_episode(Episode(id="ghost", kind="k", summary="x", details={}, created_at=0.0))

    report = svc.memory_audit()
    assert report["orphans"] == [ep.id]  # real episode not yet indexed
    assert report["stale_index"] == ["ghost"]  # backend entry without a source episode


def test_rebuild_backend_projects_all_episodes(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    fake = FakeBackend()
    svc.set_backend(fake)
    for i in range(3):
        svc.record_episode(make_episode("k", f"ep {i}"))
    n = svc.rebuild_backend()
    assert n == 3
    assert fake.indexed_ids() == {ep.id for ep in svc.list_episodes()}


def test_sync_stats_empty_without_sync(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    assert svc.sync_stats() == {}


# ---------------------------------------------------------------------------
# Conflict detection (heuristic, human-gated)
# ---------------------------------------------------------------------------


def test_detect_conflicts_flags_state_change(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("preference", "prefer python for scripts"))
    svc.record_episode(make_episode("preference", "改为 prefer rust for scripts"))
    conflicts = svc.detect_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0]["marker"] == "改为"


def test_detect_conflicts_empty_without_marker(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.record_episode(make_episode("preference", "prefer python for scripts"))
    svc.record_episode(make_episode("preference", "prefer rust for scripts"))
    assert svc.detect_conflicts() == []

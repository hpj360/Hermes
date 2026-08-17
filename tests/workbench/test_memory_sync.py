"""Tests for the M4 async memory sync pipeline (P1-2)."""

from __future__ import annotations

import queue as _queue
import time as _time
from pathlib import Path
from typing import Any

from hermes.workbench.memory import Episode, make_episode
from hermes.workbench.memory_sync import MemorySyncConfig, MemorySyncService


class RecordingBackend:
    """Fake backend that records indexed ids and can be told to fail."""

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.indexed: list[str] = []
        self._fail = set(fail_for or [])
        self._healthy = True

    def index_episode(self, episode: Episode) -> None:
        if episode.id in self._fail:
            raise RuntimeError("boom")
        self.indexed.append(episode.id)

    def delete_episode(self, episode_id: str) -> None:
        return None

    def rebuild(self, episodes: list[Episode]) -> None:
        self.indexed = [e.id for e in episodes]

    def indexed_ids(self) -> set[str]:
        return set(self.indexed)

    def health(self) -> bool:
        return self._healthy

    def search(
        self, query: str, limit: int = 10, kind: str | None = None
    ) -> list[tuple[Episode, float]]:
        return []


def _drain(q: Any) -> list[Episode]:
    items: list[Episode] = []
    while True:
        try:
            items.append(q.get_nowait())
        except _queue.Empty:
            break
    return items


def _wait_until(predicate: Any, timeout: float = 2.0) -> None:
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if predicate():
            return
        _time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


def _make_sync(
    tmp_path: Path, backend: RecordingBackend, **cfg: Any
) -> MemorySyncService:
    config = MemorySyncConfig(enabled=True, **cfg)
    return MemorySyncService(backend=backend, state_dir=tmp_path, config=config)


# ---------------------------------------------------------------------------
# Enqueue (hot path)
# ---------------------------------------------------------------------------


def test_enqueue_returns_false_when_disabled(tmp_path: Path) -> None:
    backend = RecordingBackend()
    svc = MemorySyncService(
        backend=backend, state_dir=tmp_path, config=MemorySyncConfig(enabled=False)
    )
    assert svc.enqueue(make_episode("k", "x")) is False


def test_enqueue_is_idempotent_by_id(tmp_path: Path) -> None:
    backend = RecordingBackend()
    svc = _make_sync(tmp_path, backend)
    ep = make_episode("k", "hello")
    assert svc.enqueue(ep) is True
    assert svc.enqueue(ep) is False
    assert svc.pending_ids() == {ep.id}


def test_enqueue_persists_pending(tmp_path: Path) -> None:
    backend = RecordingBackend()
    svc = _make_sync(tmp_path, backend)
    svc.enqueue(make_episode("k", "hello"))
    assert (tmp_path / "memory_sync_pending.json").exists()


def test_recover_reenqueues_pending_from_disk(tmp_path: Path) -> None:
    backend = RecordingBackend()
    cfg = MemorySyncConfig(enabled=True)
    svc1 = MemorySyncService(backend=backend, state_dir=tmp_path, config=cfg)
    ep = make_episode("k", "hello")
    svc1.enqueue(ep)
    _drain(svc1._queue)  # simulate items still pending at shutdown

    svc2 = MemorySyncService(backend=backend, state_dir=tmp_path, config=cfg)
    svc2._recover()
    recovered = _drain(svc2._queue)
    assert [e.id for e in recovered] == [ep.id]


# ---------------------------------------------------------------------------
# Worker processing
# ---------------------------------------------------------------------------


def test_worker_indexes_enqueued_episodes(tmp_path: Path) -> None:
    backend = RecordingBackend()
    svc = _make_sync(tmp_path, backend, poll_interval=0.01)
    ep = make_episode("k", "hello")
    svc.enqueue(ep)
    svc.start()
    _wait_until(lambda: ep.id in backend.indexed)
    svc.stop()
    assert svc.stats()["total_indexed"] == 1
    assert svc.pending_ids() == set()


def test_worker_records_failure_after_retries(tmp_path: Path) -> None:
    backend = RecordingBackend(fail_for={"bad"})
    svc = _make_sync(
        tmp_path,
        backend,
        max_retries=1,
        base_delay=0.0,
        max_delay=0.0,
        poll_interval=0.01,
    )
    svc.enqueue(Episode(id="bad", kind="k", summary="boom", details={}, created_at=0.0))
    svc.start()
    _wait_until(lambda: svc.stats()["failure_count"] >= 1)
    svc.stop()
    assert svc.pending_ids() == set()
    failures = svc.failure_log()
    assert len(failures) == 1
    assert failures[0]["episode_id"] == "bad"


def test_stats_empty_when_idle(tmp_path: Path) -> None:
    backend = RecordingBackend()
    svc = _make_sync(tmp_path, backend)
    stats = svc.stats()
    assert stats["pending"] == 0
    assert stats["total_indexed"] == 0
    assert stats["failure_count"] == 0

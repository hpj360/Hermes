"""Tests for the Mem0 backend adapter (P1-1), using an injected fake client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hermes.workbench.mem0_adapter import Mem0Backend, Mem0BackendConfig
from hermes.workbench.memory import MemoryService, make_episode


class FakeMem0Client:
    """Fake mem0 ``Memory`` client with an in-memory store."""

    def __init__(self) -> None:
        self.memories: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def add(self, messages: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        mid = f"mem-{self._seq}"
        self._seq += 1
        rec = {
            "id": mid,
            "memory": messages[0]["content"],
            "metadata": kwargs.get("metadata", {}),
            "score": 1.0,
        }
        self.memories[mid] = rec
        return [rec]

    def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in self.memories.values()]

    def delete(self, memory_id: str) -> None:
        self.memories.pop(memory_id, None)

    def get_all(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self.memories.values())


def _make_backend(
    tmp_path: Path,
    client: FakeMem0Client | None = None,
    factory: Any = None,
) -> tuple[MemoryService, Mem0Backend]:
    svc = MemoryService(state_dir=tmp_path / "state")
    cfg = Mem0BackendConfig()
    if factory is None:
        client = client or FakeMem0Client()

        def factory(_cfg: Mem0BackendConfig) -> Any:
            return client

    backend = Mem0Backend(
        memory=svc, state_dir=tmp_path / "backend", config=cfg, client_factory=factory
    )
    return svc, backend


# ---------------------------------------------------------------------------
# Client lifecycle / health
# ---------------------------------------------------------------------------


def test_health_false_when_client_factory_raises(tmp_path: Path) -> None:
    svc = MemoryService(state_dir=tmp_path / "state")

    def boom(_cfg: Mem0BackendConfig) -> Any:
        raise ImportError("no mem0")

    backend = Mem0Backend(
        memory=svc,
        state_dir=tmp_path / "b",
        config=Mem0BackendConfig(),
        client_factory=boom,
    )
    assert backend.health() is False


def test_default_factory_does_not_raise_without_mem0(tmp_path: Path) -> None:
    svc = MemoryService(state_dir=tmp_path / "state")
    backend = Mem0Backend(memory=svc, state_dir=tmp_path / "b")
    # Must never raise at construction; health may be False when mem0 absent.
    assert backend.health() in (True, False)


def test_index_raises_when_unhealthy(tmp_path: Path) -> None:
    svc = MemoryService(state_dir=tmp_path / "state")

    def boom(_cfg: Mem0BackendConfig) -> Any:
        raise RuntimeError("no mem0")

    backend = Mem0Backend(
        memory=svc, state_dir=tmp_path / "b", config=Mem0BackendConfig(), client_factory=boom
    )
    with pytest.raises(RuntimeError):
        backend.index_episode(make_episode("k", "x"))


# ---------------------------------------------------------------------------
# Index / search / delete / rebuild
# ---------------------------------------------------------------------------


def test_index_and_search_resolves_episode(tmp_path: Path) -> None:
    client = FakeMem0Client()
    svc, backend = _make_backend(tmp_path, client=client)
    ep = make_episode("note", "deploy python service")
    svc.record_episode(ep)
    backend.index_episode(ep)

    assert backend.indexed_ids() == {ep.id}
    results = backend.search("python", limit=10)
    assert [r[0].id for r in results] == [ep.id]


def test_search_skips_missing_episode(tmp_path: Path) -> None:
    client = FakeMem0Client()
    svc, backend = _make_backend(tmp_path, client=client)
    # index metadata references an episode id not present in the log
    client.add([{"role": "user", "content": "ghost"}], metadata={"episode_id": "ghost"})
    assert backend.search("anything", limit=10) == []


def test_delete_removes_mapping_and_memory(tmp_path: Path) -> None:
    client = FakeMem0Client()
    svc, backend = _make_backend(tmp_path, client=client)
    ep = make_episode("k", "x")
    svc.record_episode(ep)
    backend.index_episode(ep)
    backend.delete_episode(ep.id)
    assert backend.indexed_ids() == set()
    assert client.memories == {}


def test_rebuild_replaces_all(tmp_path: Path) -> None:
    client = FakeMem0Client()
    svc, backend = _make_backend(tmp_path, client=client)
    eps = [make_episode("k", "a"), make_episode("k", "b")]
    for e in eps:
        svc.record_episode(e)
    backend.rebuild(eps)
    assert backend.indexed_ids() == {e.id for e in eps}

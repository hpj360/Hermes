"""Tests for hermes.workbench.broker (P2-3)."""

from __future__ import annotations

import sys
import types

import pytest

from hermes.workbench.broker import BrokerInterface, RedisBroker
from hermes.workbench.scheduler import JobQueue


def test_job_queue_satisfies_broker_interface() -> None:
    """The existing in-memory JobQueue must satisfy the broker protocol."""
    assert isinstance(JobQueue(), BrokerInterface)


def test_redis_broker_raises_without_redis(monkeypatch) -> None:
    """RedisBroker must raise a clear ImportError when 'redis' is missing."""
    monkeypatch.setitem(sys.modules, "redis", None)
    with pytest.raises(ImportError):
        RedisBroker()


# ---------------------------------------------------------------------------
# Fake redis module for exercising put/get/size without a real server.
# ---------------------------------------------------------------------------


class _FakeRedisClient:
    def __init__(self) -> None:
        self._zset: list[tuple[str, float]] = []

    @classmethod
    def from_url(cls, url: str, decode_responses: bool = False) -> "_FakeRedisClient":
        return cls()

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        for member, score in mapping.items():
            self._zset.append((member, score))
        self._zset.sort(key=lambda x: x[1])
        return len(mapping)

    def bzpopmin(self, key: str, timeout: int = 0) -> tuple[str, str] | None:
        if not self._zset:
            return None
        member, _ = self._zset.pop(0)
        return (key, member)

    def zcard(self, key: str) -> int:
        return len(self._zset)


def _install_fake_redis(monkeypatch) -> None:
    mod = types.ModuleType("redis")
    mod.Redis = _FakeRedisClient
    monkeypatch.setitem(sys.modules, "redis", mod)


def test_redis_broker_put_get_size(monkeypatch) -> None:
    _install_fake_redis(monkeypatch)
    broker = RedisBroker(job_factory=lambda d: d)

    assert broker.size() == 0
    broker.put({"priority": 1, "name": "job-a"})
    broker.put({"priority": 0, "name": "job-b"})
    assert broker.size() == 2

    # Lower priority value = higher urgency → job-b comes out first.
    first = broker.get(timeout=1)
    assert first is not None
    assert first["name"] == "job-b"
    assert broker.size() == 1


def test_redis_broker_returns_none_on_empty(monkeypatch) -> None:
    _install_fake_redis(monkeypatch)
    broker = RedisBroker()
    assert broker.get(timeout=0) is None


def test_redis_broker_uses_job_factory(monkeypatch) -> None:
    _install_fake_redis(monkeypatch)
    broker = RedisBroker(job_factory=lambda d: f"rebuilt:{d['name']}")
    broker.put({"priority": 0, "name": "x"})
    assert broker.get(timeout=1) == "rebuilt:x"


def test_redis_broker_roundtrip_preserves_payload(monkeypatch) -> None:
    _install_fake_redis(monkeypatch)
    broker = RedisBroker()
    payload = {"priority": 3, "job_id": "j1", "nested": {"a": 1}}
    broker.put(payload)
    result = broker.get(timeout=1)
    assert result == payload  # json round-trip preserves structure

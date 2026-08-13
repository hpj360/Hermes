"""Job transport abstraction for the scheduler (P2-3).

The scheduler hard-codes an in-process :class:`~hermes.workbench.scheduler.JobQueue`
(priority queue over ``threading``). For a multi-machine deployment the transport
must be swappable without touching worker/queue logic. This module defines:

* :class:`BrokerInterface` — structural protocol (``put`` / ``get`` / ``size``),
  satisfied by the existing in-memory ``JobQueue`` with zero changes.
* :class:`RedisBroker` — Redis-backed priority queue (ZSET + ``BZPOPMIN``).

Zero-runtime-dependency constraint: ``redis`` is imported lazily inside
:class:`RedisBroker` and raises a clear error when missing, so the default
in-memory path keeps the project's stdlib-only core intact.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Protocol, runtime_checkable

__all__ = ["BrokerInterface", "RedisBroker"]


@runtime_checkable
class BrokerInterface(Protocol):
    """Structural contract for a job transport.

    ``get`` must block up to *timeout* seconds and raise the scheduler's
    ``EmptyError`` (or a compatible ``queue.Empty`` subclass) when no job is
    available — the caller treats that as "idle, keep polling".
    """

    def put(self, job: Any) -> None: ...

    def get(self, timeout: float = 0.0) -> Any: ...

    def size(self) -> int: ...


class RedisBroker:
    """Redis-backed priority job queue (ZSET ordered by ``(priority, seq)``).

    Jobs are stored as JSON payloads under a ZSET member; ``get`` uses
    ``BZPOPMIN`` so the lowest ``(priority, seq)`` job wins, mirroring the
    in-memory ``JobQueue`` semantics. A caller-supplied ``job_factory``
    reconstructs domain objects from the JSON dict (e.g.
    ``ScheduledJob.from_dict``); without one, ``get`` returns the raw dict.

    This is an optional backend for multi-machine deployments — it requires
    the third-party ``redis`` package and a running Redis server.
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        key: str = "hermes:jobs",
        *,
        job_factory: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - depends on env
            raise ImportError(
                "RedisBroker requires the 'redis' package; "
                "install it with `pip install redis`"
            ) from e
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._key = key
        self._seq = 0
        self._job_factory = job_factory

    def put(self, job: Any) -> None:
        """Serialize *job* and ZADD it with score ``(priority, seq)``."""
        data = job.to_dict() if hasattr(job, "to_dict") else dict(job)
        score = float(data.get("priority", 0))
        # Preserve FIFO within the same priority via a tiny fractional seq.
        seq = self._seq
        self._seq += 1
        member = json.dumps(data, ensure_ascii=False, default=str)
        self._client.zadd(self._key, {member: score + seq * 1e-9})

    def get(self, timeout: float = 0.0) -> Any:
        """Pop the lowest-score job. Returns ``None`` on timeout (no raise)."""
        result = self._client.bzpopmin(self._key, timeout=int(timeout) or 0)
        if result is None:
            return None
        _, member = result
        data = json.loads(member)
        if self._job_factory is not None:
            return self._job_factory(data)
        return data

    def size(self) -> int:
        return int(self._client.zcard(self._key))

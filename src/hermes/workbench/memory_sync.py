"""Asynchronous memory extraction pipeline (M4).

``MemorySyncService`` decouples episode recording (hot path) from backend
indexing (which may call an LLM for fact extraction). Design (ADR-0021):

- ``enqueue(episode)`` 只做三件事：内存去重、写 pending 文件、入队。绝不调用
  后端，绝不阻塞 ``record_episode``。
- 单个 daemon worker 批量消费队列，调用 ``backend.index_episode``；失败按
  ``RetryPolicy`` 指数退避重试，耗尽后记入失败日志（供 audit CLI 消费）。
- pending 文件（``memory_sync_pending.json``）记录「已入队未索引」的 episode，
  进程重启后由 ``recover()`` 重放入队，保证不丢。

纯 stdlib（``threading`` / ``queue`` / ``json`` / ``time``），零外部依赖。
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hermes.workbench.memory_backend import MemoryBackend
from hermes.workbench.persistence import atomic_write_json, safe_read_json

if TYPE_CHECKING:  # pragma: no cover - type-check only
    from hermes.workbench.memory import Episode

logger = logging.getLogger("hermes.workbench.memory_sync")


@dataclass
class MemorySyncConfig:
    """Configuration for the async memory extraction pipeline."""

    enabled: bool = False
    batch_size: int = 10
    poll_interval: float = 1.0
    max_retries: int = 3
    base_delay: float = 2.0
    max_delay: float = 60.0


def _episode_to_payload(episode: Episode) -> dict[str, Any]:
    return {
        "id": episode.id,
        "kind": episode.kind,
        "summary": episode.summary,
        "details": episode.details,
        "created_at": episode.created_at,
    }


def _payload_to_episode(payload: dict[str, Any]) -> Episode:
    # Lazy import to avoid a circular import (memory.py -> memory_sync.py).
    from hermes.workbench.memory import Episode

    details_raw = payload.get("details")
    details = details_raw if isinstance(details_raw, dict) else {}
    return Episode(
        id=str(payload["id"]),
        kind=str(payload["kind"]),
        summary=str(payload.get("summary", "")),
        details=details,
        created_at=float(payload.get("created_at", 0.0)),
    )


class MemorySyncService:
    """Async backend-indexing worker with crash-safe pending persistence."""

    def __init__(
        self,
        backend: MemoryBackend,
        state_dir: Path,
        config: MemorySyncConfig | None = None,
    ) -> None:
        self._backend = backend
        self._config = config or MemorySyncConfig()
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._pending_path = self._state_dir / "memory_sync_pending.json"
        self._failure_path = self._state_dir / "memory_sync_failures.jsonl"

        self._pending: dict[str, dict[str, Any]] = self._load_pending()
        self._queue: queue.Queue[Episode] = queue.Queue()
        self._queued_ids: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

        # Metrics (guarded by _lock)
        self._total_indexed = 0
        self._failure_count = 0
        self._last_error: str | None = None
        self._last_success_at: float | None = None

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _load_pending(self) -> dict[str, dict[str, Any]]:
        data = safe_read_json(self._pending_path, default={})
        return data if isinstance(data, dict) else {}

    def _save_pending(self) -> None:
        atomic_write_json(self._pending_path, self._pending)

    def _append_failure(self, episode_id: str, error: str) -> None:
        from hermes.workbench.persistence import atomic_append_jsonl

        atomic_append_jsonl(
            self._failure_path,
            {"episode_id": episode_id, "error": error, "at": time.time()},
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the worker and re-enqueue any pending episodes from disk."""
        if self._worker is not None:
            return
        self._recover()
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._loop, name="memory-sync", daemon=True
        )
        self._worker.start()

    def stop(self) -> None:
        """Signal the worker to stop (does not join a stuck index call)."""
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None

    def _recover(self) -> None:
        """Re-enqueue episodes that were pending at last shutdown.

        Skips ids already sitting in the in-memory queue (``_queued_ids``), so
        calling this after ``enqueue`` never double-processes an episode.
        """
        with self._lock:
            pending = dict(self._pending)
        for episode_id, payload in pending.items():
            if episode_id not in self._queued_ids:
                self._queued_ids.add(episode_id)
                self._queue.put(_payload_to_episode(payload))

    # ------------------------------------------------------------------
    # Hot-path enqueue
    # ------------------------------------------------------------------
    def enqueue(self, episode: Episode) -> bool:
        """Enqueue an episode for async indexing. Returns True if newly queued.

        Idempotent by ``episode.id``: a duplicate id is silently dropped.
        This method never calls the backend and never blocks on the network.
        """
        if not self._config.enabled:
            return False
        with self._lock:
            if episode.id in self._pending:
                return False
            self._pending[episode.id] = _episode_to_payload(episode)
            self._save_pending()
            self._queued_ids.add(episode.id)
        self._queue.put(episode)
        return True

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            batch: list[Episode] = []
            try:
                first = self._queue.get(timeout=self._config.poll_interval)
                batch.append(first)
            except queue.Empty:
                continue
            # Drain up to batch_size additional items without blocking.
            for _ in range(self._config.batch_size - 1):
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            for episode in batch:
                if self._stop.is_set():
                    # Put unconsumed episodes back so they survive as pending.
                    self._queue.put(episode)
                    continue
                self._process(episode)

    def _process(self, episode: Episode) -> None:
        """Index one episode with retry/backoff; drop from pending on success."""
        cfg = self._config
        last_error: str | None = None
        for attempt in range(cfg.max_retries + 1):
            try:
                self._backend.index_episode(episode)
                with self._lock:
                    self._pending.pop(episode.id, None)
                    self._queued_ids.discard(episode.id)
                    self._save_pending()
                    self._total_indexed += 1
                    self._last_success_at = time.time()
                return
            except Exception as exc:  # noqa: BLE001 — backend boundary
                last_error = str(exc)
                logger.warning(
                    "memory sync index failed for %s (attempt %d): %s",
                    episode.id,
                    attempt + 1,
                    last_error,
                )
                if attempt < cfg.max_retries:
                    delay = min(cfg.base_delay * (2**attempt), cfg.max_delay)
                    self._stop.wait(delay)
        # Retries exhausted: drop from pending, record failure for audit.
        with self._lock:
            self._pending.pop(episode.id, None)
            self._queued_ids.discard(episode.id)
            self._save_pending()
            self._failure_count += 1
            self._last_error = last_error
        self._append_failure(episode.id, last_error or "unknown error")

    # ------------------------------------------------------------------
    # Introspection (audit / metrics)
    # ------------------------------------------------------------------
    def pending_ids(self) -> set[str]:
        with self._lock:
            return set(self._pending.keys())

    def failure_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent failure records (newest first)."""
        if not self._failure_path.exists():
            return []
        items: list[dict[str, Any]] = []
        with self._failure_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return list(reversed(items[-limit:]))

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._config.enabled,
                "pending": len(self._pending),
                "queue_depth": self._queue.qsize(),
                "total_indexed": self._total_indexed,
                "failure_count": self._failure_count,
                "last_error": self._last_error,
                "last_success_at": self._last_success_at,
            }

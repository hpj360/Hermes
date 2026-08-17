"""Mem0 backend adapter (M4).

``Mem0Backend`` 实现 :class:`MemoryBackend` 协议，把 Hermes episodes 单向投影到
Mem0（``mem0ai``，Apache 2.0）做 LLM 事实抽取与实体/时间感知检索。

关键设计：

- **懒加载**：mem0 只在首次实例化时 import；未安装/配置失败时 ``health()``
  返回 False，调用方降级到本地 RRF，模块导入本身永不抛错。
- **单向投影**：``mem0_index.json`` 维护 ``episode_id → memory_id`` 映射，
  任何后端状态可由 ``rebuild`` 从 episodes 全量重建。
- **可注入 client**：``client_factory`` 默认走真实 mem0，测试注入 fake，使本
  模块在未安装 mem0 的环境也能被完整测试。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from hermes.workbench.persistence import atomic_write_json, safe_read_json

if TYPE_CHECKING:  # pragma: no cover - type-check only
    from hermes.workbench.memory import Episode, MemoryService

logger = logging.getLogger("hermes.workbench.mem0_adapter")

__all__ = ["Mem0Backend", "Mem0BackendConfig"]


class Mem0Client(Protocol):
    """Minimal surface of the mem0 ``Memory`` client that we depend on."""

    def add(self, messages: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]: ...

    def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]: ...

    def delete(self, memory_id: str) -> None: ...

    def get_all(self, **kwargs: Any) -> list[dict[str, Any]]: ...


@dataclass
class Mem0BackendConfig:
    """Mem0 backend configuration (defaults target local Ollama)."""

    user_id: str = "hermes"
    llm_model: str = ""
    embed_model: str = ""
    llm_base_url: str = ""
    embed_base_url: str = ""
    api_key: str = "ollama"


def _default_client_factory(config: Mem0BackendConfig) -> Mem0Client:
    """Build a real mem0 client (lazy import). Raises on failure."""
    from mem0 import Memory  # type: ignore[import-not-found]

    llm_model = config.llm_model or "llama3.2"
    embed_model = config.embed_model or "nomic-embed-text"
    llm_base = config.llm_base_url or "http://localhost:11434/v1"
    embed_base = config.embed_base_url or "http://localhost:11434/v1"

    mem0_config: dict[str, Any] = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": llm_model,
                "api_key": config.api_key,
                "openai_base_url": llm_base,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": embed_model,
                "api_key": config.api_key,
                "openai_base_url": embed_base,
            },
        },
    }
    return Memory.from_config(mem0_config)  # type: ignore[no-any-return]


class Mem0Backend:
    """Mem0-backed implementation of the :class:`MemoryBackend` protocol."""

    def __init__(
        self,
        memory: MemoryService,
        state_dir: Path,
        config: Mem0BackendConfig | None = None,
        client_factory: Any = None,
    ) -> None:
        self._memory = memory
        self._config = config or Mem0BackendConfig()
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._state_dir / "mem0_index.json"
        self._index: dict[str, str] = self._load_index()
        self._client: Mem0Client | None = None
        self._client_error: str | None = None
        self._client_factory: Any = client_factory or _default_client_factory
        self._init_client()

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------
    def _init_client(self) -> None:
        try:
            self._client = self._client_factory(self._config)
            self._client_error = None
        except Exception as exc:  # noqa: BLE001 — optional backend boundary
            self._client = None
            self._client_error = str(exc)
            logger.warning("mem0 backend unavailable: %s", exc)

    def health(self) -> bool:
        return self._client is not None

    def _require_client(self) -> Mem0Client:
        if self._client is None:
            raise RuntimeError(self._client_error or "mem0 client unavailable")
        return self._client

    # ------------------------------------------------------------------
    # Index persistence (episode_id -> memory_id)
    # ------------------------------------------------------------------
    def _load_index(self) -> dict[str, str]:
        data = safe_read_json(self._index_path, default={})
        return data if isinstance(data, dict) else {}

    def _save_index(self) -> None:
        atomic_write_json(self._index_path, self._index)

    @staticmethod
    def _episode_text(episode: Episode) -> str:
        text = episode.summary
        if episode.details:
            text += " " + json.dumps(episode.details, ensure_ascii=False)
        return text

    # ------------------------------------------------------------------
    # MemoryBackend implementation
    # ------------------------------------------------------------------
    def index_episode(self, episode: Episode) -> None:
        client = self._require_client()
        results = client.add(
            messages=[{"role": "user", "content": self._episode_text(episode)}],
            user_id=self._config.user_id,
            metadata={"episode_id": episode.id, "kind": episode.kind},
        )
        memory_id = self._extract_memory_id(results)
        if memory_id:
            self._index[episode.id] = memory_id
            self._save_index()

    def delete_episode(self, episode_id: str) -> None:
        memory_id = self._index.get(episode_id)
        if memory_id is None:
            return
        client = self._require_client()
        try:
            client.delete(memory_id)
        finally:
            self._index.pop(episode_id, None)
            self._save_index()

    def rebuild(self, episodes: list[Episode]) -> None:
        client = self._require_client()
        # Delete every tracked memory, then re-index from ground truth.
        for memory_id in list(self._index.values()):
            try:
                client.delete(memory_id)
            except Exception:  # noqa: BLE001 — best-effort clear
                pass
        self._index.clear()
        self._save_index()
        for episode in episodes:
            self.index_episode(episode)

    def indexed_ids(self) -> set[str]:
        return set(self._index.keys())

    def search(
        self, query: str, limit: int = 10, kind: str | None = None
    ) -> list[tuple[Episode, float]]:
        client = self._require_client()
        if not query or not query.strip():
            return []
        results = client.search(query, user_id=self._config.user_id, limit=limit)
        episodes = self._memory.list_episodes(limit=10**9)
        by_id = {ep.id: ep for ep in episodes}
        scored: list[tuple[Episode, float]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            metadata = r.get("metadata")
            episode_id = None
            if isinstance(metadata, dict):
                episode_id = metadata.get("episode_id")
            if episode_id is None:
                continue
            episode = by_id.get(str(episode_id))
            if episode is None:
                continue
            if kind is not None and episode.kind != kind:
                continue
            score = r.get("score")
            try:
                score_f = float(score) if score is not None else 0.0
            except (TypeError, ValueError):
                score_f = 0.0
            scored.append((episode, score_f))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    @staticmethod
    def _extract_memory_id(results: list[dict[str, Any]]) -> str | None:
        for r in results:
            if isinstance(r, dict) and r.get("id"):
                return str(r["id"])
        return None

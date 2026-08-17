"""Memory backend protocol and the local RRF baseline implementation.

M4 记忆升级：把记忆检索抽象为一个可替换的后端协议。两个实现：

- :class:`LocalRRFBackend` — 现有 ``MemoryService.search_episodes_rrf`` 的薄封装，
  直接从 ``episodes.jsonl`` 推导，无独立索引，永远是保底基线（stdlib-only）。
- ``Mem0Backend``（``mem0_adapter.py``）— 可选外部后端，懒加载 mem0。

协议契约（ADR-0021）：

- ``index_episode`` / ``delete_episode`` / ``rebuild`` 是**单向投影**：episodes.jsonl
  是 ground truth，后端侧任何状态都可由 ``rebuild`` 重建。
- ``search`` 返回 ``(Episode, score)``，分数越高越相关；空查询/无结果返回 ``[]``。
- ``health`` 为 False 时，调用方必须降级到本地 RRF，不得抛错。

所有类型注解用 ``from __future__ import annotations`` 延迟求值，``Episode`` /
``MemoryService`` 仅在 TYPE_CHECKING 下导入，避免与 ``memory.py`` 形成运行时循环依赖。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - type-check only
    from hermes.workbench.memory import Episode, MemoryService

__all__ = ["LocalRRFBackend", "MemoryBackend"]


class MemoryBackend(Protocol):
    """Pluggable memory retrieval/indexing backend."""

    def search(
        self, query: str, limit: int = 10, kind: str | None = None
    ) -> list[tuple[Episode, float]]: ...

    def index_episode(self, episode: Episode) -> None: ...

    def delete_episode(self, episode_id: str) -> None: ...

    def rebuild(self, episodes: list[Episode]) -> None: ...

    def indexed_ids(self) -> set[str]: ...

    def health(self) -> bool: ...


class LocalRRFBackend:
    """Baseline backend: delegate to the local MemoryService RRF search.

    本地后端不维护独立索引——检索直接从 ``episodes.jsonl`` 推导，因此
    ``index_episode`` / ``delete_episode`` / ``rebuild`` 都是 no-op，
    ``indexed_ids`` 恒等于当前全部 episode id（即「全量已索引」）。
    """

    def __init__(self, memory: MemoryService) -> None:
        self._memory = memory

    def search(
        self, query: str, limit: int = 10, kind: str | None = None
    ) -> list[tuple[Episode, float]]:
        return self._memory.search_episodes_rrf(query, limit=limit, kind=kind)

    def index_episode(self, episode: Episode) -> None:
        return None

    def delete_episode(self, episode_id: str) -> None:
        return None

    def rebuild(self, episodes: list[Episode]) -> None:
        return None

    def indexed_ids(self) -> set[str]:
        return {ep.id for ep in self._memory.list_episodes(limit=10**9)}

    def health(self) -> bool:
        return True

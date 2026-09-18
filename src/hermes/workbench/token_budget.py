"""全局每日 token 预算：用量记账 + 前置熔断（C4）。

采集每次 LLM 调用的 token 用量（来自 provider 响应的 ``usage`` 字段），
按日累计并落盘，并在调用前做预算熔断——达到上限即拒绝继续调用，避免
LLM 成本失控。

设计原则：
1. **零硬依赖**：仅 stdlib（json/threading），与运行时基线一致。
2. **记账 best-effort**：记录失败绝不打断业务请求；只有预算熔断是硬失败。
3. **可注入/可测**：``TokenUsageStore`` 可指向 tmp 目录；``DailyTokenBudget``
   接收 limit<=0 时表示不限制（关闭）。
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

__all__ = [
    "BudgetSnapshot",
    "DailyTokenBudget",
    "TokenBudgetExceeded",
    "TokenUsageStore",
]


class TokenBudgetExceeded(Exception):
    """Raised by :meth:`DailyTokenBudget.preflight` when the budget is spent."""


@dataclass(frozen=True)
class BudgetSnapshot:
    """A day's accumulated token usage."""

    day: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class TokenUsageStore:
    """JSON-backed daily token usage ledger under the state dir."""

    FILENAME = "token_usage.json"

    def __init__(self, state_dir: Path | str) -> None:
        self._path = Path(state_dir) / self.FILENAME
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, int]]:
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict[str, dict[str, int]]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        tmp.replace(self._path)

    def snapshot(self, day: str | None = None) -> BudgetSnapshot:
        """Return the usage for *day* (default today, UTC)."""
        key = day or date.today().isoformat()
        row = self._read().get(key) or {}
        return BudgetSnapshot(
            day=key,
            prompt_tokens=int(row.get("prompt_tokens", 0) or 0),
            completion_tokens=int(row.get("completion_tokens", 0) or 0),
            calls=int(row.get("calls", 0) or 0),
        )

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Add one call's usage to today's bucket (best-effort, thread-safe)."""
        day = date.today().isoformat()
        with self._lock:
            data = self._read()
            row = data.setdefault(
                day, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
            )
            row["prompt_tokens"] = int(row.get("prompt_tokens", 0)) + max(
                0, int(prompt_tokens)
            )
            row["completion_tokens"] = int(row.get("completion_tokens", 0)) + max(
                0, int(completion_tokens)
            )
            row["calls"] = int(row.get("calls", 0)) + 1
            self._write(data)


class DailyTokenBudget:
    """Preflight circuit-breaker over a :class:`TokenUsageStore`.

    ``limit <= 0`` disables enforcement (recording still happens).
    """

    def __init__(self, store: TokenUsageStore, limit: int) -> None:
        self.store = store
        self.limit = int(limit or 0)

    def preflight(self) -> None:
        """Raise :class:`TokenBudgetExceeded` when today's budget is spent."""
        if self.limit <= 0:
            return
        used = self.store.snapshot().total_tokens
        if used >= self.limit:
            raise TokenBudgetExceeded(
                f"daily token budget exhausted: {used}/{self.limit}"
            )

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record usage (best-effort; never raises into the caller)."""
        try:
            self.store.record(prompt_tokens, completion_tokens)
        except Exception:  # noqa: BLE001 — accounting must not break requests
            pass

    @staticmethod
    def usage_from_payload(payload: Any) -> tuple[int, int]:
        """Extract ``(prompt_tokens, completion_tokens)`` from a response payload.

        Tolerates missing/oddly-typed ``usage`` (returns ``(0, 0)``).
        """
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            return 0, 0

        def _int(key: str) -> int:
            try:
                return max(0, int(usage.get(key, 0) or 0))
            except (TypeError, ValueError):
                return 0

        return _int("prompt_tokens"), _int("completion_tokens")

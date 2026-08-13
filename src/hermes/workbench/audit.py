"""Persistent audit trail for external-system write/read operations.

The audit store appends structured records to ``.state/audit.jsonl`` using the
same lock-guarded append primitive as episodes, so audit history survives
process restarts. Clients (e.g. :class:`~hermes.mcp.GitHubMCPClient`) record a
call into both their in-memory log (for cheap access within a run) and this
store (for durability).

Public surface:
    * :class:`AuditRecord` — a single audited call
    * :class:`AuditStore` — append / list / tail over the JSONL log
    * :func:`default_audit_store` — singleton wired to ``Settings.hermes_state_dir``
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

from hermes.workbench.persistence import atomic_append_jsonl

__all__ = [
    "AuditRecord",
    "AuditStore",
    "default_audit_store",
]


@dataclass
class AuditRecord:
    """A single audited operation."""

    server: str
    method: str
    success: bool
    args: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    timestamp: str = ""
    record_id: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.record_id:
            self.record_id = uuid.uuid4().hex

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "timestamp": self.timestamp,
            "server": self.server,
            "method": self.method,
            "args": self.args,
            "success": self.success,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditRecord:
        args_raw = data.get("args")
        args: dict[str, Any] = args_raw if isinstance(args_raw, dict) else {}
        return cls(
            record_id=str(data.get("record_id", "")),
            timestamp=str(data.get("timestamp", "")),
            server=str(data.get("server", "")),
            method=str(data.get("method", "")),
            args=args,
            success=bool(data.get("success", False)),
            error=str(data.get("error", "")),
        )


class AuditStore:
    """Append-only audit log persisted to a JSONL file in *state_dir*."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.state_dir / "audit.jsonl"

    def record(
        self,
        server: str,
        method: str,
        success: bool,
        args: dict[str, Any] | None = None,
        error: str = "",
    ) -> AuditRecord:
        """Append an audit record and return it."""
        rec = AuditRecord(
            server=server,
            method=method,
            success=success,
            args=args or {},
            error=error,
        )
        atomic_append_jsonl(self._path, rec.to_dict())
        return rec

    def list(self, limit: int = 1000, server: str | None = None) -> List[AuditRecord]:
        """Return the most recent *limit* records, optionally filtered by server."""
        if not self._path.exists():
            return []
        records: List[AuditRecord] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rec = AuditRecord.from_dict(obj)
                if server is not None and rec.server != server:
                    continue
                records.append(rec)
        if limit <= 0:
            return []
        return records[-limit:]

    def tail(self, n: int = 20, server: str | None = None) -> List[AuditRecord]:
        """Return the last *n* records (alias for :meth:`list` with a small limit)."""
        return self.list(limit=n, server=server)


# Module-level singleton cache.
_store: AuditStore | None = None


def default_audit_store() -> AuditStore:
    """Return the process-wide audit store wired to the Hermes state dir."""
    global _store
    if _store is None:
        from hermes.config import get_settings

        _store = AuditStore(state_dir=get_settings().hermes_state_dir)
    return _store

"""U7: Personal todos, the todo→job bridge and the external sync ledger.

Conceptual split (PRD §4.3):
* **Todo** — a human-owned item ("写一篇关于博若莱新酒的文章").
* **Job** — an agent-executed run ("生成选题草稿", 8-state machine).
* **Hand-off** — explicitly bridging the two: the todo is marked ``HANDED_OFF``
  with the resulting ``job_id``. The bridge is **one-way**: job terminal states
  never write back to the todo, keeping a single source of truth.
* **SyncLedger** — ``external_ref`` mapping (e.g. GitHub issue# ↔ local id)
  with a conflict strategy: a local todo already ``DONE`` is read-only for the
  external side (pull never reverts it to open).

Stdlib-only, mirrors the ``JobStore`` SQLite pattern (WAL, busy_timeout,
thread-local connection, schema lock).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


__all__ = [
    "TodoStatus",
    "Todo",
    "TodoStore",
    "TodoService",
    "SyncLedger",
    "SyncConflict",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TodoStatus(str, Enum):
    PENDING = "PENDING"
    HANDED_OFF = "HANDED_OFF"
    DONE = "DONE"
    CANCELLED = "CANCELLED"

    def is_terminal(self) -> bool:
        return self in (TodoStatus.DONE, TodoStatus.CANCELLED)


class SyncConflict(str, Enum):
    """Conflict resolution for external two-way sync (PRD §4.3)."""

    # Local todo is terminal (DONE/CANCELLED) — the external side must not
    # revert it to open. External reads see it as closed.
    LOCAL_TERMINAL = "local_terminal"
    # No conflict: external change can be applied.
    APPLY = "apply"


_SCHEMA_LOCK = threading.Lock()


@dataclass
class Todo:
    """A personal todo item."""

    title: str
    type: str = "todo"  # idea | link | fact | todo | note
    status: TodoStatus = TodoStatus.PENDING
    due: str | None = None
    source: str = "manual"  # manual | inbox | feishu | github
    external_ref: str | None = None
    job_id: str | None = None
    todo_id: str = field(default_factory=lambda: _new_id("todo"))
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Todo":
        data = dict(data)
        data["status"] = TodoStatus(data.get("status", "PENDING"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class TodoStore:
    """SQLite-backed CRUD for personal todos (+ the sync ledger table)."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self.state_dir / "todos.db"
        self._local = threading.local()
        self._ensure_schema()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=True, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        with _SCHEMA_LOCK:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=True, timeout=30.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS todos("
                    "  todo_id TEXT PRIMARY KEY,"
                    "  status TEXT,"
                    "  type TEXT,"
                    "  payload TEXT"
                    ")"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_todos_type ON todos(type)")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS sync_ledger("
                    "  external_ref TEXT PRIMARY KEY,"
                    "  local_id TEXT NOT NULL,"
                    "  kind TEXT NOT NULL,"
                    "  direction TEXT NOT NULL DEFAULT 'push',"
                    "  state TEXT,"
                    "  created_at TEXT,"
                    "  updated_at TEXT"
                    ")"
                )
                conn.commit()
            finally:
                conn.close()

    # -- todos -------------------------------------------------------------

    def create(self, todo: Todo) -> Todo:
        conn = self._conn
        conn.execute(
            "INSERT OR REPLACE INTO todos(todo_id, status, type, payload) VALUES (?, ?, ?, ?)",
            (todo.todo_id, todo.status.value, todo.type, json.dumps(todo.to_dict(), ensure_ascii=False)),
        )
        conn.commit()
        return todo

    def get(self, todo_id: str) -> Todo | None:
        row = self._conn.execute(
            "SELECT payload FROM todos WHERE todo_id = ?", (todo_id,)
        ).fetchone()
        if row is None:
            return None
        return Todo.from_dict(json.loads(row[0]))

    def list(self, status: TodoStatus | None = None, type_: str | None = None) -> list[Todo]:
        sql = "SELECT payload FROM todos"
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if type_ is not None:
            clauses.append("type = ?")
            params.append(type_)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY json_extract(payload, '$.created_at'), rowid"
        rows = self._conn.execute(sql, params).fetchall()
        return [Todo.from_dict(json.loads(r[0])) for r in rows]

    def update_status(self, todo_id: str, status: TodoStatus) -> bool:
        """Atomically update status (+ updated_at) via SQLite json_set."""
        conn = self._conn
        now = _now_iso()
        cur = conn.execute(
            "UPDATE todos SET status = ?, "
            "payload = json_set(payload, '$.status', ?, '$.updated_at', ?) "
            "WHERE todo_id = ?",
            (status.value, status.value, now, todo_id),
        )
        conn.commit()
        return bool(cur.rowcount > 0)

    def set_job(self, todo_id: str, job_id: str) -> bool:
        conn = self._conn
        now = _now_iso()
        cur = conn.execute(
            "UPDATE todos SET status = ?, "
            "payload = json_set(payload, '$.status', ?, '$.job_id', ?, '$.updated_at', ?) "
            "WHERE todo_id = ?",
            (
                TodoStatus.HANDED_OFF.value,
                TodoStatus.HANDED_OFF.value,
                job_id,
                now,
                todo_id,
            ),
        )
        conn.commit()
        return bool(cur.rowcount > 0)

    def delete(self, todo_id: str) -> bool:
        conn = self._conn
        cur = conn.execute("DELETE FROM todos WHERE todo_id = ?", (todo_id,))
        conn.commit()
        return bool(cur.rowcount > 0)

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._local.conn = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass


class SyncLedger:
    """External two-way sync mapping (issue# ↔ local todo/job).

    Conflict strategy: a local record whose state is terminal (DONE/CANCELLED)
    is reported as ``SyncConflict.LOCAL_TERMINAL`` so the external side (e.g.
    GitHub pull) never reverts a completed local item back to open.
    """

    TERMINAL_STATES = {"DONE", "CANCELLED", "CLOSED"}

    def __init__(self, store: TodoStore) -> None:
        self._conn = store._conn

    def upsert(self, external_ref: str, local_id: str, kind: str, state: str | None = None) -> None:
        now = _now_iso()
        self._conn.execute(
            "INSERT OR REPLACE INTO sync_ledger"
            "(external_ref, local_id, kind, state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM sync_ledger "
            "WHERE external_ref = ?), ?), ?)",
            (external_ref, local_id, kind, state, external_ref, now, now),
        )
        self._conn.commit()

    def get(self, external_ref: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM sync_ledger WHERE external_ref = ?", (external_ref,)
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._conn.execute("SELECT * FROM sync_ledger LIMIT 0").description]
        return dict(zip(cols, row))

    def resolve_conflict(self, external_ref: str, incoming_state: str) -> SyncConflict:
        """Decide whether an incoming external state change may be applied."""
        record = self.get(external_ref)
        if record is None:
            return SyncConflict.APPLY
        if (record.get("state") or "").upper() in self.TERMINAL_STATES:
            return SyncConflict.LOCAL_TERMINAL
        return SyncConflict.APPLY


class TodoService:
    """Bridge between todos and the scheduler center (hand-off is one-way)."""

    def __init__(self, store: TodoStore) -> None:
        self.store = store

    def hand_off(
        self,
        todo_id: str,
        plan: list[dict[str, Any]],
        project: str = "default",
        priority: int = 5,
        timeout: float | None = None,
    ) -> str:
        """Create a job for *todo_id* and mark the todo HANDED_OFF.

        Returns the created ``job_id``. Raises ``ValueError`` when the todo is
        missing or already terminal (a terminal todo cannot be handed off).
        """
        todo = self.store.get(todo_id)
        if todo is None:
            raise ValueError(f"todo not found: {todo_id}")
        if todo.status.is_terminal():
            raise ValueError(f"todo {todo_id} is already terminal: {todo.status.value}")

        from hermes.workbench import cli as wb_cli
        from hermes.workbench.cli import Task
        from hermes.workbench.scheduler import JobStatus, ScheduledJob

        center = wb_cli._make_scheduler_center()
        task = Task(task_id=f"job-{uuid.uuid4().hex[:8]}", plan=plan, mode="oneshot")
        job = ScheduledJob(
            task=task,
            target_project=project,
            priority=priority,
            timeout=timeout,
        )
        center.job_store.save(job)
        job.status = JobStatus.QUEUED
        center.job_store.save(job)
        center.job_queue.put(job)
        center.status_bus.emit(job)
        self.store.set_job(todo_id, job.job_id)
        return job.job_id

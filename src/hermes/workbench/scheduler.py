"""Phase 3 scheduling center core.

Provides the in-process async job execution layer built on top of the existing
``TaskScheduler`` / ``AgentLoop`` / ``Orchestrator`` primitives. All concurrency
uses the Python standard library (``threading`` / ``queue``); no external
dependencies are introduced.

Key components:
- ``ScheduledJob`` / ``JobExecution`` / ``JobStatus``: data model + lifecycle
- ``RetryPolicy``: exponential backoff retry configuration
- ``JobStore``: thread-safe persistence (Lock + atomic_write_json)
- ``JobQueue``: priority queue (priority, seq) FIFO within same priority
- ``WorkerPool``: N daemon workers consuming jobs, with cancel/retry/timeout
- ``StatusBus``: in-process pub/sub for job status changes (used by SSE)

Design contract: this module only owns queueing/routing/lifecycle. Actual job
execution delegates to ``ProjectRuntime.scheduler().run(task_id)`` which wraps
the existing ``TaskScheduler.run``. We never re-implement execution logic.
"""

from __future__ import annotations

import builtins
import json
import queue as _queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from hermes.workbench.persistence import safe_read_json

# Guards concurrent first-touch schema creation on the JobStore SQLite database.
_JOBSTORE_SCHEMA_LOCK = threading.Lock()


__all__ = [
    "EmptyError",
    "JobExecution",
    "JobQueue",
    "JobQueueBackend",
    "JobStatus",
    "JobStore",
    "RetryPolicy",
    "ScheduledJob",
    "StatusBus",
    "WorkerPool",
    "compute_metrics",
]


# ---------------------------------------------------------------------------
# JobStatus
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """Lifecycle states of a ScheduledJob."""

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    ABANDONED = "ABANDONED"

    def is_terminal(self) -> bool:
        """Return True for states that will never transition again."""
        return self in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
            JobStatus.ABANDONED,
        }


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------


@dataclass
class RetryPolicy:
    """Exponential backoff retry configuration."""

    max_retries: int = 0
    base_delay: float = 2.0
    max_delay: float = 60.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_retries": self.max_retries,
            "base_delay": self.base_delay,
            "max_delay": self.max_delay,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RetryPolicy:
        if not data:
            return cls()
        return cls(
            max_retries=int(data.get("max_retries", 0)),
            base_delay=float(data.get("base_delay", 2.0)),
            max_delay=float(data.get("max_delay", 60.0)),
        )


# ---------------------------------------------------------------------------
# JobExecution
# ---------------------------------------------------------------------------


@dataclass
class JobExecution:
    """A single execution attempt of a ScheduledJob."""

    attempt_num: int
    started_at: str
    ended_at: str | None = None
    status: JobStatus = JobStatus.RUNNING
    error: str | None = None
    trace_id: str | None = None
    round_summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_num": self.attempt_num,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status.value,
            "error": self.error,
            "trace_id": self.trace_id,
            "round_summary": self.round_summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobExecution:
        return cls(
            attempt_num=int(data["attempt_num"]),
            started_at=data["started_at"],
            ended_at=data.get("ended_at"),
            status=JobStatus(data.get("status", "RUNNING")),
            error=data.get("error"),
            trace_id=data.get("trace_id"),
            round_summary=data.get("round_summary"),
        )


# ---------------------------------------------------------------------------
# ScheduledJob
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC timestamp in ISO 8601."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _task_to_dict(task: Any) -> dict[str, Any]:
    """Serialize a Task object (duck-typed: has to_dict())."""
    if hasattr(task, "to_dict"):
        result: dict[str, Any] = task.to_dict()
        return result
    if isinstance(task, dict):
        return task
    raise TypeError(f"task must have to_dict() or be a dict, got {type(task)}")


def _task_from_dict(data: dict[str, Any]) -> Any:
    """Deserialize a Task (lazy import to avoid circular dependency)."""
    from hermes.workbench.cli import Task

    return Task(
        task_id=data.get("task_id", ""),
        plan=data.get("plan", []),
        mode=data.get("mode", "oneshot"),
        max_rounds=int(data.get("max_rounds", 1)),
        max_runs=int(data.get("max_runs", 1)),
        interval=float(data.get("interval", 0.0)),
        goal=data.get("goal"),
    )


@dataclass
class ScheduledJob:
    """A scheduling unit: Task + routing + priority + retry + lifecycle."""

    task: Any
    job_id: str = ""
    target_project: str = "default"
    priority: int = 5
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: float | None = None
    depends_on: list[str] = field(default_factory=list)
    status: JobStatus = JobStatus.PENDING
    attempts: list[JobExecution] = field(default_factory=list)
    created_at: str = ""
    submitted_by: str = "cli"
    queued_at: str | None = None
    started_at: str | None = None
    # Non-persistent: cancel signal shared with worker
    cancel_event: threading.Event = field(
        default_factory=threading.Event, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.job_id:
            self.job_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = _now_iso()

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence. Excludes cancel_event (not pickleable cross-process)."""
        return {
            "job_id": self.job_id,
            "task": _task_to_dict(self.task),
            "target_project": self.target_project,
            "priority": self.priority,
            "retry_policy": self.retry_policy.to_dict(),
            "timeout": self.timeout,
            "depends_on": list(self.depends_on),
            "status": self.status.value,
            "attempts": [a.to_dict() for a in self.attempts],
            "created_at": self.created_at,
            "submitted_by": self.submitted_by,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduledJob:
        return cls(
            task=_task_from_dict(data.get("task", {})),
            job_id=data.get("job_id", ""),
            target_project=data.get("target_project", "default"),
            priority=int(data.get("priority", 5)),
            retry_policy=RetryPolicy.from_dict(data.get("retry_policy")),
            timeout=data.get("timeout"),
            depends_on=list(data.get("depends_on", [])),
            status=JobStatus(data.get("status", "PENDING")),
            attempts=[JobExecution.from_dict(a) for a in data.get("attempts", [])],
            created_at=data.get("created_at", _now_iso()),
            submitted_by=data.get("submitted_by", "cli"),
            queued_at=data.get("queued_at"),
            started_at=data.get("started_at"),
        )

    @classmethod
    def from_template(cls, template: dict[str, Any], submitted_by: str = "cron") -> ScheduledJob:
        """Instantiate a new job from a template (job_id/status/attempts regenerated)."""
        template = dict(template)
        template.pop("job_id", None)
        template["status"] = "PENDING"
        template.pop("attempts", None)
        template.pop("queued_at", None)
        template.pop("started_at", None)
        template["submitted_by"] = submitted_by
        return cls.from_dict(template)


# ---------------------------------------------------------------------------
# JobStore
# ---------------------------------------------------------------------------


class JobStore:
    """Thread-safe persistence for ScheduledJob + execution history.

    Backed by SQLite (stdlib ``sqlite3``, WAL mode) for concurrent read/write
    without a global lock. Each thread uses its own connection (sqlite3
    connections are thread-affine); schema creation is guarded by a module
    lock. On first construction, a legacy ``jobs.json`` file (from the pre-SQLite
    implementation) is migrated in automatically, then left in place for a
    30-day grace window (never deleted).
    """

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self.state_dir / "jobs.db"
        self._legacy_path = self.state_dir / "jobs.json"
        self._local = threading.local()
        self._ensure_schema()
        self._migrate_legacy()

    @property
    def _conn(self) -> Any:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = __import__("sqlite3").connect(
                str(self._db_path), check_same_thread=True, timeout=30.0
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        import sqlite3

        with _JOBSTORE_SCHEMA_LOCK:
            conn = sqlite3.connect(
                str(self._db_path), check_same_thread=True, timeout=30.0
            )
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS jobs("
                    "  job_id TEXT PRIMARY KEY,"
                    "  status TEXT,"
                    "  target_project TEXT,"
                    "  payload TEXT"
                    ")"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(target_project)"
                )
                conn.commit()
            finally:
                conn.close()

    def _migrate_legacy(self) -> None:
        """Import a legacy ``jobs.json`` into SQLite (idempotent)."""
        if not self._legacy_path.exists():
            return
        data = safe_read_json(self._legacy_path, default={})
        if not isinstance(data, dict):
            return
        conn = self._conn
        for job_id, payload in data.items():
            if not isinstance(payload, dict):
                continue
            status = str(payload.get("status", "PENDING"))
            project = str(payload.get("target_project", "default"))
            conn.execute(
                "INSERT OR IGNORE INTO jobs(job_id, status, target_project, payload) "
                "VALUES (?, ?, ?, ?)",
                (
                    job_id,
                    status,
                    project,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        conn.commit()

    def save(self, job: ScheduledJob) -> None:
        conn = self._conn
        payload = job.to_dict()
        conn.execute(
            "INSERT OR REPLACE INTO jobs(job_id, status, target_project, payload) "
            "VALUES (?, ?, ?, ?)",
            (
                job.job_id,
                job.status.value,
                job.target_project,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()

    def get(self, job_id: str) -> ScheduledJob | None:
        row = self._conn.execute(
            "SELECT payload FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return ScheduledJob.from_dict(json.loads(row[0]))

    def list(self) -> builtins.list[ScheduledJob]:
        # Order by the job's creation timestamp (inside payload JSON) so
        # re-saving a job (INSERT OR REPLACE reassigns rowid) does not change
        # its ordering position.
        rows = self._conn.execute(
            "SELECT payload FROM jobs "
            "ORDER BY json_extract(payload, '$.created_at'), rowid"
        ).fetchall()
        return [ScheduledJob.from_dict(json.loads(r[0])) for r in rows]

    def list_by_status(self, status: JobStatus) -> builtins.list[ScheduledJob]:
        rows = self._conn.execute(
            "SELECT payload FROM jobs WHERE status = ? "
            "ORDER BY json_extract(payload, '$.created_at'), rowid",
            (status.value,),
        ).fetchall()
        return [ScheduledJob.from_dict(json.loads(r[0])) for r in rows]

    def update_status(self, job_id: str, status: JobStatus) -> bool:
        """Atomically update a job's status (single SQL statement).

        Uses SQLite's ``json_set`` so the read-modify-write of the payload's
        status field is one atomic statement — no lost-update window between a
        SELECT and an UPDATE.
        """
        conn = self._conn
        cur = conn.execute(
            "UPDATE jobs SET status = ?, "
            "payload = json_set(payload, '$.status', ?) "
            "WHERE job_id = ?",
            (status.value, status.value, job_id),
        )
        conn.commit()
        return bool(cur.rowcount > 0)

    def delete(self, job_id: str) -> bool:
        conn = self._conn
        cur = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
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


# ---------------------------------------------------------------------------
# JobQueue
# ---------------------------------------------------------------------------


class EmptyError(_queue.Empty):
    """Raised by JobQueue.get when no job available within timeout."""


class JobQueueBackend(Protocol):
    """Backend contract for the scheduler's job queue (P2-3).

    The in-process :class:`JobQueue` is the default implementation (stdlib
    ``queue.PriorityQueue``). A broker-backed implementation (e.g. Redis
    Streams / RQ / RabbitMQ) only needs to satisfy ``put`` / ``get`` /
    ``size`` to plug into :class:`WorkerPool` — the lifecycle of the *job
    payload* remains the same ``ScheduledJob`` object (serialized to JSON by
    the broker adapter). This keeps a clean seam for future multi-machine
    scheduling without changing WorkerPool's execution logic.
    """

    def put(self, job: ScheduledJob) -> None: ...

    def get(self, timeout: float = 0.0) -> ScheduledJob: ...

    def size(self) -> int: ...


class JobQueue:
    """Thread-safe priority queue (in-memory ``JobQueueBackend`` implementation).

    Items are dequeued by ``(priority, seq)`` ascending — lower priority value
    means higher urgency. Within the same priority, FIFO order is preserved via
    a monotonic ``seq`` counter.
    """

    def __init__(self) -> None:
        self._pq: _queue.PriorityQueue[tuple[int, int, ScheduledJob]] = _queue.PriorityQueue()
        self._seq = 0
        self._seq_lock = threading.Lock()

    def put(self, job: ScheduledJob) -> None:
        with self._seq_lock:
            seq = self._seq
            self._seq += 1
        if job.queued_at is None:
            job.queued_at = _now_iso()
        self._pq.put((job.priority, seq, job))

    def get(self, timeout: float = 0.0) -> ScheduledJob:
        """Block up to *timeout* seconds for a job. Raise EmptyError if none."""
        try:
            _, _, job = self._pq.get(timeout=timeout)
            return job
        except _queue.Empty as e:
            raise EmptyError() from e

    def size(self) -> int:
        return self._pq.qsize()


# ---------------------------------------------------------------------------
# StatusBus
# ---------------------------------------------------------------------------


class StatusBus:
    """In-process pub/sub for job status changes.

    Workers emit events; SSE handlers subscribe. Queue overflow drops old
    events (put_nowait) to avoid blocking workers.
    """

    def __init__(self) -> None:
        self._subscribers: list[_queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def emit(self, job: ScheduledJob) -> None:
        event = {
            "job_id": job.job_id,
            "status": job.status.value,
            "ts": _now_iso(),
        }
        with self._lock:
            subs = list(self._subscribers)
        for sub in subs:
            try:
                sub.put_nowait(event)
            except _queue.Full:
                # Drop oldest to make room
                try:
                    sub.get_nowait()
                except _queue.Empty:
                    pass
                try:
                    sub.put_nowait(event)
                except _queue.Full:
                    pass  # give up

    def subscribe(self) -> _queue.Queue[dict[str, Any]]:
        q: _queue.Queue[dict[str, Any]] = _queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: _queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# WorkerPool
# ---------------------------------------------------------------------------


class WorkerPool:
    """N daemon workers consuming jobs from JobQueue.

    Each worker:
    1. Blocks on JobQueue.get
    2. Resolves ProjectRuntime via Router
    3. try_acquire concurrency slot (requeue + sleep on failure)
    4. Runs job with cancel_event check between steps
    5. Applies RetryPolicy on failure (exponential backoff)
    6. Starts TimeoutWatcher if job.timeout set
    7. Calls DependencyGraph.on_job_done callback (if set)
    8. Releases concurrency slot in finally
    """

    def __init__(
        self,
        size: int,
        router: Any,
        queue: JobQueueBackend,
        store: JobStore,
        bus: StatusBus | None = None,
        requeue_sleep: float = 1.0,
        on_job_done: Callable[[str, JobStatus], None] | None = None,
    ) -> None:
        self.size = size
        self._router = router
        self._queue = queue
        self._store = store
        self._bus = bus or StatusBus()
        self._requeue_sleep = requeue_sleep
        self._on_job_done = on_job_done
        self._stop = threading.Event()
        self._workers: list[threading.Thread] = []

    def start(self) -> None:
        if self._workers:
            return  # already started
        self._stop.clear()
        for i in range(self.size):
            t = threading.Thread(target=self._loop, name=f"worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._workers:
            t.join(timeout=2.0)
        self._workers = []

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except EmptyError:
                continue
            if job is None:
                break
            try:
                self._execute(job)
            except Exception:  # noqa: BLE001 - boundary
                # Worker must not die; mark job FAILED as last resort
                try:
                    job.status = JobStatus.FAILED
                    self._store.save(job)
                    self._bus.emit(job)
                except Exception:  # noqa: BLE001
                    pass

    def _execute(self, job: ScheduledJob) -> None:
        # Resolve runtime
        try:
            runtime = self._router.resolve(job.target_project)
        except Exception as e:  # noqa: BLE001
            job.status = JobStatus.FAILED
            exec_record = JobExecution(
                attempt_num=0,
                started_at=_now_iso(),
                ended_at=_now_iso(),
                status=JobStatus.FAILED,
                error=f"router resolve failed: {e}",
            )
            job.attempts.append(exec_record)
            self._store.save(job)
            self._bus.emit(job)
            self._fire_on_done(job)
            return

        # Concurrency limit
        if not self._router.try_acquire(job.target_project):
            # Requeue and sleep
            if not job.cancel_event.is_set():
                self._queue.put(job)
                time.sleep(self._requeue_sleep)
            return

        # Timeout watcher
        timer: threading.Timer | None = None
        if job.timeout is not None:
            timer = threading.Timer(job.timeout, job.cancel_event.set)
            timer.daemon = True
            timer.start()

        try:
            self._run_with_retries(job, runtime)
        finally:
            if timer is not None:
                timer.cancel()
            self._router.release(job.target_project)
            self._store.save(job)
            self._bus.emit(job)
            self._fire_on_done(job)

    def _run_with_retries(self, job: ScheduledJob, runtime: Any) -> None:
        max_attempts = job.retry_policy.max_retries + 1
        for attempt in range(max_attempts):
            if job.cancel_event.is_set():
                break
            exec_record = JobExecution(
                attempt_num=attempt,
                started_at=_now_iso(),
                status=JobStatus.RUNNING,
            )
            if job.started_at is None:
                job.started_at = _now_iso()
            job.status = JobStatus.RUNNING
            self._store.save(job)
            self._bus.emit(job)

            try:
                scheduler = runtime.scheduler()
                scheduler.run(job.task.task_id)
                # Check cancel after run
                if job.cancel_event.is_set():
                    exec_record.status = (
                        JobStatus.TIMEOUT if job.timeout is not None else JobStatus.CANCELLED
                    )
                    exec_record.ended_at = _now_iso()
                    job.attempts.append(exec_record)
                    job.status = exec_record.status
                    self._store.save(job)
                    self._bus.emit(job)
                    return
                exec_record.status = JobStatus.SUCCEEDED
                exec_record.ended_at = _now_iso()
                job.attempts.append(exec_record)
                job.status = JobStatus.SUCCEEDED
                self._store.save(job)
                self._bus.emit(job)
                return
            except Exception as e:  # noqa: BLE001
                exec_record.status = JobStatus.FAILED
                exec_record.ended_at = _now_iso()
                exec_record.error = str(e)
                job.attempts.append(exec_record)
                self._store.save(job)
                self._bus.emit(job)
                if attempt < max_attempts - 1:
                    delay = min(
                        job.retry_policy.base_delay * (2**attempt),
                        job.retry_policy.max_delay,
                    )
                    # Sleep but wake on stop
                    self._stop.wait(delay)
                    if self._stop.is_set():
                        job.status = JobStatus.FAILED
                        return
                else:
                    job.status = JobStatus.FAILED
                    return
        # If we exit the loop without success (e.g. cancel before first attempt)
        if not job.status.is_terminal():
            job.status = (
                JobStatus.TIMEOUT if job.timeout is not None and job.cancel_event.is_set()
                else JobStatus.CANCELLED if job.cancel_event.is_set()
                else JobStatus.FAILED
            )
            self._store.save(job)
            self._bus.emit(job)

    def _fire_on_done(self, job: ScheduledJob) -> None:
        if self._on_job_done is not None:
            try:
                self._on_job_done(job.job_id, job.status)
            except Exception:  # noqa: BLE001
                pass  # DAG callback must not break worker


# ---------------------------------------------------------------------------
# Metrics aggregation
# ---------------------------------------------------------------------------


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp (with trailing ``Z``) into a datetime.

    Returns ``None`` if *ts* is falsy or unparseable. ``_now_iso`` emits
    ``%Y-%m-%dT%H:%M:%SZ``; ``datetime.fromisoformat`` (3.11+) accepts the
    trailing ``Z`` directly, but we normalize for older runtimes.
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile: index ``int(len * p)`` clamped to ``[0, len-1]``."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * p), len(ordered) - 1)
    return ordered[idx]


def compute_metrics(jobs: list[ScheduledJob]) -> dict[str, Any]:
    """Aggregate job metrics for the dashboard ``/jobs/metrics`` endpoint.

    Returns a flat dict with status counts, success rate, and duration /
    queue-wait percentiles (avg + p95). Durations are derived from each
    attempt's ``started_at``/``ended_at``; queue wait is derived from the
    job-level ``queued_at`` → ``started_at`` delta. All times are in
    milliseconds. Empty input yields zeroed counters.
    """
    total = len(jobs)
    if total == 0:
        return {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "success_rate": 0.0,
            "avg_duration_ms": 0.0,
            "p95_duration_ms": 0.0,
            "avg_queue_wait_ms": 0.0,
            "p95_queue_wait_ms": 0.0,
        }

    status_counts: dict[str, int] = {s.value: 0 for s in JobStatus}
    durations: list[float] = []
    queue_waits: list[float] = []
    for job in jobs:
        status_counts[job.status.value] = status_counts.get(job.status.value, 0) + 1
        for attempt in job.attempts:
            started = _parse_iso(attempt.started_at)
            ended = _parse_iso(attempt.ended_at)
            if started is not None and ended is not None and ended > started:
                durations.append((ended - started).total_seconds() * 1000.0)
        queued = _parse_iso(job.queued_at)
        started_job = _parse_iso(job.started_at)
        if queued is not None and started_job is not None and started_job > queued:
            queue_waits.append((started_job - queued).total_seconds() * 1000.0)

    succeeded = status_counts.get(JobStatus.SUCCEEDED.value, 0)
    failed = status_counts.get(JobStatus.FAILED.value, 0)
    return {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "success_rate": succeeded / total if total else 0.0,
        "avg_duration_ms": sum(durations) / len(durations) if durations else 0.0,
        "p95_duration_ms": _percentile(durations, 0.95),
        "avg_queue_wait_ms": sum(queue_waits) / len(queue_waits) if queue_waits else 0.0,
        "p95_queue_wait_ms": _percentile(queue_waits, 0.95),
    }

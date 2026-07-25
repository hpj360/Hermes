"""Tests for Phase 3.5 DAG dependency module (dag.py).

Covers:
- AC-14: upstream SUCCEEDED → downstream auto-enqueued
- AC-15: upstream FAILED/CANCELLED/TIMEOUT/ABANDONED → downstream cascade-cancelled
- AC-16: cycle detection at register time → ValidationError
- Depth limit (10): 11-layer chain rejected at register
- ready_to_queue: partial vs all deps SUCCEEDED
- Multi-downstream fan-out
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.workbench.cli import Task
from hermes.workbench.dag import DependencyGraph
from hermes.workbench.errors import ValidationError
from hermes.workbench.scheduler import (
    JobQueue,
    JobStatus,
    JobStore,
    ScheduledJob,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(state_dir=tmp_path)


@pytest.fixture
def queue() -> JobQueue:
    return JobQueue()


@pytest.fixture
def graph(store: JobStore, queue: JobQueue) -> DependencyGraph:
    return DependencyGraph(store=store, queue=queue, bus=None)


def _make_job(job_id: str, depends_on: list[str] | None = None) -> ScheduledJob:
    """Construct a ScheduledJob with explicit id and deps."""
    return ScheduledJob(
        task=Task(task_id=f"task-{job_id}", plan=[]),
        job_id=job_id,
        depends_on=list(depends_on or []),
    )


# ---------------------------------------------------------------------------
# AC-14: upstream success auto-enqueues downstream
# ---------------------------------------------------------------------------


class TestAutoEnqueueOnSuccess:
    def test_downstream_enqueued_after_upstream_succeeds(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """AC-14: A→B, A done SUCCEEDED → B auto-queued."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])

        # B starts PENDING, queue empty
        assert store.get("job-B").status == JobStatus.PENDING
        assert queue.size() == 0

        # A completes successfully (worker updates store, then fires callback)
        store.update_status("job-A", JobStatus.SUCCEEDED)
        graph.on_job_done("job-A", JobStatus.SUCCEEDED)

        # B auto-enqueued
        assert queue.size() == 1
        enqueued = queue.get(timeout=1.0)
        assert enqueued.job_id == "job-B"
        assert store.get("job-B").status == JobStatus.QUEUED

    def test_downstream_not_enqueued_when_upstream_still_pending(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """A→B→C, A done SUCCEEDED → B enqueued, C stays PENDING (B not done)."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))
        store.save(_make_job("job-C", depends_on=["job-B"]))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])
        graph.register("job-C", ["job-B"])

        store.update_status("job-A", JobStatus.SUCCEEDED)
        graph.on_job_done("job-A", JobStatus.SUCCEEDED)

        # Only B should be enqueued; C still waits on B
        assert queue.size() == 1
        assert queue.get(timeout=1.0).job_id == "job-B"
        assert store.get("job-C").status == JobStatus.PENDING


# ---------------------------------------------------------------------------
# AC-15: upstream failure cascade-cancels downstream
# ---------------------------------------------------------------------------


class TestCascadeCancelOnFailure:
    def test_downstream_cancelled_after_upstream_fails(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """AC-15: A fails → B CANCELLED with 'upstream job-A FAILED'."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])

        store.update_status("job-A", JobStatus.FAILED)
        graph.on_job_done("job-A", JobStatus.FAILED)

        fetched = store.get("job-B")
        assert fetched is not None
        assert fetched.status == JobStatus.CANCELLED
        assert len(fetched.attempts) >= 1
        last = fetched.attempts[-1]
        assert last.status == JobStatus.CANCELLED
        assert last.error is not None
        assert "upstream job-A FAILED" in last.error

    def test_cascade_cancel_propagates_through_chain(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """A→B→C, A fails → B and C both CANCELLED with upstream reason."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))
        store.save(_make_job("job-C", depends_on=["job-B"]))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])
        graph.register("job-C", ["job-B"])

        store.update_status("job-A", JobStatus.FAILED)
        graph.on_job_done("job-A", JobStatus.FAILED)

        for jid in ("job-B", "job-C"):
            fetched = store.get(jid)
            assert fetched is not None
            assert fetched.status == JobStatus.CANCELLED
            assert fetched.attempts[-1].error is not None
            assert "upstream job-A FAILED" in fetched.attempts[-1].error

    def test_cascade_does_not_enqueue_anything(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """Failure path must never push downstream jobs into the queue."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])

        store.update_status("job-A", JobStatus.FAILED)
        graph.on_job_done("job-A", JobStatus.FAILED)

        assert queue.size() == 0

    @pytest.mark.parametrize(
        "status",
        [JobStatus.TIMEOUT, JobStatus.ABANDONED, JobStatus.CANCELLED],
    )
    def test_cascade_cancel_on_other_terminal_statuses(
        self, store: JobStore, queue: JobQueue, status: JobStatus
    ) -> None:
        """Non-FAILED terminal statuses also cascade-cancel downstreams."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))

        fresh_graph = DependencyGraph(store=store, queue=queue, bus=None)
        fresh_graph.register("job-A", [])
        fresh_graph.register("job-B", ["job-A"])

        store.update_status("job-A", status)
        fresh_graph.on_job_done("job-A", status)

        fetched = store.get("job-B")
        assert fetched is not None
        assert fetched.status == JobStatus.CANCELLED
        assert f"upstream job-A {status.value}" in (fetched.attempts[-1].error or "")


# ---------------------------------------------------------------------------
# AC-16: cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_direct_cycle_raises(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """AC-16: A→B and B→A is a cycle → ValidationError."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B"))

        graph.register("job-A", ["job-B"])  # A depends on B
        with pytest.raises(ValidationError):
            graph.register("job-B", ["job-A"])  # B depends on A → cycle

    def test_self_cycle_raises(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        store.save(_make_job("job-A"))
        with pytest.raises(ValidationError):
            graph.register("job-A", ["job-A"])

    def test_indirect_cycle_raises(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """A→B→C→A is a cycle."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B"))
        store.save(_make_job("job-C"))

        graph.register("job-A", ["job-B"])
        graph.register("job-B", ["job-C"])
        with pytest.raises(ValidationError):
            graph.register("job-C", ["job-A"])

    def test_no_cycle_when_diamond(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """Diamond A→B, A→C, B→D, C→D is NOT a cycle."""
        for jid in ("job-A", "job-B", "job-C", "job-D"):
            store.save(_make_job(jid))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])
        graph.register("job-C", ["job-A"])
        # D depends on both B and C — common ancestor A is fine, no cycle
        graph.register("job-D", ["job-B", "job-C"])


# ---------------------------------------------------------------------------
# Depth limit
# ---------------------------------------------------------------------------


class TestDepthLimit:
    def test_chain_at_depth_10_ok(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """10-layer chain (A..J) registers fine."""
        ids = [chr(ord("A") + i) for i in range(10)]  # A..J
        for i, jid in enumerate(ids):
            store.save(_make_job(jid))
            deps = [ids[i - 1]] if i > 0 else []
            graph.register(jid, deps)  # should not raise

    def test_chain_at_depth_11_raises(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """11-layer chain (A..K), registering K (depth 11) → ValidationError."""
        ids = [chr(ord("A") + i) for i in range(11)]  # A..K
        for i, jid in enumerate(ids[:10]):  # A..J at depths 1..10
            store.save(_make_job(jid))
            deps = [ids[i - 1]] if i > 0 else []
            graph.register(jid, deps)
        # Registering K would put it at depth 11 → reject
        store.save(_make_job(ids[10]))
        with pytest.raises(ValidationError):
            graph.register(ids[10], [ids[9]])


# ---------------------------------------------------------------------------
# ready_to_queue
# ---------------------------------------------------------------------------


class TestReadyToQueue:
    def test_no_deps_ready(self, graph: DependencyGraph) -> None:
        graph.register("job-A", [])
        assert graph.ready_to_queue("job-A") is True

    def test_unregistered_job_ready(self, graph: DependencyGraph) -> None:
        """Unknown job_id has no deps → ready (defensive default)."""
        assert graph.ready_to_queue("never-registered") is True

    def test_partial_deps_not_ready(
        self, store: JobStore, graph: DependencyGraph
    ) -> None:
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B"))
        store.save(_make_job("job-C", depends_on=["job-A", "job-B"]))

        graph.register("job-A", [])
        graph.register("job-B", [])
        graph.register("job-C", ["job-A", "job-B"])

        store.update_status("job-A", JobStatus.SUCCEEDED)
        # B still PENDING → C not ready
        assert graph.ready_to_queue("job-C") is False

    def test_all_deps_succeeded_ready(
        self, store: JobStore, graph: DependencyGraph
    ) -> None:
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B"))
        store.save(_make_job("job-C", depends_on=["job-A", "job-B"]))

        graph.register("job-A", [])
        graph.register("job-B", [])
        graph.register("job-C", ["job-A", "job-B"])

        store.update_status("job-A", JobStatus.SUCCEEDED)
        store.update_status("job-B", JobStatus.SUCCEEDED)
        assert graph.ready_to_queue("job-C") is True

    def test_dep_failed_not_ready(
        self, store: JobStore, graph: DependencyGraph
    ) -> None:
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])

        store.update_status("job-A", JobStatus.FAILED)
        assert graph.ready_to_queue("job-B") is False


# ---------------------------------------------------------------------------
# Multi-downstream fan-out
# ---------------------------------------------------------------------------


class TestMultiDownstreamFanOut:
    def test_succeeded_enqueues_all_ready_downstreams(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """A→B, A→C; A done SUCCEEDED → both B and C enqueued."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))
        store.save(_make_job("job-C", depends_on=["job-A"]))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])
        graph.register("job-C", ["job-A"])

        store.update_status("job-A", JobStatus.SUCCEEDED)
        graph.on_job_done("job-A", JobStatus.SUCCEEDED)

        assert queue.size() == 2
        enqueued_ids = set()
        while queue.size() > 0:
            enqueued_ids.add(queue.get(timeout=1.0).job_id)
        assert enqueued_ids == {"job-B", "job-C"}

    def test_partial_fanout_only_ready_enqueued(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """A→B, A→C where C also depends on D (D not done).

        A succeeds → only B enqueued, C stays PENDING.
        """
        store.save(_make_job("job-A"))
        store.save(_make_job("job-D"))
        store.save(_make_job("job-B", depends_on=["job-A"]))
        store.save(_make_job("job-C", depends_on=["job-A", "job-D"]))

        graph.register("job-A", [])
        graph.register("job-D", [])
        graph.register("job-B", ["job-A"])
        graph.register("job-C", ["job-A", "job-D"])

        store.update_status("job-A", JobStatus.SUCCEEDED)
        graph.on_job_done("job-A", JobStatus.SUCCEEDED)

        assert queue.size() == 1
        enqueued = queue.get(timeout=1.0)
        assert enqueued.job_id == "job-B"
        assert store.get("job-C").status == JobStatus.PENDING

    def test_already_queued_downstream_not_re_enqueued(
        self, store: JobStore, queue: JobQueue, graph: DependencyGraph
    ) -> None:
        """A→B; B already QUEUED manually → on_job_done(A) must not double-enqueue."""
        store.save(_make_job("job-A"))
        store.save(_make_job("job-B", depends_on=["job-A"]))

        graph.register("job-A", [])
        graph.register("job-B", ["job-A"])

        # Pre-queue B manually
        b = store.get("job-B")
        b.status = JobStatus.QUEUED
        store.save(b)

        store.update_status("job-A", JobStatus.SUCCEEDED)
        graph.on_job_done("job-A", JobStatus.SUCCEEDED)

        # Should NOT have been re-enqueued
        assert queue.size() == 0

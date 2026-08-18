"""Workbench CLI: skills / run / loop / memory / task / serve subcommands.

Service factories are module-level so tests can monkeypatch them. The CLI is
registered into the top-level ``hermes`` parser via ``add_workbench_subparser``
and is also runnable standalone through ``workbench_main``.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hermes.config import get_settings
from hermes.skills import skills_dir as _hermes_skills_dir
from hermes.workbench.agent_loop import AgentLoop, LoopStep
from hermes.workbench.memory import MemoryService
from hermes.workbench.skill_runner import SkillRunner

# ---------------------------------------------------------------------------
# Task runtime (minimal; the full scheduler lands in P2)
# ---------------------------------------------------------------------------


class Task:
    """A registered task definition with its run history."""

    def __init__(
        self,
        task_id: str,
        plan: list[dict[str, Any]],
        mode: str = "oneshot",
        max_rounds: int = 1,
        max_runs: int = 1,
        interval: float = 0.0,
        goal: dict[str, Any] | None = None,
    ) -> None:
        self.task_id = task_id
        self.plan = plan
        self.mode = mode
        self.max_rounds = max_rounds
        self.max_runs = max_runs
        self.interval = interval
        self.goal = goal
        self.status = "PENDING"
        self.rounds: list[dict[str, Any]] = []
        self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "plan": self.plan,
            "mode": self.mode,
            "max_rounds": self.max_rounds,
            "max_runs": self.max_runs,
            "interval": self.interval,
            "goal": self.goal,
            "status": self.status,
            "rounds": self.rounds,
            "created_at": self.created_at,
        }


class TaskStore:
    """Persistence for task definitions and their run history."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.state_dir / "tasks.json"
        self._tasks: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        from hermes.workbench.persistence import atomic_write_json
        atomic_write_json(self._path, self._tasks)

    def save(self, task: Task) -> None:
        self._tasks[task.task_id] = task.to_dict()
        self._save()

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self._tasks.get(task_id)

    def list(self) -> list[dict[str, Any]]:
        return list(self._tasks.values())

    def update_status(self, task_id: str, status: str) -> bool:
        if task_id not in self._tasks:
            return False
        self._tasks[task_id]["status"] = status
        self._save()
        return True


class TaskRegistry:
    """In-memory registry of live Task objects."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def register(self, task: Task) -> Task:
        self._tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        return list(self._tasks.values())


class TaskScheduler:
    """Runs registered tasks via the AgentLoop."""

    def __init__(
        self,
        store: TaskStore,
        registry: TaskRegistry,
        runner: SkillRunner,
        memory: MemoryService,
        llm: Any | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.runner = runner
        self.memory = memory
        self.llm = llm

    def run(self, task_id: str) -> Any:
        task = self.registry.get(task_id)
        if task is None:
            return None
        if task.mode == "loop":
            results = self.run_loop(task_id)
            return results[-1] if results else None
        loop = AgentLoop(runner=self.runner, memory=self.memory)
        plan = [
            LoopStep(
                skill=step["skill"],
                args=list(step.get("args", [])),
                timeout=step.get("timeout"),
                abort_on_error=step.get("abort_on_error", False),
            )
            for step in task.plan
        ]
        result = loop.execute(plan)
        task.rounds.append(
            {
                "ok": result.ok,
                "steps": len(result.steps),
                "error": result.error,
                "at": time.time(),
            }
        )
        task.status = "COMPLETED" if result.ok else "FAILED"
        self.store.save(task)
        return result

    def run_loop(self, task_id: str) -> list[Any]:
        """Run task in loop mode: iterate until goal is met or boundary hit.

        Uses Planner/Generator/Evaluator sub-agents for each cycle.
        Each round opens a tracing span so all episodes recorded by the
        three sub-agents share a ``trace_id``, making the full chain
        reconstructable for debugging.
        Returns the list of LoopResult objects from each run.
        """
        from hermes.workbench.goal import (
            EvaluatorAgent,
            GeneratorAgent,
            Goal,
            GoalBoundary,
            PlannerAgent,
        )
        from hermes.workbench.tracing import Tracer

        task = self.registry.get(task_id)
        if task is None:
            return []

        goal = Goal.from_dict(task.goal) if task.goal else None
        boundary = goal.boundary if goal else GoalBoundary(
            max_rounds=task.max_runs or 1
        )

        tracer = Tracer(self.memory)
        planner = PlannerAgent(self.runner, self.memory, llm=self.llm, tracer=tracer)
        generator = GeneratorAgent(
            self.runner, self.memory, llm=self.llm, tracer=tracer
        )
        evaluator = EvaluatorAgent(
            self.runner, self.memory, llm=self.llm, tracer=tracer
        )

        fallback_plan = [
            LoopStep(
                skill=step["skill"],
                args=list(step.get("args", [])),
                timeout=step.get("timeout"),
                abort_on_error=step.get("abort_on_error", False),
            )
            for step in task.plan
        ]

        results: list[Any] = []
        start_time = time.time()
        consecutive_failures = 0

        # Bind task_id to log context for the entire loop run.
        from contextlib import nullcontext
        loop_ctx: Any = nullcontext()
        try:
            from hermes.workbench.structured_logging import log_context
            loop_ctx = log_context(task_id=task_id, mode="loop")
        except Exception:  # noqa: BLE001
            pass  # loop_ctx 已初始化为 nullcontext 兜底

        with loop_ctx:
            for run_num in range(boundary.max_rounds):
                # Check time boundary
                if time.time() - start_time > boundary.max_time:
                    task.status = "TIMEOUT"
                    break
                # Check failure boundary
                if consecutive_failures >= boundary.max_failures:
                    task.status = "FAILED"
                    break

                # Each round gets its own trace_id; episodes recorded by the
                # planner/generator/evaluator within this span all share it.
                with tracer.span() as trace_id:
                    plan = planner.plan(goal, fallback_plan)
                    result = generator.generate(plan)
                    results.append(result)
                    verification = evaluator.evaluate(result, goal)

                    task.rounds.append(
                        {
                            "run": run_num + 1,
                            "trace_id": trace_id,
                            "ok": result.ok,
                            "achieved": verification.achieved,
                            "evidence": verification.evidence,
                            "steps": len(result.steps),
                            "error": result.error,
                            "at": time.time(),
                        }
                    )

                if verification.achieved:
                    task.status = "COMPLETED"
                    break
                if not result.ok:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0

                if task.interval > 0 and run_num < boundary.max_rounds - 1:
                    time.sleep(task.interval)

            if task.status not in ("COMPLETED", "FAILED", "TIMEOUT"):
                task.status = "COMPLETED" if all(
                    getattr(r, "ok", False) for r in results
                ) else "FAILED"

        self.store.save(task)
        return results

    def cancel(self, task_id: str) -> bool:
        task = self.registry.get(task_id)
        if task is None:
            return False
        task.status = "CANCELLED"
        self.store.update_status(task_id, "CANCELLED")
        return True

    def list_rounds(self, task_id: str) -> list[dict[str, Any]]:
        task = self.registry.get(task_id)
        if task is None:
            return []
        return list(task.rounds)


# ---------------------------------------------------------------------------
# Service factories (module-level; patchable in tests)
# ---------------------------------------------------------------------------


def _state_dir() -> Path:
    return get_settings().hermes_state_dir


def _make_runner() -> SkillRunner:
    return SkillRunner(base_dir=_hermes_skills_dir())


_memory_lock: threading.Lock = threading.Lock()
_memory_cache: dict[tuple[str, str, bool], MemoryService] = {}


def _reset_memory_cache() -> None:
    """Drop the cached memory services (used by tests for state isolation)."""
    global _memory_cache
    with _memory_lock:
        for svc in _memory_cache.values():
            svc.stop_sync()
        _memory_cache = {}


def _make_memory() -> MemoryService:
    from hermes.config import get_settings
    from hermes.workbench.memory import EmbeddingClient, MemosConfig

    settings = get_settings()
    # M4: cache the memory service per (state_dir, backend, sync) so long-running
    # `serve` mode reuses one instance and one sync worker instead of leaking a
    # daemon thread per request. Tests isolate via unique tmp state dirs; reset
    # with :func:`_reset_memory_cache` when a forced rebuild is required.
    key = (
        str(_state_dir()),
        settings.hermes_memory_backend.lower(),
        settings.hermes_memory_sync_enabled,
    )
    with _memory_lock:
        cached = _memory_cache.get(key)
        if cached is not None:
            return cached

        embed = EmbeddingClient(
            base_url=settings.ollama_embed_url,
            model=settings.ollama_embed_model,
        )
        memos_cfg = MemosConfig(
            enabled=settings.memos_enabled,
            base_url=settings.memos_base_url,
        )
        svc = MemoryService(
            state_dir=_state_dir(),
            embed_client=embed,
            memos_config=memos_cfg,
        )
        _attach_memory_backend(svc, settings)
        _memory_cache[key] = svc
        return svc


def _attach_memory_backend(svc: MemoryService, settings: Any) -> None:
    """Wire an external memory backend + async sync pipeline onto *svc* (M4).

    Default backend is the local RRF baseline built inside ``MemoryService``;
    only ``mem0`` requires an explicit attachment here. The sync pipeline is
    only started for non-local backends when explicitly enabled.
    """
    name = settings.hermes_memory_backend.lower()
    if name == "mem0":
        from hermes.workbench.mem0_adapter import Mem0Backend, Mem0BackendConfig

        cfg = Mem0BackendConfig(
            llm_model=settings.hermes_mem0_llm_model or settings.hermes_llm_model,
            embed_model=settings.hermes_mem0_embed_model or settings.ollama_embed_model,
            llm_base_url=settings.ollama_base_url,
            embed_base_url=settings.ollama_embed_url,
        )
        svc.set_backend(Mem0Backend(memory=svc, state_dir=_state_dir(), config=cfg))

    if settings.hermes_memory_sync_enabled and name != "local_rrf":
        from hermes.workbench.memory_sync import MemorySyncConfig, MemorySyncService

        sync_cfg = MemorySyncConfig(
            enabled=True,
            batch_size=settings.hermes_memory_sync_batch_size,
        )
        sync = MemorySyncService(
            backend=svc.get_backend(), state_dir=_state_dir(), config=sync_cfg
        )
        svc.set_sync(sync)
        sync.start()


def _make_loop() -> AgentLoop:
    return AgentLoop(runner=_make_runner(), memory=_make_memory())


def _make_store() -> TaskStore:
    return TaskStore(state_dir=_state_dir())


def _make_registry() -> TaskRegistry:
    return TaskRegistry()


def _make_llm() -> Any | None:
    """Build an LLM client from settings, or None when unavailable.

    Silently returns None when the provider is unconfigured so that loop
    mode falls back to the rule-based planner/evaluator without crashing.
    """
    try:
        from hermes.workbench.llm import make_llm_client
        return make_llm_client()
    except Exception:  # noqa: BLE001 — config errors are non-fatal here
        return None


def _make_scheduler() -> TaskScheduler:
    return TaskScheduler(
        store=_make_store(),
        registry=_make_registry(),
        runner=_make_runner(),
        memory=_make_memory(),
        llm=_make_llm(),
    )


def _best_effort_memory() -> Any | None:
    """Build a memory service for recovery audit, or None when unavailable."""
    try:
        return _make_memory()
    except Exception:  # noqa: BLE001 — recovery must not break on memory issues
        return None


def _recovery_enabled() -> bool:
    """Whether crash recovery is enabled (HERMES_SCHEDULER_RECOVERY != 'off')."""
    import os

    raw = os.environ.get("HERMES_SCHEDULER_RECOVERY", "on")
    return raw.strip().lower() != "off"


# ---------------------------------------------------------------------------
# Phase 3 scheduler center (JobStore/Queue/StatusBus/Router/Trigger/DAG)
# ---------------------------------------------------------------------------


class _SchedulerCenter:
    """Bundle of the Phase 3.1-3.6 services that must share in-memory state.

    ``JobQueue`` and ``StatusBus`` are inherently in-memory (priority queue +
    pub/sub), so a single cached instance must back the whole server/CLI run.
    ``JobStore`` / ``ProjectRegistry`` / ``TriggerStore`` re-read from disk on
    first construction but are then cached so concurrent handlers see a
    consistent snapshot.
    """

    __slots__ = (
        "cron_scheduler",
        "dag",
        "job_queue",
        "job_store",
        "project_registry",
        "recovery",
        "router",
        "status_bus",
        "trigger_store",
        "worker_pool",
    )

    def __init__(self) -> None:
        from hermes.workbench.dag import DependencyGraph
        from hermes.workbench.projects import ProjectRegistry, Router
        from hermes.workbench.recovery import RecoveryManager
        from hermes.workbench.scheduler import JobQueue, JobStatus, JobStore, StatusBus, WorkerPool
        from hermes.workbench.triggers import CronScheduler, TriggerStore

        self.job_store = JobStore(state_dir=_state_dir())
        self.job_queue = JobQueue()
        self.status_bus = StatusBus()
        self.project_registry = ProjectRegistry(state_dir=_state_dir())
        self.router = Router(self.project_registry)
        self.trigger_store = TriggerStore(state_dir=_state_dir())

        # Fired jobs must be persisted (so they are visible in /jobs and
        # recoverable on crash) before being handed to the queue.
        def _submit_fired_job(job: Any) -> None:
            job.status = JobStatus.QUEUED
            self.job_store.save(job)
            self.job_queue.put(job)
            self.status_bus.emit(job)

        self.cron_scheduler = CronScheduler(self.trigger_store, _submit_fired_job)
        self.dag = DependencyGraph(
            self.job_store, self.job_queue, self.status_bus
        )

        # 调度执行主线（P0 U1a）：serve 模式下必须真正消费 job，否则
        # POST /jobs 的 job 永远停在 QUEUED。WorkerPool 消费队列，
        # RecoveryManager 处理崩溃遗留，on_job_done 接 DAG 级联回调。
        self.worker_pool = WorkerPool(
            size=2,
            router=self.router,
            queue=self.job_queue,
            store=self.job_store,
            bus=self.status_bus,
            on_job_done=self.dag.on_job_done,
        )
        self.recovery = RecoveryManager(
            store=self.job_store,
            queue=self.job_queue,
            memory=_best_effort_memory(),
            enabled=_recovery_enabled(),
        )

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """Run crash recovery, then start the worker pool and cron scheduler.

        Returns the recovery stats ``{requeued, abandoned, skipped}`` so the
        server can surface them. All three steps are idempotent.
        """
        stats = self.recovery.recover()
        self.worker_pool.start()
        self.cron_scheduler.start()
        return stats

    def stop(self) -> None:
        """Stop cron scheduler and worker pool (graceful)."""
        self.cron_scheduler.stop()
        self.worker_pool.stop()

    @property
    def scheduler_status(self) -> dict[str, Any]:
        """Human/API-facing scheduler status (worker active/idle + queue)."""
        return {
            "running": self.worker_pool.is_running() or self.cron_scheduler.is_running(),
            "workers": {
                "active": self.worker_pool.active_count(),
                "idle": max(0, self.worker_pool.size - self.worker_pool.active_count()),
                "size": self.worker_pool.size,
            },
            "queue_depth": self.job_queue.size(),
            "cron": self.cron_scheduler.is_running(),
        }


_center_lock: threading.Lock = threading.Lock()
_center: _SchedulerCenter | None = None


def _make_scheduler_center() -> _SchedulerCenter:
    """Return the cached scheduler center, building it lazily on first call.

    Tests can reset the cache via :func:`_reset_scheduler_center` or monkeypatch
    this function to inject a center pointed at a tmp state dir.
    """
    global _center
    if _center is None:
        with _center_lock:
            if _center is None:
                _center = _SchedulerCenter()
    return _center


def _reset_scheduler_center() -> None:
    """Drop the cached scheduler center (used by tests for state isolation)."""
    global _center
    with _center_lock:
        _center = None


def _make_todo_store() -> Any:
    """Build (or reuse) the TodoStore backed by the shared state dir."""
    from hermes.workbench.todos import TodoStore

    return TodoStore(state_dir=_state_dir())


def _make_notes_dir() -> Any:
    """Resolve the capture notes directory (HERMES_NOTES_DIR)."""
    notes_dir = get_settings().hermes_notes_dir
    if not notes_dir.is_absolute():
        notes_dir = get_settings().hermes_state_dir.parent / notes_dir
    return notes_dir


def _make_dag() -> Any:
    """Return the shared :class:`DependencyGraph` from the scheduler center."""
    return _make_scheduler_center().dag


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_workbench_skills_list(args: argparse.Namespace) -> int:
    runner = _make_runner()
    specs = runner.discover()
    if not specs:
        print("(no skills found)")
        return 0
    for s in specs:
        print(f"{s.name}\t{s.runtime}\t{s.description}")
    return 0


def cmd_workbench_skills_show(args: argparse.Namespace) -> int:
    runner = _make_runner()
    spec = runner.get(args.name)
    if spec is None:
        print(f"skill not found: {args.name}", file=sys.stderr)
        return 1
    print(f"name:          {spec.name}")
    print(f"path:          {spec.path}")
    print(f"runtime:       {spec.runtime}")
    print(f"entrypoint:    {spec.entrypoint}")
    print(f"description:   {spec.description}")
    print(f"requires_bins: {spec.requires_bins}")
    print(f"requires_env:  {spec.requires_env}")
    return 0


def cmd_workbench_run(args: argparse.Namespace) -> int:
    runner = _make_runner()
    result = runner.run(args.name, args=args.args, timeout=args.timeout)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return 0 if result.ok else 1


def cmd_workbench_loop(args: argparse.Namespace) -> int:
    plan_data = _resolve_plan(args)
    if plan_data is None:
        print("error: provide --plan JSON or --plan-file PATH", file=sys.stderr)
        return 1
    plan: list[LoopStep] = []
    for step in plan_data:
        if not isinstance(step, dict) or "skill" not in step:
            print("error: each plan step needs a 'skill' field", file=sys.stderr)
            return 1
        plan.append(
            LoopStep(
                skill=str(step["skill"]),
                args=list(step.get("args", [])),
                timeout=step.get("timeout"),
                abort_on_error=bool(step.get("abort_on_error", False)),
            )
        )
    loop = _make_loop()
    result = loop.execute(plan)
    print(f"ok={result.ok} steps={len(result.steps)} duration={result.duration:.3f}")
    for sr in result.steps:
        status = "OK" if sr.ok else "FAIL"
        print(f"  [{status}] {sr.skill} ({sr.duration:.3f}s)")
        if sr.error:
            print(f"      error: {sr.error}")
    if result.error:
        print(f"loop aborted: {result.error}", file=sys.stderr)
    return 0 if result.ok else 1


def _resolve_plan(args: argparse.Namespace) -> list[dict[str, Any]] | None:
    raw: str | None = getattr(args, "plan", None)
    if raw:
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    plan_file: str | None = getattr(args, "plan_file", None)
    if plan_file:
        text = Path(plan_file).read_text(encoding="utf-8")
        data = json.loads(text)
        return data if isinstance(data, list) else None
    return None


def cmd_workbench_memory_facts_list(args: argparse.Namespace) -> int:
    mem = _make_memory()
    facts = mem.list_facts()
    if not facts:
        print("(no facts)")
        return 0
    for f in facts:
        print(f"{f['key']} = {json.dumps(f['value'], ensure_ascii=False)}")
    return 0


def cmd_workbench_memory_facts_remember(args: argparse.Namespace) -> int:
    mem = _make_memory()
    try:
        value: Any = json.loads(args.value)
    except json.JSONDecodeError:
        value = args.value
    mem.remember_fact(args.key, value)
    print(f"remembered: {args.key}")
    return 0


def cmd_workbench_memory_facts_get(args: argparse.Namespace) -> int:
    mem = _make_memory()
    fact = mem.get_fact(args.key)
    if fact is None:
        print(f"(no fact: {args.key})", file=sys.stderr)
        return 1
    print(json.dumps(fact, ensure_ascii=False, indent=2))
    return 0


def cmd_workbench_memory_facts_forget(args: argparse.Namespace) -> int:
    mem = _make_memory()
    ok = mem.forget_fact(args.key)
    if not ok:
        print(f"(no fact: {args.key})", file=sys.stderr)
        return 1
    print(f"forgot: {args.key}")
    return 0


def cmd_workbench_memory_episodes_list(args: argparse.Namespace) -> int:
    mem = _make_memory()
    episodes = mem.list_episodes(kind=args.kind, limit=args.limit)
    if not episodes:
        print("(no episodes)")
        return 0
    for ep in episodes:
        print(f"[{ep.kind}] {ep.summary} ({ep.id[:8]})")
    return 0


def cmd_workbench_memory_profile_show(args: argparse.Namespace) -> int:
    mem = _make_memory()
    profile = mem.get_user_profile()
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


def cmd_workbench_memory_rebuild(args: argparse.Namespace) -> int:
    mem = _make_memory()
    try:
        n = mem.rebuild_backend()
    except Exception as e:  # noqa: BLE001 — unhealthy backend degrades to a message
        print(f"rebuild failed: {e}", file=sys.stderr)
        return 1
    print(f"rebuilt backend index from {n} episodes")
    return 0


def cmd_workbench_memory_audit(args: argparse.Namespace) -> int:
    mem = _make_memory()
    report = mem.memory_audit(recent_count=args.recent)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_workbench_task_register(args: argparse.Namespace) -> int:
    plan_data = _resolve_plan(args)
    if plan_data is None:
        print("error: provide --plan JSON or --plan-file PATH", file=sys.stderr)
        return 1
    store = _make_store()
    registry = _make_registry()
    task_id = args.task_id or f"task-{uuid.uuid4().hex[:8]}"
    task = Task(
        task_id=task_id,
        plan=plan_data,
        mode=args.mode,
        max_rounds=args.max_rounds,
        max_runs=args.max_runs,
        interval=args.interval,
        goal=json.loads(args.goal) if getattr(args, "goal", None) else None,
    )
    registry.register(task)
    store.save(task)
    print(f"registered: {task_id}")
    return 0


def cmd_workbench_task_list(args: argparse.Namespace) -> int:
    store = _make_store()
    tasks = store.list()
    if not tasks:
        print("(no tasks)")
        return 0
    for t in tasks:
        print(f"{t['task_id']}\t{t['status']}\t{len(t.get('rounds', []))} rounds")
    return 0


def cmd_workbench_task_run(args: argparse.Namespace) -> int:
    scheduler = _make_scheduler()
    result = scheduler.run(args.task_id)
    if result is None:
        print(f"task not found: {args.task_id}", file=sys.stderr)
        return 1
    ok = getattr(result, "ok", False)
    steps = getattr(result, "steps", [])
    print(f"ok={ok} steps={len(steps)}")
    return 0 if ok else 1


def cmd_workbench_task_show(args: argparse.Namespace) -> int:
    store = _make_store()
    task = store.get(args.task_id)
    if task is None:
        print(f"task not found: {args.task_id}", file=sys.stderr)
        return 1
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0


def cmd_workbench_task_cancel(args: argparse.Namespace) -> int:
    scheduler = _make_scheduler()
    ok = scheduler.cancel(args.task_id)
    if not ok:
        print(f"task not found: {args.task_id}", file=sys.stderr)
        return 1
    print(f"cancelled: {args.task_id}")
    return 0


def cmd_workbench_serve(args: argparse.Namespace) -> int:
    try:
        from hermes.workbench.server import run_server
    except ImportError as exc:
        print(f"server not available: {exc}", file=sys.stderr)
        return 1
    run_server(args.host, args.port, insecure=getattr(args, "insecure", False))
    return 0


def cmd_workbench_github_sync(args: argparse.Namespace) -> int:
    """Sync GitHub issues to workbench tasks and push results back."""
    from hermes.workbench.errors import ValidationError
    from hermes.workbench.github_sync import GitHubSyncService

    try:
        service = GitHubSyncService.from_env(repo=args.repo)
    except ValidationError as e:
        print(f"sync error: {e}", file=sys.stderr)
        return 1
    result = service.sync(label=args.label)
    print(
        f"sync: pulled={result['pulled']} ran={result['ran']} "
        f"pushed={result['pushed']} errors={len(result['errors'])}"
    )
    for err in result["errors"]:
        print(f"  error: {err}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# workbench ima
# ---------------------------------------------------------------------------


def cmd_workbench_ima(args: argparse.Namespace) -> int:
    """IMA 知识库操作：列出/搜索/推送/同步/笔记管理。"""
    from hermes.workbench.ima_sync import ImaClient, ImaSyncResult, ImaSyncService

    action = args.ima_action

    # Knowledge-base module actions
    if action == "list":
        svc = ImaSyncService()
        kbs = svc.list_kbs(query=getattr(args, "query", ""))
        if not kbs:
            print("(no knowledge bases found)")
            return 0
        for kb in kbs:
            print(f"  {kb.kb_name}  (id={kb.kb_id[:20]}..., {kb.content_count} 条)")
        return 0

    if action == "search":
        svc = ImaSyncService()
        results = svc.pull(args.query, args.kb_id)
        if not results:
            print("(no results)")
            return 0
        for r in results:
            print(f"  [{r.title}]")
            if r.highlight_content:
                print(f"    {r.highlight_content[:120]}...")
        return 0

    if action == "push":
        svc = ImaSyncService()
        content = args.content
        if args.file:
            content = Path(args.file).read_text(encoding="utf-8")
        result = svc.push(args.kb_id, args.title, content)
        print(f"pushed: {result}")
        return 0

    if action == "sync":
        svc = ImaSyncService()
        sync_result: ImaSyncResult = svc.sync(args.query, args.kb_id, push_kind=getattr(args, "push_kind", None))
        print(f"sync: pulled={sync_result.pulled} pushed={sync_result.pushed} errors={len(sync_result.errors)}")
        for err in sync_result.errors:
            print(f"  error: {err}", file=sys.stderr)
        return 0

    if action == "urls-import":
        svc = ImaSyncService()
        urls = list(args.urls)
        result = svc.push_urls(args.kb_id, urls, folder_id=getattr(args, "folder_id", "") or "")
        print(f"imported: {result}")
        return 0

    if action == "file-upload":
        svc = ImaSyncService()
        result = svc.push_file(
            args.kb_id,
            args.file,
            content_type=getattr(args, "content_type", None),
            folder_id=getattr(args, "folder_id", "") or "",
        )
        print(f"uploaded: media_id={result.get('media_id', '')} file={result.get('file_name', '')}")
        return 0

    # Notes module actions (note/v1)
    if action == "notes-list":
        client = ImaClient()
        notes, is_end, cursor = client.list_note(limit=getattr(args, "limit", 20))
        if not notes:
            print("(no notes found)")
            return 0
        for n in notes:
            print(f"  [{n.note_id}] {n.title}")
            if n.summary:
                print(f"    {n.summary[:120]}")
        if not is_end:
            print(f"  ... more notes available (cursor={cursor})")
        return 0

    if action == "notes-search":
        client = ImaClient()
        notes, is_end, total = client.search_note_book(
            args.query,
            start=0,
            end=getattr(args, "limit", 20),
        )
        if not notes:
            print("(no notes found)")
            return 0
        print(f"  total hits: {total}")
        for n in notes:
            print(f"  [{n.note_id}] {n.title}")
        if not is_end:
            print("  ... more notes available")
        return 0

    if action == "notes-get":
        client = ImaClient()
        data = client.get_doc_content(args.note_id)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if action == "notes-create":
        client = ImaClient()
        content = args.content
        if args.file:
            content = Path(args.file).read_text(encoding="utf-8")
        if not content:
            print("error: --content or --file is required", file=sys.stderr)
            return 1
        result = client.import_doc(content=content, title=args.title)
        print(f"created: {result}")
        return 0

    if action == "notes-append":
        client = ImaClient()
        content = args.content
        if args.file:
            content = Path(args.file).read_text(encoding="utf-8")
        if not content:
            print("error: --content or --file is required", file=sys.stderr)
            return 1
        result = client.append_doc(args.note_id, content)
        print(f"appended: {result}")
        return 0

    print(f"unknown action: {action}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# Phase 3 job / project / trigger / sync commands
# ---------------------------------------------------------------------------


def cmd_workbench_job_submit(args: argparse.Namespace) -> int:
    from hermes.workbench.scheduler import JobStatus, ScheduledJob

    plan_data = _resolve_plan(args)
    if plan_data is None:
        print("error: provide --plan JSON or --plan-file PATH", file=sys.stderr)
        return 1
    task = Task(
        task_id=f"job-{uuid.uuid4().hex[:8]}",
        plan=plan_data,
        mode=getattr(args, "mode", "oneshot"),
    )
    depends_on = list(getattr(args, "depends_on", None) or [])
    job = ScheduledJob(
        task=task,
        target_project=getattr(args, "project", "default"),
        priority=getattr(args, "priority", 5),
        timeout=getattr(args, "timeout", None),
        depends_on=depends_on,
    )
    center = _make_scheduler_center()
    center.job_store.save(job)
    if depends_on:
        center.dag.register(job.job_id, depends_on)
    # Enqueue immediately if no deps (or deps already satisfied).
    if center.dag.ready_to_queue(job.job_id):
        job.status = JobStatus.QUEUED
        center.job_store.save(job)
        center.job_queue.put(job)
        center.status_bus.emit(job)
    print(job.job_id)
    return 0


def cmd_workbench_job_list(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    jobs = center.job_store.list()
    status_filter = getattr(args, "status", None)
    if status_filter:
        jobs = [j for j in jobs if j.status.value == status_filter]
    if not jobs:
        print("(no jobs)")
        return 0
    for j in jobs:
        print(f"{j.job_id}\t{j.status.value}\t{j.target_project}\tP{j.priority}")
    return 0


def cmd_workbench_job_show(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    job = center.job_store.get(args.job_id)
    if job is None:
        print(f"job not found: {args.job_id}", file=sys.stderr)
        return 1
    print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_workbench_job_cancel(args: argparse.Namespace) -> int:
    from hermes.workbench.scheduler import JobStatus

    center = _make_scheduler_center()
    job = center.job_store.get(args.job_id)
    if job is None:
        print(f"job not found: {args.job_id}", file=sys.stderr)
        return 1
    job.cancel_event.set()
    if not job.status.is_terminal():
        job.status = JobStatus.CANCELLED
        center.job_store.save(job)
        center.status_bus.emit(job)
    print(f"cancelled: {args.job_id}")
    return 0


def cmd_workbench_job_retry(args: argparse.Namespace) -> int:
    from hermes.workbench.scheduler import JobStatus

    center = _make_scheduler_center()
    job = center.job_store.get(args.job_id)
    if job is None:
        print(f"job not found: {args.job_id}", file=sys.stderr)
        return 1
    if not job.status.is_terminal():
        print(f"job not terminal: {job.status.value}", file=sys.stderr)
        return 1
    job.status = JobStatus.QUEUED
    job.cancel_event.clear()
    center.job_store.save(job)
    center.job_queue.put(job)
    center.status_bus.emit(job)
    print(f"requeued: {args.job_id}")
    return 0


def cmd_workbench_job_metrics(args: argparse.Namespace) -> int:
    from hermes.workbench.scheduler import compute_metrics

    center = _make_scheduler_center()
    jobs = center.job_store.list()
    metrics = compute_metrics(jobs)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


def cmd_workbench_project_list(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    projects = center.project_registry.list()
    if not projects:
        print("(no projects)")
        return 0
    for p in projects:
        print(f"{p.id}\t{p.name}\t{p.project_type}\t{p.health}")
    return 0


def cmd_workbench_project_add(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    try:
        conn = center.project_registry.add(
            name=args.name,
            project_type=args.type,
            state_dir=args.state_dir,
            skills_dir=getattr(args, "skills_dir", None),
            max_concurrent=getattr(args, "max_concurrent", 1),
        )
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(conn.id)
    return 0


def cmd_workbench_project_show(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    conn = center.project_registry.get(args.project_id)
    if conn is None:
        print(f"project not found: {args.project_id}", file=sys.stderr)
        return 1
    print(json.dumps(conn.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_workbench_project_remove(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    try:
        ok = center.project_registry.remove(args.project_id)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not ok:
        print(f"project not found: {args.project_id}", file=sys.stderr)
        return 1
    print(f"removed: {args.project_id}")
    return 0


def cmd_workbench_project_ping(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    result = center.project_registry.ping(args.project_id)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("reachable") else 1


def cmd_workbench_trigger_list(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    triggers = center.trigger_store.list()
    if not triggers:
        print("(no triggers)")
        return 0
    for t in triggers:
        cron = t.config.get("cron", "")
        print(f"{t.trigger_id}\t{t.trigger_type}\t{cron}\tenabled={t.enabled}")
    return 0


def cmd_workbench_trigger_create(args: argparse.Namespace) -> int:
    from hermes.workbench.triggers import Trigger

    plan_data = _resolve_plan(args)
    if plan_data is None:
        print("error: provide --plan JSON or --plan-file PATH", file=sys.stderr)
        return 1
    cron = getattr(args, "cron", None)
    config: dict[str, Any] = {}
    if cron:
        config["cron"] = cron
    trigger = Trigger(
        job_template={"plan": plan_data},
        trigger_type="cron" if cron else "manual",
        config=config,
    )
    center = _make_scheduler_center()
    center.trigger_store.save(trigger)
    print(trigger.trigger_id)
    return 0


def cmd_workbench_trigger_show(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    trigger = center.trigger_store.get(args.trigger_id)
    if trigger is None:
        print(f"trigger not found: {args.trigger_id}", file=sys.stderr)
        return 1
    print(json.dumps(trigger.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_workbench_trigger_delete(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    if not center.trigger_store.delete(args.trigger_id):
        print(f"trigger not found: {args.trigger_id}", file=sys.stderr)
        return 1
    print(f"deleted: {args.trigger_id}")
    return 0


def cmd_workbench_trigger_fire(args: argparse.Namespace) -> int:
    center = _make_scheduler_center()
    if not center.cron_scheduler.fire(args.trigger_id):
        print(f"trigger not found or fire failed: {args.trigger_id}", file=sys.stderr)
        return 1
    print(f"fired: {args.trigger_id}")
    return 0


def cmd_workbench_sync(args: argparse.Namespace) -> int:
    from hermes.workbench.asset_sync import AssetSync

    center = _make_scheduler_center()
    targets = list(getattr(args, "targets", None) or [])
    if not targets:
        print("error: at least one target project id is required", file=sys.stderr)
        return 1
    sync = AssetSync(center.router)
    try:
        result = sync.sync(
            source=args.source, targets=targets, scope=getattr(args, "scope", "all")
        )
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(
        f"sync: ok={result.ok} scope={result.scope} "
        f"targets={len(result.targets)} synced={result.synced_count} "
        f"errors={len(result.errors)}"
    )
    for err in result.errors:
        print(f"  error: {err}", file=sys.stderr)
    return 0 if result.ok else 1


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------


def _register_skills(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("skills", help="List and inspect skills")
    skills_sub = p.add_subparsers(dest="workbench_skills_cmd", required=True)
    p_list = skills_sub.add_parser("list", help="List all skills")
    p_list.set_defaults(func=cmd_workbench_skills_list)
    p_show = skills_sub.add_parser("show", help="Show one skill")
    p_show.add_argument("name", help="Skill name")
    p_show.set_defaults(func=cmd_workbench_skills_show)


def _register_run(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("run", help="Run a single skill")
    p.add_argument("name", help="Skill name")
    p.add_argument("args", nargs="*", help="Positional args to pass to the skill")
    p.add_argument("--timeout", type=float, default=None, help="Timeout in seconds")
    p.set_defaults(func=cmd_workbench_run)


def _register_loop(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("loop", help="Run a plan of skills sequentially")
    p.add_argument("--plan", default=None, help="JSON plan string")
    p.add_argument("--plan-file", default=None, help="Path to JSON plan file")
    p.set_defaults(func=cmd_workbench_loop)


def _register_memory(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("memory", help="Inspect L1/L2/L3 memory")
    mem_sub = p.add_subparsers(dest="workbench_memory_cmd", required=True)

    p_facts = mem_sub.add_parser("facts", help="Manage L1 facts")
    facts_sub = p_facts.add_subparsers(dest="workbench_memory_facts_cmd", required=True)
    p_fl = facts_sub.add_parser("list", help="List all facts")
    p_fl.set_defaults(func=cmd_workbench_memory_facts_list)
    p_fr = facts_sub.add_parser("remember", help="Remember a fact")
    p_fr.add_argument("key")
    p_fr.add_argument("value")
    p_fr.set_defaults(func=cmd_workbench_memory_facts_remember)
    p_fg = facts_sub.add_parser("get", help="Get a fact")
    p_fg.add_argument("key")
    p_fg.set_defaults(func=cmd_workbench_memory_facts_get)
    p_ff = facts_sub.add_parser("forget", help="Forget a fact")
    p_ff.add_argument("key")
    p_ff.set_defaults(func=cmd_workbench_memory_facts_forget)

    p_eps = mem_sub.add_parser("episodes", help="List L2 episodes")
    p_eps.add_argument("--kind", default=None)
    p_eps.add_argument("--limit", type=int, default=1000)
    p_eps.set_defaults(func=cmd_workbench_memory_episodes_list)

    p_prof = mem_sub.add_parser("profile", help="Show user profile (L3)")
    prof_sub = p_prof.add_subparsers(dest="workbench_memory_profile_cmd", required=True)
    p_ps = prof_sub.add_parser("show", help="Show profile JSON")
    p_ps.set_defaults(func=cmd_workbench_memory_profile_show)

    p_rebuild = mem_sub.add_parser("rebuild", help="Rebuild the memory backend index (M4)")
    p_rebuild.set_defaults(func=cmd_workbench_memory_rebuild)

    p_audit = mem_sub.add_parser("audit", help="Memory health / consistency report (M4)")
    p_audit.add_argument("--recent", type=int, default=500, help="Episodes to scan for conflicts")
    p_audit.set_defaults(func=cmd_workbench_memory_audit)


def _register_memos(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("memos", help="MemOS local plugin integration")
    memos_sub = p.add_subparsers(dest="workbench_memos_cmd", required=True)

    p_health = memos_sub.add_parser("health", help="Check MemOS plugin health")
    p_health.set_defaults(func=cmd_workbench_memos_health)

    p_search = memos_sub.add_parser("search", help="Search MemOS plugin")
    p_search.add_argument("--query", "-q", required=True, help="Search query")
    p_search.add_argument("--limit", type=int, default=10, help="Max results")
    p_search.set_defaults(func=cmd_workbench_memos_search)

    p_feedback = memos_sub.add_parser("feedback", help="Submit feedback correction")
    p_feedback.add_argument("memory_id", help="Memory ID")
    p_feedback.add_argument("correction", help="Correction text")
    p_feedback.set_defaults(func=cmd_workbench_memos_feedback)


def cmd_workbench_memos_health(args: argparse.Namespace) -> int:
    mem = _make_memory()
    ok = mem.memos_health()
    enabled = mem._memos.available
    print(f"MemOS enabled: {enabled}")
    print(f"MemOS healthy: {ok}")
    return 0 if ok else 1


def cmd_workbench_memos_search(args: argparse.Namespace) -> int:
    mem = _make_memory()
    results = mem.memos_search(query=args.query, limit=args.limit)
    if not results:
        print("(no results)")
        return 0
    for r in results:
        print(f"  [{r.get('kind', '?')}] {r.get('summary', '')}")
    return 0


def cmd_workbench_memos_feedback(args: argparse.Namespace) -> int:
    mem = _make_memory()
    ok = mem.memos_feedback(args.memory_id, args.correction)
    if ok:
        print(f"feedback submitted for {args.memory_id}")
    else:
        print(f"feedback failed for {args.memory_id}")
    return 0 if ok else 1


def _register_task(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("task", help="Manage scheduled tasks")
    task_sub = p.add_subparsers(dest="workbench_task_cmd", required=True)
    p_reg = task_sub.add_parser("register", help="Register a new task")
    p_reg.add_argument("--task-id", default=None)
    p_reg.add_argument("--plan", default=None)
    p_reg.add_argument("--plan-file", default=None)
    p_reg.add_argument("--mode", default="oneshot")
    p_reg.add_argument("--max-rounds", type=int, default=1)
    p_reg.add_argument("--max-runs", type=int, default=1)
    p_reg.add_argument("--interval", type=float, default=0.0)
    p_reg.add_argument("--goal", default=None, help="Goal JSON for loop mode")
    p_reg.set_defaults(func=cmd_workbench_task_register)
    p_list = task_sub.add_parser("list", help="List registered tasks")
    p_list.set_defaults(func=cmd_workbench_task_list)
    p_run = task_sub.add_parser("run", help="Run a task")
    p_run.add_argument("task_id")
    p_run.set_defaults(func=cmd_workbench_task_run)
    p_show = task_sub.add_parser("show", help="Show task detail")
    p_show.add_argument("task_id")
    p_show.set_defaults(func=cmd_workbench_task_show)
    p_cancel = task_sub.add_parser("cancel", help="Cancel a task")
    p_cancel.add_argument("task_id")
    p_cancel.set_defaults(func=cmd_workbench_task_cancel)


def _register_serve(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("serve", help="Run the dashboard API server (P3)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument(
        "--insecure",
        action="store_true",
        help="Allow binding non-loopback without HERMES_API_TOKEN (not recommended)",
    )
    p.set_defaults(func=cmd_workbench_serve)


def _register_github(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("github-sync", help="Sync GitHub issues to workbench tasks (P4)")
    p.add_argument("--repo", required=True, help="GitHub repo as owner/name")
    p.add_argument("--label", default="workbench", help="Issue label to filter (default: workbench)")
    p.set_defaults(func=cmd_workbench_github_sync)


def _register_ima(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("ima", help="IMA 知识库操作")
    ima_sub = p.add_subparsers(dest="ima_action", required=True)

    p_list = ima_sub.add_parser("list", help="列出知识库")
    p_list.add_argument("--query", default="", help="搜索关键词")
    p_list.set_defaults(func=cmd_workbench_ima)

    p_search = ima_sub.add_parser("search", help="搜索知识库内容")
    p_search.add_argument("--kb-id", required=True, help="知识库 ID")
    p_search.add_argument("--query", required=True, help="搜索关键词")
    p_search.set_defaults(func=cmd_workbench_ima)

    p_push = ima_sub.add_parser("push", help="推送内容到 IMA")
    p_push.add_argument("--kb-id", required=True, help="知识库 ID")
    p_push.add_argument("--title", required=True, help="笔记标题")
    p_push.add_argument("--content", default="", help="笔记内容")
    p_push.add_argument("--file", default=None, help="从文件读取内容")
    p_push.set_defaults(func=cmd_workbench_ima)

    p_sync = ima_sub.add_parser("sync", help="双向同步")
    p_sync.add_argument("--kb-id", required=True, help="知识库 ID")
    p_sync.add_argument("--query", required=True, help="搜索关键词 (pull)")
    p_sync.add_argument("--push-kind", default=None, help="推送的 episode 类型")
    p_sync.set_defaults(func=cmd_workbench_ima)

    # knowledge-base module: content ingestion subcommands
    p_urls = ima_sub.add_parser("urls-import", help="批量导入网页 URL 到知识库")
    p_urls.add_argument("--kb-id", required=True, help="目标知识库 ID")
    p_urls.add_argument("--urls", nargs="+", required=True, help="一个或多个网页 URL")
    p_urls.add_argument("--folder-id", default=None, help="目标文件夹 ID (可选)")
    p_urls.set_defaults(func=cmd_workbench_ima)

    p_upload = ima_sub.add_parser("file-upload", help="上传本地文件到知识库 (3 步流程)")
    p_upload.add_argument("--kb-id", required=True, help="目标知识库 ID")
    p_upload.add_argument("--file", required=True, help="本地文件路径")
    p_upload.add_argument("--content-type", default=None, help="MIME 类型 (默认按扩展名推断)")
    p_upload.add_argument("--folder-id", default=None, help="目标文件夹 ID (可选)")
    p_upload.set_defaults(func=cmd_workbench_ima)

    # Notes module (note/v1) subcommands
    p_notes_list = ima_sub.add_parser("notes-list", help="列出笔记")
    p_notes_list.add_argument("--limit", type=int, default=20, help="返回条数上限")
    p_notes_list.set_defaults(func=cmd_workbench_ima)

    p_notes_search = ima_sub.add_parser("notes-search", help="按标题搜索笔记")
    p_notes_search.add_argument("--query", required=True, help="搜索关键词")
    p_notes_search.add_argument("--limit", type=int, default=20, help="返回条数上限")
    p_notes_search.set_defaults(func=cmd_workbench_ima)

    p_notes_get = ima_sub.add_parser("notes-get", help="获取笔记完整内容")
    p_notes_get.add_argument("--note-id", required=True, help="笔记 note_id")
    p_notes_get.set_defaults(func=cmd_workbench_ima)

    p_notes_create = ima_sub.add_parser("notes-create", help="创建新笔记 (import_doc)")
    p_notes_create.add_argument("--title", default=None, help="笔记标题 (作为 H1 前置)")
    p_notes_create.add_argument("--content", default="", help="笔记内容 (markdown)")
    p_notes_create.add_argument("--file", default=None, help="从文件读取内容")
    p_notes_create.set_defaults(func=cmd_workbench_ima)

    p_notes_append = ima_sub.add_parser("notes-append", help="追加内容到已有笔记")
    p_notes_append.add_argument("--note-id", required=True, help="目标笔记 note_id")
    p_notes_append.add_argument("--content", default="", help="要追加的内容 (markdown)")
    p_notes_append.add_argument("--file", default=None, help="从文件读取内容")
    p_notes_append.set_defaults(func=cmd_workbench_ima)


def _register_job(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("job", help="Manage scheduled jobs (Phase 3)")
    job_sub = p.add_subparsers(dest="workbench_job_cmd", required=True)

    p_submit = job_sub.add_parser("submit", help="Submit a new job")
    p_submit.add_argument("--plan", default=None, help="JSON plan string")
    p_submit.add_argument("--plan-file", default=None, help="Path to JSON plan file")
    p_submit.add_argument("--project", default="default", help="Target project id")
    p_submit.add_argument("--priority", type=int, default=5, help="Job priority (1-10, lower=urgent)")
    p_submit.add_argument("--timeout", type=float, default=None, help="Per-job timeout (seconds)")
    p_submit.add_argument("--mode", default="oneshot", help="Task mode")
    p_submit.add_argument(
        "--depends-on", nargs="*", default=None, help="Upstream job ids this job depends on"
    )
    p_submit.set_defaults(func=cmd_workbench_job_submit)

    p_list = job_sub.add_parser("list", help="List jobs")
    p_list.add_argument("--status", default=None, help="Filter by status (e.g. QUEUED)")
    p_list.set_defaults(func=cmd_workbench_job_list)

    p_show = job_sub.add_parser("show", help="Show job detail")
    p_show.add_argument("job_id")
    p_show.set_defaults(func=cmd_workbench_job_show)

    p_cancel = job_sub.add_parser("cancel", help="Cancel a job")
    p_cancel.add_argument("job_id")
    p_cancel.set_defaults(func=cmd_workbench_job_cancel)

    p_retry = job_sub.add_parser("retry", help="Retry a terminal job")
    p_retry.add_argument("job_id")
    p_retry.set_defaults(func=cmd_workbench_job_retry)

    p_metrics = job_sub.add_parser("metrics", help="Aggregate job metrics")
    p_metrics.set_defaults(func=cmd_workbench_job_metrics)


def _register_project(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("project", help="Manage project connections (Phase 3)")
    proj_sub = p.add_subparsers(dest="workbench_project_cmd", required=True)

    p_list = proj_sub.add_parser("list", help="List projects")
    p_list.set_defaults(func=cmd_workbench_project_list)

    p_add = proj_sub.add_parser("add", help="Add a project connection")
    p_add.add_argument("--name", required=True, help="Project display name")
    p_add.add_argument("--type", required=True, help="local | github | api")
    p_add.add_argument("--state-dir", required=True, help="Project state directory")
    p_add.add_argument("--skills-dir", default=None, help="Project skills directory")
    p_add.add_argument("--max-concurrent", type=int, default=1, help="Max concurrent jobs")
    p_add.set_defaults(func=cmd_workbench_project_add)

    p_show = proj_sub.add_parser("show", help="Show project detail")
    p_show.add_argument("project_id")
    p_show.set_defaults(func=cmd_workbench_project_show)

    p_remove = proj_sub.add_parser("remove", help="Remove a project")
    p_remove.add_argument("project_id")
    p_remove.set_defaults(func=cmd_workbench_project_remove)

    p_ping = proj_sub.add_parser("ping", help="Health-check a project")
    p_ping.add_argument("project_id")
    p_ping.set_defaults(func=cmd_workbench_project_ping)


def _register_trigger(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("trigger", help="Manage job triggers (Phase 3)")
    trig_sub = p.add_subparsers(dest="workbench_trigger_cmd", required=True)

    p_list = trig_sub.add_parser("list", help="List triggers")
    p_list.set_defaults(func=cmd_workbench_trigger_list)

    p_create = trig_sub.add_parser("create", help="Create a trigger")
    p_create.add_argument("--plan", default=None, help="JSON plan string")
    p_create.add_argument("--plan-file", default=None, help="Path to JSON plan file")
    p_create.add_argument("--cron", default=None, help="5-field cron expression")
    p_create.set_defaults(func=cmd_workbench_trigger_create)

    p_show = trig_sub.add_parser("show", help="Show trigger detail")
    p_show.add_argument("trigger_id")
    p_show.set_defaults(func=cmd_workbench_trigger_show)

    p_delete = trig_sub.add_parser("delete", help="Delete a trigger")
    p_delete.add_argument("trigger_id")
    p_delete.set_defaults(func=cmd_workbench_trigger_delete)

    p_fire = trig_sub.add_parser("fire", help="Manually fire a trigger")
    p_fire.add_argument("trigger_id")
    p_fire.set_defaults(func=cmd_workbench_trigger_fire)


def _register_sync(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("sync", help="Cross-project asset sync (Phase 3)")
    p.add_argument("--source", required=True, help="Source project id")
    p.add_argument(
        "targets", nargs="+", help="One or more target project ids"
    )
    p.add_argument(
        "--scope",
        default="all",
        choices=["skills", "memory", "profile", "all"],
        help="Asset scope to sync (default: all)",
    )
    p.set_defaults(func=cmd_workbench_sync)


def cmd_workbench_feishu_inbox(args: argparse.Namespace) -> int:
    """Long-running Feishu bot inbox: consume im.message.receive_v1 into capture.

    Spawns ``lark-cli event consume im.message.receive_v1`` (Feishu WebSocket
    long-connection, NDJSON on stdout) and ingests each event through
    :class:`CaptureService`. Bounded with ``--max-events`` / ``--timeout``.
    """
    import json as _json
    import subprocess

    from hermes.workbench.capture import CaptureService
    from hermes.workbench.feishu_inbox import FeishuInboxService

    svc = FeishuInboxService(CaptureService(_make_todo_store(), _make_notes_dir()))
    cmd = ["lark-cli", "event", "consume", "im.message.receive_v1"]
    if args.max_events:
        cmd += ["--max-events", str(args.max_events)]
    if args.timeout:
        cmd += ["--timeout", args.timeout]
    if args.quiet:
        cmd += ["--quiet"]

    print("feishu-inbox: consuming im.message.receive_v1 (chat_type=p2p only)")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            result = svc.ingest(event)
            if result is not None:
                print(f"captured: [{result['type']}] {result['title'][:60]}")
            else:
                print("skipped (non-p2p / duplicate / empty)")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
    return proc.returncode or 0


def _register_feishu_inbox(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("feishu-inbox", help="Feishu bot inbox: capture messages into the workbench")
    p.add_argument("--max-events", type=int, default=0, help="Exit after N events (0 = unlimited)")
    p.add_argument("--timeout", default=None, help="Exit after DURATION (e.g. 30s, 2m)")
    p.add_argument("--quiet", action="store_true", help="Suppress lark-cli informational messages")
    p.set_defaults(func=cmd_workbench_feishu_inbox)


def add_workbench_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``workbench`` subcommand and its nested subcommands."""
    p = sub.add_parser("workbench", help="Hermes Workbench runtime commands")
    wb_sub = p.add_subparsers(dest="workbench_cmd", required=False)
    _register_skills(wb_sub)
    _register_run(wb_sub)
    _register_loop(wb_sub)
    _register_memory(wb_sub)
    _register_memos(wb_sub)
    _register_task(wb_sub)
    _register_serve(wb_sub)
    _register_github(wb_sub)
    _register_ima(wb_sub)
    _register_job(wb_sub)
    _register_project(wb_sub)
    _register_trigger(wb_sub)
    _register_sync(wb_sub)
    _register_feishu_inbox(wb_sub)


def register_workbench_commands(parser: argparse.ArgumentParser) -> None:
    """Register workbench subcommands on an existing top-level parser."""
    sub = parser.add_subparsers(dest="command", required=False)
    add_workbench_subparser(sub)


def workbench_main(argv: list[str] | None = None) -> int:
    """Standalone entry point for the workbench CLI."""
    parser = argparse.ArgumentParser(prog="hermes-workbench")
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Log level (DEBUG/INFO/WARNING/ERROR). Default: INFO",
    )
    parser.add_argument(
        "--log-format",
        default="text",
        choices=["text", "json"],
        help="Log format. 'json' emits structured JSON logs. Default: text",
    )
    register_workbench_commands(parser)
    args = parser.parse_args(argv)

    # One-time structured logging setup.
    try:
        from hermes.workbench.structured_logging import configure_logging
        configure_logging(level=args.log_level, json=(args.log_format == "json"))
    except Exception:  # noqa: BLE001
        pass

    func: Callable[[argparse.Namespace], int] | None = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return int(func(args))

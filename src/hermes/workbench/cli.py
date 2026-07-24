"""Workbench CLI: skills / run / loop / memory / task / serve subcommands.

Service factories are module-level so tests can monkeypatch them. The CLI is
registered into the top-level ``hermes`` parser via ``add_workbench_subparser``
and is also runnable standalone through ``workbench_main``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable

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
        try:
            from hermes.workbench.structured_logging import log_context
            loop_ctx = log_context(task_id=task_id, mode="loop")
        except Exception:  # noqa: BLE001
            # Fall back to a no-op context manager if structured logging
            # is unavailable.
            from contextlib import nullcontext as _null
            loop_ctx = _null()

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


def _make_memory() -> MemoryService:
    return MemoryService(state_dir=_state_dir())


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
        from hermes.workbench.server import run_server  # type: ignore[import-untyped]
    except ImportError as exc:
        print(f"server not available: {exc}", file=sys.stderr)
        return 1
    run_server(args.host, args.port)
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
    from hermes.workbench.ima_sync import ImaClient, ImaSyncService

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
        result = svc.sync(args.query, args.kb_id, push_kind=getattr(args, "push_kind", None))
        print(f"sync: pulled={result.pulled} pushed={result.pushed} errors={len(result.errors)}")
        for err in result.errors:
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


def add_workbench_subparser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``workbench`` subcommand and its nested subcommands."""
    p = sub.add_parser("workbench", help="Hermes Workbench runtime commands")
    wb_sub = p.add_subparsers(dest="workbench_cmd", required=False)
    _register_skills(wb_sub)
    _register_run(wb_sub)
    _register_loop(wb_sub)
    _register_memory(wb_sub)
    _register_task(wb_sub)
    _register_serve(wb_sub)
    _register_github(wb_sub)
    _register_ima(wb_sub)


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

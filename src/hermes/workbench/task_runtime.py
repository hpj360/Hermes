"""Task runtime: Task / TaskStore / TaskRegistry / TaskScheduler.

从 workbench/cli.py 拆出的任务运行时层（原 1691 行巨型文件的
L31-296）：任务定义、持久化、注册表与执行器。无 CLI 依赖，
可被 server / CLI / content_team 三个入口复用。

向后兼容：``hermes.workbench.cli`` 继续 re-export 本模块全部符号
（tests 与 github_sync/projects/scheduler/todos 均从 cli 导入）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hermes.workbench.agent_loop import AgentLoop, LoopStep
from hermes.workbench.memory import MemoryService
from hermes.workbench.skill_runner import SkillRunner

__all__ = ["Task", "TaskStore", "TaskRegistry", "TaskScheduler"]


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

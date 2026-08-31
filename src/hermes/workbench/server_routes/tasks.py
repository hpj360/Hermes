"""Task routes: create+run / list / get / run / cancel.

从 server.py 拆出的路由域 mixin。
"""
from __future__ import annotations

from hermes.workbench.server_routes.base import RouteBase

from hermes.workbench.errors import ValidationError, NotFoundError


class TasksRoutes(RouteBase):
    def h_post_tasks(self) -> None:
        """Create and optionally run a task in one call.

        Body: {"plan": [...], "mode": "oneshot", "run": true, "task_id": "..."}
        """
        from hermes.workbench.cli import Task, _make_registry, _make_store

        body = self._read_json_body()
        if not isinstance(body, dict) or "plan" not in body:
            raise ValidationError("body must contain 'plan'")
        plan = body["plan"]
        if not isinstance(plan, list):
            raise ValidationError("'plan' must be a JSON array")

        import uuid

        task_id = body.get("task_id") or f"task-{uuid.uuid4().hex[:8]}"
        task = Task(
            task_id=task_id,
            plan=plan,
            mode=body.get("mode", "oneshot"),
            max_rounds=body.get("max_rounds", 1),
            max_runs=body.get("max_runs", 1),
            interval=body.get("interval", 0.0),
            goal=body.get("goal"),
        )
        _make_registry().register(task)
        _make_store().save(task)

        run_now = body.get("run", True)
        if run_now:
            from hermes.workbench.cli import _make_scheduler

            result = _make_scheduler().run(task_id)
            task_dict = _make_store().get(task_id)
            if task_dict is None:
                raise NotFoundError(f"task vanished after run: {task_id}")
            task_dict["result_ok"] = getattr(result, "ok", False) if result else False
            self._send_json(200, task_dict)
        else:
            self._send_json(201, task.to_dict())

    def h_get_tasks(self) -> None:
        from hermes.workbench.cli import _make_store

        tasks = _make_store().list()
        self._send_json(200, {"tasks": tasks})

    def h_get_task(self, task_id: str) -> None:
        from hermes.workbench.cli import _make_store

        task = _make_store().get(task_id)
        if task is None:
            raise NotFoundError(f"task not found: {task_id}")
        self._send_json(200, task)

    def h_post_task_run(self, task_id: str) -> None:
        """Run a previously-registered task."""
        from hermes.workbench.cli import _make_scheduler, _make_store

        existing = _make_store().get(task_id)
        if existing is None:
            raise NotFoundError(f"task not found: {task_id}")
        # Re-register if the in-memory registry lost it (e.g. new request).
        from hermes.workbench.cli import Task, _make_registry

        if _make_registry().get(task_id) is None:
            task = Task(
                task_id=existing["task_id"],
                plan=existing["plan"],
                mode=existing.get("mode", "oneshot"),
                max_rounds=existing.get("max_rounds", 1),
                max_runs=existing.get("max_runs", 1),
                interval=existing.get("interval", 0.0),
                goal=existing.get("goal"),
            )
            task.rounds = existing.get("rounds", [])
            task.status = existing.get("status", "PENDING")
            _make_registry().register(task)

        result = _make_scheduler().run(task_id)
        task_dict = _make_store().get(task_id)
        if task_dict is None:
            raise NotFoundError(f"task vanished after run: {task_id}")
        task_dict["result_ok"] = getattr(result, "ok", False) if result else False
        self._send_json(200, task_dict)

    def h_post_task_cancel(self, task_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler, _make_store

        existing = _make_store().get(task_id)
        if existing is None:
            raise NotFoundError(f"task not found: {task_id}")
        # Re-register if needed so scheduler.cancel can find it.
        from hermes.workbench.cli import Task, _make_registry

        if _make_registry().get(task_id) is None:
            task = Task(
                task_id=existing["task_id"],
                plan=existing["plan"],
                mode=existing.get("mode", "oneshot"),
                goal=existing.get("goal"),
            )
            task.rounds = existing.get("rounds", [])
            task.status = existing.get("status", "PENDING")
            _make_registry().register(task)

        _make_scheduler().cancel(task_id)
        task_dict = _make_store().get(task_id)
        self._send_json(200, task_dict or {"task_id": task_id, "status": "CANCELLED"})


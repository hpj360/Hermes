"""Scheduler routes: jobs / projects / triggers / asset-sync / job SSE.

从 server.py 拆出的路由域 mixin（Phase 3 调度域）。
"""
from __future__ import annotations

from hermes.workbench.server_routes.base import RouteBase
import json
import queue as _queue
import uuid
from typing import Any


from hermes.workbench.errors import ValidationError, NotFoundError


class SchedulerRoutes(RouteBase):
    def h_post_jobs(self) -> None:
        """Submit a new scheduled job.

        Body: {"plan": [...], "project": "default", "priority": 5,
               "timeout": null, "depends_on": [], "mode": "oneshot"}
        """
        from hermes.workbench.cli import _make_scheduler_center
        from hermes.workbench.scheduler import JobStatus, ScheduledJob

        body = self._read_json_body()
        if not isinstance(body, dict) or "plan" not in body:
            raise ValidationError("body must contain 'plan'")
        plan = body["plan"]
        if not isinstance(plan, list):
            raise ValidationError("'plan' must be a JSON array")
        from hermes.workbench.cli import Task

        task = Task(task_id=f"job-{uuid.uuid4().hex[:8]}", plan=plan, mode=body.get("mode", "oneshot"))
        depends_on = list(body.get("depends_on", []) or [])
        job = ScheduledJob(
            task=task,
            target_project=body.get("project", "default"),
            priority=int(body.get("priority", 5)),
            timeout=body.get("timeout"),
            depends_on=depends_on,
        )
        center = _make_scheduler_center()
        center.job_store.save(job)
        if depends_on:
            center.dag.register(job.job_id, depends_on)
        if center.dag.ready_to_queue(job.job_id):
            job.status = JobStatus.QUEUED
            center.job_store.save(job)
            center.job_queue.put(job)
            center.status_bus.emit(job)
        self._send_json(201, job.to_dict())

    def h_get_jobs(self) -> None:
        """List jobs, optionally filtered by ?status=QUEUED."""
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        params = self._query_params()
        status = params.get("status")
        if status:
            from hermes.workbench.scheduler import JobStatus

            try:
                jobs = center.job_store.list_by_status(JobStatus(status))
            except ValueError as e:
                raise ValidationError(f"invalid status: {status}") from e
        else:
            jobs = center.job_store.list()
        self._send_json(200, {"jobs": [j.to_dict() for j in jobs]})

    def h_get_jobs_metrics(self) -> None:
        from hermes.workbench.cli import _make_scheduler_center
        from hermes.workbench.scheduler import compute_metrics

        center = _make_scheduler_center()
        metrics = compute_metrics(center.job_store.list())
        self._send_json(200, metrics)

    def h_get_job(self, job_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        job = center.job_store.get(job_id)
        if job is None:
            raise NotFoundError(f"job not found: {job_id}")
        self._send_json(200, job.to_dict())

    def h_post_job_cancel(self, job_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center
        from hermes.workbench.scheduler import JobStatus

        center = _make_scheduler_center()
        job = center.job_store.get(job_id)
        if job is None:
            raise NotFoundError(f"job not found: {job_id}")
        job.cancel_event.set()
        if not job.status.is_terminal():
            job.status = JobStatus.CANCELLED
            center.job_store.save(job)
            center.status_bus.emit(job)
        self._send_json(200, job.to_dict())

    def h_post_job_retry(self, job_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center
        from hermes.workbench.scheduler import JobStatus

        center = _make_scheduler_center()
        job = center.job_store.get(job_id)
        if job is None:
            raise NotFoundError(f"job not found: {job_id}")
        if not job.status.is_terminal():
            raise ValidationError(f"job not terminal: {job.status.value}")
        job.status = JobStatus.QUEUED
        job.cancel_event.clear()
        center.job_store.save(job)
        center.job_queue.put(job)
        center.status_bus.emit(job)
        self._send_json(200, job.to_dict())

    def h_get_projects(self) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        projects = center.project_registry.list()
        self._send_json(
            200,
            {"projects": [p.to_public_dict() for p in projects], **center.project_registry.summary()},
        )

    def h_post_projects(self) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        body = self._read_json_body()
        if not isinstance(body, dict):
            raise ValidationError("body must be a JSON object")
        name = body.get("name")
        project_type = body.get("type")
        state_dir = body.get("state_dir")
        if not name or not project_type or not state_dir:
            raise ValidationError("name, type, and state_dir are required")
        center = _make_scheduler_center()
        conn = center.project_registry.add(
            name=name,
            project_type=project_type,
            state_dir=state_dir,
            skills_dir=body.get("skills_dir"),
            config=body.get("config"),
            max_concurrent=self._parse_int(body.get("max_concurrent"), 1),
        )
        self._send_json(201, conn.to_public_dict())

    def h_get_project(self, project_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        conn = center.project_registry.get(project_id)
        if conn is None:
            raise NotFoundError(f"project not found: {project_id}")
        self._send_json(200, conn.to_public_dict())

    def h_delete_project(self, project_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        if not center.project_registry.remove(project_id):
            raise NotFoundError(f"project not found: {project_id}")
        self._send_no_content()

    def h_post_project_ping(self, project_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        result = center.project_registry.ping(project_id)
        if not result.get("reachable"):
            raise NotFoundError(f"project unreachable: {project_id}")
        self._send_json(200, result)

    def h_get_triggers(self) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        triggers = center.trigger_store.list()
        self._send_json(200, {"triggers": [t.to_dict() for t in triggers]})

    def h_post_triggers(self) -> None:
        from hermes.workbench.cli import _make_scheduler_center
        from hermes.workbench.triggers import Trigger

        body = self._read_json_body()
        if not isinstance(body, dict) or "plan" not in body:
            raise ValidationError("body must contain 'plan'")
        cron = body.get("cron")
        config: dict[str, Any] = {"cron": cron} if cron else {}
        trigger = Trigger(
            job_template={"plan": body["plan"]},
            trigger_type="cron" if cron else "manual",
            config=config,
        )
        center = _make_scheduler_center()
        center.trigger_store.save(trigger)
        self._send_json(201, trigger.to_dict())

    def h_get_trigger(self, trigger_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        trigger = center.trigger_store.get(trigger_id)
        if trigger is None:
            raise NotFoundError(f"trigger not found: {trigger_id}")
        self._send_json(200, trigger.to_dict())

    def h_delete_trigger(self, trigger_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        if not center.trigger_store.delete(trigger_id):
            raise NotFoundError(f"trigger not found: {trigger_id}")
        self._send_no_content()

    def h_post_trigger_fire(self, trigger_id: str) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        if not center.cron_scheduler.fire(trigger_id):
            raise NotFoundError(f"trigger not found or fire failed: {trigger_id}")
        self._send_json(200, {"fired": trigger_id})

    def h_post_sync(self) -> None:
        from hermes.workbench.asset_sync import AssetSync
        from hermes.workbench.cli import _make_scheduler_center

        body = self._read_json_body()
        if not isinstance(body, dict):
            raise ValidationError("body must be a JSON object")
        source = body.get("source")
        targets = body.get("targets")
        if not source or not targets or not isinstance(targets, list):
            raise ValidationError("source and targets (list) are required")
        scope = body.get("scope", "all")
        center = _make_scheduler_center()
        sync = AssetSync(center.router)
        result = sync.sync(source=source, targets=targets, scope=scope)
        self._send_json(
            200,
            {
                "ok": result.ok,
                "scope": result.scope,
                "source": result.source,
                "targets": result.targets,
                "synced_count": result.synced_count,
                "errors": result.errors,
            },
        )

    def h_get_stream_jobs(self) -> None:
        """Stream job status changes via SSE (subscribes to StatusBus)."""
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        bus = center.status_bus
        q = bus.subscribe()

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_cors_headers()
        self.end_headers()

        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=15.0)
                    data = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except _queue.Empty:
                    # Heartbeat keeps the connection alive.
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Client disconnected
        finally:
            bus.unsubscribe(q)


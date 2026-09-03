"""System routes: health / metrics / dashboard / trace / SSE.

从 server.py 拆出的路由域 mixin：进程健康、Prometheus 指标、聚合
dashboard 快照、trace 重建与 episode SSE 流。
"""
from __future__ import annotations

from hermes.workbench.server_routes.base import RouteBase
import json
import time
from typing import Any



class SystemRoutes(RouteBase):
    def h_get_health(self) -> None:
        from hermes.workbench.cli import _make_scheduler_center

        center = _make_scheduler_center()
        jobs = center.job_store.list()
        non_terminal = sum(1 for j in jobs if not j.status.is_terminal())
        self._send_json(
            200,
            {
                "status": "ok",
                "services": ["skills", "memory", "tasks", "scheduler"],
                "scheduler": {
                    "queue_depth": center.job_queue.size(),
                    "jobs_total": len(jobs),
                    "jobs_active": non_terminal,
                    "recovery": "ready",
                    "workers": {
                        "active": center.worker_pool.active_count(),
                        "size": center.worker_pool.size,
                        "running": center.worker_pool.is_running(),
                    },
                    "cron": center.cron_scheduler.is_running(),
                },
            },
        )

    def h_get_metrics(self) -> None:
        """Prometheus text exposition for the scheduler (scrape endpoint).

        Exposes ``hermes_jobs_total``, ``hermes_jobs_queue_depth``, and
        per-status counts (``hermes_jobs_by_status``) in the Prometheus
        0.0.4 text format for scraping by Prometheus / VictoriaMetrics.
        """
        from hermes.workbench.cli import _make_scheduler_center
        from hermes.workbench.scheduler import JobStatus

        center = _make_scheduler_center()
        jobs = center.job_store.list()
        queue_depth = center.job_queue.size()

        status_counts: dict[str, int] = {s.value: 0 for s in JobStatus}
        for job in jobs:
            status_counts[job.status.value] = status_counts.get(job.status.value, 0) + 1

        lines = [
            "# HELP hermes_jobs_total Total number of scheduled jobs.",
            "# TYPE hermes_jobs_total gauge",
            f"hermes_jobs_total {len(jobs)}",
            "# HELP hermes_jobs_queue_depth Current scheduler job-queue depth.",
            "# TYPE hermes_jobs_queue_depth gauge",
            f"hermes_jobs_queue_depth {queue_depth}",
            "# HELP hermes_jobs_by_status Number of jobs grouped by lifecycle status.",
            "# TYPE hermes_jobs_by_status gauge",
        ]
        for status in sorted(status_counts):
            lines.append(f'hermes_jobs_by_status{{status="{status}"}} {status_counts[status]}')

        # Memory backend metrics (M4). Degrades to zeroes if unavailable.
        try:
            from hermes.workbench.cli import _make_memory

            mem = _make_memory()
            backend = mem.get_backend()
            sync_stats = mem.sync_stats()
            lines.append("# HELP hermes_memory_backend_healthy Whether the memory backend is usable.")
            lines.append("# TYPE hermes_memory_backend_healthy gauge")
            lines.append(f'hermes_memory_backend_healthy{{backend="{type(backend).__name__}"}} {1 if backend.health() else 0}')
            lines.append("# HELP hermes_memory_sync_pending Episodes awaiting async extraction.")
            lines.append("# TYPE hermes_memory_sync_pending gauge")
            lines.append(f"hermes_memory_sync_pending {sync_stats.get('pending', 0)}")
            lines.append("# HELP hermes_memory_sync_failures Cumulative async-extraction failures.")
            lines.append("# TYPE hermes_memory_sync_failures gauge")
            lines.append(f"hermes_memory_sync_failures {sync_stats.get('failure_count', 0)}")
        except Exception:  # noqa: BLE001 — metrics must never break the scrape
            pass

        # LLM KV-cache prefix metrics (P0-1). Client-side approximation of the
        # provider-side KV-cache hit rate for the stable prompt prefix.
        try:
            from hermes.workbench.llm import kv_cache_stats

            kv = kv_cache_stats()
            lines.append("# HELP hermes_llm_kv_cache_hit_rate Fraction of LLM requests whose stable prefix was seen before.")
            lines.append("# TYPE hermes_llm_kv_cache_hit_rate gauge")
            lines.append(f"hermes_llm_kv_cache_hit_rate {kv['hit_rate']}")
            lines.append("# HELP hermes_llm_kv_cache_requests_total LLM requests observed for KV-cache tracking.")
            lines.append("# TYPE hermes_llm_kv_cache_requests_total counter")
            lines.append(f"hermes_llm_kv_cache_requests_total {kv['total']}")
            lines.append("# HELP hermes_llm_kv_cache_unique_prefixes Distinct stable prefixes observed.")
            lines.append("# TYPE hermes_llm_kv_cache_unique_prefixes gauge")
            lines.append(f"hermes_llm_kv_cache_unique_prefixes {kv['unique_prefixes']}")
        except Exception:  # noqa: BLE001 — metrics must never break the scrape
            pass

        self._send_text(
            200,
            "\n".join(lines) + "\n",
            content_type="text/plain; version=0.0.4; charset=utf-8",
        )

    def h_get_root(self) -> None:
        """Serve the single-page HTML dashboard."""
        from hermes.workbench.dashboard import DASHBOARD_HTML

        body = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def h_get_trace(self, trace_id: str) -> None:
        """Return all episodes carrying the given trace_id, oldest first.

        Reconstructs a Planner→Generator→Evaluator chain for debugging.
        """
        from hermes.workbench.cli import _make_memory
        from hermes.workbench.tracing import Tracer

        tracer = Tracer(_make_memory())
        episodes = tracer.get_trace(trace_id)
        self._send_json(
            200,
            {
                "trace_id": trace_id,
                "count": len(episodes),
                "episodes": [ep.__dict__ for ep in episodes],
            },
        )

    def h_get_dashboard(self) -> None:
        """Aggregated dashboard snapshot: tasks, memory, traces, skills.

        Query params:
            ?task_limit=20        - max tasks to return (default 20)
            ?episode_limit=50     - max recent episodes (default 50)
            ?fact_limit=100       - max facts (default 100)
        """
        from hermes.workbench.cli import (
            _make_memory,
            _make_runner,
            _make_store,
        )

        params = self._query_params()
        task_limit = self._parse_int(params.get("task_limit"), 20)
        episode_limit = self._parse_int(params.get("episode_limit"), 50)
        fact_limit = self._parse_int(params.get("fact_limit"), 100)

        mem = _make_memory()
        store = _make_store()
        runner = _make_runner()

        # Tasks (most recent first)
        tasks = store.list()
        tasks = tasks[-task_limit:] if task_limit > 0 else tasks
        tasks.reverse()

        # Recent episodes
        episodes = mem.list_episodes(limit=episode_limit)

        # Facts
        facts = mem.list_facts()[:fact_limit]

        # Skills
        try:
            skills = runner.discover()
            skill_summaries = [
                {"name": s.name, "runtime": s.runtime, "description": s.description}
                for s in skills
            ]
        except Exception:  # noqa: BLE001
            skill_summaries = []

        # Group episodes by trace_id for trace summary
        traces: dict[str, list[dict[str, Any]]] = {}
        for ep in episodes:
            tid = (ep.details or {}).get("trace_id")
            if tid:
                traces.setdefault(tid, []).append(ep.__dict__)
        trace_summaries = [
            {
                "trace_id": tid,
                "count": len(eps),
                "kinds": sorted({e["kind"] for e in eps}),
                "first_at": min(e["created_at"] for e in eps),
                "last_at": max(e["created_at"] for e in eps),
            }
            for tid, eps in traces.items()
        ]
        trace_summaries.sort(key=lambda t: t["last_at"], reverse=True)

        self._send_json(
            200,
            {
                "tasks": tasks,
                "episodes": [ep.__dict__ for ep in episodes],
                "facts": facts,
                "skills": skill_summaries,
                "traces": trace_summaries,
                "totals": {
                    "tasks": len(tasks),
                    "episodes": len(episodes),
                    "facts": len(facts),
                    "skills": len(skill_summaries),
                    "traces": len(trace_summaries),
                },
            },
        )

    def h_get_stream_episodes(self) -> None:
        """Stream episodes via Server-Sent Events (SSE).

        Polls for new episodes every 2 seconds and pushes them to the client.
        Query params: ?kind=some_kind (optional filter)
        """
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        kind = params.get("kind")
        mem = _make_memory()

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_cors_headers()
        self.end_headers()

        seen_ids: set[str] = set()
        try:
            while True:
                episodes = mem.list_episodes(kind=kind, limit=50)
                for ep in episodes:
                    if ep.id not in seen_ids:
                        seen_ids.add(ep.id)
                        data = json.dumps(ep.__dict__, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                # Heartbeat keeps the connection alive
                self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # Client disconnected


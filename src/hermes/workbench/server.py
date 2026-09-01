"""Dashboard HTTP API.

Exposes workbench capabilities (skills/memory/tasks) as a RESTful JSON API
using only the standard library (http.server). The server is a stateless
adapter: all state flows through the cli.py service factories. Errors map
to HTTP status codes via workbench.errors.

Features:
- Bearer Token authentication (when OPENCLAW_GATEWAY_TOKEN is set)
- CORS support for browser-based dashboards
- SSE streaming endpoint for real-time episode updates

Run via ``hermes workbench serve --host 127.0.0.1 --port 8080``.

模块拆分（本文件曾是 1726 行的巨型文件）：
- 本文件          — 路由表（_ROUTES，API surface 单一事实来源）、dispatch、
                     auth/CORS、make_server/run_server 工厂
- ``server_routes`` — 各路由域 mixin（system/skills/memory/todos/tasks/kb/
                     scheduler/loops）+ 公共 helpers（base.RouteBase）

DashboardHandler = BaseHTTPRequestHandler + 全部域 mixin；对外符号
（DashboardHandler / make_server / run_server / _ROUTES）保持不变。
"""

from __future__ import annotations

import re
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from hermes.workbench.errors import NotFoundError, WorkbenchError, status_code_for
from hermes.workbench.server_routes import (
    KbRoutes,
    LoopRoutes,
    MemoryRoutes,
    SchedulerRoutes,
    SkillsRoutes,
    SystemRoutes,
    TasksRoutes,
    TodosRoutes,
)

__all__ = ["DashboardHandler", "NotFoundError", "make_server", "run_server"]


# Route table: (method, regex, handler_name). Named groups become kwargs.
_ROUTES: list[tuple[str, str, str]] = [
    ("GET", r"^/health$", "h_get_health"),
    ("GET", r"^/metrics$", "h_get_metrics"),
    ("GET", r"^/$", "h_get_root"),
    ("GET", r"^/dashboard\.html$", "h_get_root"),
    ("GET", r"^/skills$", "h_get_skills"),
    ("GET", r"^/skills/(?P<name>[^/]+)$", "h_get_skill"),
    ("POST", r"^/skills/(?P<name>[^/]+)/run$", "h_post_skill_run"),
    ("GET", r"^/memory/facts$", "h_get_facts"),
    ("POST", r"^/memory/facts$", "h_post_facts"),
    ("GET", r"^/memory/facts/(?P<key>[^/]+)$", "h_get_fact"),
    ("DELETE", r"^/memory/facts/(?P<key>[^/]+)$", "h_delete_fact"),
    ("GET", r"^/memory/episodes$", "h_get_episodes"),
    ("GET", r"^/memory/search$", "h_get_memory_search"),
    ("GET", r"^/memory/search/rrf$", "h_get_memory_search_rrf"),
    ("GET", r"^/memory/search/fts$", "h_get_memory_search_fts"),
    ("GET", r"^/memory/search/semantic$", "h_get_memory_search_semantic"),
    ("POST", r"^/memory/cleanup$", "h_post_memory_cleanup"),
    ("POST", r"^/memory/learn$", "h_post_memory_learn"),
    ("POST", r"^/memory/compact$", "h_post_memory_compact"),
    ("GET", r"^/memory/profile$", "h_get_profile"),
    ("GET", r"^/todos$", "h_get_todos"),
    ("POST", r"^/todos$", "h_post_todos"),
    ("GET", r"^/todos/(?P<todo_id>[^/]+)$", "h_get_todo"),
    ("POST", r"^/todos/(?P<todo_id>[^/]+)/status$", "h_post_todo_status"),
    ("POST", r"^/todos/(?P<todo_id>[^/]+)/hand-off$", "h_post_todo_handoff"),
    ("DELETE", r"^/todos/(?P<todo_id>[^/]+)$", "h_delete_todo"),
    ("POST", r"^/inbox$", "h_post_inbox"),
    ("GET", r"^/notes/summary$", "h_get_notes_summary"),
    ("GET", r"^/traces/(?P<trace_id>[^/]+)$", "h_get_trace"),
    ("POST", r"^/tasks$", "h_post_tasks"),
    ("GET", r"^/tasks$", "h_get_tasks"),
    ("GET", r"^/tasks/(?P<task_id>[^/]+)$", "h_get_task"),
    ("POST", r"^/tasks/(?P<task_id>[^/]+)/cancel$", "h_post_task_cancel"),
    ("POST", r"^/tasks/(?P<task_id>[^/]+)/run$", "h_post_task_run"),
    ("GET", r"^/dashboard$", "h_get_dashboard"),
    ("GET", r"^/github/sync$", "h_get_github_sync"),
    ("GET", r"^/ima/knowledge-bases$", "h_get_ima_kbs"),
    ("GET", r"^/ima/search$", "h_get_ima_search"),
    ("GET", r"^/kb/search$", "h_get_kb_search"),
    ("POST", r"^/ima/push$", "h_post_ima_push"),
    ("POST", r"^/ima/sync$", "h_post_ima_sync"),
    ("POST", r"^/ima/urls$", "h_post_ima_urls"),
    ("POST", r"^/ima/files$", "h_post_ima_files"),
    ("GET", r"^/ima/notes$", "h_get_ima_notes"),
    ("GET", r"^/ima/notes/search$", "h_get_ima_notes_search"),
    ("GET", r"^/ima/notes/(?P<doc_id>[^/]+)$", "h_get_ima_note_content"),
    ("POST", r"^/ima/notes$", "h_post_ima_note_create"),
    ("POST", r"^/ima/notes/(?P<doc_id>[^/]+)/append$", "h_post_ima_note_append"),
    ("GET", r"^/stream/episodes$", "h_get_stream_episodes"),
    # Phase 3 scheduler routes
    ("POST", r"^/jobs$", "h_post_jobs"),
    ("GET", r"^/jobs$", "h_get_jobs"),
    ("GET", r"^/jobs/metrics$", "h_get_jobs_metrics"),
    ("GET", r"^/jobs/(?P<job_id>[^/]+)$", "h_get_job"),
    ("POST", r"^/jobs/(?P<job_id>[^/]+)/cancel$", "h_post_job_cancel"),
    ("POST", r"^/jobs/(?P<job_id>[^/]+)/retry$", "h_post_job_retry"),
    ("GET", r"^/projects$", "h_get_projects"),
    ("POST", r"^/projects$", "h_post_projects"),
    ("GET", r"^/projects/(?P<project_id>[^/]+)$", "h_get_project"),
    ("DELETE", r"^/projects/(?P<project_id>[^/]+)$", "h_delete_project"),
    ("POST", r"^/projects/(?P<project_id>[^/]+)/ping$", "h_post_project_ping"),
    ("GET", r"^/triggers$", "h_get_triggers"),
    ("POST", r"^/triggers$", "h_post_triggers"),
    ("GET", r"^/triggers/(?P<trigger_id>[^/]+)$", "h_get_trigger"),
    ("DELETE", r"^/triggers/(?P<trigger_id>[^/]+)$", "h_delete_trigger"),
    ("POST", r"^/triggers/(?P<trigger_id>[^/]+)/fire$", "h_post_trigger_fire"),
    ("POST", r"^/sync$", "h_post_sync"),
    ("GET", r"^/stream/jobs$", "h_get_stream_jobs"),
    # MemOS integration routes
    ("GET", r"^/memos/health$", "h_get_memos_health"),
    ("GET", r"^/memos/search$", "h_get_memos_search"),
    ("POST", r"^/memos/feedback$", "h_post_memos_feedback"),
    # Loop trajectory view (ADR-0017 / ADR-0020)
    ("GET", r"^/loops$", "h_get_loops"),
    ("GET", r"^/loops/(?P<name>[^/]+)/trajectory/verify$", "h_get_loop_trajectory_verify"),
    ("GET", r"^/loops/(?P<name>[^/]+)/trajectory$", "h_get_loop_trajectory"),
]

# Routes that skip authentication (always public).
_PUBLIC_ROUTES: set[str] = {"h_get_health", "h_get_root"}


class DashboardHandler(  # noqa: FIX001 — MRO: 各域 mixin → RouteBase → BaseHTTPRequestHandler
    SystemRoutes,
    SkillsRoutes,
    MemoryRoutes,
    TodosRoutes,
    TasksRoutes,
    KbRoutes,
    SchedulerRoutes,
    LoopRoutes,
):
    """HTTP handler dispatching to workbench services."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    # Dispatch -----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _dispatch(self, method: str) -> None:
        path = urlsplit(self.path).path
        for route_method, pattern, handler_name in _ROUTES:
            if route_method != method:
                continue
            match = re.match(pattern, path)
            if match:
                # Authentication check (skip for public routes)
                if handler_name not in _PUBLIC_ROUTES and not self._check_auth():
                    self._send_json(401, {"error": "unauthorized", "type": "AuthError"})
                    return
                handler = getattr(self, handler_name)
                try:
                    handler(**match.groupdict())
                except WorkbenchError as e:
                    self._send_json(status_code_for(e), {"error": str(e), "type": type(e).__name__})
                except Exception as e:  # noqa: BLE001 - boundary
                    self._send_json(500, {"error": str(e), "type": type(e).__name__})
                return
        # No route matched: 405 if path matches another method, else 404.
        for _m, pattern, _h in _ROUTES:
            if re.match(pattern, path):
                self._method_not_allowed()
                return
        self._send_json(404, {"error": "not found", "path": path})

    # Auth ---------------------------------------------------------------

    def _check_auth(self) -> bool:
        """Return True if the request is authenticated.

        Uses ``HERMES_API_TOKEN`` (constant-time compare) with a backward
        compatible fallback to ``OPENCLAW_GATEWAY_TOKEN``. When neither is
        set, auth is disabled (dev mode) — callers must then ensure the
        server binds loopback only (see :func:`make_server`).
        """
        import secrets

        from hermes.config import get_settings

        settings = get_settings()
        expected = getattr(settings, "hermes_api_token", None) or getattr(
            settings, "openclaw_gateway_token", None
        )
        if not expected:
            return True  # dev mode: no token configured
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return secrets.compare_digest(auth_header[7:], expected)
        return False


def _is_loopback(host: str) -> bool:
    """True when *host* is a loopback address (127.x, ::1, localhost, empty)."""
    return host in ("", "127.0.0.1", "::1", "localhost")


def make_server(host: str, port: int, insecure: bool = False) -> ThreadingHTTPServer:
    """Create a ThreadingHTTPServer bound to *host:port*.

    When no API token is configured, binding a non-loopback address is
    refused (unless ``insecure=True``) so the server never silently runs
    unauthenticated on the network.
    """
    from hermes.config import get_settings

    settings = get_settings()
    has_token = bool(
        getattr(settings, "hermes_api_token", None)
        or getattr(settings, "openclaw_gateway_token", None)
    )
    if not has_token and not _is_loopback(host) and not insecure:
        raise ValueError(
            "HERMES_API_TOKEN is not set: refusing to bind non-loopback "
            f"address {host!r}. Set a token, bind loopback, or pass --insecure."
        )
    return ThreadingHTTPServer((host, port), DashboardHandler)


def run_server(host: str = "127.0.0.1", port: int = 8080, insecure: bool = False) -> None:
    """Start the dashboard server (blocking).

    Before serving, the scheduler center is started (crash recovery + worker
    pool + cron scheduler) so that submitted jobs are actually consumed. On
    shutdown the scheduler is stopped gracefully.
    """
    from hermes.workbench.cli import _make_scheduler_center

    center = _make_scheduler_center()
    recovery_stats = center.start()
    httpd = make_server(host, port, insecure=insecure)
    print(f"Hermes workbench dashboard listening on http://{host}:{port}")
    print(
        f"scheduler started: requeued={recovery_stats['requeued']} "
        f"abandoned={recovery_stats['abandoned']}"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        center.stop()
        httpd.shutdown()

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
"""

from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from hermes.workbench.errors import NotFoundError, ValidationError, WorkbenchError, status_code_for

__all__ = ["DashboardHandler", "make_server", "run_server"]


# Route table: (method, regex, handler_name). Named groups become kwargs.
_ROUTES: list[tuple[str, str, str]] = [
    ("GET", r"^/health$", "h_get_health"),
    ("GET", r"^/$", "h_get_root"),
    ("GET", r"^/dashboard\.html$", "h_get_root"),
    ("GET", r"^/skills$", "h_get_skills"),
    ("GET", r"^/skills/(?P<name>[^/]+)$", "h_get_skill"),
    ("GET", r"^/memory/facts$", "h_get_facts"),
    ("POST", r"^/memory/facts$", "h_post_facts"),
    ("GET", r"^/memory/facts/(?P<key>[^/]+)$", "h_get_fact"),
    ("DELETE", r"^/memory/facts/(?P<key>[^/]+)$", "h_delete_fact"),
    ("GET", r"^/memory/episodes$", "h_get_episodes"),
    ("GET", r"^/memory/search$", "h_get_memory_search"),
    ("GET", r"^/memory/search/rrf$", "h_get_memory_search_rrf"),
    ("POST", r"^/memory/cleanup$", "h_post_memory_cleanup"),
    ("POST", r"^/memory/learn$", "h_post_memory_learn"),
    ("POST", r"^/memory/compact$", "h_post_memory_compact"),
    ("GET", r"^/memory/profile$", "h_get_profile"),
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
]

# Routes that skip authentication (always public).
_PUBLIC_ROUTES: set[str] = {"h_get_health", "h_get_root"}


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP handler dispatching to workbench services."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
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

        When ``OPENCLAW_GATEWAY_TOKEN`` is unset, auth is disabled (dev mode).
        """
        from hermes.config import get_settings

        token = get_settings().openclaw_gateway_token
        if not token:
            return True  # dev mode: no token configured
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:] == token
        return False

    # CORS ---------------------------------------------------------------

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    # Helpers ------------------------------------------------------------

    def _send_json(self, status: int, obj: Any) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_no_content(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValidationError(f"invalid JSON body: {e}") from e

    def _query_params(self) -> dict[str, str]:
        parsed = parse_qs(urlsplit(self.path).query)
        return {k: v[0] for k, v in parsed.items() if v}

    def _method_not_allowed(self) -> None:
        self._send_json(405, {"error": "method not allowed"})

    # Services (injected by make_server) ---------------------------------
    # These are set as class attributes by make_server via type().

    # health -------------------------------------------------------------

    def h_get_health(self) -> None:
        self._send_json(200, {"status": "ok", "services": ["skills", "memory", "tasks"]})

    # root (HTML dashboard) ---------------------------------------------

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

    # skills -------------------------------------------------------------

    def h_get_skills(self) -> None:
        from hermes.workbench.cli import _make_runner

        specs = _make_runner().discover()
        self._send_json(
            200,
            {
                "skills": [
                    {
                        "name": s.name,
                        "runtime": s.runtime,
                        "description": s.description,
                        "entrypoint": s.entrypoint,
                    }
                    for s in specs
                ]
            },
        )

    def h_get_skill(self, name: str) -> None:
        from hermes.workbench.cli import _make_runner

        spec = _make_runner().get(name)
        if spec is None:
            raise NotFoundError(f"skill not found: {name}")
        self._send_json(
            200,
            {
                "name": spec.name,
                "path": str(spec.path),
                "runtime": spec.runtime,
                "entrypoint": spec.entrypoint,
                "description": spec.description,
                "requires_bins": spec.requires_bins,
            },
        )

    # memory facts -------------------------------------------------------

    def h_get_facts(self) -> None:
        from hermes.workbench.cli import _make_memory

        facts = _make_memory().list_facts()
        self._send_json(200, {"facts": facts})

    def h_post_facts(self) -> None:
        from hermes.workbench.cli import _make_memory

        body = self._read_json_body()
        if not isinstance(body, dict) or "key" not in body or "value" not in body:
            raise ValidationError("body must contain 'key' and 'value'")
        _make_memory().remember_fact(body["key"], body["value"])
        self._send_json(201, {"key": body["key"], "value": body["value"]})

    def h_get_fact(self, key: str) -> None:
        from hermes.workbench.cli import _make_memory

        fact = _make_memory().get_fact(key)
        if fact is None:
            raise NotFoundError(f"fact not found: {key}")
        self._send_json(200, fact)

    def h_delete_fact(self, key: str) -> None:
        from hermes.workbench.cli import _make_memory

        if not _make_memory().forget_fact(key):
            raise NotFoundError(f"fact not found: {key}")
        self._send_no_content()

    # memory episodes ----------------------------------------------------

    def h_get_episodes(self) -> None:
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        episodes = _make_memory().list_episodes(kind=params.get("kind"))
        self._send_json(200, {"episodes": [e.__dict__ for e in episodes]})

    def h_get_memory_search(self) -> None:
        """Search episodes by keyword (TF-IDF cosine similarity).

        Query params: ?q=keyword&limit=10&kind=some_kind
        """
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        limit = int(params.get("limit", "10"))
        kind = params.get("kind")
        results = _make_memory().search_episodes(query=q, limit=limit, kind=kind)
        self._send_json(
            200,
            {
                "query": q,
                "results": [
                    {"episode": ep.__dict__, "score": round(score, 4)}
                    for ep, score in results
                ],
            },
        )

    def h_get_memory_search_rrf(self) -> None:
        """Hybrid episode search via Reciprocal Rank Fusion.

        Fuses exact-substring and TF-IDF signals. Query params same as
        /memory/search, plus optional ``k`` (RRF constant, default 60).
        """
        from hermes.workbench.cli import _make_memory

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        limit = int(params.get("limit", "10"))
        kind = params.get("kind")
        k = int(params.get("k", "60"))
        results = _make_memory().search_episodes_rrf(
            query=q, limit=limit, kind=kind, k=k
        )
        self._send_json(
            200,
            {
                "query": q,
                "method": "rrf",
                "results": [
                    {"episode": ep.__dict__, "score": round(score, 6)}
                    for ep, score in results
                ],
            },
        )

    def h_post_memory_cleanup(self) -> None:
        """Purge all expired facts (TTL elapsed). Returns the count removed."""
        from hermes.workbench.cli import _make_memory

        removed = _make_memory().cleanup_expired_facts()
        self._send_json(200, {"removed": removed})

    def h_post_memory_learn(self) -> None:
        """Learn profile insights from recent episodes.

        Body (optional): {"recent_count": 200, "top_n": 5}
        """
        from hermes.workbench.cli import _make_memory

        body = self._read_json_body()
        recent_count = int(body.get("recent_count", 200))
        top_n = int(body.get("top_n", 5))
        insights = _make_memory().learn_profile_from_episodes(
            recent_count=recent_count, top_n=top_n
        )
        self._send_json(200, {"insights": insights})

    def h_post_memory_compact(self) -> None:
        """Compact old episodes into per-kind summary episodes.

        Body (optional): {"keep_recent": 200, "kind": null}
        """
        from hermes.workbench.cli import _make_memory

        body = self._read_json_body()
        keep_recent = int(body.get("keep_recent", 200))
        kind = body.get("kind")
        result = _make_memory().compact_episodes(keep_recent=keep_recent, kind=kind)
        self._send_json(200, result)

    # memory profile -----------------------------------------------------

    def h_get_profile(self) -> None:
        from hermes.workbench.cli import _make_memory

        profile = _make_memory().get_user_profile()
        self._send_json(200, profile)

    # tasks --------------------------------------------------------------

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

    # github sync --------------------------------------------------------

    def h_get_github_sync(self) -> None:
        """Trigger a GitHub sync cycle (pull issues → run → push results).

        Query params: ?repo=owner/name&label=workbench
        """
        from hermes.workbench.github_sync import GitHubSyncService

        params = self._query_params()
        repo = params.get("repo")
        if not repo:
            raise ValidationError("query param 'repo' is required (e.g. owner/name)")
        label = params.get("label", "workbench")
        try:
            service = GitHubSyncService.from_env(repo=repo)
        except ValidationError:
            raise
        result = service.sync(label=label)
        self._send_json(200, result)

    # IMA knowledge base -------------------------------------------------

    def h_get_ima_kbs(self) -> None:
        """List IMA knowledge bases."""
        from hermes.workbench.ima_sync import ImaSyncService

        params = self._query_params()
        query = params.get("query", "")
        svc = ImaSyncService()
        kbs = svc.list_kbs(query=query)
        self._send_json(
            200,
            {
                "knowledge_bases": [
                    {
                        "kb_id": kb.kb_id,
                        "kb_name": kb.kb_name,
                        "content_count": kb.content_count,
                        "description": kb.description,
                        "base_type": kb.base_type,
                    }
                    for kb in kbs
                ]
            },
        )

    def h_get_ima_search(self) -> None:
        """Search IMA knowledge base content."""
        from hermes.workbench.ima_sync import ImaSyncService

        params = self._query_params()
        kb_id = params.get("kb_id", "")
        q = params.get("q", "").strip()
        if not kb_id:
            raise ValidationError("query param 'kb_id' is required")
        if not q:
            raise ValidationError("query param 'q' is required")
        svc = ImaSyncService()
        results = svc.pull(q, kb_id)
        self._send_json(
            200,
            {
                "query": q,
                "kb_id": kb_id,
                "results": [
                    {
                        "title": r.title,
                        "highlight_content": r.highlight_content,
                        "url": r.url,
                    }
                    for r in results
                ],
            },
        )

    def h_post_ima_push(self) -> None:
        """Push content to IMA as a note."""
        from hermes.workbench.ima_sync import ImaSyncService

        body = self._read_json()
        kb_id = body.get("kb_id", "")
        title = body.get("title", "")
        content = body.get("content", "")
        if not kb_id or not title or not content:
            raise ValidationError("kb_id, title, and content are required")
        svc = ImaSyncService()
        result = svc.push(kb_id, title, content)
        self._send_json(200, {"ok": True, "result": result})

    def h_post_ima_sync(self) -> None:
        """Bidirectional sync between Hermes and IMA."""
        from hermes.workbench.ima_sync import ImaSyncService

        body = self._read_json()
        kb_id = body.get("kb_id", "")
        query = body.get("query", "")
        push_kind = body.get("push_kind")
        if not kb_id or not query:
            raise ValidationError("kb_id and query are required")
        svc = ImaSyncService()
        result = svc.sync(query, kb_id, push_kind=push_kind)
        self._send_json(
            200,
            {
                "pulled": result.pulled,
                "pushed": result.pushed,
                "errors": result.errors,
                "details": result.details,
            },
        )

    def h_post_ima_urls(self) -> None:
        """Batch import web page URLs into an IMA knowledge base.

        Body: {"kb_id": "...", "urls": ["https://..."], "folder_id": "..." (optional)}
        """
        from hermes.workbench.ima_sync import ImaSyncService

        body = self._read_json()
        kb_id = body.get("kb_id", "")
        urls = body.get("urls", [])
        folder_id = body.get("folder_id", "")
        if not kb_id:
            raise ValidationError("kb_id is required")
        if not urls or not isinstance(urls, list):
            raise ValidationError("urls (non-empty list) is required")
        svc = ImaSyncService()
        result = svc.push_urls(kb_id, urls, folder_id=folder_id)
        self._send_json(200, {"ok": True, "result": result, "count": len(urls)})

    def h_post_ima_files(self) -> None:
        """Upload a local file to an IMA knowledge base (3-step flow).

        Body: {
            "kb_id": "...",
            "file_path": "/path/to/file.pdf",
            "content_type": "application/pdf" (optional),
            "folder_id": "..." (optional)
        }

        Note: file_path must be readable by the server process. For remote
        clients, upload the file via HTTP first and pass the resulting
        temp path, or use the CLI ``hermes workbench ima file-upload``.
        """
        from hermes.workbench.ima_sync import ImaSyncService

        body = self._read_json()
        kb_id = body.get("kb_id", "")
        file_path = body.get("file_path", "")
        content_type = body.get("content_type")
        folder_id = body.get("folder_id", "")
        if not kb_id:
            raise ValidationError("kb_id is required")
        if not file_path:
            raise ValidationError("file_path is required")
        svc = ImaSyncService()
        result = svc.push_file(
            kb_id, file_path, content_type=content_type, folder_id=folder_id
        )
        self._send_json(200, {"ok": True, "result": result})

    # IMA notes module (note/v1) ------------------------------------------

    def h_get_ima_notes(self) -> None:
        """List notes in the user's IMA account."""
        from hermes.workbench.ima_sync import ImaClient

        params = self._query_params()
        limit = int(params.get("limit", "20"))
        client = ImaClient()
        notes, is_end, cursor = client.list_note(limit=limit)
        self._send_json(
            200,
            {
                "notes": [
                    {
                        "note_id": n.note_id,
                        "title": n.title,
                        "summary": n.summary,
                        "create_time": n.create_time,
                        "modify_time": n.modify_time,
                        "folder_id": n.folder_id,
                        "folder_name": n.folder_name,
                    }
                    for n in notes
                ],
                "is_end": is_end,
                "next_cursor": cursor,
            },
        )

    def h_get_ima_notes_search(self) -> None:
        """Search notes by title."""
        from hermes.workbench.ima_sync import ImaClient

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        limit = int(params.get("limit", "20"))
        client = ImaClient()
        notes, is_end, total = client.search_note_book(q, start=0, end=limit)
        self._send_json(
            200,
            {
                "query": q,
                "total_hit_num": total,
                "notes": [
                    {"note_id": n.note_id, "title": n.title, "summary": n.summary}
                    for n in notes
                ],
                "is_end": is_end,
            },
        )

    def h_get_ima_note_content(self, doc_id: str) -> None:
        """Fetch the full content of a single note.

        Path parameter is named `doc_id` for URL stability but is forwarded
        to `get_doc_content(note_id=...)` — IMA accepts both field names.
        """
        from hermes.workbench.ima_sync import ImaClient

        client = ImaClient()
        data = client.get_doc_content(doc_id)
        self._send_json(200, data)

    def h_post_ima_note_create(self) -> None:
        """Create a new note via import_doc."""
        from hermes.workbench.ima_sync import ImaClient

        body = self._read_json()
        content = body.get("content", "")
        title = body.get("title")
        if not content:
            raise ValidationError("content is required")
        client = ImaClient()
        result = client.import_doc(content=content, title=title)
        self._send_json(200, {"ok": True, "result": result})

    def h_post_ima_note_append(self, doc_id: str) -> None:
        """Append content to an existing note.

        Path parameter is named `doc_id` for URL stability but is forwarded
        to `append_doc(note_id=...)` — IMA accepts both field names.
        """
        from hermes.workbench.ima_sync import ImaClient

        body = self._read_json()
        content = body.get("content", "")
        if not content:
            raise ValidationError("content is required")
        client = ImaClient()
        result = client.append_doc(doc_id, content)
        self._send_json(200, {"ok": True, "result": result})

    # traces -------------------------------------------------------------

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

    # dashboard ----------------------------------------------------------

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
        task_limit = int(params.get("task_limit", "20"))
        episode_limit = int(params.get("episode_limit", "50"))
        fact_limit = int(params.get("fact_limit", "100"))

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

    # SSE streaming ------------------------------------------------------

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


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    """Create a ThreadingHTTPServer bound to *host:port*."""
    return ThreadingHTTPServer((host, port), DashboardHandler)


def run_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Start the dashboard server (blocking)."""
    httpd = make_server(host, port)
    print(f"Hermes workbench dashboard listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.shutdown()
        httpd.server_close()

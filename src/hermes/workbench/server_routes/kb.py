"""Knowledge-base routes: GitHub sync / IMA KB / IMA notes / hermes-kb proxy.

从 server.py 拆出的路由域 mixin。
"""
from __future__ import annotations

from hermes.workbench.server_routes.base import RouteBase

from hermes.workbench.errors import ValidationError


class KbRoutes(RouteBase):
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

    def h_get_kb_search(self) -> None:
        """Proxy a semantic search to the hermes-kb service (P2-1).

        Degrades gracefully: 503 when ``HERMES_KB_BASE_URL`` is unset, 502 when
        the upstream is unreachable, otherwise forwards the response verbatim.
        """
        import json as _json
        import urllib.error
        import urllib.parse
        import urllib.request

        from hermes.config import get_settings

        params = self._query_params()
        q = params.get("q", "").strip()
        if not q:
            raise ValidationError("query param 'q' is required")
        base = get_settings().hermes_kb_base_url.strip()
        if not base:
            self._send_json(
                503,
                {
                    "query": q,
                    "results": [],
                    "error": "hermes-kb not configured (set HERMES_KB_BASE_URL)",
                },
            )
            return
        url = f"{base.rstrip('/')}/kb/search?q={urllib.parse.quote(q)}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, _json.JSONDecodeError):
            self._send_json(
                502, {"query": q, "results": [], "error": "hermes-kb unreachable"}
            )
            return
        self._send_json(200, data)

    def h_post_ima_push(self) -> None:
        """Push content to IMA as a note."""
        from hermes.workbench.ima_sync import ImaSyncService

        body = self._read_json_body()
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

        body = self._read_json_body()
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

        body = self._read_json_body()
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

        body = self._read_json_body()
        if not isinstance(body, dict):
            raise ValidationError("body must be a JSON object")
        kb_id = body.get("kb_id", "")
        file_path = body.get("file_path", "")
        content_type = body.get("content_type")
        folder_id = body.get("folder_id", "")
        if not kb_id:
            raise ValidationError("kb_id is required")
        if not file_path:
            raise ValidationError("file_path is required")
        # Security: reject paths that escape the project root so this endpoint
        # cannot be used to exfiltrate arbitrary local files (e.g. /.env).
        from pathlib import Path

        from hermes.config import get_settings

        root = Path(get_settings().hermes_project_root).resolve()
        target = Path(file_path).resolve()
        if root not in target.parents and target != root:
            raise ValidationError("file_path must be within the project root")
        svc = ImaSyncService()
        result = svc.push_file(
            kb_id, file_path, content_type=content_type, folder_id=folder_id
        )
        self._send_json(200, {"ok": True, "result": result})

    def h_get_ima_notes(self) -> None:
        """List notes in the user's IMA account."""
        from hermes.workbench.ima_sync import ImaClient

        params = self._query_params()
        limit = self._parse_int(params.get("limit"), 20)
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

        body = self._read_json_body()
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

        body = self._read_json_body()
        content = body.get("content", "")
        if not content:
            raise ValidationError("content is required")
        client = ImaClient()
        result = client.append_doc(doc_id, content)
        self._send_json(200, {"ok": True, "result": result})


"""Todo & capture routes: todos CRUD / hand-off / inbox / notes summary.

从 server.py 拆出的路由域 mixin。
"""
from __future__ import annotations

from typing import Any

from hermes.workbench.errors import NotFoundError, ValidationError
from hermes.workbench.server_routes.base import RouteBase


class TodosRoutes(RouteBase):
    def _todos(self) -> Any:
        from hermes.workbench.cli import _make_todo_store

        return _make_todo_store()

    def h_get_todos(self) -> None:
        from hermes.workbench.todos import TodoStatus

        params = self._query_params()
        status = None
        if params.get("status"):
            status = TodoStatus(params["status"].upper())
        type_ = params.get("type")
        todos = self._todos().list(status=status, type_=type_)
        self._send_json(200, {"todos": [t.to_dict() for t in todos]})

    def h_post_todos(self) -> None:
        from hermes.workbench.todos import Todo

        body = self._read_json_body()
        if not isinstance(body, dict) or not body.get("title"):
            raise ValidationError("body must contain 'title'")
        todo = Todo(
            title=body["title"],
            type=body.get("type", "todo"),
            due=body.get("due"),
            source=body.get("source", "manual"),
            external_ref=body.get("external_ref"),
        )
        self._todos().create(todo)
        self._send_json(201, todo.to_dict())

    def h_get_todo(self, todo_id: str) -> None:
        todo = self._todos().get(todo_id)
        if todo is None:
            raise NotFoundError(f"todo not found: {todo_id}")
        self._send_json(200, todo.to_dict())

    def h_post_todo_status(self, todo_id: str) -> None:
        from hermes.workbench.todos import TodoStatus

        body = self._read_json_body()
        raw = str(body.get("status", "")).upper()
        try:
            status = TodoStatus(raw)
        except ValueError as e:
            raise ValidationError(f"invalid status: {raw}") from e
        ok = self._todos().update_status(todo_id, status)
        if not ok:
            raise NotFoundError(f"todo not found: {todo_id}")
        self._send_json(200, self._todos().get(todo_id).to_dict())

    def h_post_todo_handoff(self, todo_id: str) -> None:
        from hermes.workbench.todos import TodoService

        body = self._read_json_body()
        plan = body.get("plan")
        if not isinstance(plan, list):
            raise ValidationError("body must contain 'plan' (JSON array)")
        store = self._todos()
        if store.get(todo_id) is None:
            raise NotFoundError(f"todo not found: {todo_id}")
        try:
            job_id = TodoService(store).hand_off(
                todo_id,
                plan,
                project=body.get("project", "default"),
                priority=body.get("priority", 5),
                timeout=body.get("timeout"),
            )
        except ValueError as e:
            raise ValidationError(str(e)) from e
        self._send_json(200, {"todo_id": todo_id, "job_id": job_id})

    def h_delete_todo(self, todo_id: str) -> None:
        ok = self._todos().delete(todo_id)
        if not ok:
            raise NotFoundError(f"todo not found: {todo_id}")
        self._send_no_content()

    def h_post_inbox(self) -> None:
        """Route a capture: todo + notes markdown + async summary job.

        Body: {"title", "type": idea|link|fact|todo, "url"?, "source"?,
               "due"?}. See :class:`CaptureService`.
        """
        from hermes.workbench.capture import CaptureService
        from hermes.workbench.cli import _make_notes_dir, _make_todo_store

        body = self._read_json_body()
        if not isinstance(body, dict) or not body.get("title"):
            raise ValidationError("body must contain 'title'")
        type_ = str(body.get("type", "idea"))
        if type_ not in ("idea", "link", "fact", "todo"):
            raise ValidationError(f"invalid capture type: {type_}")
        result = CaptureService(
            _make_todo_store(), _make_notes_dir()
        ).capture(
            title=str(body["title"]),
            type_=type_,
            url=body.get("url"),
            source=body.get("source", "inbox"),
            due=body.get("due"),
        )
        self._send_json(201, result)

    def h_get_notes_summary(self) -> None:
        """Return a lightweight vault index summary."""
        from hermes.workbench.cli import _make_notes_dir, _make_todo_store
        from hermes.workbench.notes import NotesStore

        notes = NotesStore(_make_notes_dir())
        todos = _make_todo_store().list()
        self._send_json(200, {"notes": notes.summary(), "inbox_todos": len(todos)})


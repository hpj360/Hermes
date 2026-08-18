"""P0.5: Capture pipeline — route inbox entries and schedule summary jobs.

One endpoint (``POST /wb/inbox``) handles every capture type (PRD §4.2):

* ``todo``  → persisted to the TodoStore only.
* ``idea`` / ``fact`` → persisted to the TodoStore **and** written to the
  notes vault (``HERMES_NOTES_DIR``) as markdown.
* ``link`` → persisted + written to notes + an **async summary job** is
  submitted (best-effort). The summary job is a background agent run that
  reads the URL and stores a summary episode; if it fails it lands in the
  "needs attention" view for manual retry instead of losing the entry.

The sync part (TodoStore write + notes markdown) is fail-safe: an exception
during the async summary submission never drops the capture itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hermes.workbench.todos import Todo, TodoStore

__all__ = ["CaptureService", "SUMMARY_PLAN"]


# Plan for the background summary job. ``summarize`` is a prompt/shell skill
# that reads a URL and produces a summary; execution is best-effort.
SUMMARY_PLAN = [{"skill": "summarize", "args": ["{url}"]}]


class CaptureService:
    """Routes a capture through todo store, notes vault and summary job."""

    def __init__(self, todo_store: TodoStore, notes_dir: Path | str) -> None:
        from hermes.workbench.notes import NotesStore

        self.todo_store = todo_store
        self.notes = NotesStore(notes_dir)

    def capture(
        self,
        title: str,
        type_: str = "idea",
        url: str | None = None,
        source: str = "inbox",
        due: str | None = None,
        submit_summary: bool = True,
    ) -> dict[str, Any]:
        """Run the capture pipeline; returns ``{todo, note_path, job_id?}``.

        Raises on TodoStore persistence failure (the entry must not be lost).
        Summary-job submission failures are best-effort and never raise.
        """
        todo = Todo(title=title, type=type_, source=source, due=due)
        self.todo_store.create(todo)

        note_path: Path | None = None
        if type_ in ("idea", "fact", "link"):
            note_path = self.notes.write(
                todo.todo_id,
                title,
                type_=type_,
                body=url or "",
                url=url,
                source=source,
            )

        job_id: str | None = None
        if type_ == "link" and url and submit_summary:
            job_id = self._submit_summary_job(todo, url)

        return {
            "todo": todo.to_dict(),
            "note_path": str(note_path) if note_path else None,
            "job_id": job_id,
        }

    def _submit_summary_job(self, todo: Todo, url: str) -> str | None:
        """Submit the async summary job for a link capture (best-effort)."""
        from hermes.workbench.todos import TodoService

        plan = [{"skill": "summarize", "args": [url]}]
        try:
            return TodoService(self.todo_store).hand_off(todo.todo_id, plan)
        except Exception:  # noqa: BLE001 — summary is best-effort
            return None

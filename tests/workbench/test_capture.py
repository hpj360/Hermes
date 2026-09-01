"""P0.5: capture pipeline tests (notes markdown + summary job)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.workbench.capture import CaptureService
from hermes.workbench.notes import NotesStore, slugify
from hermes.workbench.todos import TodoStore, TodoStatus


@pytest.fixture
def store(tmp_path: Path) -> TodoStore:
    return TodoStore(state_dir=tmp_path / "state")


@pytest.fixture
def notes_dir(tmp_path: Path) -> Path:
    return tmp_path / "notes"


def test_slugify() -> None:
    assert slugify("写一篇关于 勃艮第 的文章!") == "写一篇关于-勃艮第-的文章"
    assert slugify("  ") == "note"


def test_notes_write_creates_markdown(notes_dir: Path) -> None:
    notes = NotesStore(notes_dir)
    path = notes.write("todo-abc", "收藏的链接", type_="link", url="https://example.com/x", body="some text")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "id: todo-abc" in content
    assert "type: link" in content
    assert "原文链接: https://example.com/x" in content
    assert "some text" in content
    assert path.parent.parent.name == "inbox"


def test_notes_idempotent_resolve(notes_dir: Path) -> None:
    notes = NotesStore(notes_dir)
    p1 = notes.write("todo-1", "标题")
    p2 = notes.resolve("todo-1")
    assert p2 is not None
    assert p1 == p2


def test_capture_todo_only(store: TodoStore, notes_dir: Path) -> None:
    svc = CaptureService(store, notes_dir)
    result = svc.capture("买牛奶", type_="todo")
    assert result["note_path"] is None
    assert result["job_id"] is None
    todos = store.list()
    assert len(todos) == 1
    assert todos[0].title == "买牛奶"
    assert todos[0].type == "todo"


def test_capture_idea_writes_note(store: TodoStore, notes_dir: Path) -> None:
    svc = CaptureService(store, notes_dir)
    result = svc.capture("勃艮第新酒的灵感", type_="idea")
    assert result["note_path"] is not None
    assert Path(result["note_path"]).exists()
    assert result["job_id"] is None
    assert len(store.list()) == 1


def test_capture_link_writes_note_and_summary_job(
    store: TodoStore, notes_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U: a link capture writes a note AND submits an async summary job."""
    from hermes.workbench import cli as wb_cli

    monkeypatch.setattr("hermes.workbench.services._state_dir", lambda: notes_dir.parent / "state")
    wb_cli._reset_scheduler_center()
    try:
        svc = CaptureService(store, notes_dir)
        result = svc.capture("一篇好文章", type_="link", url="https://example.com/a")
        assert result["note_path"] is not None
        assert result["job_id"] is not None
        # todo is HANDED_OFF to the summary job
        todo = store.get(result["todo"]["todo_id"])
        assert todo is not None
        assert todo.status == TodoStatus.HANDED_OFF
        assert todo.job_id == result["job_id"]
        # job exists in the shared center store
        center = wb_cli._make_scheduler_center()
        job = center.job_store.get(result["job_id"])
        assert job is not None
    finally:
        wb_cli._reset_scheduler_center()


def test_capture_link_summary_failure_best_effort(
    store: TodoStore, notes_dir: Path
) -> None:
    """U: summary-job failure never drops the note / todo (best-effort)."""
    svc = CaptureService(store, notes_dir)
    # Simulate an unavailable summary job (e.g. missing summarize skill).
    svc._submit_summary_job = lambda todo, url: None  # type: ignore[assignment]
    result = svc.capture("链接不丢", type_="link", url="https://example.com/b")
    assert result["note_path"] is not None
    assert Path(result["note_path"]).exists()
    assert result["job_id"] is None
    assert len(store.list()) >= 1


def test_capture_persists_due_and_source(store: TodoStore, notes_dir: Path) -> None:
    svc = CaptureService(store, notes_dir)
    result = svc.capture("带截止日期", type_="todo", due="2026-09-01", source="feishu")
    todo = store.get(result["todo"]["todo_id"])
    assert todo is not None
    assert todo.due == "2026-09-01"
    assert todo.source == "feishu"

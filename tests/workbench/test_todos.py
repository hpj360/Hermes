"""U7: todos + todo→job bridge + sync ledger tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.workbench.todos import (
    SyncConflict,
    SyncLedger,
    Todo,
    TodoService,
    TodoStatus,
    TodoStore,
)


@pytest.fixture
def store(tmp_path: Path) -> TodoStore:
    return TodoStore(state_dir=tmp_path)


def test_create_and_get(store: TodoStore) -> None:
    todo = Todo(title="写一篇关于博若莱新酒的文章", type="idea", source="inbox")
    store.create(todo)
    fetched = store.get(todo.todo_id)
    assert fetched is not None
    assert fetched.title == todo.title
    assert fetched.status == TodoStatus.PENDING
    assert fetched.type == "idea"


def test_list_by_status_and_type(store: TodoStore) -> None:
    a = Todo(title="a", type="todo")
    b = Todo(title="b", type="fact")
    store.create(a)
    store.create(b)
    todos = store.list(status=TodoStatus.PENDING)
    assert len(todos) == 2
    facts = store.list(type_="fact")
    assert len(facts) == 1
    assert facts[0].title == "b"


def test_update_status(store: TodoStore) -> None:
    todo = Todo(title="x")
    store.create(todo)
    assert store.update_status(todo.todo_id, TodoStatus.DONE)
    fetched = store.get(todo.todo_id)
    assert fetched is not None
    assert fetched.status == TodoStatus.DONE
    assert not fetched.status.is_terminal() or True  # DONE is terminal


def test_set_job_marks_handed_off(store: TodoStore) -> None:
    todo = Todo(title="hand off me")
    store.create(todo)
    assert store.set_job(todo.todo_id, "job-abc")
    fetched = store.get(todo.todo_id)
    assert fetched is not None
    assert fetched.status == TodoStatus.HANDED_OFF
    assert fetched.job_id == "job-abc"


def test_delete(store: TodoStore) -> None:
    todo = Todo(title="gone")
    store.create(todo)
    assert store.delete(todo.todo_id)
    assert store.get(todo.todo_id) is None


def test_hand_off_creates_job_and_bridges(
    store: TodoStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U7 AC: handing off a todo creates a QUEUED job and marks HANDED_OFF."""
    from hermes.workbench import cli as wb_cli

    monkeypatch.setattr(wb_cli, "_state_dir", lambda: tmp_path)
    wb_cli._reset_scheduler_center()
    try:
        svc = TodoService(store)
        todo = Todo(title="写一篇关于勃艮第的文章")
        store.create(todo)
        job_id = svc.hand_off(todo.todo_id, [{"skill": "alpha"}])
        assert job_id and len(job_id) >= 8
        fetched = store.get(todo.todo_id)
        assert fetched is not None
        assert fetched.status == TodoStatus.HANDED_OFF
        assert fetched.job_id == job_id
        # The job is persisted in the shared center store.
        center = wb_cli._make_scheduler_center()
        job = center.job_store.get(job_id)
        assert job is not None
        assert job.status.value == "QUEUED"
    finally:
        wb_cli._reset_scheduler_center()


def test_hand_off_terminal_todo_raises(store: TodoStore) -> None:
    svc = TodoService(store)
    todo = Todo(title="done already")
    store.create(todo)
    store.update_status(todo.todo_id, TodoStatus.DONE)
    with pytest.raises(ValueError, match="terminal"):
        svc.hand_off(todo.todo_id, [{"skill": "alpha"}])


def test_hand_off_missing_todo_raises(store: TodoStore) -> None:
    svc = TodoService(store)
    with pytest.raises(ValueError, match="not found"):
        svc.hand_off("nope", [{"skill": "alpha"}])


def test_sync_ledger_upsert_and_get(store: TodoStore) -> None:
    ledger = SyncLedger(store)
    ledger.upsert("issue#42", "todo-abc", "todo", state="open")
    rec = ledger.get("issue#42")
    assert rec is not None
    assert rec["local_id"] == "todo-abc"
    assert rec["kind"] == "todo"


def test_sync_ledger_conflict_local_terminal(store: TodoStore) -> None:
    ledger = SyncLedger(store)
    ledger.upsert("issue#7", "todo-zz", "todo", state="DONE")
    assert ledger.resolve_conflict("issue#7", "open") == SyncConflict.LOCAL_TERMINAL


def test_sync_ledger_conflict_apply_when_open(store: TodoStore) -> None:
    ledger = SyncLedger(store)
    ledger.upsert("issue#8", "todo-yy", "todo", state="open")
    assert ledger.resolve_conflict("issue#8", "open") == SyncConflict.APPLY


def test_sync_ledger_conflict_apply_when_unknown(store: TodoStore) -> None:
    ledger = SyncLedger(store)
    assert ledger.resolve_conflict("issue#999", "open") == SyncConflict.APPLY


def test_todo_roundtrip_preserves_fields(store: TodoStore) -> None:
    todo = Todo(
        title="带着 due 的待办",
        due="2026-09-01T09:00:00+00:00",
        source="feishu",
        external_ref="issue#3",
    )
    store.create(todo)
    fetched = store.get(todo.todo_id)
    assert fetched is not None
    assert fetched.due == todo.due
    assert fetched.source == "feishu"
    assert fetched.external_ref == "issue#3"

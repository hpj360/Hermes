"""Tests for GitHub sync ↔ SyncLedger integration (C2, PRD 4.3)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.workbench.cli import TaskRegistry, TaskStore
from hermes.workbench.github_sync import GitHubClient, GitHubSyncService
from hermes.workbench.todos import SyncLedger, TodoStore


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(state_dir=tmp_path)


@pytest.fixture
def registry() -> TaskRegistry:
    return TaskRegistry()


@pytest.fixture
def ledger(tmp_path: Path) -> SyncLedger:
    return SyncLedger(TodoStore(state_dir=tmp_path / "state"))


@pytest.fixture
def service(store, registry, ledger) -> GitHubSyncService:
    return GitHubSyncService(
        client=GitHubClient(token="t", repo="o/r"),
        scheduler=MagicMock(),
        store=store,
        registry=registry,
        ledger=ledger,
    )


def _monkeypatch_issues(service: GitHubSyncService, issues: list[dict]) -> None:
    service.client.list_issues = (  # type: ignore[assignment]
        lambda label="workbench", state="open": issues
    )


def test_pull_records_issue_in_ledger(service, ledger) -> None:
    _monkeypatch_issues(
        service,
        [{"number": 1, "body": '{"plan": [{"skill": "weather"}]}'}],
    )
    created = service.pull_issues()
    assert len(created) == 1
    rec = ledger.get("gh#1")
    assert rec is not None
    assert rec["local_id"] == created[0]["task_id"]
    assert rec["kind"] == "task"


def test_pull_skips_already_linked_issue(service, ledger) -> None:
    ledger.upsert("gh#1", "task-existing", kind="task", state="open")
    _monkeypatch_issues(
        service,
        [{"number": 1, "body": '{"plan": [{"skill": "weather"}]}'}],
    )
    skipped: list[int] = []
    created = service.pull_issues(skipped=skipped)
    assert created == []
    assert skipped == [1]


def test_pull_does_not_revert_terminal_local(service, ledger) -> None:
    """A locally-terminal issue must not be re-pulled (PRD 4.3)."""
    ledger.upsert("gh#1", "task-done", kind="task", state="DONE")
    _monkeypatch_issues(
        service,
        [{"number": 1, "body": '{"plan": [{"skill": "weather"}]}'}],
    )
    assert service.pull_issues() == []
    # ledger state preserved (not reverted to open)
    assert ledger.get("gh#1")["state"] == "DONE"


def test_push_result_updates_ledger_state(service, ledger, store) -> None:
    from hermes.workbench.cli import Task

    task = Task(task_id="t-1", plan=[{"skill": "weather"}], mode="oneshot")
    task.status = "SUCCEEDED"
    store.save(task)
    ledger.upsert("gh#5", "t-1", kind="task", state="open")
    service.client.create_comment = lambda n, b: {"id": 1}  # type: ignore[assignment]

    service.push_result("t-1", 5)
    assert ledger.get("gh#5")["state"] == "SUCCEEDED"


def test_sync_counts_skipped(service, ledger) -> None:
    ledger.upsert("gh#1", "task-existing", kind="task", state="open")
    _monkeypatch_issues(
        service,
        [
            {"number": 1, "body": '{"plan": [{"skill": "weather"}]}'},  # skipped
            {"number": 2, "body": '{"plan": [{"skill": "summarize"}]}'},  # new
        ],
    )
    result = service.sync()
    assert result["skipped"] == 1
    assert result["pulled"] == 1

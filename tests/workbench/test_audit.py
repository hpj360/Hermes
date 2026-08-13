"""Tests for hermes.workbench.audit (persistent audit trail)."""

from __future__ import annotations

from pathlib import Path

from hermes.workbench.audit import AuditRecord, AuditStore


def _make_store(tmp_path: Path) -> AuditStore:
    return AuditStore(state_dir=tmp_path / "state")


def test_record_appends_and_persists(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.record("github", "get_pr", True, args={"pr_number": 1})
    store.record("github", "create_pr", False, args={"head": "a"}, error="boom")

    records = store.list()
    assert len(records) == 2
    assert records[0].method == "get_pr"
    assert records[0].success is True
    assert records[1].method == "create_pr"
    assert records[1].success is False
    assert records[1].error == "boom"


def test_persists_across_instances(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.record("github", "get_issue", True, args={"issue_number": 3})

    store2 = _make_store(tmp_path)
    records = store2.list()
    assert len(records) == 1
    assert records[0].method == "get_issue"


def test_tail_returns_last_n(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    for i in range(10):
        store.record("github", f"method_{i}", True)
    tail = store.tail(n=3)
    assert [r.method for r in tail] == ["method_7", "method_8", "method_9"]


def test_filter_by_server(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    store.record("github", "get_pr", True)
    store.record("notion", "create_page", True)
    github = store.list(server="github")
    assert len(github) == 1
    assert github[0].server == "github"


def test_empty_store_returns_empty(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    assert store.list() == []
    assert store.tail() == []


def test_audit_record_roundtrip(tmp_path: Path) -> None:
    rec = AuditRecord(
        server="github", method="get_pr", success=True, args={"pr_number": 42}
    )
    restored = AuditRecord.from_dict(rec.to_dict())
    assert restored.server == "github"
    assert restored.method == "get_pr"
    assert restored.args == {"pr_number": 42}
    assert restored.record_id == rec.record_id

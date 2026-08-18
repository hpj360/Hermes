"""U1b: gateway tests.

Uses FastAPI TestClient against the unified gateway. The scheduler center is
reset per test and pointed at a tmp state dir; a fake router replaces the
default one so no real skills directory is required.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.workbench import cli as wb_cli
from hermes.workbench.gateway import create_app


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wb_cli, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(wb_cli, "_make_notes_dir", lambda: tmp_path / "notes")
    wb_cli._reset_scheduler_center()
    center = wb_cli._make_scheduler_center()

    mock_runtime = MagicMock()
    mock_scheduler = MagicMock()
    mock_scheduler.run.return_value = None
    mock_runtime.scheduler.return_value = mock_scheduler
    mock_router = MagicMock()
    mock_router.resolve.return_value = mock_runtime
    mock_router.try_acquire.return_value = True
    mock_router.release.return_value = None
    center.router = mock_router

    from fastapi.testclient import TestClient

    gateway = create_app()
    with TestClient(gateway) as client:
        yield client
    wb_cli._reset_scheduler_center()


def test_gateway_health(app) -> None:
    resp = app.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "scheduler" in data["services"]


def test_gateway_skills_list(app) -> None:
    resp = app.get("/wb/skills")
    assert resp.status_code == 200
    assert "skills" in resp.json()


def test_gateway_todos_crud(app) -> None:
    resp = app.post("/wb/todos", json={"title": "网关测试待办", "type": "todo"})
    assert resp.status_code == 201
    todo = resp.json()
    todo_id = todo["todo_id"]

    resp = app.get("/wb/todos")
    assert resp.status_code == 200
    assert any(t["todo_id"] == todo_id for t in resp.json()["todos"])

    resp = app.post(f"/wb/todos/{todo_id}/status", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "DONE"


def test_gateway_job_submit_and_execute(app) -> None:
    resp = app.post("/wb/jobs", json={"plan": [{"skill": "alpha"}]})
    assert resp.status_code == 201
    job = resp.json()
    job_id = job["job_id"]

    # The gateway lifespan started the worker pool; the job should reach a
    # terminal state shortly after submission.
    import time

    deadline = time.time() + 5.0
    final = None
    while time.time() < deadline:
        resp = app.get(f"/wb/jobs/{job_id}")
        final = resp.json()
        if final.get("status") in ("SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"):
            break
        time.sleep(0.1)
    assert final is not None
    assert final["status"] == "SUCCEEDED"


def test_gateway_auth_blocks_without_token(app, monkeypatch: pytest.MonkeyPatch) -> None:
    """U1b/D3: with a token configured, /wb/* and /api/* require Bearer."""

    class FakeSettings:
        hermes_api_token = "gateway-secret"
        openclaw_gateway_token = None

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    from hermes.workbench.gateway import create_app as build
    from fastapi.testclient import TestClient

    with TestClient(build()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/wb/skills").status_code == 401
        r = client.get("/wb/skills", headers={"Authorization": "Bearer gateway-secret"})
        assert r.status_code == 200


def test_gateway_handoff_bridges_todo_to_job(app) -> None:
    resp = app.post("/wb/todos", json={"title": "派给 agent"})
    todo = resp.json()
    resp = app.post(
        f"/wb/todos/{todo['todo_id']}/hand-off",
        json={"plan": [{"skill": "alpha"}]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"]

    resp = app.get(f"/wb/todos/{todo['todo_id']}")
    assert resp.json()["status"] == "HANDED_OFF"


def test_gateway_inbox_todo_capture(app) -> None:
    """P0.5: POST /wb/inbox routes a todo capture (no notes, no summary job)."""
    resp = app.post("/wb/inbox", json={"title": "收件箱待办", "type": "todo"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["note_path"] is None
    assert data["job_id"] is None

    resp = app.get("/wb/todos")
    assert any(t["title"] == "收件箱待办" for t in resp.json()["todos"])


def test_gateway_inbox_link_capture(app, tmp_path: Path) -> None:
    """P0.5: a link capture writes a notes markdown entry + submits a job."""
    resp = app.post(
        "/wb/inbox",
        json={"title": "收藏的文章", "type": "link", "url": "https://example.com/a"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["todo"]["type"] == "link"
    assert data["job_id"]  # summary job submitted
    assert data["note_path"] is not None
    note = Path(data["note_path"])
    assert note.exists()
    assert "收藏的文章" in note.read_text(encoding="utf-8")


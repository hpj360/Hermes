"""C4 observability: GET /wb/llm/usage endpoint."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from hermes.config import get_settings
    from hermes.workbench import cli as wb_cli
    from hermes.workbench.gateway import create_app

    monkeypatch.setenv("HERMES_LLM_DAILY_TOKEN_BUDGET", "100")
    settings = get_settings(force_reload=True)
    ledger = {
        date.today().isoformat(): {
            "prompt_tokens": 30,
            "completion_tokens": 40,
            "calls": 2,
        }
    }
    (settings.hermes_state_dir / "token_usage.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    monkeypatch.setattr(wb_cli, "_state_dir", lambda: settings.hermes_state_dir)
    wb_cli._reset_scheduler_center()
    center = wb_cli._make_scheduler_center()
    mock_router = MagicMock()
    mock_router.resolve.return_value = MagicMock()
    mock_router.try_acquire.return_value = True
    mock_router.release.return_value = None
    center.router = mock_router

    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        yield client
    wb_cli._reset_scheduler_center()


def test_llm_usage_endpoint(app) -> None:
    resp = app.get("/wb/llm/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["limit"] == 100
    assert data["prompt_tokens"] == 30
    assert data["completion_tokens"] == 40
    assert data["total_tokens"] == 70
    assert data["calls"] == 2
    assert data["remaining"] == 30


def test_llm_usage_disabled(app, monkeypatch) -> None:
    from hermes.config import get_settings

    monkeypatch.setenv("HERMES_LLM_DAILY_TOKEN_BUDGET", "0")
    get_settings(force_reload=True)
    resp = app.get("/wb/llm/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["remaining"] is None

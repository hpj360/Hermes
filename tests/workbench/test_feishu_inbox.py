"""C3: Feishu bot inbox tests (parser, service, webhook, CLI parser)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.workbench import cli as wb_cli
from hermes.workbench.capture import CaptureService
from hermes.workbench.feishu_inbox import FeishuInboxService, parse_feishu_event
from hermes.workbench.todos import TodoStore


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

    from hermes.workbench.gateway import create_app

    with TestClient(create_app()) as client:
        yield client
    wb_cli._reset_scheduler_center()


def _event(content: str = "hello", chat_type: str = "p2p", message_id: str = "om_1") -> dict:
    return {
        "event_id": "evt_1",
        "message_id": message_id,
        "chat_id": "oc_x",
        "chat_type": chat_type,
        "content": content,
        "message_type": "text",
        "sender_id": "ou_me",
    }


class TestParse:
    def test_p2p_text_is_todo(self) -> None:
        parsed = parse_feishu_event(_event("写一篇关于勃艮第的笔记"))
        assert parsed is not None
        assert parsed["type"] == "todo"
        assert parsed["title"] == "写一篇关于勃艮第的笔记"
        assert parsed["url"] is None

    def test_p2p_with_url_is_link(self) -> None:
        parsed = parse_feishu_event(_event("看看这篇文章 https://example.com/a"))
        assert parsed is not None
        assert parsed["type"] == "link"
        assert parsed["url"] == "https://example.com/a"
        assert "看看这篇文章" in parsed["title"]

    def test_group_skipped(self) -> None:
        assert parse_feishu_event(_event(chat_type="group")) is None

    def test_empty_content_skipped(self) -> None:
        assert parse_feishu_event(_event(content="  ")) is None


class TestService:
    @pytest.fixture
    def svc(self, tmp_path: Path) -> FeishuInboxService:
        store = TodoStore(state_dir=tmp_path / "state")
        notes = tmp_path / "notes"
        return FeishuInboxService(CaptureService(store, notes))

    def test_ingest_creates_todo(self, svc: FeishuInboxService) -> None:
        result = svc.ingest(_event("记得买酒"))
        assert result is not None
        assert result["todo"]["type"] == "todo"
        assert result["message_id"] == "om_1"
        assert svc.stats()["seen_messages"] == 1

    def test_dedup_same_message(self, svc: FeishuInboxService) -> None:
        assert svc.ingest(_event("x")) is not None
        assert svc.ingest(_event("x")) is None

    def test_ingest_link_captures(self, svc: FeishuInboxService) -> None:
        result = svc.ingest(_event("https://example.com/wine"))
        assert result is not None
        assert result["todo"]["type"] == "link"
        assert result["note_path"] is not None

    def test_ingest_group_skipped(self, svc: FeishuInboxService) -> None:
        assert svc.ingest(_event(chat_type="group")) is None


def test_gateway_webhook_url_verification(app) -> None:
    """C3: /feishu/events echoes the challenge during handshake."""
    resp = app.post("/feishu/events", json={"type": "url_verification", "challenge": "abc123"})
    assert resp.status_code == 200
    assert resp.json()["challenge"] == "abc123"


def test_gateway_webhook_ingests_message(app) -> None:
    """C3: an im.message.receive_v1 event is captured via the webhook."""
    event = {"type": "event_callback", "event": _event("https://example.com/x", message_id="om_9")}
    resp = app.post("/feishu/events", json=event)
    assert resp.status_code == 201
    body = resp.json()
    assert body["skipped"] is False
    assert body["result"]["todo"]["type"] == "link"
    assert body["result"]["message_id"] == "om_9"


def test_gateway_webhook_signature_required_when_token_set(app, monkeypatch: pytest.MonkeyPatch) -> None:
    """C3: with FEISHU_VERIFICATION_TOKEN set, bad/missing signature is 401."""
    import hashlib
    import hmac as _hmac

    from hermes.workbench.gateway import create_app as build
    from fastapi.testclient import TestClient

    class FakeSettings:
        feishu_verification_token = "verify-secret"
        hermes_api_token = None
        openclaw_gateway_token = None

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    with TestClient(build()) as client:
        event = {"type": "event_callback", "event": _event("hello", message_id="om_5")}
        # no signature → 401
        resp = client.post("/feishu/events", json=event)
        assert resp.status_code == 401
        # valid signature → 201
        import json as _json

        raw = _json.dumps(event).encode("utf-8")
        ts, nonce = "1234567890", "nonce1"
        sign = _hmac.new(b"verify-secret", f"{ts}{nonce}{raw.decode('utf-8')}".encode(), hashlib.sha256).hexdigest()
        resp = client.post(
            "/feishu/events",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Lark-Request-Timestamp": ts,
                "X-Lark-Request-Nonce": nonce,
                "X-Lark-Signature": sign,
            },
        )
        assert resp.status_code in (200, 201)


def test_feishu_inbox_command_registered() -> None:
    from hermes.workbench import cli as wb_cli

    import argparse

    parser = argparse.ArgumentParser()
    wb_cli.register_workbench_commands(parser)
    args = parser.parse_args(["workbench", "feishu-inbox", "--max-events", "3", "--timeout", "10s"])
    assert args.func is wb_cli.cmd_workbench_feishu_inbox
    assert args.max_events == 3
    assert args.timeout == "10s"

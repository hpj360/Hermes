"""U9: Feishu notification pipeline tests (contract via fake executor)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.workbench.feishu_notify import (
    DailyBrief,
    DeadLetterStore,
    FeishuClient,
    Notifier,
)


def _fake_executor(responses: list[dict]) -> "object":
    """Build a fake executor returning queued responses as JSON bytes."""

    def exec(req) -> bytes:  # noqa: ANN001
        resp = responses.pop(0)
        return json.dumps(resp).encode("utf-8")

    return exec


def _ok_responses() -> list[dict]:
    return [{"code": 0, "tenant_access_token": "tok-1", "expire": 7200}, {"code": 0}]


def test_token_refresh_and_send(tmp_path: Path) -> None:
    calls: list[dict] = []

    def fake_executor(req) -> bytes:  # noqa: ANN001
        path = str(req.full_url)
        if "auth/v3/tenant_access_token" in path:
            calls.append({"kind": "token"})
            return json.dumps({"code": 0, "tenant_access_token": "tok-9", "expire": 7200}).encode("utf-8")
        calls.append({"kind": "message", "url": path})
        return json.dumps({"code": 0}).encode("utf-8")

    client = FeishuClient("app", "secret", request_executor=fake_executor)
    resp = client.send_text("chat-1", "hello")
    assert resp["code"] == 0
    kinds = [c["kind"] for c in calls]
    assert kinds == ["token", "message"]


def test_token_cached_between_sends(tmp_path: Path) -> None:
    token_calls = {"n": 0}

    def fake_executor(req) -> bytes:  # noqa: ANN001
        if "tenant_access_token" in str(req.full_url):
            token_calls["n"] += 1
            return json.dumps({"code": 0, "tenant_access_token": "t", "expire": 7200}).encode("utf-8")
        return json.dumps({"code": 0}).encode("utf-8")

    client = FeishuClient("app", "secret", request_executor=fake_executor)
    client.send_text("c", "1")
    client.send_text("c", "2")
    assert token_calls["n"] == 1


def test_send_error_raises(tmp_path: Path) -> None:
    def fake_executor(req) -> bytes:  # noqa: ANN001
        return json.dumps({"code": 9499, "msg": "rate limited"}).encode("utf-8")

    client = FeishuClient("app", "secret", request_executor=fake_executor)
    from hermes.workbench.errors import UpstreamError

    with pytest.raises(UpstreamError):
        client.send_text("c", "boom")


def test_daily_brief_silent() -> None:
    assert DailyBrief().is_silent()
    assert not DailyBrief(succeeded=1).is_silent()
    assert not DailyBrief(notes=["x"]).is_silent()


def test_daily_brief_render() -> None:
    brief = DailyBrief(succeeded=2, failed=1, new_memories=3, pending_decisions=1)
    text = brief.render_text()
    assert "完成任务: 2" in text
    assert "失败任务: 1" in text


def test_notifier_silent_brief_not_sent(tmp_path: Path) -> None:
    sent: list[str] = []

    def fake_executor(req) -> bytes:  # noqa: ANN001
        sent.append(str(req.full_url))
        return json.dumps({"code": 0}).encode("utf-8")

    client = FeishuClient("app", "secret", request_executor=fake_executor)
    notifier = Notifier(client, DeadLetterStore(tmp_path), "chat-1")
    assert notifier.send_daily_brief(DailyBrief()) is False
    assert sent == []


def test_notifier_brief_sent_when_activity(tmp_path: Path) -> None:
    sent: list[str] = []

    def fake_executor(req) -> bytes:  # noqa: ANN001
        sent.append(str(req.full_url))
        if "tenant_access_token" in str(req.full_url):
            return json.dumps({"code": 0, "tenant_access_token": "t", "expire": 7200}).encode("utf-8")
        return json.dumps({"code": 0}).encode("utf-8")

    client = FeishuClient("app", "secret", request_executor=fake_executor)
    notifier = Notifier(client, DeadLetterStore(tmp_path), "chat-1")
    assert notifier.send_daily_brief(DailyBrief(succeeded=3)) is True
    assert len(sent) == 2  # token + message


def test_notifier_failure_dead_letter(tmp_path: Path) -> None:
    def fake_executor(req) -> bytes:  # noqa: ANN001
        return json.dumps({"code": 9999, "msg": "down"}).encode("utf-8")

    client = FeishuClient("app", "secret", request_executor=fake_executor, max_retries=1)
    store = DeadLetterStore(tmp_path)
    notifier = Notifier(client, store, "chat-1")
    assert notifier.send_failure("job-1", "oops") is False
    assert store.stats()["dead_letters"] == 1
    items = store.list()
    assert items[0]["subject"] == "job-1"
    assert "down" in items[0]["error"]


def test_dead_letter_clear(tmp_path: Path) -> None:
    store = DeadLetterStore(tmp_path)
    store.record("brief", "chat-1", "s", "e")
    assert store.stats()["dead_letters"] == 1
    assert store.clear() == 1
    assert store.stats()["dead_letters"] == 0


def test_notifier_from_settings_unconfigured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSettings:
        feishu_app_id = None
        feishu_app_secret = None

    monkeypatch.setattr("hermes.config.get_settings", lambda: FakeSettings())
    assert Notifier.from_settings(tmp_path, "chat-1") is None

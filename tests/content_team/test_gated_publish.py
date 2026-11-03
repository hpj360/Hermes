"""C5 Gated 发布流测试：store 幂等裁决 / 卡片构造 / 事件解析 / job 提交 / API 门禁。"""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# GatedPublishStore
# ---------------------------------------------------------------------------


def test_gate_lifecycle_and_idempotency(tmp_path) -> None:
    from hermes.content_team.publish.gated import GatedPublishStore

    store = GatedPublishStore(tmp_path)
    gate = store.create_gate(
        str(uuid.uuid4()), "DOUYIN", {"passed": True, "summary": "合规通过"}
    )
    assert gate.status == "pending"

    resolved, changed = store.resolve(gate.gate_id, "approve", "o_user1")
    assert changed and resolved.status == "approved"
    assert resolved.decided_by == "o_user1"

    # 重复裁决幂等：返回既有结果且不再变更
    again, second_changed = store.resolve(gate.gate_id, "reject", "o_user2")
    assert not second_changed and again.status == "approved"

    assert store.get(gate.gate_id) is not None
    assert store.get("missing") is None

    with pytest.raises(KeyError):
        store.resolve("missing", "approve", "o")


def test_gate_reject_and_receipt(tmp_path) -> None:
    from hermes.content_team.publish.gated import GatedPublishStore

    store = GatedPublishStore(tmp_path)
    gate = store.create_gate("c1", "XIAOHONGSHU", {"passed": False})
    resolved, changed = store.resolve(gate.gate_id, "reject", "o")
    assert changed and resolved.status == "rejected"


# ---------------------------------------------------------------------------
# 卡片构造与事件解析
# ---------------------------------------------------------------------------


def test_build_gate_card_buttons_carry_intent() -> None:
    from hermes.content_team.publish.gated import build_gate_card

    elements = build_gate_card("g1", "测试内容", {"passed": True, "summary": "ok"})
    action_block = next(e for e in elements if e.get("tag") == "action")
    values = [b["value"] for b in action_block["actions"]]
    assert values[0]["gate_id"] == "g1" and values[0]["decision"] == "approve"
    assert values[1]["gate_id"] == "g1" and values[1]["decision"] == "reject"
    assert "测试内容" in elements[0]["text"]["content"]


def test_parse_gate_event_card_and_message_shapes() -> None:
    from hermes.content_team.publish.gated import parse_gate_event

    value = {"gate_action": "publish_gate", "gate_id": "g1", "decision": "approve"}
    card_v2 = {
        "schema": "2.0",
        "header": {"event_type": "card.action.trigger"},
        "event": {"action": {"value": value}, "operator": {"open_id": "ou1"}},
    }
    assert parse_gate_event(card_v2["event"]) == {
        "gate_id": "g1",
        "decision": "approve",
        "operator": "ou1",
    }

    v1 = {
        "type": "card_action_trigger",
        "event": {"action": {"value": value}, "operator": {"union_id": "un1"}},
    }
    assert parse_gate_event(v1["event"]) == {
        "gate_id": "g1",
        "decision": "approve",
        "operator": "un1",
    }

    # 普通消息事件（im.message.receive_v1）不含 action → None
    assert parse_gate_event({"message_type": "text"}) is None
    # 非本方法的卡片 value → None
    other = {"action": {"value": {"other": 1}}}
    assert parse_gate_event(other) is None
    # 非法 decision → None
    bad = {"action": {"value": {**value, "decision": "haha"}}, "operator": {}}
    assert parse_gate_event(bad) is None


# ---------------------------------------------------------------------------
# job 提交
# ---------------------------------------------------------------------------


def test_submit_publish_job_enqueues_to_center(monkeypatch, tmp_path) -> None:
    from hermes.content_team import scheduler as ct_sched
    from hermes.content_team.publish.gated import submit_publish_job
    from hermes.workbench.scheduler import JobStatus

    saved: list = []
    queued: list = []

    class _Store:
        def save(self, job) -> None:
            saved.append(job)

    class _Queue:
        def put(self, job) -> None:
            queued.append(job)

    monkeypatch.setattr(
        ct_sched,
        "get_scheduler",
        lambda: {"store": _Store(), "queue": _Queue()},
    )
    job_id = submit_publish_job("c-uuid", "DOUYIN", ["acc-1"])
    assert job_id
    assert len(saved) == 1 and len(queued) == 1
    job = saved[0]
    assert job.status == JobStatus.QUEUED
    assert job.target_project == "content-team"
    assert job.task.goal["type"] == "publish"
    assert job.task.goal["payload"]["platform_account_ids"] == ["acc-1"]


# ---------------------------------------------------------------------------
# API 门禁端点
# ---------------------------------------------------------------------------


async def test_create_publish_gate_endpoint(client, monkeypatch, tmp_path) -> None:
    from hermes.content_team.publish import gated as gated_mod

    monkeypatch.setattr(gated_mod, "gated_store_dir", lambda: str(tmp_path))
    # 第一次调用（已配置）返回发送成功；之后回退真实实现（测试环境未配置飞书）
    real_send = gated_mod.try_send_gate_card
    calls = {"n": 0}

    def _send_stub(elements, title):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, ""
        return real_send(elements, title)

    monkeypatch.setattr(gated_mod, "try_send_gate_card", _send_stub)

    created = await client.post(
        "/api/content",
        json={"title": "发布确认测试", "body": "正文", "content_type": "article"},
    )
    assert created.status_code == 201
    content_id = created.json()["id"]

    resp = await client.post(
        "/api/publish/gate",
        json={
            "content_id": content_id,
            "platform": "DOUYIN",
            "title": "发布确认测试",
            "checklist": {"passed": True, "summary": "合规通过"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["sent"] is True
    assert data["platform"] == "DOUYIN"
    assert data["card_elements"], "应包含可渲染的卡片 elements"

    # 未配置飞书 → 不发送但门禁照常创建
    resp2 = await client.post(
        "/api/publish/gate",
        json={
            "content_id": content_id,
            "platform": "BILIBILI",
            "title": "发布确认测试",
        },
    )
    assert resp2.status_code == 200
    assert resp2.json()["sent"] is False
    assert "feishu not configured" in resp2.json()["send_reason"]

    # 不存在的内容 → 404
    resp3 = await client.post(
        "/api/publish/gate",
        json={
            "content_id": str(uuid.uuid4()),
            "platform": "DOUYIN",
            "title": "不校验",
        },
    )
    assert resp3.status_code == 404

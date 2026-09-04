"""Tests for P2 轮内 steering（orchestrator.py SteeringController + fan_in）.

覆盖：SteeringCommand 校验、SteeringController 队列语义（FIFO / 多 key
优先级 / role 广播键）、fan_in steering 路径（中途纠偏消息送达、stop
提前止损保留部分结果、正常完成等价性、超时降级）。
"""

from __future__ import annotations

from typing import Any

import pytest

import hermes.orchestrator as orch_module
from hermes.orchestrator import (
    AgentTask,
    Orchestrator,
    SteeringCommand,
    SteeringController,
)


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """轮询间隔缩到 10ms，steering 测试毫秒级完成。"""
    monkeypatch.setattr(orch_module, "STEERING_POLL_INTERVAL", 0.01)


# ---------------------------------------------------------------------------
# SteeringCommand / SteeringController 单元
# ---------------------------------------------------------------------------


def test_steering_command_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="invalid steering action"):
        SteeringCommand(action="explode")


def test_controller_fifo_and_pop_order() -> None:
    c = SteeringController()
    c.steer("s1", "先跑 mypy")
    c.steer("s1", "再跑 ruff")
    c.stop("s1", reason="方向错了")

    cmd = c.pop("s1")
    assert cmd is not None and cmd.action == "message" and cmd.text == "先跑 mypy"
    cmd = c.pop("s1")
    assert cmd is not None and cmd.text == "再跑 ruff"
    cmd = c.pop("s1")
    assert cmd is not None and cmd.action == "stop" and cmd.reason == "方向错了"
    assert c.pop("s1") is None


def test_controller_pop_multi_key_priority() -> None:
    """session_id 精确键优先于 role 广播键。"""
    c = SteeringController()
    c.steer(SteeringController.role_key("builder"), "广播纠偏")
    c.steer("sess-1", "精确纠偏")

    cmd = c.pop("sess-1", SteeringController.role_key("builder"))
    assert cmd is not None and cmd.text == "精确纠偏"
    cmd = c.pop("sess-1", SteeringController.role_key("builder"))
    assert cmd is not None and cmd.text == "广播纠偏"


def test_controller_empty_queue_returns_none() -> None:
    assert SteeringController().pop("any") is None


# ---------------------------------------------------------------------------
# fan_in steering 路径（FakeClient）
# ---------------------------------------------------------------------------


class FakeClient:
    """可控的网关替身：按脚本推进 session 状态。"""

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self._script = list(script)  # 每次 check_session 弹出一帧
        self.sent: list[str] = []
        self.messages: list[dict[str, Any]] = []

    def check_session(self, session_id: str) -> dict[str, Any] | None:
        if not self._script:
            return {"status": "completed", "tokens_used": 100}
        return self._script.pop(0)

    def wait_for_completion(
        self, session_id: str, timeout: float = 300.0, poll_interval: float = 5.0
    ) -> dict[str, Any] | None:
        return {"status": "completed", "tokens_used": 100}

    def send_message(self, session_id: str, message: str) -> bool:
        self.sent.append(message)
        return True

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self.messages


def _task(session_id: str = "sess-1") -> AgentTask:
    t = AgentTask(role="builder", task_description="do stuff")
    t.session_id = session_id
    t.status = "running"
    return t


def test_fan_in_steering_delivers_message_then_completes() -> None:
    # 3 帧 running，之后 completed——第 2 帧 poll 间隙送达纠偏消息
    client = FakeClient(
        script=[
            {"status": "running"},
            {"status": "running"},
            {"status": "running"},
        ]
    )
    client.messages = [
        {"role": "assistant", "content": "done with correction applied"}
    ]
    orch = Orchestrator(client=client)  # type: ignore[arg-type]
    steering = SteeringController()
    steering.steer("sess-1", "改用 pytest -k fast 先跑")

    task = _task()
    orch.fan_in([task], timeout=5.0, steering=steering)

    assert client.sent == ["改用 pytest -k fast 先跑"]
    assert task.status == "completed"
    assert task.result == "done with correction applied"


def test_fan_in_steering_stop_preserves_partial_result() -> None:
    client = FakeClient(script=[{"status": "running"}, {"status": "running"}])
    client.messages = [
        {"role": "assistant", "content": "已完成 60%：测试文件已重构"}
    ]
    orch = Orchestrator(client=client)  # type: ignore[arg-type]
    steering = SteeringController()
    steering.stop("sess-1", reason="预算告急")

    task = _task()
    orch.fan_in([task], timeout=5.0, steering=steering)

    assert task.status == "stopped"
    assert "STOPPED BY STEERING: 预算告急" in (task.result or "")
    assert "已完成 60%" in (task.result or "")  # 部分结果保留
    assert task.tokens_used == 0


def test_fan_in_steering_role_broadcast_key() -> None:
    """派发前用 role 广播键下达的指令，fan_in 也能消费。"""
    client = FakeClient(script=[{"status": "running"}])
    client.messages = [{"role": "assistant", "content": "ok"}]
    orch = Orchestrator(client=client)  # type: ignore[arg-type]
    steering = SteeringController()
    steering.stop(SteeringController.role_key("builder"), reason="取消")

    task = _task()
    orch.fan_in([task], timeout=5.0, steering=steering)
    assert task.status == "stopped"


def test_fan_in_steering_timeout_degrades_to_failed() -> None:
    # 一直 running，deadline 到 → 与原路径一致的 failed 语义
    client = FakeClient(script=[{"status": "running"}] * 100)
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _task()
    orch.fan_in([task], timeout=0.3, steering=SteeringController())
    assert task.status == "failed"
    assert "Timeout" in (task.result or "")


def test_fan_in_steering_gateway_error_keeps_polling() -> None:
    """单次探测失败（网关瞬断）不立即放弃，最终完成。"""
    client = FakeClient(
        script=[None, None, {"status": "completed", "tokens_used": 10}]
    )
    client.messages = [{"role": "assistant", "content": "survived"}]
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _task()
    orch.fan_in([task], timeout=5.0, steering=SteeringController())
    assert task.status == "completed"
    assert task.result == "survived"


def test_fan_in_without_steering_unchanged_path() -> None:
    """steering=None 走原阻塞路径（wait_for_completion），行为不变。"""
    client = FakeClient(script=[])
    client.messages = [{"role": "assistant", "content": "legacy path"}]
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _task()
    orch.fan_in([task], timeout=5.0)  # type: ignore[call-overload]
    assert task.status == "completed"


def test_orchestrator_steer_direct_send() -> None:
    client = FakeClient(script=[])
    orch = Orchestrator(client=client)  # type: ignore[arg-type]
    task = _task()
    assert orch.steer(task, "立即纠偏") is True
    assert client.sent == ["立即纠偏"]

    # 未派发（无 session_id）的任务无法 steering
    unspawned = AgentTask(role="builder")
    assert orch.steer(unspawned, "x") is False

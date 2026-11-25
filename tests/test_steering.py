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
    WatchdogConfig,
    _last_action_fingerprint,
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


# ---------------------------------------------------------------------------
# P0：并行 fan_in 不再串行阻塞
# ---------------------------------------------------------------------------


class MultiSessionClient:
    """按 session 分别推进状态的网关替身。

    旧实现逐个 task 串行等待，单 session 脚本无法表达「A 长跑、B 可被
    立即止损」的时序，因此这里按 session_id 分桶。
    """

    def __init__(
        self,
        scripts: dict[str, list[dict[str, Any] | None]],
        messages: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._messages = messages or {}
        self.sent: list[tuple[str, str]] = []
        self.checks: list[str] = []
        self.message_probes: list[str] = []

    def check_session(self, session_id: str) -> dict[str, Any] | None:
        self.checks.append(session_id)
        queue = self._scripts.get(session_id) or []
        if not queue:
            return {"status": "completed", "tokens_used": 10}
        return queue.pop(0)

    def wait_for_completion(
        self, session_id: str, timeout: float = 300.0, poll_interval: float = 5.0
    ) -> dict[str, Any] | None:
        return {"status": "completed", "tokens_used": 10}

    def send_message(self, session_id: str, message: str) -> bool:
        self.sent.append((session_id, message))
        return True

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        self.message_probes.append(session_id)
        return self._messages.get(session_id, [])


def _running_task(role: str, session_id: str) -> AgentTask:
    t = AgentTask(role=role, task_description="work")
    t.session_id = session_id
    t.status = "running"
    return t


def test_parallel_stop_is_applied_without_waiting_for_earlier_task() -> None:
    """P0 回归：B 的 stop 必须在下一次轮询就生效，不能等 A 跑完。

    判据用收集顺序而非最终状态——旧实现里 B 最终也会被 stop，只是被
    排在 A 超时之后，最终状态无法区分两种实现。
    """
    client = MultiSessionClient(
        {
            "sess-a": [{"status": "running"}] * 5000,  # 一直不完成
            "sess-b": [{"status": "running"}] * 5000,
        }
    )
    orch = Orchestrator(client=client)  # type: ignore[arg-type]
    steering = SteeringController()
    steering.stop("sess-b", reason="方向错了")

    order: list[str] = []
    original = orch._collect_task_result

    def spy(task: AgentTask, result: Any, stop_reason: str = "") -> None:
        order.append(task.role)
        original(task, result, stop_reason=stop_reason)

    orch._collect_task_result = spy  # type: ignore[method-assign]

    tasks = [_running_task("builder", "sess-a"), _running_task("checker", "sess-b")]
    orch.fan_in(tasks, timeout=0.2, steering=steering)

    assert order == ["checker", "builder"], f"B 应被优先止损，实际顺序 {order}"
    assert tasks[0].status == "failed"  # A 超时
    assert tasks[1].status == "stopped"
    assert "方向错了" in (tasks[1].result or "")


def test_parallel_poll_probes_every_pending_session_each_round() -> None:
    """一趟轮询应覆盖所有 pending session，而不是只盯第一个。"""
    client = MultiSessionClient(
        {
            "s1": [{"status": "running"}] * 3,
            "s2": [{"status": "running"}] * 3,
            "s3": [{"status": "running"}] * 3,
        }
    )
    orch = Orchestrator(client=client)  # type: ignore[arg-type]
    tasks = [
        _running_task("a", "s1"),
        _running_task("b", "s2"),
        _running_task("c", "s3"),
    ]

    orch.fan_in(tasks, timeout=5.0, steering=SteeringController())

    assert all(t.status == "completed" for t in tasks)
    # 前 3 轮每个 session 各被探测一次
    for sid in ("s1", "s2", "s3"):
        assert client.checks.count(sid) >= 3


def test_message_steering_still_delivered_in_parallel_path() -> None:
    """并行路径下 message 指令仍按 session 精确投递。"""
    client = MultiSessionClient(
        {"s1": [{"status": "running"}] * 2, "s2": [{"status": "running"}] * 4}
    )
    client._messages = {
        "s1": [{"role": "assistant", "content": "s1 done"}],
        "s2": [{"role": "assistant", "content": "s2 done"}],
    }
    orch = Orchestrator(client=client)  # type: ignore[arg-type]
    steering = SteeringController()
    steering.steer("s2", "先跑快速用例")

    tasks = [_running_task("a", "s1"), _running_task("b", "s2")]
    orch.fan_in(tasks, timeout=5.0, steering=steering)

    assert client.sent == [("s2", "先跑快速用例")]


# ---------------------------------------------------------------------------
# P1：轮内 Watchdog（连续相同动作）
# ---------------------------------------------------------------------------


def _tool_msg(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": args}}],
    }


def test_fingerprint_ignores_plain_text_messages() -> None:
    assert _last_action_fingerprint([{"role": "assistant", "content": "思考中"}]) is None


def test_fingerprint_distinguishes_arguments() -> None:
    a = _last_action_fingerprint([_tool_msg("Bash", {"cmd": "pytest"})])
    b = _last_action_fingerprint([_tool_msg("Bash", {"cmd": "ruff check"})])
    assert a is not None and b is not None and a != b


def test_watchdog_stops_on_repeated_identical_action() -> None:
    repeated = [_tool_msg("Bash", {"cmd": "pytest tests/x.py"})]
    client = MultiSessionClient(
        {"s1": [{"status": "running"}] * 100}, messages={"s1": repeated}
    )
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _running_task("builder", "s1")
    orch.fan_in([task], timeout=5.0, watchdog=WatchdogConfig(repeat_threshold=3))

    assert task.status == "stopped"
    assert "watchdog" in (task.result or "")
    assert "连续 3 次相同动作" in (task.result or "")


def test_watchdog_ignores_changing_actions() -> None:
    """动作变化不触发，最终按超时失败（证明不是「有工具调用就杀」）。"""
    counter = {"n": 0}

    class ChangingClient(MultiSessionClient):
        def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
            counter["n"] += 1
            return [_tool_msg("Bash", {"cmd": f"step-{counter['n']}"})]

    client = ChangingClient({"s1": [{"status": "running"}] * 5000})
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _running_task("builder", "s1")
    orch.fan_in([task], timeout=0.15, watchdog=WatchdogConfig(repeat_threshold=3))

    assert task.status == "failed"
    assert "Timeout" in (task.result or "")


def test_watchdog_threshold_zero_disables_detection() -> None:
    repeated = [_tool_msg("Bash", {"cmd": "loop"})]
    client = MultiSessionClient(
        {"s1": [{"status": "running"}] * 5000}, messages={"s1": repeated}
    )
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _running_task("builder", "s1")
    orch.fan_in([task], timeout=0.1, watchdog=WatchdogConfig(repeat_threshold=0))

    assert task.status == "failed"
    assert "watchdog" not in (task.result or "")


def test_human_stop_wins_over_watchdog() -> None:
    """同时命中时，止损理由应来自人的 steering，而不是自动判定。"""
    repeated = [_tool_msg("Bash", {"cmd": "loop"})]
    client = MultiSessionClient(
        {"s1": [{"status": "running"}] * 100}, messages={"s1": repeated}
    )
    orch = Orchestrator(client=client)  # type: ignore[arg-type]
    steering = SteeringController()
    steering.stop("s1", reason="人工判定走偏")

    task = _running_task("builder", "s1")
    orch.fan_in(
        [task], timeout=5.0, steering=steering, watchdog=WatchdogConfig()
    )

    assert task.status == "stopped"
    assert "人工判定走偏" in (task.result or "")
    assert "watchdog" not in (task.result or "")


def test_watchdog_probe_failure_does_not_kill_task() -> None:
    """观测失败按无信号处理：不能因网关抖动把正常任务判死。"""

    class FlakyProbeClient(MultiSessionClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.failures = 2  # 前两次探测抖动，之后恢复

        def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
            if self.failures > 0:
                self.failures -= 1
                raise RuntimeError("gateway hiccup")
            return super().get_session_messages(session_id)

    client = FlakyProbeClient({"s1": [{"status": "running"}] * 4})
    client._messages = {"s1": [{"role": "assistant", "content": "done"}]}
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _running_task("builder", "s1")
    orch.fan_in([task], timeout=5.0, watchdog=WatchdogConfig())

    assert task.status == "completed"
    assert task.result == "done"


def test_watchdog_does_not_fire_after_completion() -> None:
    """已完成的 session 直接收集，不再做重复动作判定。

    ``get_session_messages`` 仍会被调用一次——那是收集结果，不是 watchdog。
    """
    repeated = [_tool_msg("Bash", {"cmd": "loop"})]
    client = MultiSessionClient(
        {"s1": [{"status": "completed", "tokens_used": 42}]}, messages={"s1": repeated}
    )
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _running_task("builder", "s1")
    orch.fan_in([task], timeout=5.0, watchdog=WatchdogConfig(repeat_threshold=1))

    assert task.status == "completed"
    assert client.message_probes == ["s1"]  # 仅收集那一次


def test_fan_in_without_steering_or_watchdog_uses_blocking_path() -> None:
    """两个可选参数都为 None 时行为不变（不进入轮询路径）。"""
    client = MultiSessionClient({"s1": [{"status": "running"}] * 100})
    orch = Orchestrator(client=client)  # type: ignore[arg-type]

    task = _running_task("builder", "s1")
    orch.fan_in([task], timeout=5.0)

    assert task.status == "completed"
    assert client.checks == []  # 走 wait_for_completion，不调 check_session

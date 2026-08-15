"""P1-1 修复：content_team 定时任务执行运行时测试。

不依赖真实数据库；通过 monkeypatch 验证 ``execute_content_team_task`` /
``ContentTeamTaskScheduler.run_with_task`` 正确按 ``task.goal.type`` 分发到
publish / collect 分支，并把失败转化为结构化错误。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes.content_team import runtime as rt


def _task(goal: dict) -> SimpleNamespace:
    return SimpleNamespace(task_id="t", goal=goal)


def test_execute_dispatch_unknown_type() -> None:
    result = rt.execute_content_team_task(_task({"type": "unknown"}))
    assert result["ok"] is False
    assert "unknown" in result["error"]


def test_run_with_task_publish_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """publish 分支调用 PublishDispatcher.dispatch（monkeypatch 掉 IO）。"""
    captured: dict = {}

    async def fake_run_publish(payload):
        captured["payload"] = payload
        return {"ok": True, "published": 1}

    monkeypatch.setattr(rt, "_run_publish", fake_run_publish)
    result = rt.execute_content_team_task(
        _task({"type": "publish", "payload": {"content_id": "42", "platform": "X"}})
    )
    assert result["ok"] is True
    assert captured["payload"]["content_id"] == "42"


def test_run_with_task_collect_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_run_collect(payload):
        captured["called"] = True
        return {"ok": True, "collected": 3}

    monkeypatch.setattr(rt, "_run_collect", fake_run_collect)
    result = rt.execute_content_team_task(_task({"type": "collect", "payload": {}}))
    assert result["ok"] is True
    assert captured["called"] is True


def test_scheduler_run_raises_on_failure() -> None:
    sched = rt.ContentTeamTaskScheduler()
    # 注册 unknown 类型任务 → 执行抛 RuntimeError 让 worker 记账。
    task = _task({"type": "nope"})
    sched.registry.register(task)
    with pytest.raises(RuntimeError):
        sched.run("t")


def test_scheduler_run_publish_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_publish(payload):
        return {"ok": True, "published": 1}

    monkeypatch.setattr(rt, "_run_publish", fake_run_publish)
    sched = rt.ContentTeamTaskScheduler()
    task = _task({"type": "publish", "payload": {"content_id": "42"}})
    sched.registry.register(task)
    assert sched.run("t") == {"ok": True, "published": 1}


def test_router_resolve_returns_runtime() -> None:
    router = rt.ContentTeamRouter()
    runtime = router.resolve("default")
    assert isinstance(runtime, rt.ContentTeamRuntime)
    assert isinstance(runtime.scheduler(), rt.ContentTeamTaskScheduler)

"""Tests for cron trigger memory continuity (cron_memory.py, P4-1).

覆盖：notepad 持久化、inject_context 注入语义（continuity 开关 / goal
缺失 no-op / 不改入参）、record_run 回写（last_run + 观测哈希 + notepad
追加 + episode 落记忆）、monitor 去重判定、CronScheduler 派发集成
（continuity 触发器的 job 模板携带记忆块）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from hermes.workbench.cron_memory import CronContinuity
from hermes.workbench.cli import Task
from hermes.workbench.scheduler import ScheduledJob
from hermes.workbench.triggers import CronScheduler, Trigger, TriggerStore


@pytest.fixture
def continuity(tmp_path: Path) -> CronContinuity:
    return CronContinuity(state_dir=tmp_path)


@pytest.fixture
def loop_template() -> dict[str, Any]:
    """loop 模式 job 模板（有 goal.description，continuity 注入点）。"""
    task = Task(
        task_id="daily-report",
        plan=[{"skill": "echo", "args": ["hi"]}],
        mode="loop",
        goal={"description": "生成每日巡检报告", "success_criteria": ["报告完整"]},
    )
    d = task.to_dict()
    return {"task": d, "target_project": "default", "priority": 3}


def _trigger(job_template: dict[str, Any], **config: Any) -> Trigger:
    return Trigger(
        job_template=job_template,
        trigger_type="cron",
        config={"cron": "* * * * *", **config},
    )


# ---------------------------------------------------------------------------
# notepad
# ---------------------------------------------------------------------------


def test_notepad_roundtrip_and_persistence(tmp_path: Path) -> None:
    c = CronContinuity(state_dir=tmp_path)
    assert c.get_notepad("t1") == ""
    c.set_notepad("t1", "关注 .env 泄漏问题")
    assert c.get_notepad("t1") == "关注 .env 泄漏问题"

    # 新实例（进程重启语义）从磁盘读回
    c2 = CronContinuity(state_dir=tmp_path)
    assert c2.get_notepad("t1") == "关注 .env 泄漏问题"


def test_notepad_capped_to_tail(continuity: CronContinuity) -> None:
    continuity.set_notepad("t1", "x" * 20000)
    assert len(continuity.get_notepad("t1")) == 8000


# ---------------------------------------------------------------------------
# inject_context
# ---------------------------------------------------------------------------


def test_inject_context_appends_memory_block(
    continuity: CronContinuity, loop_template: dict[str, Any]
) -> None:
    continuity.set_notepad("t1", "上次发现 test_api 超时是 mock 未重置")
    continuity.record_run("t1", success=False, summary="lint 失败：E501")
    trigger = _trigger(loop_template, continuity=True)
    trigger.trigger_id = "t1"

    merged = continuity.inject_context(trigger, loop_template)

    desc = merged["task"]["goal"]["description"]
    assert "生成每日巡检报告" in desc  # 原 description 保留
    assert "cron continuity" in desc
    assert "test_api 超时" in desc  # notepad 内容注入
    assert "lint 失败" in desc  # 上次运行摘要注入
    # 入参未被改动（浅拷贝语义）
    assert "cron continuity" not in loop_template["task"]["goal"]["description"]


def test_inject_context_noop_without_continuity_flag(
    continuity: CronContinuity, loop_template: dict[str, Any]
) -> None:
    trigger = _trigger(loop_template)  # 无 continuity
    assert continuity.inject_context(trigger, loop_template) is loop_template


def test_inject_context_noop_without_goal(
    continuity: CronContinuity
) -> None:
    """oneshot 模板（无 goal）无 LLM prompt 可注入，原样返回。"""
    oneshot = {
        "task": Task(task_id="t", plan=[{"skill": "echo", "args": ["x"]}]).to_dict()
    }
    trigger = _trigger(oneshot, continuity=True)
    assert continuity.inject_context(trigger, oneshot) is oneshot


# ---------------------------------------------------------------------------
# record_run + monitor 去重
# ---------------------------------------------------------------------------


def test_record_run_stores_last_run_and_notepad_append(
    continuity: CronContinuity,
) -> None:
    continuity.record_run(
        "t1", success=True, summary="全部通过", notepad_update="基线：2100 tests"
    )
    # notepad_update 追加进 notepad；summary 只进 last_run
    assert continuity.get_notepad("t1") == "基线：2100 tests"

    continuity.record_run("t1", success=False, summary="ruff 报错")
    # last_run 被覆盖为最新一次
    trigger = _trigger({}, continuity=True)
    trigger.trigger_id = "t1"
    merged = continuity.inject_context(
        trigger, {"task": {"goal": {"description": "d"}}, }
    )
    assert "ruff 报错" in merged["task"]["goal"]["description"]
    assert "全部通过" not in merged["task"]["goal"]["description"]


def test_record_run_records_episode_to_memory(tmp_path: Path) -> None:
    memory = MagicMock()
    c = CronContinuity(state_dir=tmp_path, memory=memory)
    c.record_run("t1", success=True, summary="OK")
    assert memory.record_episode.called
    episode = memory.record_episode.call_args[0][0]
    assert episode.kind == "cron_run"
    assert "t1" in episode.summary


def test_record_run_memory_failure_does_not_raise(tmp_path: Path) -> None:
    memory = MagicMock()
    memory.record_episode.side_effect = RuntimeError("boom")
    c = CronContinuity(state_dir=tmp_path, memory=memory)
    c.record_run("t1", success=True)  # 不得抛出


def test_observation_dedup(continuity: CronContinuity) -> None:
    obs = "uptime=99.9% errors=0"
    # 首次观测：无历史哈希 → False（不跳过）
    assert continuity.observation_unchanged("t1", obs) is False
    continuity.record_run("t1", success=True, observation=obs)
    # 相同观测 → True（monitor 跳过昂贵 LLM 步骤）
    assert continuity.observation_unchanged("t1", obs) is True
    # 观测变化 → False
    assert continuity.observation_unchanged("t1", obs + " alerts=1") is False


# ---------------------------------------------------------------------------
# CronScheduler 集成：派发的 job 携带记忆
# ---------------------------------------------------------------------------


def test_scheduler_injects_continuity_on_fire(
    tmp_path: Path, loop_template: dict[str, Any]
) -> None:
    store = TriggerStore(state_dir=tmp_path)
    cont = CronContinuity(state_dir=tmp_path)
    cont.set_notepad("t1", "记住：先跑 mypy 再跑 pytest")

    trigger = _trigger(loop_template, continuity=True)
    trigger.trigger_id = "t1"
    store.save(trigger)

    submitted: list[ScheduledJob] = []
    sched = CronScheduler(
        store, submitted.append, scan_interval=0.05, continuity=cont
    )
    assert sched.fire("t1") is True
    assert len(submitted) == 1
    goal = submitted[0].task.goal
    assert goal is not None
    assert "先跑 mypy 再跑 pytest" in goal["description"]
    assert "生成每日巡检报告" in goal["description"]


def test_scheduler_without_continuity_flag_unchanged(
    tmp_path: Path, loop_template: dict[str, Any]
) -> None:
    store = TriggerStore(state_dir=tmp_path)
    cont = CronContinuity(state_dir=tmp_path)
    cont.set_notepad("t2", "不应注入")

    trigger = _trigger(loop_template)  # 无 continuity
    trigger.trigger_id = "t2"
    store.save(trigger)

    submitted: list[ScheduledJob] = []
    sched = CronScheduler(
        store, submitted.append, scan_interval=0.05, continuity=cont
    )
    assert sched.fire("t2") is True
    desc = submitted[0].task.goal["description"]  # type: ignore[index]
    assert "不应注入" not in desc

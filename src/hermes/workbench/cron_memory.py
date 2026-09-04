"""Cron trigger memory continuity (P4-1, 借鉴 NousResearch v0.21 cron continuity).

让定时任务"带着记忆跑"：``Trigger.config["continuity"] = true`` 的触发器，
派发时由 :class:`CronContinuity` 把持久 notepad + 上次运行摘要注入任务
``goal.description``（loop 模式任务的 LLM prompt 因此携带跨运行上下文），
执行方通过 :meth:`record_run` 回写结果，形成"上次结论 → 本次输入"闭环。

monitor 模式（``config["monitor"] = true``）提供观测去重判定
:meth:`observation_unchanged`：执行方先产出廉价观测（如巡检快照），
哈希与上次一致即跳过昂贵的 LLM 步骤——省 token 的关键路径。

设计约束：
- stdlib-only（json/hashlib/threading），与 triggers.py 同级依赖水位。
- MemoryService 可选注入：缺席时仅落盘 state，不写 episodes（不炸测试）。
- 注入只改 goal.description（Goal.from_dict 忽略未知键、description 是
  自由文本流进 PlannerAgent prompt）；oneshot 纯技能流水线无 LLM prompt，
  注入为 no-op——调用方无须分支判断。
"""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any

from hermes.workbench.persistence import atomic_write_json, safe_read_json

__all__ = ["CronContinuity"]


# notepad 容量上限（字符）。超限保留尾部（最新笔记），头部截断。
_NOTEPAD_MAX_CHARS = 8000
# 单次运行摘要截断长度。
_SUMMARY_MAX_CHARS = 500


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CronContinuity:
    """Per-trigger durable state: notepad + last run + observation hash.

    状态文件 ``cron_continuity.json``（atomic_write_json，与 TriggerStore
    同水位），结构 ``{trigger_id: {"notepad", "last_run", "last_observation"}}``。
    """

    def __init__(
        self,
        state_dir: Path | str,
        memory: Any | None = None,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.state_dir / "cron_continuity.json"
        self._lock = threading.Lock()
        self._memory = memory
        self._state: dict[str, dict[str, Any]] = self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        data = safe_read_json(self._path, default={})
        return data if isinstance(data, dict) else {}

    def _save_locked(self) -> None:
        atomic_write_json(self._path, self._state)

    def _entry(self, trigger_id: str) -> dict[str, Any]:
        # 调用方须持有 self._lock
        entry = self._state.get(trigger_id)
        if not isinstance(entry, dict):
            entry = {}
            self._state[trigger_id] = entry
        return entry

    # -- notepad ------------------------------------------------------------

    def get_notepad(self, trigger_id: str) -> str:
        with self._lock:
            entry = self._state.get(trigger_id)
            return str(entry.get("notepad", "")) if isinstance(entry, dict) else ""

    def set_notepad(self, trigger_id: str, text: str) -> None:
        with self._lock:
            entry = self._entry(trigger_id)
            entry["notepad"] = text[-_NOTEPAD_MAX_CHARS:]
            self._save_locked()

    # -- context injection ---------------------------------------------------

    def _render_block(self, trigger_id: str) -> str:
        # 调用方须持有 self._lock
        entry = self._state.get(trigger_id) or {}
        last = entry.get("last_run") or {}
        lines = ["[cron continuity — 跨运行记忆]"]
        if last:
            outcome = "成功" if last.get("success") else "失败"
            lines.append(
                f"上次运行（{last.get('ts', '?')}，{outcome}）摘要：{last.get('summary', '')}"
            )
        else:
            lines.append("（首次运行，无历史）")
        notepad = str(entry.get("notepad", "")).strip()
        if notepad:
            lines.append(f"持久笔记：\n{notepad}")
        return "\n".join(lines)

    def inject_context(
        self,
        trigger: Any,
        job_template: dict[str, Any],
    ) -> dict[str, Any]:
        """continuity=true 时把记忆块追加进 task.goal.description。

        返回新的 template（浅拷贝，不改动入参）。非 continuity 触发器、
        或无 goal 的 oneshot 模板原样返回。
        """
        config = getattr(trigger, "config", None) or {}
        if not config.get("continuity"):
            return job_template
        task = job_template.get("task")
        if not isinstance(task, dict):
            return job_template
        goal = task.get("goal")
        if not isinstance(goal, dict) or not goal:
            return job_template
        with self._lock:
            block = self._render_block(getattr(trigger, "trigger_id", ""))
        merged = dict(job_template)
        merged_task = dict(task)
        merged_goal = dict(goal)
        desc = str(goal.get("description", "")).strip()
        merged_goal["description"] = f"{desc}\n\n{block}".strip()
        merged_task["goal"] = merged_goal
        merged["task"] = merged_task
        return merged

    # -- run recording -------------------------------------------------------

    def record_run(
        self,
        trigger_id: str,
        success: bool,
        summary: str = "",
        observation: str = "",
        notepad_update: str = "",
    ) -> None:
        """回写一次运行结果：last_run 摘要 + 可选 notepad 追加 + 观测哈希。

        ``observation`` 非空时更新观测哈希（供 monitor 去重判定）。
        注入了 MemoryService 时同步记一条 ``cron_run`` episode。
        """
        summary = (summary or "").strip()[:_SUMMARY_MAX_CHARS]
        with self._lock:
            entry = self._entry(trigger_id)
            entry["last_run"] = {
                "ts": _now_iso(),
                "success": bool(success),
                "summary": summary,
            }
            if observation:
                entry["last_observation"] = _digest(observation)
            if notepad_update:
                notepad = str(entry.get("notepad", ""))
                entry["notepad"] = (notepad + "\n" + notepad_update).strip()[
                    -_NOTEPAD_MAX_CHARS:
                ]
            self._save_locked()
        if self._memory is not None:
            try:
                from hermes.workbench.memory import make_episode

                self._memory.record_episode(
                    make_episode(
                        "cron_run",
                        f"cron {trigger_id}: {'OK' if success else 'FAIL'} {summary}"[
                            :_SUMMARY_MAX_CHARS
                        ],
                        {"trigger_id": trigger_id, "success": bool(success)},
                    )
                )
            except Exception:  # noqa: BLE001 — 记忆失败不得阻断调度主链路
                pass

    def observation_unchanged(self, trigger_id: str, observation: str) -> bool:
        """monitor 去重判定（纯谓词，无副作用）。

        观测哈希与上次 record_run 记录的一致 → True，执行方可据此
        跳过昂贵的 LLM 分析步骤。首次观测（无历史哈希）返回 False。
        """
        with self._lock:
            entry = self._state.get(trigger_id)
            if not isinstance(entry, dict):
                return False
            last = entry.get("last_observation")
            return bool(last) and last == _digest(observation)

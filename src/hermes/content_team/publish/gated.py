"""C5 Gated 发布流：发布检查单 → 飞书确认卡 → 人工裁决 → 批准即派发。

半自动原则的关键节点：AI 可以做完准备（合规检查 / 发布任务单），但「真的发」
出这一步必须有人在卡片上点击确认。裁决回填 GatedPublishStore（SQLite，
.state 往下锚定），同一 gate 幂等（重复点击返回既有裁决）；批准动作走「统一
调度中心」提交 publish job（复用 triggers 的 job_template 形状 →
ScheduledJob.from_template），由既有 worker 真正执行发布分发（状态回填在
PublishTask 上完成）。

依赖方向：本模块属 content_team 侧，只调用 workbench 调度与通知原语；
gateway 侧 /feishu/events 通过惰性 import 调用本模块（无顶层循环依赖）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes.content_team.observability import log_event

__all__ = [
    "GatedPublishStore",
    "build_gate_card",
    "gated_store_dir",
    "parse_gate_event",
    "submit_publish_job",
    "try_send_gate_card",
]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GatedAction:
    """一次 Gated 发布的记录（幂等裁决以 status 为准）。"""

    gate_id: str
    content_id: str
    platform: str
    checklist: dict[str, Any]
    status: str  # pending / approved / rejected
    created_at: str
    decided_at: str | None = None
    decided_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "content_id": self.content_id,
            "platform": self.platform,
            "checklist": self.checklist,
            "status": self.status,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
        }


class GatedPublishStore:
    """Gated 发布裁决存储（SQLite，WAL；线程安全）。"""

    def __init__(self, state_dir: Path | str) -> None:
        self._db_path = Path(state_dir) / "gated_publish.db"
        self._local = threading.local()
        self._ensure_schema()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self._db_path), check_same_thread=True, timeout=30.0
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        with threading.Lock():
            conn = sqlite3.connect(str(self._db_path), check_same_thread=True)
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS gated_publish("
                    "  gate_id TEXT PRIMARY KEY,"
                    "  content_id TEXT NOT NULL,"
                    "  platform TEXT NOT NULL,"
                    "  checklist TEXT NOT NULL,"
                    "  status TEXT NOT NULL,"
                    "  created_at TEXT NOT NULL,"
                    "  decided_at TEXT,"
                    "  decided_by TEXT"
                    ")"
                )
                conn.commit()
            finally:
                conn.close()

    def create_gate(
        self, content_id: str, platform: str, checklist: dict[str, Any]
    ) -> GatedAction:
        import uuid as _uuid

        gate = GatedAction(
            gate_id=_uuid.uuid4().hex[:12],
            content_id=content_id,
            platform=platform,
            checklist=checklist,
            status="pending",
            created_at=_now_iso(),
        )
        conn = self._conn
        conn.execute(
            "INSERT INTO gated_publish VALUES (?,?,?,?,?,?,?,?)",
            (
                gate.gate_id,
                gate.content_id,
                gate.platform,
                json.dumps(gate.checklist, ensure_ascii=False),
                gate.status,
                gate.created_at,
                gate.decided_at,
                gate.decided_by,
            ),
        )
        conn.commit()
        return gate

    def get(self, gate_id: str) -> GatedAction | None:
        row = self._conn.execute(
            "SELECT * FROM gated_publish WHERE gate_id = ?", (gate_id,)
        ).fetchone()
        return self._row_to_action(row) if row else None

    def resolve(
        self, gate_id: str, decision: str, decided_by: str
    ) -> tuple[GatedAction, bool]:
        """裁决一个 gate；幂等——已裁决的 gate 返回既有结果 (gate, False)。

        :param decision: "approve" / "reject"
        :returns: (最终 gate，本次是否刚发生状态变更)
        """
        gate = self.get(gate_id)
        if gate is None:
            raise KeyError(f"gate {gate_id!r} not found")
        if gate.status != "pending":
            return gate, False
        status = "approved" if decision == "approve" else "rejected"
        conn = self._conn
        conn.execute(
            "UPDATE gated_publish SET status=?, decided_at=?, decided_by=? "
            "WHERE gate_id=?",
            (status, _now_iso(), decided_by, gate_id),
        )
        conn.commit()
        log_event(
            "gated_publish_resolved",
            "Gated 发布裁决",
            gate_id=gate_id,
            status=status,
            decided_by=decided_by,
        )
        return self.get(gate_id) or gate, True

    def _row_to_action(self, row: tuple) -> GatedAction:
        return GatedAction(
            gate_id=row[0],
            content_id=row[1],
            platform=row[2],
            checklist=json.loads(row[3]),
            status=row[4],
            created_at=row[5],
            decided_at=row[6],
            decided_by=row[7],
        )


# ---------------------------------------------------------------------------
# 飞书确认卡
# ---------------------------------------------------------------------------

_BUTTON_VALUE_KEY = "gate_action"


def build_gate_card(
    gate_id: str, title: str, checklist: dict[str, Any]
) -> list[dict[str, Any]]:
    """构造发布确认卡 elements（2 个按钮，value 携带 gate_id/decision）。"""
    passed = checklist.get("passed")
    summary = checklist.get("summary", "")
    summary_lines = summary if isinstance(summary, str) else json.dumps(
        checklist, ensure_ascii=False
    )
    elements: list[dict[str, Any]] = []
    mark = "✅" if passed else "⚠️"
    elements.append(
        {
            "tag": "div",
            "text": {
                "tag": "plain_text",
                "content": f"{mark} 内容「{title}」合规检查 {'通过' if passed else '有告警'}，请确认是否发布：\n{summary_lines}",
            },
        }
    )
    elements.append(
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "确认发布"},
                    "type": "primary",
                    "value": {
                        _BUTTON_VALUE_KEY: "publish_gate",
                        "gate_id": gate_id,
                        "decision": "approve",
                    },
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "暂缓发布"},
                    "type": "default",
                    "value": {
                        _BUTTON_VALUE_KEY: "publish_gate",
                        "gate_id": gate_id,
                        "decision": "reject",
                    },
                },
            ],
        }
    )
    return elements


def parse_gate_event(event: Any) -> dict[str, str] | None:
    """从飞书回调事件里解析出 gate 裁决意图。

    兼容两种回调形态：
    - 卡片 2.0：``{"schema":"2.0","header":{"event_type":"card.action.trigger"},
      "event":{"action":{"value":{...}},"operator":{"open_id":...}}}``
    - v1：``{"type":"card_action_trigger","event":{...}}``

    非卡片事件/非 publish_gate action 返回 None（让 webhook 继续走消息入箱）。
    """
    # 卡片事件：event 里包含 operator / action；消息事件没有 action 字段
    if not isinstance(event, dict):
        return None
    action = event.get("action")
    if not isinstance(action, dict):
        return None
    value = action.get("value")
    if not isinstance(value, dict) or value.get(_BUTTON_VALUE_KEY) != "publish_gate":
        return None
    gate_id = str(value.get("gate_id", "")
    )
    decision = str(value.get("decision", ""))
    operator = event.get("operator")
    operator_id = ""
    if isinstance(operator, dict):
        operator_id = str(
            operator.get("open_id") or operator.get("union_id") or ""
        )
    if not gate_id or decision not in ("approve", "reject"):
        return None
    return {
        "gate_id": gate_id,
        "decision": decision,
        "operator": operator_id,
    }


def gated_store_dir() -> str:
    """Gated 发布库目录（可 monkeypatch 的间接层，避免测试写真实 .state）。"""
    from hermes.config import get_settings

    return str(get_settings().hermes_state_dir)


def try_send_gate_card(elements: list[dict[str, Any]], title: str) -> tuple[bool, str]:
    """把发布确认卡发到飞书（尽力而为）；失败进死信。

    :returns: (是否发送成功 / 是否已配置，reason)
    """
    from hermes.config import get_settings

    settings = get_settings()
    if not (
        settings.feishu_report_chat_id
        and settings.feishu_app_id
        and settings.feishu_app_secret
    ):
        return False, "feishu not configured (FEISHU_REPORT_CHAT_ID/APP_ID/APP_SECRET)"
    from hermes.workbench.feishu_notify import DeadLetterStore, FeishuClient

    client = FeishuClient(settings.feishu_app_id, settings.feishu_app_secret)
    try:
        client.send_card(
            settings.feishu_report_chat_id,
            title,
            elements,
            receive_id_type="chat_id",
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001 — 通知尽力而为
        DeadLetterStore(settings.hermes_state_dir).record(
            "gate_card", settings.feishu_report_chat_id, title, str(exc)
        )
        return False, str(exc)


def submit_publish_job(
    content_id: str, platform: str, platform_account_ids: list[str] | None = None
) -> str:
    """批准后续：提交 publish job 到统一调度中心，返回 job_id。

    复用 content_team.triggers 的 job_template 形状（task.goal.type=publish），
    由 gateway worker 真正执行 PublishDispatcher 分发与 PublishTask 状态回填。
    """
    from hermes.content_team.scheduler import get_scheduler
    from hermes.workbench.scheduler import ScheduledJob

    payload: dict[str, Any] = {"content_id": content_id, "platform": platform}
    if platform_account_ids:
        payload["platform_account_ids"] = platform_account_ids
    template = {
        "type": "publish",
        "target_project": "content-team",
        "payload": payload,
        "task": {
            "task_id": "content_team_gated_publish",
            "mode": "oneshot",
            "max_rounds": 1,
            "max_runs": 1,
            "goal": {"type": "publish", "payload": payload},
        },
    }
    job = ScheduledJob.from_template(template, submitted_by="gated_publish")
    components = get_scheduler()
    store = components["store"]
    queue = components["queue"]
    from hermes.workbench.scheduler import JobStatus

    job.status = JobStatus.QUEUED
    store.save(job)
    queue.put(job)
    log_event(
        "gated_publish_job_submitted",
        "Gated 发布批准后提交 job",
        job_id=job.job_id,
        content_id=content_id,
        platform=platform,
    )
    return job.job_id

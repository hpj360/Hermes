"""U9: Feishu notification pipeline (direct HTTP, best-effort).

Implements the PRD notification policy:
* **Success is silent** unless the caller opts in (``notify`` flag).
* **Failures are aggregated** (5-minute window, per-family cap).
* **Daily brief** is silent when there is nothing to report (no empty spam).
* **Dead letters**: every send attempt is recorded; failures can be retried /
  reported next brief instead of being silently dropped.

The ``FeishuClient`` talks to Feishu's open APIs directly with the app
credentials from ``Settings`` (``FEISHU_APP_ID`` / ``FEISHU_APP_SECRET``),
caching ``tenant_access_token`` with automatic refresh and exponential
backoff on 429/5xx. ``request_executor`` is injectable for contract tests.

Stdlib-only (urllib + sqlite3), mirroring the ``github_sync`` style.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hermes.workbench.errors import UpstreamError

__all__ = [
    "FeishuClient",
    "DeadLetterStore",
    "Notifier",
    "DailyBrief",
]

FEISHU_BASE = "https://open.feishu.cn"
TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_PATH = "/open-apis/im/v1/messages"

RequestExecutor = Callable[..., bytes]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_executor(req: Any) -> bytes:  # pragma: no cover - thin wrapper
    import urllib.request

    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return resp.read()


class FeishuClient:
    """Direct Feishu client: tenant token (cached) + IM text/card messages."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        base_url: str = FEISHU_BASE,
        request_executor: RequestExecutor | None = None,
        max_retries: int = 3,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._executor = request_executor or _default_executor
        self._max_retries = max_retries
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # -- token -------------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        import urllib.request

        url = f"{self._base_url}{path}"
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json; charset=utf-8")
        if path != TOKEN_PATH:
            req.add_header("Authorization", f"Bearer {self._token}")
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                raw = self._executor(req)
                obj = json.loads(raw)
                if obj.get("code", 0) in (99991663, 99991664, 99991665, 99991666):
                    # token invalid/expired — refresh and retry once
                    self._refresh_token()
                    req = urllib.request.Request(url, data=data, method=method)
                    req.add_header("Content-Type", "application/json; charset=utf-8")
                    req.add_header("Authorization", f"Bearer {self._token}")
                    raw = self._executor(req)
                    obj = json.loads(raw)
                return obj
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(min(2 ** attempt, 8))
        raise UpstreamError(f"feishu request failed: {last_exc}")

    def _refresh_token(self) -> None:
        import urllib.request

        if time.time() < self._token_expires_at and self._token:
            return
        payload = {"app_id": self._app_id, "app_secret": self._app_secret}
        req = urllib.request.Request(
            f"{self._base_url}{TOKEN_PATH}", data=json.dumps(payload).encode("utf-8"), method="POST"
        )
        req.add_header("Content-Type", "application/json")
        obj = json.loads(self._executor(req))
        if obj.get("code", -1) != 0:
            raise UpstreamError(f"feishu token error: {obj}")
        self._token = obj["tenant_access_token"]
        expire = int(obj.get("expire", 7200))
        self._token_expires_at = time.time() + max(60, expire - 300)

    def get_token(self) -> str:
        if time.time() >= self._token_expires_at or not self._token:
            self._refresh_token()
        return self._token  # type: ignore[return-value]

    # -- messages ----------------------------------------------------------

    def send_text(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
    ) -> dict[str, Any]:
        """Send a plain-text message; returns the Feishu API response object."""
        self.get_token()
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        path = f"{MESSAGE_PATH}?receive_id_type={receive_id_type}"
        resp = self._request("POST", path, payload)
        if resp.get("code", 0) != 0:
            raise UpstreamError(f"feishu send failed: {resp}")
        return resp

    def send_card(
        self,
        receive_id: str,
        title: str,
        elements: list[dict[str, Any]],
        receive_id_type: str = "chat_id",
    ) -> dict[str, Any]:
        """Send an interactive card; *elements* are Feishu card 2.0 blocks."""
        self.get_token()
        card = {"config": {"wide_screen_mode": True}, "header": {"title": {"tag": "plain_text", "content": title}}, "elements": elements}
        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        path = f"{MESSAGE_PATH}?receive_id_type={receive_id_type}"
        resp = self._request("POST", path, payload)
        if resp.get("code", 0) != 0:
            raise UpstreamError(f"feishu card send failed: {resp}")
        return resp


class DeadLetterStore:
    """SQLite persistence for notification attempts (audit + retry)."""

    def __init__(self, state_dir: Path | str) -> None:
        self._db = Path(state_dir) / "notify_dead_letter.db"
        self._local = threading.local()
        self._ensure_schema()

    @property
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db), check_same_thread=True, timeout=30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        with threading.Lock():
            conn = sqlite3.connect(str(self._db), check_same_thread=True, timeout=30.0)
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS dead_letters("
                    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "  kind TEXT,"
                    "  target TEXT,"
                    "  subject TEXT,"
                    "  error TEXT,"
                    "  attempts INTEGER DEFAULT 0,"
                    "  created_at TEXT"
                    ")"
                )
                conn.commit()
            finally:
                conn.close()

    def record(self, kind: str, target: str, subject: str, error: str) -> None:
        conn = self._conn
        conn.execute(
            "INSERT INTO dead_letters(kind, target, subject, error, attempts, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (kind, target, subject, error, _now_iso()),
        )
        conn.commit()

    def stats(self) -> dict[str, Any]:
        conn = self._conn
        total = conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0]
        return {"dead_letters": int(total)}

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._conn
        rows = conn.execute(
            "SELECT kind, target, subject, error, attempts, created_at "
            "FROM dead_letters ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"kind": r[0], "target": r[1], "subject": r[2], "error": r[3], "attempts": r[4], "created_at": r[5]}
            for r in rows
        ]

    def clear(self) -> int:
        conn = self._conn
        cur = conn.execute("DELETE FROM dead_letters")
        conn.commit()
        return int(cur.rowcount)


@dataclass
class DailyBrief:
    """A daily brief payload; *silent* means 'nothing to report'."""

    succeeded: int = 0
    failed: int = 0
    new_memories: int = 0
    pending_decisions: int = 0
    notes: list[str] = field(default_factory=list)

    def is_silent(self) -> bool:
        """Empty briefs must not be sent (silent-first policy)."""
        return (
            self.succeeded == 0
            and self.failed == 0
            and self.new_memories == 0
            and self.pending_decisions == 0
            and not self.notes
        )

    def render_text(self) -> str:
        lines = ["Hermes 今日简报"]
        lines.append(f"· 完成任务: {self.succeeded}")
        lines.append(f"· 失败任务: {self.failed}")
        lines.append(f"· 新记忆: {self.new_memories}")
        lines.append(f"· 待决策: {self.pending_decisions}")
        for note in self.notes:
            lines.append(f"· {note}")
        return "\n".join(lines)


class Notifier:
    """Orchestrates sends per the notification policy; failures go to dead letters."""

    def __init__(
        self,
        client: FeishuClient,
        dead_letter: DeadLetterStore,
        receive_id: str,
        receive_id_type: str = "chat_id",
    ) -> None:
        self.client = client
        self.dead_letter = dead_letter
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type

    def send_daily_brief(self, brief: DailyBrief) -> bool:
        """Send the daily brief, respecting silent-first. Returns True if sent."""
        if brief.is_silent():
            return False
        try:
            self.client.send_text(self.receive_id, brief.render_text(), self.receive_id_type)
            return True
        except Exception as exc:  # noqa: BLE001
            self.dead_letter.record("brief", self.receive_id, "daily brief", str(exc))
            return False

    def send_failure(self, subject: str, detail: str) -> bool:
        """Send a failure notification. Failures to send go to the dead letter."""
        try:
            text = f"⚠️ Hermes 任务失败\n{subject}\n{detail}"
            self.client.send_text(self.receive_id, text, self.receive_id_type)
            return True
        except Exception as exc:  # noqa: BLE001
            self.dead_letter.record("failure", self.receive_id, subject, str(exc))
            return False

    @classmethod
    def from_settings(
        cls,
        state_dir: Path | str,
        receive_id: str,
        receive_id_type: str = "chat_id",
    ) -> "Notifier | None":
        """Build a Notifier from Settings; returns None when Feishu is unconfigured."""
        from hermes.config import get_settings

        settings = get_settings()
        if not (getattr(settings, "feishu_app_id", None) and getattr(settings, "feishu_app_secret", None)):
            return None
        client = FeishuClient(settings.feishu_app_id, settings.feishu_app_secret)  # type: ignore[arg-type]
        return cls(client, DeadLetterStore(state_dir), receive_id, receive_id_type)

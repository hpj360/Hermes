"""C3: Feishu bot inbox — messages sent to the bot land in the capture inbox.

Two ingestion channels feed the same pipeline:

1. **Webhook** — ``POST /feishu/events`` on the gateway. Requires a public URL
   (tunnel) for Feishu to reach it; supports ``url_verification`` challenge and
   optional ``FEISHU_VERIFICATION_TOKEN`` signature check.
2. **Long connection (lark-cli bridge)** — ``hermes workbench feishu-inbox``
   spawns ``lark-cli event consume im.message.receive_v1`` (NDJSON on stdout,
   Feishu WebSocket long-connection mode) and ingests each event. This is the
   no-tunnel local path.

Rules (notification fatigue / noise control):
* Only ``chat_type == p2p`` (direct messages to the bot) are captured.
* Duplicate ``message_id`` events are ignored (idempotency key).
* Content with a URL → ``link`` capture (note + summary job); otherwise a
  ``todo``-style inbox entry.
"""

from __future__ import annotations

import re
from typing import Any

from hermes.workbench.capture import CaptureService

__all__ = ["parse_feishu_event", "FeishuInboxService"]

_URL_RE = re.compile(r"https?://[^\s]+")


def parse_feishu_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a capturable item from an ``im.message.receive_v1`` event.

    Returns ``{title, type, url?, chat_id, message_id, sender_id}`` or None
    when the event should be skipped (non-p2p chat / no usable content).
    """
    chat_type = str(event.get("chat_type", ""))
    if chat_type and chat_type != "p2p":
        return None

    content = str(event.get("content", "") or "").strip()
    if not content:
        return None

    message_id = str(event.get("message_id", "") or event.get("id", "") or "")
    chat_id = str(event.get("chat_id", "") or "")
    sender_id = str(event.get("sender_id", "") or "")

    url_match = _URL_RE.search(content)
    url = url_match.group(0) if url_match else None
    title = content
    if url:
        # Title: text minus the URL, trimmed; fall back to the URL itself.
        title = content.replace(url, "").strip() or url

    return {
        "title": title[:500],
        "type": "link" if url else "todo",
        "url": url,
        "chat_id": chat_id,
        "message_id": message_id,
        "sender_id": sender_id,
    }


class FeishuInboxService:
    """Ingest Feishu events into the capture pipeline with message dedup."""

    def __init__(
        self,
        capture: CaptureService,
        dedup_capacity: int = 1000,
        allow_group: bool = False,
    ) -> None:
        self.capture = capture
        self._seen: dict[str, str] = {}
        self._capacity = dedup_capacity
        self._allow_group = allow_group

    def ingest(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Process one event; returns the capture result or None when skipped."""
        parsed = parse_feishu_event(event)
        if parsed is None:
            return None

        message_id = parsed["message_id"]
        if message_id:
            if message_id in self._seen:
                return None
            if len(self._seen) >= self._capacity:
                self._seen.clear()
            self._seen[message_id] = parsed["title"]

        result = self.capture.capture(
            title=parsed["title"],
            type_=parsed["type"],
            url=parsed.get("url"),
            source="feishu",
        )
        result["message_id"] = message_id
        result["chat_id"] = parsed["chat_id"]
        result["sender_id"] = parsed["sender_id"]
        return result

    def stats(self) -> dict[str, Any]:
        return {"seen_messages": len(self._seen)}

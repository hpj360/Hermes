"""Content-team observability: structured logging + tracing integration.

Wraps hermes workbench structured_logging and tracing for content-team:
- JSON structured logs with trace_id, event, task_id fields
- Per-request trace_id generation and propagation
- Log context binding for API endpoints
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from hermes.workbench.structured_logging import (
    configure_logging,
    get_log_context,
    log_context,
)
from hermes.workbench.tracing import new_trace_id

__all__ = [
    "setup_logging",
    "generate_trace_id",
    "with_trace",
    "log_event",
    "get_current_trace_id",
]

# content_team 统一日志器，所有 log_event 通过它发出
_logger = logging.getLogger("hermes.content_team")


def setup_logging(level: str = "INFO", json: bool = True) -> None:
    """初始化 content_team 根日志配置（委托给 hermes workbench）。

    :param level: 日志级别名称，如 ``"INFO"``、``"DEBUG"``
    :param json: True 输出 JSON 结构化日志，False 输出纯文本
    """
    configure_logging(level=level, json=json)


def generate_trace_id() -> str:
    """生成 8 字符十六进制 trace_id（委托给 hermes workbench）。"""
    return new_trace_id()


@contextmanager
def with_trace(trace_id: str | None = None, **context: Any) -> Iterator[str]:
    """绑定 trace_id 及额外上下文到当前日志作用域。

    未提供 ``trace_id`` 时自动生成。在 with 块内发出的所有日志都会
    自动携带 trace_id（以及 ``context`` 中的字段）。

    用法::

        with with_trace() as trace_id:
            log_event("topic_created", "Topic created", topic_id="123")

    :param trace_id: 显式 trace_id；为 None 时自动生成
    :param context: 附加到日志上下文的任意字段（如 user、task_id）
    :returns: 生成或传入的 trace_id
    """
    tid = trace_id or generate_trace_id()
    with log_context(trace_id=tid, **context):
        yield tid


def log_event(event: str, message: str = "", **fields: Any) -> None:
    """以 INFO 级别记录一条带事件名与额外字段的结构化日志。

    自动带上当前日志上下文中的 trace_id 等字段（由 StructuredFormatter
    在格式化时从 contextvars 注入）。

    示例::

        log_event("topic_created", "Topic created", topic_id="123", title="test")

    :param event: 事件名，如 ``"topic_created"``
    :param message: 人类可读的日志消息
    :param fields: 任意附加字段，会合并进日志记录
    """
    _logger.info(message, extra={"event": event, **fields})


def get_current_trace_id() -> str | None:
    """从当前日志上下文中提取 trace_id；未设置时返回 None。"""
    return get_log_context().get("trace_id")

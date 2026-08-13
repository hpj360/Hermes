"""Tests for hermes.content_team.observability."""

from __future__ import annotations

import json
import logging

from hermes.content_team.observability import (
    generate_trace_id,
    get_current_trace_id,
    log_event,
    setup_logging,
    with_trace,
)
from hermes.workbench.structured_logging import get_log_context, log_context


def _parse_json_log(stderr: str, event: str | None = None) -> dict:
    """从 stderr 输出中解析 JSON 日志行。

    setup_logging 配置的 root handler 会把日志以 JSON 形式写入 sys.stderr，
    这里按行扫描，返回第一条能解析为 JSON 且 ``event`` 匹配的记录，避免被
    其他库的杂散输出干扰。
    """
    for raw in stderr.strip().splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event is None or parsed.get("event") == event:
            return parsed
    raise AssertionError(
        f"未在 stderr 中找到匹配的 JSON 日志 (event={event}): {stderr!r}"
    )


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


def test_setup_logging_produces_json(capsys: object) -> None:
    """setup_logging(json=True) 应输出 JSON 结构化日志。"""
    setup_logging(level="INFO", json=True)
    log = logging.getLogger("test.content_team.observability.json")
    log.info("hello world", extra={"event": "test_event"})

    data = _parse_json_log(capsys.readouterr().err, event="test_event")  # type: ignore[attr-defined]

    assert data["msg"] == "hello world"
    assert data["event"] == "test_event"
    assert data["level"] == "INFO"
    assert "ts" in data


def test_setup_logging_text_mode(capsys: object) -> None:
    """setup_logging(json=False) 应输出纯文本而非 JSON。"""
    setup_logging(level="INFO", json=False)
    log = logging.getLogger("test.content_team.observability.text")
    log.warning("plain message")

    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert "plain message" in err
    assert "WARNING" in err
    # 不应是 JSON
    assert not err.strip().startswith("{")


# ---------------------------------------------------------------------------
# generate_trace_id
# ---------------------------------------------------------------------------


def test_generate_trace_id_returns_8_char_hex() -> None:
    tid = generate_trace_id()
    assert isinstance(tid, str)
    assert len(tid) == 8
    int(tid, 16)  # 可解析为十六进制


def test_generate_trace_ids_are_unique() -> None:
    ids = {generate_trace_id() for _ in range(50)}
    assert len(ids) == 50


# ---------------------------------------------------------------------------
# with_trace
# ---------------------------------------------------------------------------


def test_with_trace_binds_trace_id() -> None:
    """with_trace 应在上下文内绑定 trace_id，退出后恢复。"""
    assert get_log_context() == {}
    with with_trace() as tid:
        assert isinstance(tid, str)
        assert len(tid) == 8
        ctx = get_log_context()
        assert ctx["trace_id"] == tid
    # 退出后上下文恢复为空
    assert get_log_context() == {}


def test_with_trace_accepts_explicit_trace_id() -> None:
    with with_trace("custom-id") as tid:
        assert tid == "custom-id"
        assert get_log_context()["trace_id"] == "custom-id"


def test_with_trace_binds_extra_context() -> None:
    with with_trace("tid-x", user="alice", task_id="t1") as tid:
        assert tid == "tid-x"
        ctx = get_log_context()
        assert ctx["trace_id"] == "tid-x"
        assert ctx["user"] == "alice"
        assert ctx["task_id"] == "t1"
    # 退出后清理
    assert get_log_context() == {}


def test_with_trace_propagates_to_nested_log_context() -> None:
    """with_trace 绑定的 trace_id 应在嵌套 log_context 中继续可见。"""
    with with_trace("outer-tid", user="alice") as tid:
        assert tid == "outer-tid"
        with log_context(task_id="t1"):
            ctx = get_log_context()
            # trace_id 仍然存在（从 with_trace 传播下来）
            assert ctx["trace_id"] == "outer-tid"
            assert ctx["user"] == "alice"
            assert ctx["task_id"] == "t1"
        # 退出嵌套后恢复为 with_trace 的绑定
        assert get_log_context() == {"trace_id": "outer-tid", "user": "alice"}


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------


def test_log_event_includes_trace_id(capsys: object) -> None:
    """log_event 在 with_trace 内调用时，输出应包含 trace_id 与事件字段。"""
    setup_logging(level="INFO", json=True)
    with with_trace() as trace_id:
        log_event(
            "topic_created",
            "Topic created",
            topic_id="123",
            title="test",
        )

    data = _parse_json_log(capsys.readouterr().err, event="topic_created")  # type: ignore[attr-defined]

    assert data["trace_id"] == trace_id
    assert data["event"] == "topic_created"
    assert data["topic_id"] == "123"
    assert data["title"] == "test"
    assert data["msg"] == "Topic created"
    assert data["logger"] == "hermes.content_team"


# ---------------------------------------------------------------------------
# get_current_trace_id
# ---------------------------------------------------------------------------


def test_get_current_trace_id_outside_with_trace() -> None:
    """未进入 with_trace 时，get_current_trace_id 应返回 None。"""
    assert get_current_trace_id() is None


def test_get_current_trace_id_inside_with_trace() -> None:
    """进入 with_trace 后，get_current_trace_id 应返回当前 trace_id。"""
    with with_trace("abc123") as tid:
        assert tid == "abc123"
        assert get_current_trace_id() == "abc123"
    # 退出后恢复 None
    assert get_current_trace_id() is None

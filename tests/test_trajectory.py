"""Tests for the dispatch trajectory log + reconstruction invariant (ADR-0017)."""

from __future__ import annotations

import threading

import pytest

from hermes.trajectory import (
    TrajectoryDesyncError,
    TrajectoryLogger,
    archive_trajectory,
    assert_reconstructable,
    verify_trajectory,
)


# ── TrajectoryLogger.record ─────────────────────────────────────────


def test_record_appends_and_increments_seq(tmp_path):
    logger = TrajectoryLogger(tmp_path / "trajectory.jsonl")
    s1 = logger.record("dispatch/request", {"role": "builder"})
    s2 = logger.record("dispatch/result", {"request_seq": s1})
    assert s1 == 1
    assert s2 == 2
    assert logger.last_seq() == 2

    events = logger.events()
    assert [e.seq for e in events] == [1, 2]
    assert events[0].type == "dispatch/request"
    assert events[0].data["role"] == "builder"


def test_record_creates_parent_dir(tmp_path):
    logger = TrajectoryLogger(tmp_path / "nested" / "dir" / "trajectory.jsonl")
    logger.record("dispatch/request", {})
    assert (tmp_path / "nested" / "dir" / "trajectory.jsonl").exists()


def test_events_skips_corrupt_lines(tmp_path, caplog):
    path = tmp_path / "trajectory.jsonl"
    logger = TrajectoryLogger(path)
    logger.record("dispatch/request", {"a": 1})
    # append a corrupt line
    with open(path, "a", encoding="utf-8") as f:
        f.write("{not valid json}\n")
    logger.record("dispatch/result", {"b": 2})

    events = logger.events()
    assert len(events) == 2
    assert [e.seq for e in events] == [1, 2]  # corrupt line skipped, seq continues


def test_record_concurrent_append_seq_unique_and_monotonic(tmp_path):
    logger = TrajectoryLogger(tmp_path / "trajectory.jsonl")

    def worker():
        for _ in range(50):
            logger.record("dispatch/request", {"worker": threading.get_ident()})

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    events = logger.events()
    seqs = [e.seq for e in events]
    assert len(seqs) == 500
    assert len(set(seqs)) == 500  # 无重复
    # 文件内 seq 单调递增
    assert seqs == sorted(seqs)
    assert logger.last_seq() == 500


# ── assert_reconstructable ──────────────────────────────────────────


def _events_with_request(seq, payload):
    from hermes.trajectory import TrajectoryEvent

    return [
        TrajectoryEvent(seq=seq, type="dispatch/request", data={"payload": payload})
    ]


def test_assert_reconstructable_passes_on_match():
    payload = {"task": "hi", "allowed_tools": ["a", "b"]}
    assert_reconstructable(_events_with_request(1, payload), 1, payload)


def test_assert_reconstructable_raises_on_tamper():
    payload = {"task": "hi", "allowed_tools": ["a", "b"]}
    tampered = {"task": "hi", "allowed_tools": ["a"]}
    with pytest.raises(TrajectoryDesyncError):
        assert_reconstructable(_events_with_request(1, payload), 1, tampered)


def test_assert_reconstructable_raises_on_missing_event():
    with pytest.raises(TrajectoryDesyncError):
        assert_reconstructable([], 1, {"task": "hi"})


def test_assert_reconstructable_raises_on_wrong_seq():
    payload = {"task": "hi"}
    with pytest.raises(TrajectoryDesyncError):
        assert_reconstructable(_events_with_request(2, payload), 1, payload)


def test_logger_assert_reconstructable_round_trip(tmp_path):
    logger = TrajectoryLogger(tmp_path / "trajectory.jsonl")
    payload = {"task": "build", "context": "c", "denylist": ["auth/"]}
    seq = logger.record("dispatch/request", {"role": "builder", "payload": payload})
    logger.assert_reconstructable(seq, payload)  # 不应抛


# ── _build_spawn_payload ────────────────────────────────────────────


def test_build_spawn_payload_full_fields(tmp_path):
    from hermes.orchestrator import AgentTask, _build_spawn_payload

    agent_file = tmp_path / "builder.md"
    agent_file.write_text("do the thing", encoding="utf-8")

    task = AgentTask(
        role="builder",
        agent_file=str(agent_file),
        task_description="build it",
        context="prev",
        model="deepseek-v4-pro",
        allowed_mcp_tools=["github.get_pr"],
        tools=["read", "grep"],
        denylist=["auth/"],
    )
    payload = _build_spawn_payload(task)
    assert payload["task"] == "build it"
    assert payload["context"] == "prev"
    assert payload["model"] == "deepseek-v4-pro"
    assert payload["allowed_tools"] == ["github.get_pr"]
    assert payload["allowed_builtin_tools"] == ["read", "grep"]
    assert payload["denylist"] == ["auth/"]
    assert payload["agent_definition"] == "do the thing"
    assert payload["isolated"] is True


def test_build_spawn_payload_no_agent_file():
    from hermes.orchestrator import AgentTask, _build_spawn_payload

    task = AgentTask(role="builder", task_description="x")
    payload = _build_spawn_payload(task)
    assert "agent_definition" not in payload


def test_build_spawn_payload_matches_legacy_spawn_agent(tmp_path):
    """legacy spawn_agent 构造的 payload 与 _build_spawn_payload 等价（重构不改变行为）。"""
    from hermes.orchestrator import AgentTask, OpenClawClient, _build_spawn_payload

    agent_file = tmp_path / "builder.md"
    agent_file.write_text("do the thing", encoding="utf-8")

    task = AgentTask(
        role="builder",
        agent_file=str(agent_file),
        task_description="build it",
        context="prev",
        allowed_mcp_tools=["github.get_pr"],
        denylist=["auth/"],
    )
    direct = _build_spawn_payload(task)

    # legacy path: build payload via a captured request — use a subclass that
    # records the payload passed to the HTTP layer.
    client = OpenClawClient(port=1, token="")
    captured: dict = {}

    def fake_request(method, path, data=None, timeout=30.0):
        captured["payload"] = data
        return None

    client._request = fake_request  # type: ignore[assignment]
    client.spawn_agent(
        agent_file=str(agent_file),
        task="build it",
        context="prev",
        allowed_tools=["github.get_pr"],
        denylist=["auth/"],
    )
    assert captured["payload"] == direct


# ── Orchestrator integration ────────────────────────────────────────


def _make_orch(client, trajectory=None):
    from hermes.orchestrator import Orchestrator

    orch = Orchestrator(trajectory=trajectory)
    orch.client = client
    return orch


class _RecordingClient:
    def __init__(self):
        self.payloads: list[dict] = []
        self.spawn_calls = 0

    def health_check(self):
        return True

    def spawn_payload(self, payload):
        self.spawn_calls += 1
        self.payloads.append(payload)
        return "session-1"

    def wait_for_completion(self, session_id, timeout=300.0):
        return {"status": "completed", "tokens_used": 1000}

    def get_session_messages(self, session_id):
        return [{"role": "assistant", "content": "done"}]


def test_orchestrator_records_paired_events(tmp_path):
    from hermes.orchestrator import AgentTask

    client = _RecordingClient()
    trajectory = TrajectoryLogger(tmp_path / "trajectory.jsonl")
    orch = _make_orch(client, trajectory)

    task = AgentTask(role="builder", task_description="build", parallel=False)
    orch.fan_out([task])
    orch.fan_in([task])

    events = trajectory.events()
    requests = [e for e in events if e.type == "dispatch/request"]
    results = [e for e in events if e.type == "dispatch/result"]
    assert len(requests) == 1
    assert len(results) == 1
    assert results[0].data["request_seq"] == requests[0].seq
    assert results[0].data["status"] == "completed"
    assert results[0].data["tokens_used"] == 1000


def test_orchestrator_four_task_pairing(tmp_path):
    from hermes.orchestrator import AgentTask

    client = _RecordingClient()
    trajectory = TrajectoryLogger(tmp_path / "trajectory.jsonl")
    orch = _make_orch(client, trajectory)

    tasks = [
        AgentTask(role="builder", task_description="b", parallel=False),
        AgentTask(role="checker_lint", task_description="l", parallel=True),
        AgentTask(role="checker_type", task_description="t", parallel=True),
        AgentTask(role="checker_test", task_description="x", parallel=True),
    ]
    orch.fan_out(tasks)
    orch.fan_in(tasks)

    events = trajectory.events()
    requests = {e.seq: e for e in events if e.type == "dispatch/request"}
    results = {e.data["request_seq"]: e for e in events if e.type == "dispatch/result"}
    assert len(requests) == 4
    assert len(results) == 4
    assert set(requests) == set(results)  # 每个 request 都有配对的 result


def test_orchestrator_desync_aborts_spawn(tmp_path):
    from hermes.orchestrator import AgentTask
    from hermes.trajectory import TrajectoryDesyncError

    client = _RecordingClient()
    trajectory = TrajectoryLogger(tmp_path / "trajectory.jsonl")
    orch = _make_orch(client, trajectory)

    def _boom(seq, payload):
        raise TrajectoryDesyncError("boom")

    trajectory.assert_reconstructable = _boom  # type: ignore[method-assign]

    task = AgentTask(role="builder", task_description="build", parallel=False)
    orch.fan_out([task])

    assert client.spawn_calls == 0  # 未派发 HTTP 请求
    assert task.status == "failed"
    assert "trajectory invariant failed" in (task.result or "")
    # 失败路径也补记 result
    results = [e for e in trajectory.events() if e.type == "dispatch/result"]
    assert len(results) == 1
    assert results[0].data["status"] == "failed"


def test_orchestrator_gateway_unavailable_records_result(tmp_path):
    from hermes.orchestrator import AgentTask

    class _NoGateway:
        def health_check(self):
            return True

        def spawn_payload(self, payload):
            return None  # gateway down

    trajectory = TrajectoryLogger(tmp_path / "trajectory.jsonl")
    orch = _make_orch(_NoGateway(), trajectory)

    task = AgentTask(role="builder", task_description="build", parallel=False)
    orch.fan_out([task])

    assert task.status == "failed"
    results = [e for e in trajectory.events() if e.type == "dispatch/result"]
    assert len(results) == 1
    assert results[0].data["status"] == "failed"


def test_orchestrator_without_trajectory_is_backward_compatible():
    from hermes.orchestrator import AgentTask

    client = _RecordingClient()
    orch = _make_orch(client, trajectory=None)

    task = AgentTask(role="builder", task_description="build", parallel=False)
    orch.fan_out([task])
    assert task.session_id == "session-1"
    assert task.status == "running"


# ── workbench.llm trajectory recording ──────────────────────────────


def test_llm_chat_records_trajectory(tmp_path):
    from hermes.trajectory import TrajectoryLogger
    from hermes.workbench.llm import LlmClient, LlmMessage

    trajectory = TrajectoryLogger(tmp_path / "llm-trajectory.jsonl")

    client = LlmClient(
        base_url="http://127.0.0.1:1",
        api_key=None,
        model="test-model",
        retry_policy=None,
    )
    # 用假 _post_once 避免真实网络请求
    from hermes.workbench.llm import LlmResponse

    client._post_once = lambda url, payload, timeout: LlmResponse(content="ok")  # type: ignore[assignment]

    client.chat(
        [LlmMessage(role="user", content="hi")],
        max_tokens=100,
        trajectory=trajectory,
    )

    events = trajectory.events()
    types = [e.type for e in events]
    assert types == ["request/header", "request/context"]
    assert events[0].data["model"] == "test-model"
    assert events[0].data["max_tokens"] == 100
    assert events[1].data["request_seq"] == events[0].seq


# ── verify_trajectory ───────────────────────────────────────────────


def _write_agent_and_trajectory(tmp_path, agent_text="do the thing"):
    import hashlib

    agent_file = tmp_path / "builder.md"
    agent_file.write_text(agent_text, encoding="utf-8")
    logger = TrajectoryLogger(tmp_path / "trajectory.jsonl")
    seq = logger.record(
        "dispatch/request",
        {
            "role": "builder",
            "agent_file": str(agent_file),
            "agent_file_sha256": hashlib.sha256(agent_text.encode("utf-8")).hexdigest(),
            "payload": {"agent_definition": agent_text},
        },
    )
    logger.record(
        "dispatch/result",
        {"request_seq": seq, "role": "builder", "status": "completed"},
    )
    return tmp_path / "trajectory.jsonl", agent_file


def test_verify_trajectory_ok(tmp_path):
    path, _ = _write_agent_and_trajectory(tmp_path)
    result = verify_trajectory(path)
    assert result["ok"] is True
    assert result["requests"] == 1
    assert result["results"] == 1


def test_verify_trajectory_detects_unpaired_request(tmp_path):
    path, _ = _write_agent_and_trajectory(tmp_path)
    # 追加一个无配对的 request
    logger = TrajectoryLogger(path)
    logger.record(
        "dispatch/request",
        {"role": "builder", "agent_file": None, "payload": {}},
    )
    result = verify_trajectory(path)
    assert result["ok"] is False
    assert len(result["unpaired_requests"]) == 1


def test_verify_trajectory_detects_hash_mismatch(tmp_path):
    path, agent_file = _write_agent_and_trajectory(tmp_path)
    # 修改 agent 文件使其哈希与轨迹快照不一致
    agent_file.write_text("CHANGED", encoding="utf-8")
    result = verify_trajectory(path)
    assert result["ok"] is False
    assert len(result["hash_mismatches"]) == 1


def test_verify_trajectory_empty_file(tmp_path):
    result = verify_trajectory(tmp_path / "nonexistent.jsonl")
    assert result["ok"] is True
    assert result["events"] == 0


# ── archive_trajectory ──────────────────────────────────────────────


def test_archive_trajectory_renames(tmp_path):
    path = tmp_path / "trajectory.jsonl"
    path.write_text("old", encoding="utf-8")
    dest = archive_trajectory(path)
    assert dest is not None
    assert not path.exists()
    assert dest.name == "trajectory.1.jsonl"
    assert dest.read_text() == "old"


def test_archive_trajectory_nonexistent(tmp_path):
    assert archive_trajectory(tmp_path / "nope.jsonl") is None


def test_archive_trajectory_increments_cycle(tmp_path):
    path = tmp_path / "trajectory.jsonl"
    path.write_text("old1", encoding="utf-8")
    assert archive_trajectory(path) is not None
    # second archive increments to .2
    path.write_text("old2", encoding="utf-8")
    dest = archive_trajectory(path)
    assert dest is not None
    assert dest.name == "trajectory.2.jsonl"
    assert dest.read_text() == "old2"


def test_record_write_failure_raises(tmp_path, monkeypatch):
    from hermes.trajectory import TrajectoryLogger

    logger = TrajectoryLogger(tmp_path / "trajectory.jsonl")

    def _boom(path, obj):
        raise OSError("disk full")

    monkeypatch.setattr("hermes.trajectory.atomic_append_jsonl", _boom)
    with pytest.raises(OSError):
        logger.record("dispatch/request", {})


def test_verify_trajectory_detects_corrupt_line(tmp_path):
    from hermes.trajectory import TrajectoryLogger, verify_trajectory

    path = tmp_path / "trajectory.jsonl"
    logger = TrajectoryLogger(path)
    logger.record("dispatch/request", {"role": "b", "payload": {}})
    with open(path, "a", encoding="utf-8") as f:
        f.write("{corrupt\n")
    result = verify_trajectory(path)
    assert result["ok"] is False
    assert result["corrupt_lines"] == 1


def test_assert_reconstructable_empty_data_boundary():
    from hermes.trajectory import TrajectoryEvent

    payload = {"task": "x"}
    events = [TrajectoryEvent(seq=1, type="dispatch/request", data={})]
    with pytest.raises(TrajectoryDesyncError):
        assert_reconstructable(events, 1, payload)


def test_orchestrator_records_round_num(tmp_path):
    from hermes.orchestrator import AgentTask

    client = _RecordingClient()
    trajectory = TrajectoryLogger(tmp_path / "trajectory.jsonl")
    orch = _make_orch(client, trajectory)

    task = AgentTask(
        role="builder", task_description="build", parallel=False, round_num=7
    )
    orch.fan_out([task])
    orch.fan_in([task])

    events = trajectory.events()
    request = next(e for e in events if e.type == "dispatch/request")
    result = next(e for e in events if e.type == "dispatch/result")
    assert request.data["round_num"] == 7
    assert result.data["round_num"] == 7

"""Tests for traj_verify: append-only log, reconstruction invariant, offline audit."""

from __future__ import annotations

import hashlib
import threading

import pytest

from traj_verify import (
    TrajectoryDesyncError,
    TrajectoryEvent,
    TrajectoryLogger,
    archive_trajectory,
    assert_reconstructable,
    verify_trajectory,
)

# ── TrajectoryLogger.record ─────────────────────────────────────────


class TestRecord:
    def test_appends_and_increments_seq(self, tmp_path):
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

    def test_creates_parent_dir(self, tmp_path):
        logger = TrajectoryLogger(tmp_path / "nested" / "dir" / "trajectory.jsonl")
        logger.record("dispatch/request", {})
        assert (tmp_path / "nested" / "dir" / "trajectory.jsonl").exists()

    def test_skips_corrupt_lines(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        logger = TrajectoryLogger(path)
        logger.record("dispatch/request", {"a": 1})
        with open(path, "a", encoding="utf-8") as f:
            f.write("{not valid json}\n")
        logger.record("dispatch/result", {"b": 2})

        events = logger.events()
        assert len(events) == 2
        assert [e.seq for e in events] == [1, 2]

    def test_seq_resumes_from_existing_file(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        first = TrajectoryLogger(path)
        first.record("dispatch/request", {})
        first.record("dispatch/request", {})

        second = TrajectoryLogger(path)  # fresh instance must continue the seq
        assert second.last_seq() == 2
        assert second.record("dispatch/result", {}) == 3

    def test_concurrent_append_seq_unique_and_monotonic(self, tmp_path):
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
        assert len(set(seqs)) == 500  # no duplicates
        assert seqs == sorted(seqs)  # monotonic in file order
        assert logger.last_seq() == 500

    def test_write_failure_raises(self, tmp_path, monkeypatch):
        logger = TrajectoryLogger(tmp_path / "trajectory.jsonl")

        def _boom(path, obj):
            raise OSError("disk full")

        monkeypatch.setattr("traj_verify.trajectory.atomic_append_jsonl", _boom)
        with pytest.raises(OSError):
            logger.record("dispatch/request", {})

    def test_event_to_dict_roundtrip(self):
        ev = TrajectoryEvent(seq=1, type="dispatch/request", data={"a": 1}, time="t")
        d = ev.to_dict()
        assert d == {"seq": 1, "time": "t", "type": "dispatch/request", "data": {"a": 1}}


# ── assert_reconstructable ──────────────────────────────────────────


def _events_with_request(seq, payload):
    return [TrajectoryEvent(seq=seq, type="dispatch/request", data={"payload": payload})]


class TestAssertReconstructable:
    def test_passes_on_match(self):
        payload = {"task": "hi", "allowed_tools": ["a", "b"]}
        assert_reconstructable(_events_with_request(1, payload), 1, payload)

    def test_key_order_irrelevant(self):
        stored = _events_with_request(1, {"a": 1, "b": 2})
        assert_reconstructable(stored, 1, {"b": 2, "a": 1})

    def test_raises_on_tamper(self):
        payload = {"task": "hi", "allowed_tools": ["a", "b"]}
        tampered = {"task": "hi", "allowed_tools": ["a"]}
        with pytest.raises(TrajectoryDesyncError):
            assert_reconstructable(_events_with_request(1, payload), 1, tampered)

    def test_raises_on_missing_event(self):
        with pytest.raises(TrajectoryDesyncError):
            assert_reconstructable([], 1, {"task": "hi"})

    def test_raises_on_wrong_seq(self):
        payload = {"task": "hi"}
        with pytest.raises(TrajectoryDesyncError):
            assert_reconstructable(_events_with_request(2, payload), 1, payload)

    def test_raises_on_empty_data(self):
        events = [TrajectoryEvent(seq=1, type="dispatch/request", data={})]
        with pytest.raises(TrajectoryDesyncError):
            assert_reconstructable(events, 1, {"task": "x"})

    def test_logger_round_trip(self, tmp_path):
        logger = TrajectoryLogger(tmp_path / "trajectory.jsonl")
        payload = {"task": "build", "context": "c", "denylist": ["auth/"]}
        seq = logger.record("dispatch/request", {"role": "builder", "payload": payload})
        logger.assert_reconstructable(seq, payload)  # must not raise


# ── verify_trajectory ───────────────────────────────────────────────


def _write_agent_and_trajectory(tmp_path, agent_text="do the thing"):
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


class TestVerifyTrajectory:
    def test_ok(self, tmp_path):
        path, _ = _write_agent_and_trajectory(tmp_path)
        result = verify_trajectory(path)
        assert result["ok"] is True
        assert result["requests"] == 1
        assert result["results"] == 1
        assert result["seq_gaps"] == []

    def test_detects_unpaired_request(self, tmp_path):
        path, _ = _write_agent_and_trajectory(tmp_path)
        TrajectoryLogger(path).record("dispatch/request", {"role": "builder", "payload": {}})
        result = verify_trajectory(path)
        assert result["ok"] is False
        assert len(result["unpaired_requests"]) == 1

    def test_detects_orphan_result(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        logger = TrajectoryLogger(path)
        logger.record("dispatch/result", {"request_seq": 99, "status": "completed"})
        result = verify_trajectory(path)
        assert result["ok"] is False
        assert result["orphan_results"] == [99]

    def test_detects_malformed_result(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        logger = TrajectoryLogger(path)
        logger.record("dispatch/result", {"status": "completed"})  # no request_seq
        result = verify_trajectory(path)
        assert result["ok"] is False
        assert result["malformed_results"] == [None]

    def test_detects_hash_mismatch(self, tmp_path):
        path, agent_file = _write_agent_and_trajectory(tmp_path)
        agent_file.write_text("CHANGED", encoding="utf-8")
        result = verify_trajectory(path)
        assert result["ok"] is False
        assert len(result["hash_mismatches"]) == 1
        assert result["hash_mismatches"][0]["request_seq"] == 1

    def test_detects_seq_gap(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        logger = TrajectoryLogger(path)
        s1 = logger.record("dispatch/request", {"payload": {}})
        logger.record("dispatch/result", {"request_seq": s1})
        # hand-write seq 4 (gap at 2,3)
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"seq": 4, "type": "dispatch/request", "data": {"payload": {}}}\n')
        result = verify_trajectory(path)
        assert result["ok"] is False
        assert result["seq_gaps"] == [3]

    def test_detects_corrupt_line(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        TrajectoryLogger(path).record("dispatch/request", {"role": "b", "payload": {}})
        with open(path, "a", encoding="utf-8") as f:
            f.write("{corrupt\n")
        result = verify_trajectory(path)
        assert result["ok"] is False
        assert result["corrupt_lines"] == 1

    def test_missing_file_is_ok(self, tmp_path):
        result = verify_trajectory(tmp_path / "nonexistent.jsonl")
        assert result["ok"] is True
        assert result["events"] == 0


# ── archive_trajectory ──────────────────────────────────────────────


class TestArchiveTrajectory:
    def test_renames(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        path.write_text("old", encoding="utf-8")
        dest = archive_trajectory(path)
        assert dest is not None
        assert not path.exists()
        assert dest.name == "trajectory.1.jsonl"
        assert dest.read_text() == "old"

    def test_nonexistent_returns_none(self, tmp_path):
        assert archive_trajectory(tmp_path / "nope.jsonl") is None

    def test_increments_cycle(self, tmp_path):
        path = tmp_path / "trajectory.jsonl"
        path.write_text("old1", encoding="utf-8")
        assert archive_trajectory(path) is not None
        path.write_text("old2", encoding="utf-8")
        dest = archive_trajectory(path)
        assert dest is not None
        assert dest.name == "trajectory.2.jsonl"
        assert dest.read_text() == "old2"

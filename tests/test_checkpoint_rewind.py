"""Tests for A2 checkpoint / rewind (src/hermes/loop.py + trajectory.truncate)."""

from __future__ import annotations

import shutil

from hermes.loop import (
    LoopRound,
    LoopStatus,
    get_loop,
    init_loop,
    list_checkpoints,
    loops_dir,
    record_round,
    rewind_loop,
)


def _mk_round(n: int, passed: bool = False) -> LoopRound:
    return LoopRound(
        round_num=n,
        timestamp="2025-01-01T00:00:00Z",
        action=f"round {n}",
        result_summary=f"summary {n}",
        verifier_result="ok",
        passed=passed,
    )


def _cleanup(name: str) -> None:
    d = loops_dir() / name
    if d.exists():
        shutil.rmtree(d)


def test_checkpoint_loop_creates_checkpoint():
    name = "test-ckpt-create"
    init_loop(name, pattern="knowledge-hygiene")
    try:
        record_round(name, _mk_round(1), tokens_used=100)
        assert (loops_dir() / name / "checkpoints" / "1.json").exists()
    finally:
        _cleanup(name)


def test_list_checkpoints_sorted():
    name = "test-ckpt-list"
    init_loop(name, pattern="knowledge-hygiene")
    try:
        record_round(name, _mk_round(1), tokens_used=10)
        record_round(name, _mk_round(2), tokens_used=10)
        assert list_checkpoints(name) == [1, 2]
    finally:
        _cleanup(name)


def test_rewind_loop_truncates_rounds():
    name = "test-ckpt-rewind"
    init_loop(name, pattern="knowledge-hygiene")
    try:
        record_round(name, _mk_round(1), tokens_used=10)
        record_round(name, _mk_round(2), tokens_used=10)
        result = rewind_loop(name, 1)
        assert result["success"] is True
        loop = get_loop(name)
        assert loop is not None
        assert loop.current_round == 1
        assert len(loop.rounds) == 1
        assert loop.status == LoopStatus.NEEDS_HUMAN
    finally:
        _cleanup(name)


def test_rewind_loop_missing_checkpoint():
    name = "test-ckpt-missing"
    init_loop(name, pattern="knowledge-hygiene")
    try:
        result = rewind_loop(name, 99)
        assert result["success"] is False
    finally:
        _cleanup(name)

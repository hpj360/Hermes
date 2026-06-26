"""Tests for Loop Engineering: stop rules, state management, and orchestration."""

from __future__ import annotations

from hermes.loop import (
    LOOP_PATTERNS,
    STOP_RULES,
    LoopRound,
    check_budget,
    check_stop_rules,
    init_loop,
    list_loops,
    record_round,
)


# ── Stop Rules Tests ──────────────────────────────────────────────────


def _make_round(
    round_num: int,
    passed: bool = False,
    failure_items: list[str] | None = None,
    failure_count: int | None = None,
    result_summary: str = "",
    verifier_result: str = "",
) -> LoopRound:
    """Helper to create a LoopRound for testing."""
    if failure_items is None:
        failure_items = []
    if failure_count is None:
        failure_count = len(failure_items)
    return LoopRound(
        round_num=round_num,
        timestamp="2025-01-01T00:00:00Z",
        action="test action",
        result_summary=result_summary or "test summary",
        verifier_result=verifier_result,
        passed=passed,
        failure_count=failure_count,
        failure_items=failure_items,
    )


def test_stop_rule_all_green() -> None:
    """Rule 1: ALL GREEN — latest round passed."""
    rounds = [_make_round(1, passed=False, failure_items=["a"]), _make_round(2, passed=True)]
    result = check_stop_rules("test", current_round=2, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    assert result["rule_id"] == "all_green"
    assert result["action"] == "stop_success"


def test_stop_rule_rounds_exhausted() -> None:
    """Rule 2: Rounds exhausted — reached max_rounds."""
    rounds = [_make_round(1, passed=False, failure_items=["a"])]
    result = check_stop_rules("test", current_round=5, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    assert result["rule_id"] == "rounds_exhausted"
    assert result["action"] == "stop_escalate"


def test_stop_rule_same_failure_twice() -> None:
    """Rule 3: Same failure appears in two consecutive rounds."""
    rounds = [
        _make_round(1, passed=False, failure_items=["file.py:10 - error"]),
        _make_round(2, passed=False, failure_items=["file.py:10 - error"]),
    ]
    result = check_stop_rules("test", current_round=2, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    assert result["rule_id"] == "same_failure_twice"


def test_stop_rule_same_failure_twice_no_overlap() -> None:
    """Rule 3 should NOT trigger if failures are different."""
    rounds = [
        _make_round(1, passed=False, failure_items=["file.py:10 - error A"]),
        _make_round(2, passed=False, failure_items=["file.py:20 - error B"]),
    ]
    result = check_stop_rules("test", current_round=2, max_rounds=5, rounds=rounds)
    # May still trigger on no_progress since count didn't decrease
    assert result["rule_id"] != "same_failure_twice"


def test_stop_rule_regression() -> None:
    """Rule 4: Regression — fixing one thing broke another."""
    rounds = [
        _make_round(1, passed=False, failure_items=["a.py:1", "b.py:2"]),
        _make_round(2, passed=False, failure_items=["a.py:1", "c.py:3"]),
    ]
    result = check_stop_rules("test", current_round=2, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    assert result["rule_id"] == "regression"


def test_stop_rule_no_progress() -> None:
    """Rule 5: No progress — failure count not decreasing."""
    rounds = [
        _make_round(1, passed=False, failure_items=["a", "b"], failure_count=2),
        _make_round(2, passed=False, failure_items=["c", "d"], failure_count=2),
    ]
    result = check_stop_rules("test", current_round=2, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    assert result["rule_id"] == "no_progress"


def test_stop_rule_no_progress_count_increased() -> None:
    """Rule 3/5: When failure count increases, same_failure_twice triggers
    (because overlap exists AND count didn't decrease)."""
    rounds = [
        _make_round(1, passed=False, failure_items=["a"], failure_count=1),
        _make_round(2, passed=False, failure_items=["a", "b"], failure_count=2),
    ]
    result = check_stop_rules("test", current_round=2, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    # same_failure_twice triggers because "a" overlaps AND count increased
    assert result["rule_id"] in ("same_failure_twice", "no_progress")


def test_stop_rule_beyond_capability() -> None:
    """Rule 6: Beyond capability — external dependency signals."""
    rounds = [
        _make_round(
            1,
            passed=False,
            failure_items=["import error"],
            result_summary="ModuleNotFoundError: No module named 'requests'",
        ),
    ]
    result = check_stop_rules("test", current_round=1, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    assert result["rule_id"] == "beyond_capability"
    assert "modulenotfounderror" in result["description"].lower()


def test_stop_rule_beyond_capability_permission_denied() -> None:
    """Rule 6: Beyond capability — permission denied."""
    rounds = [
        _make_round(
            1,
            passed=False,
            failure_items=["access error"],
            verifier_result="Permission denied: cannot write to /etc/config",
        ),
    ]
    result = check_stop_rules("test", current_round=1, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    assert result["rule_id"] == "beyond_capability"


def test_stop_rule_no_trigger_on_progress() -> None:
    """No stop rule should trigger when there IS progress."""
    rounds = [
        _make_round(1, passed=False, failure_items=["a", "b", "c"], failure_count=3),
        _make_round(2, passed=False, failure_items=["a"], failure_count=1),
    ]
    result = check_stop_rules("test", current_round=2, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is False
    assert result["action"] == "continue"


def test_stop_rule_empty_rounds() -> None:
    """No rounds — should not stop."""
    result = check_stop_rules("test", current_round=0, max_rounds=5, rounds=[])
    assert result["should_stop"] is False
    assert result["action"] == "continue"


def test_stop_rule_single_round_not_passed() -> None:
    """Single round, not passed, no capability signals — should continue."""
    rounds = [_make_round(1, passed=False, failure_items=["a"])]
    result = check_stop_rules("test", current_round=1, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is False


def test_all_six_rules_defined() -> None:
    """Verify all 6 stop rules are defined in STOP_RULES."""
    assert len(STOP_RULES) == 6
    rule_ids = [r["id"] for r in STOP_RULES]
    assert "all_green" in rule_ids
    assert "rounds_exhausted" in rule_ids
    assert "same_failure_twice" in rule_ids
    assert "regression" in rule_ids
    assert "no_progress" in rule_ids
    assert "beyond_capability" in rule_ids


# ── Loop Patterns Tests ───────────────────────────────────────────────


def test_all_patterns_have_sub_agents() -> None:
    """Every pattern should have sub_agents configuration."""
    for name, pattern in LOOP_PATTERNS.items():
        assert "sub_agents" in pattern, f"Pattern '{name}' missing sub_agents config"
        assert isinstance(pattern["sub_agents"], list)
        assert len(pattern["sub_agents"]) > 0, f"Pattern '{name}' has empty sub_agents"


def test_builder_checker_has_parallel_checkers() -> None:
    """builder-checker pattern should have parallel checker agents."""
    pattern = LOOP_PATTERNS["builder-checker"]
    sub_agents = pattern["sub_agents"]
    parallel_checkers = [a for a in sub_agents if a.get("parallel") and "checker" in a["role"]]
    assert len(parallel_checkers) >= 3, "Expected at least 3 parallel checker agents"


def test_knowledge_hygiene_has_parallel_scanners() -> None:
    """knowledge-hygiene pattern should have parallel scanner agents."""
    pattern = LOOP_PATTERNS["knowledge-hygiene"]
    sub_agents = pattern["sub_agents"]
    parallel_scanners = [a for a in sub_agents if a.get("parallel")]
    assert len(parallel_scanners) >= 3, "Expected at least 3 parallel scanner agents"


# ── LoopRound Serialization Tests ─────────────────────────────────────


def test_loop_round_to_dict_from_dict_roundtrip() -> None:
    """LoopRound serialization should roundtrip correctly."""
    original = LoopRound(
        round_num=3,
        timestamp="2025-01-01T00:00:00Z",
        action="builder-checker round",
        result_summary="Fixed 2 issues",
        verifier_result="ALL GREEN",
        passed=True,
        next_action="stop",
        failure_count=0,
        failure_items=[],
        tokens_used=50000,
        agent_reports={"builder": "Fixed bugs", "checker": "ALL GREEN"},
    )
    d = original.to_dict()
    restored = LoopRound.from_dict(d)

    assert restored.round_num == original.round_num
    assert restored.timestamp == original.timestamp
    assert restored.action == original.action
    assert restored.passed == original.passed
    assert restored.tokens_used == original.tokens_used
    assert restored.agent_reports == original.agent_reports


def test_loop_round_from_dict_defaults() -> None:
    """LoopRound.from_dict should handle missing fields gracefully."""
    minimal = {"round_num": 1}
    restored = LoopRound.from_dict(minimal)
    assert restored.round_num == 1
    assert restored.passed is False
    assert restored.failure_items == []
    assert restored.tokens_used == 0


# ── LoopState Persistence Tests ───────────────────────────────────────


def test_init_and_list_loop() -> None:
    """init_loop creates a loop, list_loops finds it."""
    from hermes.loop import loops_dir

    try:
        result = init_loop("test-temp-loop", pattern="knowledge-hygiene")
        assert result["success"] is True
        assert result["name"] == "test-temp-loop"
        assert "STATE.md" in result["files"]
        assert "loop-budget.md" in result["files"]

        # Verify it shows in list_loops
        loops = list_loops()
        assert any(lp.name == "test-temp-loop" for lp in loops)
    finally:
        import shutil
        test_dir = loops_dir() / "test-temp-loop"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_record_round_persists() -> None:
    """record_round should persist round data to meta.json."""
    import shutil
    from hermes.loop import get_loop, loops_dir

    # Create a test loop
    result = init_loop("test-record-loop", pattern="knowledge-hygiene")
    assert result["success"]

    try:
        # Record a round
        round_data = LoopRound(
            round_num=1,
            timestamp="2025-01-01T00:00:00Z",
            action="test scan",
            result_summary="Found 2 issues",
            verifier_result="2 high priority",
            passed=False,
            failure_count=2,
            failure_items=["issue1", "issue2"],
            tokens_used=10000,
        )
        record_result = record_round("test-record-loop", round_data, tokens_used=10000)
        assert record_result["success"] is True
        assert record_result["round"] == 1
        assert record_result["tokens_used"] == 10000

        # Reload and verify persistence
        loop = get_loop("test-record-loop")
        assert loop is not None
        assert len(loop.rounds) == 1
        assert loop.rounds[0].round_num == 1
        assert loop.rounds[0].failure_items == ["issue1", "issue2"]
        assert loop.rounds[0].tokens_used == 10000
        assert loop.budget_used_tokens == 10000
        assert loop.current_round == 1
    finally:
        # Clean up
        test_dir = loops_dir() / "test-record-loop"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_check_budget_ok() -> None:
    """check_budget should return 'ok' when under 80%."""
    import shutil
    from hermes.loop import loops_dir

    result = init_loop("test-budget-loop", pattern="knowledge-hygiene")
    assert result["success"]

    try:
        budget = check_budget("test-budget-loop")
        assert budget["success"] is True
        assert budget["level"] == "ok"
        assert budget["action"] == "continue"
        assert budget["percentage"] == 0.0
    finally:
        test_dir = loops_dir() / "test-budget-loop"
        if test_dir.exists():
            shutil.rmtree(test_dir)


# ── Orchestrator Tests ────────────────────────────────────────────────


def test_orchestrator_unavailable_graceful() -> None:
    """Orchestrator should gracefully handle unavailable gateway."""
    from hermes.orchestrator import Orchestrator

    orch = Orchestrator()
    # Gateway is not running in test environment
    available = orch.is_available()
    assert available is False


def test_agent_task_serialization() -> None:
    """AgentTask should serialize to dict correctly."""
    from hermes.orchestrator import AgentTask

    task = AgentTask(
        role="builder",
        agent_file="/path/to/builder.md",
        task_description="Fix tests",
        parallel=False,
    )
    d = task.to_dict()
    assert d["role"] == "builder"
    assert d["agent_file"] == "/path/to/builder.md"
    assert d["status"] == "pending"


def test_round_result_serialization() -> None:
    """RoundResult should serialize to dict correctly."""
    from hermes.orchestrator import AgentTask, RoundResult

    tasks = [AgentTask(role="checker", result="ALL GREEN", status="completed")]
    result = RoundResult(
        round_num=1,
        tasks=tasks,
        all_passed=True,
        total_tokens=5000,
        summary="Round 1: ALL GREEN",
    )
    d = result.to_dict()
    assert d["round_num"] == 1
    assert d["all_passed"] is True
    assert d["total_tokens"] == 5000
    assert len(d["tasks"]) == 1

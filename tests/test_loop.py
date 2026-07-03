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
    """新互斥设计: {a}→{a,b} 引入新失败且有重复 → regression（改坏了）。

    旧设计此处用 "或" 断言掩盖了规则优先级 bug；新互斥设计下明确归为
    regression（new≠∅ AND overlap≠∅），不再依赖评估顺序的偶然性。
    """
    rounds = [
        _make_round(1, passed=False, failure_items=["a"], failure_count=1),
        _make_round(2, passed=False, failure_items=["a", "b"], failure_count=2),
    ]
    result = check_stop_rules("test", current_round=2, max_rounds=5, rounds=rounds)
    assert result["should_stop"] is True
    assert result["rule_id"] == "regression"


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


def test_all_stop_rules_defined() -> None:
    """Verify all stop rules are defined in STOP_RULES (1 success + 6 stop)."""
    assert len(STOP_RULES) == 7
    rule_ids = [r["id"] for r in STOP_RULES]
    assert "all_green" in rule_ids
    assert "rounds_exhausted" in rule_ids
    assert "budget_exceeded" in rule_ids
    assert "same_failure_twice" in rule_ids
    assert "regression" in rule_ids
    assert "no_progress" in rule_ids
    assert "beyond_capability" in rule_ids


def test_stop_rules_order_matches_evaluation() -> None:
    """STOP_RULES 列表顺序必须等于 check_stop_rules 评估顺序（发现4.2 一致性）。"""
    expected = [
        "all_green",
        "rounds_exhausted",
        "budget_exceeded",
        "beyond_capability",
        "regression",
        "same_failure_twice",
        "no_progress",
    ]
    assert [r["id"] for r in STOP_RULES] == expected


def test_stop_rules_mutually_exclusive() -> None:
    """互斥设计验证：regression/same_failure_twice/no_progress 三者条件不重叠。

    构造三个典型场景，各自只触发一条规则，证明无遮蔽。
    """
    # regression: new≠∅ AND overlap≠∅  ({a,b}→{a,c})
    r = check_stop_rules(
        "t", 2, 5,
        [_make_round(1, failure_items=["a.py:1", "b.py:2"]),
         _make_round(2, failure_items=["a.py:1", "c.py:3"])],
    )
    assert r["rule_id"] == "regression"

    # same_failure_twice: new=∅ AND overlap≠∅ AND count未减  ({a}→{a})
    r = check_stop_rules(
        "t", 2, 5,
        [_make_round(1, failure_items=["x.py:1"], failure_count=1),
         _make_round(2, failure_items=["x.py:1"], failure_count=1)],
    )
    assert r["rule_id"] == "same_failure_twice"

    # no_progress: new≠∅ AND overlap=∅ AND fixed≠∅ AND count未减  ({a,b}→{c,d})
    r = check_stop_rules(
        "t", 2, 5,
        [_make_round(1, failure_items=["a", "b"], failure_count=2),
         _make_round(2, failure_items=["c", "d"], failure_count=2)],
    )
    assert r["rule_id"] == "no_progress"


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
        # 阶段F: meta.json must carry schema_version.
        import json as _json

        meta = _json.loads((loops_dir() / "test-record-loop" / "meta.json").read_text("utf-8"))
        assert meta["schema_version"] == 1
    finally:
        # Clean up
        test_dir = loops_dir() / "test-record-loop"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_meta_schema_version_v0_backcompat() -> None:
    """阶段F: 旧版 meta.json（无 schema_version，v0）应能加载，不崩溃。

    旧文件缺 agent_reports/tokens_used 等字段，from_dict 默认值兜底；
    list_loops 不再静默吞错。
    """
    import json as _json
    import shutil
    from hermes.loop import _load_loop_meta, loops_dir

    loop_dir = loops_dir() / "test-v0-meta"
    loop_dir.mkdir(parents=True, exist_ok=True)
    # v0-style meta: no schema_version, minimal fields.
    v0_meta = {"pattern": "custom", "status": "idle", "stage": "l1_report", "rounds": []}
    (loop_dir / "meta.json").write_text(_json.dumps(v0_meta), encoding="utf-8")
    try:
        state = _load_loop_meta(v0_meta, "test-v0-meta")
        assert state is not None
        assert state.rounds == []
        assert state.budget_used_tokens == 0  # default
    finally:
        shutil.rmtree(loop_dir, ignore_errors=True)


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


# ── Adversarial review regression tests ──────────────────────────────


def test_aggregate_results_empty_checker_output_is_failure() -> None:
    """Bug 1 (CRITICAL): empty/None checker result must NOT be treated as success.

    The loop's own red line says 'never report success without checker output'.
    Previously `if task.result:` skipped the checker when result was empty,
    leaving all_passed=True and marking the loop COMPLETED with zero verification.
    """
    from hermes.orchestrator import AgentTask, Orchestrator

    orch = Orchestrator()
    tasks = [
        AgentTask(role="builder", status="completed", result="done", session_id="b", tokens_used=5000),
        AgentTask(role="checker_lint", status="completed", result="", session_id="c", tokens_used=1000),
    ]
    result = orch.aggregate_results(tasks, round_num=1)
    assert result.all_passed is False, "empty checker output was misjudged as ALL GREEN"


def test_aggregate_results_none_checker_output_is_failure() -> None:
    """Bug 1 variant: None checker result must also be treated as failure."""
    from hermes.orchestrator import AgentTask, Orchestrator

    orch = Orchestrator()
    tasks = [
        AgentTask(role="builder", status="completed", result="done", session_id="b"),
        AgentTask(role="checker_lint", status="completed", result=None, session_id="c"),
    ]
    result = orch.aggregate_results(tasks, round_num=1)
    assert result.all_passed is False


def test_aggregate_results_all_green_case_insensitive() -> None:
    """Bug 1.4: 'All Green' (non-uppercase) must still be recognized as success."""
    from hermes.orchestrator import AgentTask, Orchestrator

    orch = Orchestrator()
    tasks = [
        AgentTask(role="checker_lint", status="completed", result="All Green. lint: 0 errors", session_id="c"),
    ]
    result = orch.aggregate_results(tasks, round_num=1)
    assert result.all_passed is True


def test_aggregate_results_structured_failures_protocol() -> None:
    """阶段B: 结构化失败协议块应被解析为归一化 (file|type) 键，丢弃行号。

    这让 stop-rule set 比较能抵抗行号漂移（builder 编辑上方行导致行号 +1）。
    """
    from hermes.orchestrator import AgentTask, Orchestrator

    orch = Orchestrator()
    report = (
        "FAILED\n"
        "src/auth.py:42 - ImportError\n"
        "<!-- failures:json -->\n"
        '{"passed": false, "failures": [{"file": "src/auth.py", "line": 42, "type": "ImportError"}]}\n'
        "<!-- /failures -->"
    )
    tasks = [AgentTask(role="checker_lint", status="completed", result=report, session_id="c")]
    result = orch.aggregate_results(tasks, round_num=1)
    assert result.all_passed is False
    # Normalized key drops line number: "checker_lint: src/auth.py|ImportError"
    assert any("src/auth.py|ImportError" in f for f in result.failure_items)
    # Line number 42 must NOT appear in the normalized failure item.
    assert all(": 42" not in f for f in result.failure_items)


def test_aggregate_results_line_drift_survives_structured_protocol() -> None:
    """阶段B: 同一失败因行号漂移（42→43）仍应被 stop-rule 识别为重复。

    旧启发式提取整行 "src/auth.py:42"，行号变即 set 不匹配；新协议用
    file|type 归一化，行号漂移后仍判定 same_failure_twice。
    """
    from hermes.orchestrator import AgentTask, Orchestrator

    orch = Orchestrator()
    report_r1 = (
        "FAILED\n<!-- failures:json -->\n"
        '{"passed": false, "failures": [{"file": "src/auth.py", "line": 42, "type": "ImportError"}]}\n'
        "<!-- /failures -->"
    )
    report_r2 = (
        "FAILED\n<!-- failures:json -->\n"
        '{"passed": false, "failures": [{"file": "src/auth.py", "line": 43, "type": "ImportError"}]}\n'
        "<!-- /failures -->"
    )
    r1 = orch.aggregate_results(
        [AgentTask(role="checker_lint", status="completed", result=report_r1, session_id="c")], 1
    )
    r2 = orch.aggregate_results(
        [AgentTask(role="checker_lint", status="completed", result=report_r2, session_id="c")], 2
    )
    # Same normalized key → set intersection non-empty → regression/same_failure_twice reachable.
    assert set(r1.failure_items) & set(r2.failure_items), "line drift broke failure identity"


def test_aggregate_results_fallback_no_structured_block() -> None:
    """阶段B: 无结构化块时回退到 verbatim 首行，不启发式猜测 file:line。"""
    from hermes.orchestrator import AgentTask, Orchestrator

    orch = Orchestrator()
    report = "FAILED\nsomething went wrong in the build"
    tasks = [AgentTask(role="checker_test", status="completed", result=report, session_id="c")]
    result = orch.aggregate_results(tasks, round_num=1)
    assert result.all_passed is False
    # Fallback item is role-prefixed verbatim, not a guessed "file:" line.
    assert len(result.failure_items) == 1
    assert result.failure_items[0].startswith("checker_test:")


def test_loop_round_from_dict_explicit_none_normalized() -> None:
    """Bug 2 (HIGH): explicit None in failure_items/agent_reports must be
    normalized to defaults, not crash downstream set()/dict() operations."""
    data = {
        "round_num": 1,
        "passed": False,
        "failure_items": None,
        "failure_count": 1,
        "result_summary": "x",
        "verifier_result": "x",
        "agent_reports": None,
    }
    r = LoopRound.from_dict(data)
    assert r.failure_items == []
    assert r.agent_reports == {}
    # Downstream stop-rule evaluation must not crash (None normalized to []).
    r2 = LoopRound.from_dict({**data, "round_num": 2})
    result = check_stop_rules("t", 2, 5, [r, r2])
    # With empty failure_items, no regression/same_failure/no_progress triggers;
    # the point is that it returns without raising TypeError.
    assert "should_stop" in result


def test_loop_round_json_roundtrip_with_agent_reports() -> None:
    """Bug 1.4 (test): full JSON disk roundtrip must preserve agent_reports
    (including non-ASCII content), not just in-memory dict roundtrip."""
    original = LoopRound(
        round_num=1,
        timestamp="2026-01-01T00:00:00Z",
        action="build",
        result_summary="summary",
        verifier_result="verifier",
        passed=False,
        failure_count=2,
        failure_items=["src/文件.py:42 - ImportError", "src/other.py:10 - 错误"],
        tokens_used=12345,
        agent_reports={
            "checker_lint": "FAILED\nsrc/文件.py:42 - ImportError",
            "checker_test": "ALL GREEN",
        },
    )
    import json

    serialized = json.dumps(original.to_dict(), ensure_ascii=False)
    restored = LoopRound.from_dict(json.loads(serialized))
    assert restored.failure_items == original.failure_items
    assert restored.agent_reports == original.agent_reports
    assert restored.tokens_used == 12345

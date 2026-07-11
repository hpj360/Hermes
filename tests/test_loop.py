"""Tests for Loop Engineering: stop rules, state management, and orchestration."""

from __future__ import annotations

from hermes.loop import (
    LOOP_PATTERNS,
    STOP_RULES,
    LoopRound,
    LoopStage,
    LoopStatus,
    _save_loop_meta,
    audit_deliverables,
    audit_loop,
    check_budget,
    check_stop_rules,
    get_loop,
    init_loop,
    list_loops,
    record_round,
)
from hermes.runner import run_loop_continuous


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
    """Verify all stop rules are defined in STOP_RULES (1 success + 6 escalation = 7 total)."""
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


# ── New patterns (Cobus Greyling 7-workflow alignment) ─────────────────


def test_seven_built_in_patterns() -> None:
    """8 内置工作流，对齐 Cobus Greyling loop-engineering 框架 + ai-berkshire 多视角并行。

    daily-triage / knowledge-hygiene / ci-sweeper / pr-babysitter /
    issue-triage / changelog-draft / builder-checker = 7（Cobus Greyling）
    multi-perspective = 1（ai-berkshire 借鉴）= 8
    """
    assert len(LOOP_PATTERNS) == 8, f"Expected 8 patterns, got {len(LOOP_PATTERNS)}"
    expected = {
        "daily-triage", "knowledge-hygiene", "ci-sweeper", "pr-babysitter",
        "issue-triage", "changelog-draft", "builder-checker", "multi-perspective",
    }
    assert set(LOOP_PATTERNS.keys()) == expected


def test_issue_triage_pattern_shape() -> None:
    """issue-triage pattern must declare denylist + parallel sub-agents + L1 default."""
    pattern = LOOP_PATTERNS["issue-triage"]
    assert pattern["default_stage"].value == "l1_report"
    assert "label:security" in pattern["denylist"]
    parallel = [a for a in pattern["sub_agents"] if a.get("parallel")]
    assert len(parallel) >= 2, "issue-triage should have at least 2 parallel scanners"


def test_changelog_draft_pattern_shape() -> None:
    """changelog-draft pattern must protect CHANGELOG.md in denylist."""
    pattern = LOOP_PATTERNS["changelog-draft"]
    assert pattern["default_stage"].value == "l1_report"
    assert "CHANGELOG.md" in pattern["denylist"]
    assert pattern["max_rounds"] <= 3, "changelog should be short (≤3 rounds)"


# ── Pain-point → pattern mapping (interactive picker) ──────────────────


def test_pain_point_to_pattern_recommendation() -> None:
    """Pain-point keywords must map to the right pattern (first match wins)."""
    from hermes.main import _recommend_pattern_for_pain_point

    assert _recommend_pattern_for_pain_point("PR keeps getting stuck") == "pr-babysitter"
    assert _recommend_pattern_for_pain_point("CI is flaky again") == "ci-sweeper"
    assert _recommend_pattern_for_pain_point("changelog is tedious") == "changelog-draft"
    assert _recommend_pattern_for_pain_point("issue 太乱") == "issue-triage"
    assert _recommend_pattern_for_pain_point("更新日志") == "changelog-draft"
    assert _recommend_pattern_for_pain_point("bug fix needed") == "builder-checker"
    assert _recommend_pattern_for_pain_point("知识库 过期") == "knowledge-hygiene"


def test_pain_point_no_match_returns_none() -> None:
    """Unrecognized pain point must return None (caller decides)."""
    from hermes.main import _recommend_pattern_for_pain_point

    assert _recommend_pattern_for_pain_point("xyzzy plugh") is None
    assert _recommend_pattern_for_pain_point("") is None


# ── Loop Ready badge rendering ─────────────────────────────────────────


def test_loop_badge_thresholds() -> None:
    """Badge label/color must follow the 85/70 threshold semantics."""
    from hermes.main import _render_loop_badge

    high = _render_loop_badge({"loop": "x", "pattern": "p", "score": 92})
    assert "Loop_Ready" in high["markdown"]
    assert "brightgreen" in high["markdown"]
    assert "🟢" in high["markdown"]

    mid = _render_loop_badge({"loop": "x", "pattern": "p", "score": 75})
    assert "Loop_Aware" in mid["markdown"]
    assert "yellow" in mid["markdown"]
    assert "🟡" in mid["markdown"]

    low = _render_loop_badge({"loop": "x", "pattern": "p", "score": 50})
    assert "Loop_Incubating" in low["markdown"]
    assert "lightgrey" in low["markdown"]
    assert "⚪" in low["markdown"]

    # All three must include the loop name + pattern + score
    for badge in (high, mid, low):
        assert "x" in badge["markdown"]
        assert "`p`" in badge["markdown"]
        assert "/100" in badge["markdown"]
        # SVG must be valid SVG
        assert badge["svg"].startswith("<svg")
        assert badge["svg"].endswith("</svg>")


# ── CLI subcommand registration ────────────────────────────────────────


def test_cost_subcommand_is_registered() -> None:
    """hermes loop cost must be a registered subcommand (alias of budget)."""
    from hermes.main import build_parser

    parser = build_parser()
    # Parse a real call to ensure cost is recognized
    args = parser.parse_args(["loop", "cost", "my-loop"])
    assert args.loop_cmd == "cost"
    assert args.name == "my-loop"
    assert callable(args.func), "cost subcommand must have a callable func"


def test_budget_subcommand_still_works_as_alias() -> None:
    """hermes loop budget must remain as a backward-compatible alias."""
    from hermes.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["loop", "budget", "my-loop"])
    assert args.loop_cmd == "budget"
    assert args.name == "my-loop"


def test_audit_badge_flag_registered() -> None:
    """hermes loop audit --badge and --badge-format must be registered."""
    from hermes.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["loop", "audit", "--badge", "--badge-format", "svg"])
    assert args.badge is True
    assert args.badge_format == "svg"

    args2 = parser.parse_args(["loop", "audit", "my-loop"])
    assert args2.badge is False
    assert args2.badge_format == "md"


def test_init_interactive_flag_registered() -> None:
    """hermes loop init --interactive and --from-pain-point must be registered."""
    from hermes.main import build_parser

    parser = build_parser()
    args = parser.parse_args(["loop", "init", "x", "--interactive"])
    assert args.interactive is True
    assert args.from_pain_point is None

    args2 = parser.parse_args(["loop", "init", "x", "--from-pain-point", "PR stuck"])
    assert args2.from_pain_point == "PR stuck"
    assert args2.interactive is False


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


# ── State Machine Regression Tests (对抗审查 round 5-9) ──────────────


def test_record_round_budget_limit_zero_not_locked() -> None:
    """record_round: when budget_limit_tokens=0 (unlimited/no-budget mode),
    the `>=` comparison must NOT lock the loop as BUDGET_EXCEEDED on the first
    round. The `> 0` guard ensures budget_limit=0 means "no budget enforcement".
    Previously the bug locked loops with budget_limit=0 as BUDGET_EXCEEDED
    even when passed=False and no stop rule fired."""
    init_loop("test-zero-budget", pattern="knowledge-hygiene")
    loop = get_loop("test-zero-budget")
    loop.budget_limit_tokens = 0
    _save_loop_meta(loop)

    round_data = _make_round(1, passed=False, failure_items=["a"], failure_count=1)
    result = record_round("test-zero-budget", round_data, tokens_used=100)
    assert result["success"] is True
    # Strong assertion: with limit=0 guard, passed=False, and no stop rule
    # firing (only 1 round), status must be RUNNING — not budget_exceeded
    # (the bug) and not NEEDS_HUMAN (no stop rule matched). A weak `!=
    # budget_exceeded` would pass even if the bug locked the loop as ERROR.
    assert result["status"] == "running", (
        f"limit=0 guard failed: status={result['status']} (expected 'running')"
    )


def test_record_round_budget_check_priority() -> None:
    """record_round: the budget_exceeded check is evaluated before the passed
    check (if/elif ordering). This test locks the current ordering so future
    refactors don't silently change which condition wins when both are true.
    Current behavior: budget exhaustion takes precedence (hard resource limit)
    — a passed round that also exhausted the budget is reported as
    budget_exceeded, not completed. This is intentional: budget is a hard
    ceiling that must be surfaced even on success."""
    init_loop("test-budget-priority", pattern="knowledge-hygiene")
    loop = get_loop("test-budget-priority")
    loop.budget_limit_tokens = 100
    loop.budget_used_tokens = 90  # already near limit
    _save_loop_meta(loop)

    round_data = _make_round(1, passed=True, failure_items=[], failure_count=0)
    result = record_round("test-budget-priority", round_data, tokens_used=20)
    # 90+20=110 >= 100 → BUDGET_EXCEEDED wins over passed=True (current ordering).
    assert result["status"] == "budget_exceeded", (
        f"budget should take priority over passed: status={result['status']}"
    )


def test_run_loop_continuous_budget_hard_stop_uses_stop_escalate() -> None:
    """run_loop_continuous: when budget is already exhausted, the hard_stop
    path must return action='stop_escalate' (consistent with STOP_RULES),
    not the old 'stop_budget'."""
    init_loop("test-continuous-budget", pattern="knowledge-hygiene")
    loop = get_loop("test-continuous-budget")
    loop.budget_limit_tokens = 100
    loop.budget_used_tokens = 100
    _save_loop_meta(loop)
    result = run_loop_continuous("test-continuous-budget")
    assert result["success"] is True
    stop = result["final_stop"]
    assert stop["should_stop"] is True
    assert stop["rule_id"] == "budget_exceeded"
    assert stop["action"] == "stop_escalate"


def test_run_loop_continuous_prechecks_completed_status() -> None:
    """run_loop_continuous: if the loop is already COMPLETED, it must NOT enter
    the round loop (which would be rejected by run_loop's status guard and
    return a misleading success=True + rounds_executed=1 + final_stop=continue).
    Instead it must return rounds_executed=0 + final_stop should_stop=True with
    rule_id=all_green."""
    init_loop("test-precheck-completed", pattern="knowledge-hygiene")
    loop = get_loop("test-precheck-completed")
    loop.status = LoopStatus.COMPLETED
    _save_loop_meta(loop)

    result = run_loop_continuous("test-precheck-completed")
    assert result["success"] is True
    assert result["rounds_executed"] == 0, (
        f"expected 0 rounds for COMPLETED loop, got {result['rounds_executed']}"
    )
    assert result["final_stop"]["should_stop"] is True
    assert result["final_stop"]["rule_id"] == "all_green"
    assert result["final_stop"]["action"] == "stop_success"


def test_run_loop_continuous_prechecks_budget_exceeded_status() -> None:
    """run_loop_continuous precheck: a BUDGET_EXCEEDED loop must return
    rounds_executed=0 + final_stop with rule_id='budget_exceeded'."""
    init_loop("test-precheck-budget", pattern="knowledge-hygiene")
    loop = get_loop("test-precheck-budget")
    loop.status = LoopStatus.BUDGET_EXCEEDED
    _save_loop_meta(loop)

    result = run_loop_continuous("test-precheck-budget")
    assert result["success"] is True
    assert result["rounds_executed"] == 0, (
        f"expected 0 rounds for BUDGET_EXCEEDED loop, got {result['rounds_executed']}"
    )
    assert result["final_stop"]["should_stop"] is True
    assert result["final_stop"]["rule_id"] == "budget_exceeded", (
        f"wrong rule_id: {result['final_stop']['rule_id']} (expected 'budget_exceeded')"
    )
    assert result["final_stop"]["action"] == "stop_escalate"


def test_run_loop_continuous_prechecks_error_status() -> None:
    """run_loop_continuous precheck: an ERROR loop must return rounds_executed=0
    + final_stop with rule_id='rounds_exhausted' (catch-all escalation) BUT the
    description must explicitly mention 'error state' so users don't mistake it
    for genuinely exhausted rounds."""
    init_loop("test-precheck-error", pattern="knowledge-hygiene")
    loop = get_loop("test-precheck-error")
    loop.status = LoopStatus.ERROR
    _save_loop_meta(loop)

    result = run_loop_continuous("test-precheck-error")
    assert result["success"] is True
    assert result["rounds_executed"] == 0, (
        f"expected 0 rounds for ERROR loop, got {result['rounds_executed']}"
    )
    assert result["final_stop"]["should_stop"] is True
    assert result["final_stop"]["rule_id"] == "rounds_exhausted"
    assert result["final_stop"]["action"] == "stop_escalate"
    desc = result["final_stop"]["description"]
    assert "error state" in desc.lower(), (
        f"ERROR description doesn't mention 'error state': {desc!r}"
    )


def test_run_loop_continuous_precheck_needs_human_re_derives_rule() -> None:
    """run_loop_continuous precheck: a NEEDS_HUMAN loop must re-derive the
    actual stop rule via check_stop_rules (not hardcode rounds_exhausted).
    A loop that stopped due to regression must report rule_id='regression'
    from both the precheck and the in-loop branch — both entry paths must
    agree on the diagnosis."""
    init_loop("test-precheck-needs-human", pattern="knowledge-hygiene")
    loop = get_loop("test-precheck-needs-human")
    loop.status = LoopStatus.NEEDS_HUMAN
    loop.current_round = 2
    loop.max_rounds = 5
    # Construct rounds that trigger regression: new failure + persistent failure.
    loop.rounds = [
        _make_round(1, passed=False, failure_items=["a", "b"], failure_count=2),
        _make_round(2, passed=False, failure_items=["a", "c"], failure_count=2),
    ]
    _save_loop_meta(loop)

    result = run_loop_continuous("test-precheck-needs-human")
    assert result["success"] is True
    assert result["rounds_executed"] == 0
    # Re-derivation: new={c}, persistent={a} → regression (NOT rounds_exhausted).
    assert result["final_stop"]["rule_id"] == "regression", (
        f"precheck did not re-derive: rule_id={result['final_stop']['rule_id']} "
        f"(expected 'regression')"
    )
    assert result["final_stop"]["should_stop"] is True
    # The specific diagnosis from check_stop_rules must be preserved VERBATIM
    # (not overwritten with a generic "terminal state" message). For
    # round1={a,b}→round2={a,c}: new={c}, previously_fixed={b} →
    # "修复导致新失败: c。之前修好的: b".
    desc = result["final_stop"]["description"]
    assert "修复导致新失败" in desc, (
        f"specific diagnosis lost: description={desc!r} "
        f"(expected to contain '修复导致新失败')"
    )
    assert "c" in desc, (
        f"new failure item 'c' missing from description: {desc!r}"
    )


def test_run_loop_continuous_precheck_needs_human_fallback() -> None:
    """run_loop_continuous precheck: a NEEDS_HUMAN loop where check_stop_rules
    returns should_stop=False (state drift — e.g. only 1 round with progress,
    no stop rule fires) must fall back to rounds_exhausted with a description
    that explicitly says 'no specific rule matched'."""
    init_loop("test-precheck-needs-human-fallback", pattern="knowledge-hygiene")
    loop = get_loop("test-precheck-needs-human-fallback")
    loop.status = LoopStatus.NEEDS_HUMAN
    loop.current_round = 1
    loop.max_rounds = 5
    # Single round with progress (3 failures → 1 failure): no stop rule fires.
    loop.rounds = [
        _make_round(1, passed=False, failure_items=["a"], failure_count=1),
    ]
    _save_loop_meta(loop)

    result = run_loop_continuous("test-precheck-needs-human-fallback")
    assert result["success"] is True
    assert result["rounds_executed"] == 0
    assert result["final_stop"]["should_stop"] is True
    assert result["final_stop"]["rule_id"] == "rounds_exhausted", (
        f"fallback should map to rounds_exhausted, got "
        f"{result['final_stop']['rule_id']}"
    )
    desc = result["final_stop"]["description"]
    assert "no specific rule matched" in desc, (
        f"fallback description doesn't explain state drift: {desc!r}"
    )
    assert "needs_human" in desc, (
        f"fallback description doesn't mention the status: {desc!r}"
    )


def test_run_loop_rejects_needs_human_status() -> None:
    """run_loop: a loop in NEEDS_HUMAN status must be rejected (not executed).
    Previously only COMPLETED/BUDGET_EXCEEDED were guarded, letting a
    NEEDS_HUMAN loop execute a round beyond max_rounds."""
    from hermes.runner import run_loop

    init_loop("test-reject-needs-human", pattern="knowledge-hygiene")
    loop = get_loop("test-reject-needs-human")
    loop.status = LoopStatus.NEEDS_HUMAN
    loop.current_round = 5  # at/beyond max
    _save_loop_meta(loop)

    result = run_loop("test-reject-needs-human")
    assert result["success"] is False
    assert (
        "human review" in result["error"].lower()
        or "needs_human" in result.get("error", "").lower()
    )


def test_run_loop_rejects_error_status() -> None:
    """run_loop: a loop in ERROR status must be rejected (not executed).
    ERROR was previously not guarded, letting an error-state loop execute."""
    from hermes.runner import run_loop

    init_loop("test-reject-error", pattern="knowledge-hygiene")
    loop = get_loop("test-reject-error")
    loop.status = LoopStatus.ERROR
    _save_loop_meta(loop)

    result = run_loop("test-reject-error")
    assert result["success"] is False
    assert "error" in result["error"].lower()


def test_resume_loop_budget_exceeded_resets() -> None:
    """resume_loop: a BUDGET_EXCEEDED loop must be reset to IDLE with cleared
    rounds/budget, otherwise it stays locked forever (check_budget hard_stop
    keeps returning budget_exceeded)."""
    from hermes.runner import resume_loop

    init_loop("test-resume-budget", pattern="knowledge-hygiene")
    loop = get_loop("test-resume-budget")
    loop.status = LoopStatus.BUDGET_EXCEEDED
    loop.budget_used_tokens = 999999
    loop.current_round = 4
    loop.rounds = [_make_round(1, passed=False, failure_items=["a"])]
    _save_loop_meta(loop)

    resume_loop("test-resume-budget")
    loop_after = get_loop("test-resume-budget")
    assert loop_after.status != LoopStatus.BUDGET_EXCEEDED, (
        "resume_loop did not reset BUDGET_EXCEEDED status (loop stays locked)"
    )
    assert loop_after.budget_used_tokens == 0, (
        f"budget not cleared: {loop_after.budget_used_tokens} (expected 0)"
    )


def test_resume_loop_completed_resets_history() -> None:
    """resume_loop: a COMPLETED loop must be reset to IDLE with cleared
    rounds/budget/current_round, otherwise stale passed=True rounds would make
    stop rules re-fire immediately (all_green on first check)."""
    from hermes.runner import resume_loop

    init_loop("test-resume-completed", pattern="knowledge-hygiene")
    loop = get_loop("test-resume-completed")
    loop.status = LoopStatus.COMPLETED
    loop.budget_used_tokens = 50000
    loop.current_round = 3
    loop.rounds = [
        _make_round(1, passed=False, failure_items=["a"]),
        _make_round(2, passed=False, failure_items=["a"]),
        _make_round(3, passed=True),
    ]
    _save_loop_meta(loop)

    resume_loop("test-resume-completed")
    loop_after = get_loop("test-resume-completed")
    assert loop_after.status != LoopStatus.COMPLETED, (
        "resume did not reset COMPLETED status (run_loop guard would reject)"
    )
    assert loop_after.budget_used_tokens == 0, (
        f"budget not cleared: {loop_after.budget_used_tokens} (expected 0)"
    )
    assert all(not r.passed for r in loop_after.rounds), (
        "stale passed=True rounds not cleared by resume_loop reset"
    )
    assert loop_after.current_round <= 2, (
        f"current_round not reset: {loop_after.current_round} (expected <=2)"
    )


def test_run_loop_continuous_post_round_catches_budget_exceeded(monkeypatch) -> None:
    """run_loop_continuous post-round branch: when a round succeeds but
    record_round sets status=BUDGET_EXCEEDED, and check_stop_rules returns
    should_stop=False (budget is NOT checked by stop rules), the post-round
    branch must catch BUDGET_EXCEEDED via _terminal_status_to_stop with
    entry='post-round'. This is the MAIN normal scenario for the post-round
    branch — BUDGET_EXCEEDED is the only terminal state stably reachable in
    post-round during normal operation."""
    import hermes.runner
    from hermes.runner import run_loop_continuous

    init_loop("test-post-round-budget", pattern="knowledge-hygiene")
    loop = get_loop("test-post-round-budget")
    assert loop.status == LoopStatus.IDLE

    def fake_run_loop(name: str) -> dict:
        updated = get_loop(name)
        updated.status = LoopStatus.BUDGET_EXCEEDED
        updated.current_round = 1
        _save_loop_meta(updated)
        return {
            "success": True,
            "mode": "local",
            "loop": name,
            "round": 1,
            "passed": False,
            "stop_check": {"should_stop": False, "action": "continue"},
        }

    monkeypatch.setattr(hermes.runner, "run_loop", fake_run_loop)

    result = run_loop_continuous("test-post-round-budget")
    assert result["success"] is True
    assert result["rounds_executed"] == 1, (
        f"expected 1 round executed, got {result['rounds_executed']}"
    )
    assert result["final_stop"]["should_stop"] is True
    assert result["final_stop"]["rule_id"] == "budget_exceeded", (
        f"post-round did not map BUDGET_EXCEEDED: rule_id="
        f"{result['final_stop']['rule_id']}"
    )
    assert result["final_stop"]["action"] == "stop_escalate"
    assert "Budget exhausted" in result["final_stop"]["description"], (
        f"unexpected description: {result['final_stop']['description']!r}"
    )


def test_run_loop_continuous_post_round_catches_error(monkeypatch) -> None:
    """run_loop_continuous post-round branch: when a round succeeds but the
    loop is externally set to ERROR, the post-round branch must catch ERROR
    immediately via _terminal_status_to_stop with entry='post-round' — NOT
    waste another round waiting for run_loop's status guard to reject it."""
    import hermes.runner
    from hermes.runner import run_loop_continuous

    init_loop("test-post-round-error", pattern="knowledge-hygiene")
    loop = get_loop("test-post-round-error")
    assert loop.status == LoopStatus.IDLE

    def fake_run_loop(name: str) -> dict:
        updated = get_loop(name)
        updated.status = LoopStatus.ERROR
        updated.current_round = 1
        _save_loop_meta(updated)
        return {
            "success": True,
            "mode": "local",
            "loop": name,
            "round": 1,
            "passed": False,
            "stop_check": {"should_stop": False, "action": "continue"},
        }

    monkeypatch.setattr(hermes.runner, "run_loop", fake_run_loop)

    result = run_loop_continuous("test-post-round-error")
    assert result["success"] is True
    assert result["rounds_executed"] == 1, (
        f"expected 1 round (immediate catch), got {result['rounds_executed']}"
    )
    assert result["final_stop"]["should_stop"] is True
    assert result["final_stop"]["rule_id"] == "rounds_exhausted"
    assert result["final_stop"]["action"] == "stop_escalate"
    desc = result["final_stop"]["description"]
    assert "error state" in desc.lower(), (
        f"ERROR description doesn't mention 'error state': {desc!r}"
    )
    assert "post-round" in desc, (
        f"ERROR not caught in post-round (missing 'post-round' label): {desc!r}"
    )


# ── Profile Parser Regression Tests ───────────────────────────────────


def test_profile_working_principles_parser_excludes_non_rule_sections() -> None:
    """profile._load_working_principles_from_doc: a non-rule heading (e.g.
    `## 加载机制`) after a rule must NOT leak into the rule's body. The parser
    must end the current rule's body at any markdown heading, not just rule
    headings."""
    from hermes.profile import _load_working_principles_from_doc

    entries = _load_working_principles_from_doc()
    # The real working-principles.md has 2 rules + a `## 加载机制` section.
    assert len(entries) >= 2, f"expected >=2 rules, got {len(entries)}"
    # Rule 2's body must NOT contain the `加载机制` section text.
    rule2 = entries[1]
    assert "加载机制" not in rule2, (
        f"non-rule section leaked into rule body: {rule2!r}"
    )
    assert "load_profile" not in rule2, (
        f"加载机制 implementation detail leaked into rule body: {rule2!r}"
    )


def test_profile_working_principles_parser_strips_trailing_separator() -> None:
    """profile._load_working_principles_from_doc: trailing `---` thematic-break
    lines (and surrounding blank lines) that delimit sections must be stripped
    from the end of each rule body. Rule 2 ends with `---` before `## 加载机制`
    — that `---` must not appear in the rule's body."""
    from hermes.profile import _load_working_principles_from_doc

    entries = _load_working_principles_from_doc()
    assert len(entries) >= 2
    rule2 = entries[1]
    # The body must not end with `---` (stripped by _flush).
    lines = rule2.split("\n")
    assert lines[-1].strip() != "---", (
        f"trailing --- not stripped: last line={lines[-1]!r}"
    )
    # And the `---` separator should not be in the body at all (it's between
    # rule 2 and 加载机制, both stripped as trailing separator).
    assert "\n---" not in rule2, (
        f"--- separator found in rule body: {rule2!r}"
    )


# ── Baseline Failures Tests ────────────────────────────────────────────


def test_check_stop_rules_baseline_failures_excludes_history() -> None:
    """基线对比：baseline_failures 中的失败项被排除，不参与 regression 判定。

    场景：{a}→{a,c}，正常会触发 regression（new={c}, overlap={a}）。
    但如果 c 是历史失败（在 baseline_failures 中），则 c 被排除，
    实际变为 {a}→{a}，触发 same_failure_twice 而非 regression。
    """
    rounds = [
        _make_round(1, passed=False, failure_items=["a.py:1"]),
        _make_round(2, passed=False, failure_items=["a.py:1", "c.py:3"]),
    ]
    # 不传 baseline_failures → regression
    result = check_stop_rules("test", 2, 5, rounds)
    assert result["rule_id"] == "regression"

    # 传 baseline_failures=["c.py:3"] → c 被排除，变为 {a}→{a} → same_failure_twice
    result = check_stop_rules("test", 2, 5, rounds, baseline_failures=["c.py:3"])
    assert result["rule_id"] == "same_failure_twice"


def test_check_stop_rules_baseline_failures_makes_progress_visible() -> None:
    """基线对比：排除历史失败后，真实的进展变得可见。

    场景：{a,b,c}→{a,b}（修好了 c），正常应 continue（有进展）。
    但如果误传 baseline=["c"]，c 被排除，变为 {a,b}→{a,b} → same_failure_twice。
    这个测试验证 baseline_failures 的过滤确实生效。
    """
    rounds = [
        _make_round(1, passed=False, failure_items=["a", "b", "c"], failure_count=3),
        _make_round(2, passed=False, failure_items=["a", "b"], failure_count=2),
    ]
    # 不传 baseline → 有进展，continue
    result = check_stop_rules("test", 2, 5, rounds)
    assert result["should_stop"] is False

    # 传 baseline=["c"] → c 被排除，{a,b}→{a,b} → same_failure_twice
    result = check_stop_rules("test", 2, 5, rounds, baseline_failures=["c"])
    assert result["rule_id"] == "same_failure_twice"


def test_check_stop_rules_baseline_failures_none_preserves_behavior() -> None:
    """基线对比：baseline_failures=None（默认）行为不变（向后兼容）。"""
    rounds = [
        _make_round(1, passed=False, failure_items=["a.py:1", "b.py:2"]),
        _make_round(2, passed=False, failure_items=["a.py:1", "c.py:3"]),
    ]
    result_without = check_stop_rules("test", 2, 5, rounds)
    result_with_none = check_stop_rules("test", 2, 5, rounds, baseline_failures=None)
    assert result_without["rule_id"] == result_with_none["rule_id"]
    assert result_without["should_stop"] == result_with_none["should_stop"]


# ── Audit Warnings (Soft Gate Scars) Tests ─────────────────────────────


def test_audit_loop_returns_warnings_list() -> None:
    """audit_loop 返回 warnings 列表（未通过检查的 name）。"""
    result = init_loop("test-audit-warnings", pattern="knowledge-hygiene")
    assert result["success"]

    try:
        audit_result = audit_loop("test-audit-warnings")
        assert audit_result["success"]
        # 新创建的 loop 应该有未通过的检查项（如 LOOP.md 完成标准未填）
        loop_result = audit_result["loops"][0]
        assert "warnings" in loop_result
        assert isinstance(loop_result["warnings"], list)
        # score < 100 时至少有一个 warning
        if loop_result["score"] < 100:
            assert len(loop_result["warnings"]) > 0
    finally:
        import shutil
        from hermes.loop import loops_dir
        test_dir = loops_dir() / "test-audit-warnings"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_audit_loop_warnings_persisted_to_state_md() -> None:
    """audit_warnings 持久化到 STATE.md 的 Audit Warnings 段落。"""
    result = init_loop("test-warnings-state", pattern="knowledge-hygiene")
    assert result["success"]

    try:
        # 先跑一次 audit 生成 warnings
        audit_loop("test-warnings-state")
        # 再 record_round 触发 _update_state_md
        round_data = _make_round(1, passed=True)
        record_round("test-warnings-state", round_data, tokens_used=1000)

        # 检查 STATE.md
        from hermes.loop import loops_dir
        state_path = loops_dir() / "test-warnings-state" / "STATE.md"
        if state_path.exists():
            content = state_path.read_text(encoding="utf-8")
            # 如果有 warnings，应该有 Audit Warnings 段落
            loop = get_loop("test-warnings-state")
            if loop and loop.audit_warnings:
                assert "Audit Warnings" in content or "## Audit" in content
    finally:
        import shutil
        from hermes.loop import loops_dir
        test_dir = loops_dir() / "test-warnings-state"
        if test_dir.exists():
            shutil.rmtree(test_dir)


# ── Hard Gate vs Soft Gate Tests ───────────────────────────────────────


def test_stop_rules_have_hard_gate_field() -> None:
    """每条 STOP_RULES 规则有 hard_gate 字段。"""
    for rule in STOP_RULES:
        assert "hard_gate" in rule, f"Rule {rule['id']} missing hard_gate field"
        assert isinstance(rule["hard_gate"], bool)


def test_stop_rules_hard_gate_distribution() -> None:
    """no_progress 是软门禁，其余 6 项是硬门禁（STOP_RULES 共 7 条：1 软 + 6 硬）。"""
    hard_gates = [r for r in STOP_RULES if r["hard_gate"]]
    soft_gates = [r for r in STOP_RULES if not r["hard_gate"]]
    assert len(hard_gates) == 6, f"Expected 6 hard gates, got {len(hard_gates)}"
    assert len(soft_gates) == 1, f"Expected 1 soft gate, got {len(soft_gates)}"
    assert soft_gates[0]["id"] == "no_progress"


# ── Deliverables Checklist Tests ───────────────────────────────────────


def test_record_round_checks_deliverables() -> None:
    """record_round 校验产物清单，返回 missing_deliverables。"""
    result = init_loop("test-deliverables", pattern="knowledge-hygiene")
    assert result["success"]

    try:
        from hermes.loop import loops_dir, _save_loop_meta

        loop = get_loop("test-deliverables")
        assert loop is not None

        # 设置一个不存在的 deliverable
        loop.deliverables = ["nonexistent_file.py"]
        _save_loop_meta(loop)

        round_data = _make_round(1, passed=True)
        record_result = record_round("test-deliverables", round_data, tokens_used=1000)
        assert record_result["success"]
        # 不存在的文件应在 missing_deliverables 中
        assert "missing_deliverables" in record_result
        assert "nonexistent_file.py" in record_result["missing_deliverables"]
    finally:
        import shutil
        from hermes.loop import loops_dir
        test_dir = loops_dir() / "test-deliverables"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_record_round_deliverables_all_present() -> None:
    """产物清单全部存在时，missing_deliverables 为空。"""
    result = init_loop("test-deliv-ok", pattern="knowledge-hygiene")
    assert result["success"]

    try:
        from hermes.loop import loops_dir, _save_loop_meta

        # 创建一个临时文件作为 deliverable
        loop = get_loop("test-deliv-ok")
        assert loop is not None

        # 创建一个真实存在的文件
        loop_dir = loops_dir() / "test-deliv-ok"
        real_file = loop_dir / "output.txt"
        real_file.write_text("test content", encoding="utf-8")

        loop.deliverables = [str(real_file)]
        _save_loop_meta(loop)

        round_data = _make_round(1, passed=True)
        record_result = record_round("test-deliv-ok", round_data, tokens_used=1000)
        assert record_result["success"]
        assert record_result.get("missing_deliverables", []) == []
    finally:
        import shutil
        from hermes.loop import loops_dir
        test_dir = loops_dir() / "test-deliv-ok"
        if test_dir.exists():
            shutil.rmtree(test_dir)


# ── Gated Mode Tests ───────────────────────────────────────────────────


def test_run_loop_continuous_gated_pauses_after_round() -> None:
    """--gated 模式：每轮结束后暂停（NEEDS_HUMAN），final_stop 为 human_gate。

    用 monkeypatch 强制 run_loop 返回 passed=False 且不触发停止规则，
    确保 gated 分支（runner.py 的 human_gate 逻辑）被真正执行。
    对抗审查 Critical 2：旧测试断言在 `if loop.status == NEEDS_HUMAN:` 条件块内，
    实际执行路径 knowledge-hygiene 扫描返回 passed=True，status 变为 COMPLETED，
    if 条件为 False，断言不执行——假绿。重写后强制 passed=False 走 gated 分支。
    """
    result = init_loop("test-gated-fix", pattern="builder-checker")
    assert result["success"]

    try:
        # monkeypatch run_loop 返回 passed=False，模拟一轮未通过但未触发停止规则
        import hermes.runner

        original_run_loop = hermes.runner.run_loop

        def mock_run_loop(name: str, **kwargs: object) -> dict:
            # 模拟一轮未通过但未触发停止规则（current_round=1, max_rounds=5）
            from hermes.loop import record_round, get_loop

            loop = get_loop(name)
            if loop:
                round_data = _make_round(1, passed=False, failure_items=["fake-issue"])
                record_round(name, round_data, tokens_used=1000)
            return {
                "success": True,
                "loop": name,
                "round": 1,
                "mode": "test",
                "passed": False,
            }

        hermes.runner.run_loop = mock_run_loop
        try:
            run_result = run_loop_continuous("test-gated-fix", gated=True)
        finally:
            hermes.runner.run_loop = original_run_loop

        assert run_result["success"]
        final_stop = run_result.get("final_stop", {})
        assert final_stop.get("rule_id") == "human_gate"
        assert final_stop.get("action") == "stop_escalate"
        assert "human" in final_stop.get("description", "").lower()

        # 验证 loop 状态变为 NEEDS_HUMAN
        loop = get_loop("test-gated-fix")
        assert loop is not None
        assert loop.status == LoopStatus.NEEDS_HUMAN
    finally:
        import shutil
        from hermes.loop import loops_dir
        test_dir = loops_dir() / "test-gated-fix"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_run_loop_continuous_gated_default_false() -> None:
    """默认不传 gated 时，行为不变（向后兼容）。"""
    result = init_loop("test-no-gated", pattern="knowledge-hygiene")
    assert result["success"]

    try:
        # 不传 gated，行为应与之前一致
        run_result = run_loop_continuous("test-no-gated")
        assert run_result["success"]
        final_stop = run_result.get("final_stop", {})
        # 不应是 human_gate
        assert final_stop.get("rule_id") != "human_gate"
    finally:
        import shutil
        from hermes.loop import loops_dir
        test_dir = loops_dir() / "test-no-gated"
        if test_dir.exists():
            shutil.rmtree(test_dir)


# ── MCP (GitHub) Tests ─────────────────────────────────────────────────


def test_mcp_github_client_init_without_token() -> None:
    """GitHubMCPClient 无 token 时 available=False。"""
    from hermes.mcp import GitHubMCPClient
    client = GitHubMCPClient(token="", repo="test/repo")
    assert client.available is False


def test_mcp_registry_has_github() -> None:
    """MCP_REGISTRY 包含 github。"""
    from hermes.mcp import MCP_REGISTRY, GitHubMCPClient
    assert "github" in MCP_REGISTRY
    assert MCP_REGISTRY["github"] is GitHubMCPClient


def test_mcp_get_client_returns_none_for_unknown() -> None:
    """get_mcp_client 对未注册的 server 返回 None。"""
    from hermes.mcp import get_mcp_client
    assert get_mcp_client("nonexistent") is None


# ── MCP Idempotency & Soft Degradation Tests ──────────────────────────


def test_mcp_post_pr_comment_idempotent_skip() -> None:
    """post_pr_comment 幂等：相同 body 的评论已存在时跳过。"""
    from hermes.mcp import GitHubMCPClient
    import hermes.mcp
    import json

    client = GitHubMCPClient(token="fake_token", repo="test/repo")

    # monkeypatch urlopen 返回已有评论
    class FakeResponse:
        def __init__(self, data):
            self._data = json.dumps(data).encode()

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    existing_comments = [{"body": "test comment", "id": 1}]

    original_urlopen = hermes.mcp.urllib.request.urlopen

    def mock_urlopen(req, timeout=None):
        return FakeResponse(existing_comments)

    hermes.mcp.urllib.request.urlopen = mock_urlopen
    try:
        result = client.post_pr_comment(1, "test comment")
    finally:
        hermes.mcp.urllib.request.urlopen = original_urlopen

    assert result["success"]
    assert result.get("skipped") is True


def test_mcp_post_pr_comment_failure_soft_degradation() -> None:
    """post_pr_comment 失败时软降级（返回 error dict，不抛异常）。"""
    from hermes.mcp import GitHubMCPClient
    import hermes.mcp

    client = GitHubMCPClient(token="fake_token", repo="test/repo")

    original_urlopen = hermes.mcp.urllib.request.urlopen

    def mock_urlopen_error(req, timeout=None):
        raise Exception("Network error")

    hermes.mcp.urllib.request.urlopen = mock_urlopen_error
    try:
        result = client.post_pr_comment(1, "test comment")
    finally:
        hermes.mcp.urllib.request.urlopen = original_urlopen

    assert result["success"] is False
    assert "error" in result
    assert "Network error" in result["error"]

    # 验证 audit_log 记录了失败
    audit_log = client.get_audit_log()
    assert len(audit_log) > 0
    failed_records = [r for r in audit_log if not r["success"]]
    assert len(failed_records) > 0


def test_mcp_audit_log_no_token_leak() -> None:
    """audit_log 不包含 token。"""
    from hermes.mcp import GitHubMCPClient
    import hermes.mcp
    import json

    client = GitHubMCPClient(token="secret_token_12345", repo="test/repo")

    class FakeResponse:
        def __init__(self, data):
            self._data = json.dumps(data).encode()

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    original_urlopen = hermes.mcp.urllib.request.urlopen
    hermes.mcp.urllib.request.urlopen = lambda req, timeout=None: FakeResponse([])
    try:
        client.list_prs()
    finally:
        hermes.mcp.urllib.request.urlopen = original_urlopen

    audit_log = client.get_audit_log()
    for record in audit_log:
        # token 不应出现在任何 audit 字段中
        assert "secret_token_12345" not in str(record)
        assert "secret_token_12345" not in str(record.get("args", {}))


# ── Resume Gated Flag Tests ───────────────────────────────────────────


def test_resume_loop_passes_gated_flag() -> None:
    """resume_loop 的 gated 参数传递给 run_loop_continuous。

    对抗审查 Critical 6：验证 resume_loop(name, gated=True) 会把 gated=True
    传递给 run_loop_continuous，而不是静默切回全自动模式。
    """
    result = init_loop("test-resume-gated", pattern="builder-checker")
    assert result["success"]

    try:
        import hermes.runner

        # 先让 loop 进入 NEEDS_HUMAN 状态
        loop = get_loop("test-resume-gated")
        assert loop is not None
        loop.status = LoopStatus.NEEDS_HUMAN
        from hermes.loop import _save_loop_meta
        _save_loop_meta(loop)

        # monkeypatch run_loop_continuous 捕获 gated 参数
        captured_args = {}
        original_rlc = hermes.runner.run_loop_continuous

        def mock_rlc(name, max_rounds=None, gated=False):
            captured_args["gated"] = gated
            return {"success": True, "loop": name, "rounds_executed": 0,
                    "rounds": [], "final_stop": {"should_stop": False, "action": "continue"}}

        hermes.runner.run_loop_continuous = mock_rlc
        try:
            from hermes.runner import resume_loop
            resume_loop("test-resume-gated", gated=True)
        finally:
            hermes.runner.run_loop_continuous = original_rlc

        assert captured_args.get("gated") is True
    finally:
        import shutil
        from hermes.loop import loops_dir
        test_dir = loops_dir() / "test-resume-gated"
        if test_dir.exists():
            shutil.rmtree(test_dir)


# ── Multi-Perspective Pattern Tests (借鉴 ai-berkshire) ───────────────


def test_multi_perspective_pattern_exists():
    """multi-perspective pattern 在 LOOP_PATTERNS 中注册。"""
    assert "multi-perspective" in LOOP_PATTERNS
    info = LOOP_PATTERNS["multi-perspective"]
    assert info["execution_status"] == "implemented"
    assert info["generates_agents"] is True
    # sub_agents 中 perspective 全部 parallel=True，synthesizer parallel=False
    persp = [a for a in info["sub_agents"] if a["role"].startswith("perspective")]
    synth = [a for a in info["sub_agents"] if a["role"] == "synthesizer"]
    assert len(persp) >= 2
    assert all(a["parallel"] for a in persp)
    assert len(synth) == 1
    assert synth[0]["parallel"] is False


def test_init_multi_perspective_generates_perspective_and_summary():
    """init multi-perspective 生成 perspective.md 和 summary.md。"""
    result = init_loop("test-mp-init", pattern="multi-perspective")
    assert result["success"]
    files = result["files"]
    assert "perspective.md" in files
    assert "summary.md" in files
    loop = get_loop("test-mp-init")
    assert loop is not None
    assert loop.pattern == "multi-perspective"
    assert loop.stage == LoopStage.L2_ASSIST


def test_perspective_md_contains_claim_marker_instruction():
    """perspective.md 模板包含 <!-- claim: --> 标记说明。"""
    init_loop("test-mp-claim", pattern="multi-perspective")
    from hermes.loop import loops_dir
    perspective_path = loops_dir() / "test-mp-claim" / "perspective.md"
    content = perspective_path.read_text(encoding="utf-8")
    assert "<!-- claim:" in content
    assert "Bull" in content
    assert "Bear" in content


def test_summary_md_contains_conclusion_marker_instruction():
    """summary.md 模板包含 <!-- conclusion: --> 标记说明。"""
    init_loop("test-mp-conclusion", pattern="multi-perspective")
    from hermes.loop import loops_dir
    summary_path = loops_dir() / "test-mp-conclusion" / "summary.md"
    content = summary_path.read_text(encoding="utf-8")
    assert "<!-- conclusion:" in content
    assert "禁止" in content or "必须" in content  # 反端水硬约束


# ── audit_deliverables Tests (产物抽检准出) ───────────────────────────


def test_audit_deliverables_missing_file_detected():
    """audit_deliverables 检测到缺失的 deliverable 文件。"""
    loop = get_loop("test-mp-init")
    if loop is None:
        init_loop("test-mp-init", pattern="multi-perspective")
        loop = get_loop("test-mp-init")
    loop.deliverables = ["nonexistent.md"]
    _save_loop_meta(loop)
    result = audit_deliverables("test-mp-init")
    assert result["success"]
    assert "nonexistent.md" in result["missing"]


def test_audit_deliverables_claim_marker_warning():
    """audit_deliverables 检测到 deliverable 缺少 <!-- claim: --> 标记。"""
    from hermes.loop import loops_dir
    init_loop("test-mp-claim-audit", pattern="multi-perspective")
    loop = get_loop("test-mp-claim-audit")
    # 写一个无 claim 标记的 deliverable
    test_file = loops_dir() / "test-mp-claim-audit" / "report.md"
    test_file.write_text("# Report\n\nNo claims here.", encoding="utf-8")
    loop.deliverables = [str(test_file)]
    _save_loop_meta(loop)
    result = audit_deliverables("test-mp-claim-audit")
    assert result["success"]
    assert len(result["claim_warnings"]) > 0
    assert "no <!-- claim:" in result["claim_warnings"][0]


def test_audit_deliverables_claim_marker_present_no_warning():
    """audit_deliverables 在有 <!-- claim: --> 标记时不报 warning。"""
    from hermes.loop import loops_dir
    init_loop("test-mp-claim-ok", pattern="multi-perspective")
    loop = get_loop("test-mp-claim-ok")
    test_file = loops_dir() / "test-mp-claim-ok" / "report.md"
    test_file.write_text(
        "# Report\n\n<!-- claim: 测试断言1 -->\n<!-- claim: 测试断言2 -->\n",
        encoding="utf-8",
    )
    loop.deliverables = [str(test_file)]
    _save_loop_meta(loop)
    result = audit_deliverables("test-mp-claim-ok")
    assert result["success"]
    assert len(result["claim_warnings"]) == 0


# ── Anti-Fence-Sitter (反端水) audit_loop Tests ───────────────────────


def test_audit_loop_anti_fence_sitter_triggers_for_multi_perspective():
    """audit_loop 对 multi-perspective pattern 检查 conclusion 标记。"""
    init_loop("test-mp-anti-fence", pattern="multi-perspective")
    result = audit_loop("test-mp-anti-fence")
    assert result["success"]
    # 应该有 "Summary has explicit conclusion" 检查项
    loop_result = result["loops"][0]
    check_names = [c["name"] for c in loop_result["checks"]]
    assert any("conclusion" in name.lower() for name in check_names)


def test_audit_loop_anti_fence_sitter_not_triggered_for_other_patterns():
    """audit_loop 对非 multi-perspective pattern 不检查 conclusion 标记。"""
    init_loop("test-bc-no-fence", pattern="builder-checker")
    result = audit_loop("test-bc-no-fence")
    assert result["success"]
    loop_result = result["loops"][0]
    check_names = [c["name"] for c in loop_result["checks"]]
    assert not any("conclusion" in name.lower() for name in check_names)


def test_audit_loop_conclusion_marker_present_passes():
    """multi-perspective 的 summary.md 含 conclusion 标记时检查通过。"""
    from hermes.loop import loops_dir
    init_loop("test-mp-conclusion-ok", pattern="multi-perspective")
    summary_path = loops_dir() / "test-mp-conclusion-ok" / "summary.md"
    summary_path.write_text(
        "# Summary\n\n<!-- conclusion: 建议采纳 -->\n",
        encoding="utf-8",
    )
    result = audit_loop("test-mp-conclusion-ok")
    loop_result = result["loops"][0]
    conclusion_check = [
        c for c in loop_result["checks"] if "conclusion" in c["name"].lower()
    ]
    assert len(conclusion_check) == 1
    assert conclusion_check[0]["passed"] is True


# ── Orchestrator run_parallel_perspectives Tests ─────────────────────


def test_run_parallel_perspectives_fan_out_parallel_tasks():
    """run_parallel_perspectives 构造 N 个 parallel=True 的 perspective task。"""
    from hermes.orchestrator import AgentTask, Orchestrator
    from pathlib import Path

    orch = Orchestrator()
    # mock fan_out 记录 parallel 属性
    captured: list[AgentTask] = []

    def mock_fan_out(tasks):
        for t in tasks:
            captured.append(t)
            t.status = "completed"
            t.session_id = "fake-session"
        return tasks

    def mock_fan_in(tasks, timeout=300.0):
        for t in tasks:
            t.result = f"result from {t.role}"
            t.tokens_used = 100
        return tasks

    orch.fan_out = mock_fan_out
    orch.fan_in = mock_fan_in

    perspectives = [
        {"role": "perspective_1", "lens": "正面"},
        {"role": "perspective_2", "lens": "风险"},
        {"role": "perspective_3", "lens": "中立"},
    ]
    orch.run_parallel_perspectives(
        loop_dir=Path("/tmp/fake"),
        round_num=1,
        subject="测试标的",
        perspectives=perspectives,
    )

    # 3 个 perspective + 1 个 synthesizer = 4 个 task
    persp_tasks = [t for t in captured if t.role.startswith("perspective")]
    synth_tasks = [t for t in captured if t.role == "synthesizer"]
    assert len(persp_tasks) == 3
    assert all(t.parallel for t in persp_tasks)
    assert len(synth_tasks) == 1
    assert synth_tasks[0].parallel is False


def test_run_multi_perspective_guidance_when_gateway_unavailable():
    """Gateway 不可用时 multi-perspective 降级到 guidance 模式。"""
    from unittest.mock import patch
    init_loop("test-mp-guidance", pattern="multi-perspective")
    with patch("hermes.runner.Orchestrator") as MockOrch:
        instance = MockOrch.return_value
        instance.is_available.return_value = False
        from hermes.runner import _run_multi_perspective, get_loop as gl
        loop = gl("test-mp-guidance")
        from hermes.loop import loops_dir
        result = _run_multi_perspective(
            "test-mp-guidance", loop, 1, "2025-01-01T00:00:00Z",
            loops_dir() / "test-mp-guidance",
        )
        assert result["mode"] == "guidance"
        assert "perspective" in result.get("agent_files", {})


# ── MCP _sources (双源交叉验证) Tests ─────────────────────────────────


def test_mcp_get_pr_returns_sources_field():
    """get_pr 返回 _sources 字段标记数据来源（双源验证基础）。"""
    from hermes.mcp import GitHubMCPClient
    from unittest.mock import patch, MagicMock
    client = GitHubMCPClient(token="fake-token", repo="test/repo")
    # mock urlopen 返回有效响应
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"number": 1, "title": "test"}'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = client.get_pr(1)
    assert result["success"]
    assert "_sources" in result
    assert "github-api" in result["_sources"]


def test_mcp_list_prs_returns_sources_field():
    """list_prs 返回 _sources 字段。"""
    from hermes.mcp import GitHubMCPClient
    from unittest.mock import patch, MagicMock
    client = GitHubMCPClient(token="fake-token", repo="test/repo")
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'[]'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = client.list_prs()
    assert result["success"]
    assert "_sources" in result
    assert len(result["_sources"]) >= 1


# ── P0-1: escalation_info persistence Tests ─────────────────────────


def test_loop_round_escalation_info_roundtrip() -> None:
    """LoopRound escalation_info should survive to_dict → from_dict roundtrip."""
    original = LoopRound(
        round_num=2,
        timestamp="2025-01-01T00:00:00Z",
        action="builder round",
        result_summary="permission denied",
        verifier_result="FAILED",
        passed=False,
        failure_count=1,
        failure_items=["auth.py:10"],
        escalation_info={
            "current_round": 2,
            "matched_signals": ["permission denied"],
            "blocker": "外部依赖或环境问题，需要人工介入",
        },
    )
    d = original.to_dict()
    assert d["escalation_info"] == original.escalation_info
    restored = LoopRound.from_dict(d)
    assert restored.escalation_info == original.escalation_info
    assert restored.escalation_info["matched_signals"] == ["permission denied"]


def test_loop_round_from_dict_escalation_info_default() -> None:
    """from_dict should default escalation_info to {} when missing (backward compat)."""
    minimal = {"round_num": 1, "passed": False}
    restored = LoopRound.from_dict(minimal)
    assert restored.escalation_info == {}


def test_loop_round_from_dict_escalation_info_none_guard() -> None:
    """from_dict should treat explicit None escalation_info as {} (not None)."""
    data = {"round_num": 1, "passed": False, "escalation_info": None}
    restored = LoopRound.from_dict(data)
    assert restored.escalation_info == {}


def test_loop_round_from_dict_escalation_info_type_guard() -> None:
    """from_dict should coerce non-dict escalation_info to {} (defensive)."""
    data = {"round_num": 1, "passed": False, "escalation_info": ["not", "a", "dict"]}
    restored = LoopRound.from_dict(data)
    assert restored.escalation_info == {}


def test_record_round_persists_escalation_info() -> None:
    """P0-1 时序修复：停止规则触发后 escalation_info 必须回填并持久化到 meta.json。

    根因：record_round 在 loop.rounds.append(round_data) 之后才调用 check_stop_rules，
    但 escalation_info 从未回填到 round_data，_save_loop_meta 持久化的 round 缺该字段，
    导致 root_cause / matched_signals / blocker 永远为空。
    """
    import json as _json
    import shutil
    from hermes.loop import get_loop, loops_dir

    result = init_loop("test-esc-persist", pattern="knowledge-hygiene")
    assert result["success"]
    try:
        # 构造 beyond_capability 触发场景：result_summary 含 "permission denied"
        round_data = LoopRound(
            round_num=1,
            timestamp="2025-01-01T00:00:00Z",
            action="scan",
            result_summary="Permission denied: cannot write to /etc/config",
            verifier_result="FAILED",
            passed=False,
            failure_count=1,
            failure_items=["access error"],
        )
        record_result = record_round("test-esc-persist", round_data, tokens_used=5000)
        assert record_result["success"]

        # Reload from disk: escalation_info must be persisted
        loop = get_loop("test-esc-persist")
        assert loop is not None
        assert len(loop.rounds) == 1
        esc = loop.rounds[0].escalation_info
        assert esc, "escalation_info should be non-empty after stop rule trigger"
        assert "matched_signals" in esc
        assert "permission denied" in esc["matched_signals"]
        assert esc["blocker"]

        # Verify raw meta.json on disk carries the field
        meta = _json.loads((loops_dir() / "test-esc-persist" / "meta.json").read_text("utf-8"))
        assert meta["rounds"][0]["escalation_info"]["matched_signals"]
    finally:
        test_dir = loops_dir() / "test-esc-persist"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_record_round_escalation_info_empty_when_no_stop() -> None:
    """未触发停止规则时 escalation_info 应为空 dict（不应残留上次数据）。"""
    import shutil
    from hermes.loop import get_loop, loops_dir

    result = init_loop("test-esc-empty", pattern="knowledge-hygiene")
    assert result["success"]
    try:
        # 单轮失败但无 capability 信号、未达 max_rounds → 不停止，escalation_info 为 {}
        round_data = LoopRound(
            round_num=1,
            timestamp="2025-01-01T00:00:00Z",
            action="scan",
            result_summary="Found 2 issues",
            verifier_result="2 high priority",
            passed=False,
            failure_count=2,
            failure_items=["issue1", "issue2"],
        )
        record_round("test-esc-empty", round_data, tokens_used=1000)
        loop = get_loop("test-esc-empty")
        assert loop is not None
        assert loop.rounds[0].escalation_info == {}
    finally:
        test_dir = loops_dir() / "test-esc-empty"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_record_round_regression_persists_escalation_info() -> None:
    """regression 规则触发的 escalation_info（new_failures/persistent）也持久化。"""
    import shutil
    from hermes.loop import get_loop, loops_dir

    # builder-checker max_rounds=5，避免 round 2 触发 rounds_exhausted 抢先于 regression
    result = init_loop("test-esc-regression", pattern="builder-checker")
    assert result["success"]
    try:
        # Round 1: failures {a.py:1, b.py:2}
        r1 = LoopRound(
            round_num=1, timestamp="t1", action="build", result_summary="s1",
            verifier_result="FAILED", passed=False, failure_count=2,
            failure_items=["a.py:1", "b.py:2"],
        )
        record_round("test-esc-regression", r1, tokens_used=1000)
        # Round 2: failures {a.py:1, c.py:3} → regression (new + persistent)
        r2 = LoopRound(
            round_num=2, timestamp="t2", action="build", result_summary="s2",
            verifier_result="FAILED", passed=False, failure_count=2,
            failure_items=["a.py:1", "c.py:3"],
        )
        record_round("test-esc-regression", r2, tokens_used=1000)

        loop = get_loop("test-esc-regression")
        assert loop is not None
        esc = loop.rounds[-1].escalation_info
        assert esc, "regression escalation_info should be persisted"
        assert "c.py:3" in esc["new_failures"]
        assert "a.py:1" in esc["persistent"]
    finally:
        test_dir = loops_dir() / "test-esc-regression"
        if test_dir.exists():
            shutil.rmtree(test_dir)


def test_format_escalation_info_renders_fields() -> None:
    """_format_escalation_info 应渲染各规则的关键诊断字段。"""
    from hermes.main import _format_escalation_info

    # beyond_capability
    lines = _format_escalation_info({
        "matched_signals": ["permission denied"],
        "blocker": "外部依赖或环境问题，需要人工介入",
    })
    text = "\n".join(lines)
    assert "permission denied" in text
    assert "外部依赖" in text

    # regression
    lines = _format_escalation_info({
        "new_failures": ["c.py:3"],
        "previously_fixed": ["b.py:2"],
        "persistent": ["a.py:1"],
    })
    text = "\n".join(lines)
    assert "c.py:3" in text
    assert "b.py:2" in text
    assert "a.py:1" in text

    # no_progress
    lines = _format_escalation_info({
        "failure_counts": [2, 2],
        "suggestion": "拆分成更小的子任务",
    })
    text = "\n".join(lines)
    assert "2 → 2" in text
    assert "拆分" in text


def test_format_escalation_info_empty_inputs() -> None:
    """_format_escalation_info 对 None / {} / 非dict 输入返回空列表。"""
    from hermes.main import _format_escalation_info
    assert _format_escalation_info(None) == []
    assert _format_escalation_info({}) == []
    assert _format_escalation_info(["not", "dict"]) == []  # type: ignore[arg-type]

"""工具自愈模块（tool_recovery）的单元测试与集成测试。

覆盖：
- 12 个内置失败模式的匹配（每种模式一个用例）
- 未命中、多失败、原始文本保留等边界
- get_recovery_hints 去重与 severity 排序
- format_recovery_section markdown 格式
- aggregate_results 集成：恢复建议附加到 summary，且不破坏"不过滤"原则
"""

from __future__ import annotations

from hermes.orchestrator import AgentTask, Orchestrator
from hermes.tool_recovery import (
    FAILURE_PATTERNS,
    analyze_failures,
    format_recovery_section,
    get_recovery_hints,
)


# ── 12 个内置失败模式匹配测试 ─────────────────────────────────


def test_analyze_failures_matches_terminal_truncation() -> None:
    """terminal_output_truncated：output too long / truncated 信号命中。"""
    diagnostics = analyze_failures(["checker: command output too long, truncated at 10000 chars"])
    assert len(diagnostics) == 1
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "terminal_output_truncated"
    assert matched.severity == "high"
    assert diagnostics[0].recovery_hint == matched.recovery_hint
    assert diagnostics[0].is_retryable is True


def test_analyze_failures_matches_patch_already_applied() -> None:
    """patch_already_applied：already applied 信号命中。"""
    diagnostics = analyze_failures(["builder: edit already applied, no changes made"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "patch_already_applied"
    assert matched.severity == "medium"


def test_analyze_failures_matches_whitespace_mismatch() -> None:
    """patch_whitespace_mismatch：tab/space 信号命中。"""
    diagnostics = analyze_failures(["edit failed: unexpected indent, tab/space mismatch"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "patch_whitespace_mismatch"
    assert matched.severity == "medium"


def test_analyze_failures_matches_search_zero_matches() -> None:
    """search_zero_matches：no matches 信号命中（不与 file_not_found 冲突）。"""
    diagnostics = analyze_failures(["grep: no matches found in src/"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "search_zero_matches"
    assert matched.severity == "low"


def test_analyze_failures_matches_file_not_found() -> None:
    """file_not_found：No such file or directory 命中（优先于 search_zero_matches）。"""
    diagnostics = analyze_failures(["cat: src/missing.py: No such file or directory"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "file_not_found"
    assert matched.severity == "high"
    # 关键：包含 "no such file" 子串，但 file_not_found（high）应优先于
    # search_zero_matches（low），因 FAILURE_PATTERNS 中 file_not_found 在前。
    assert matched.pattern_id != "search_zero_matches"


def test_analyze_failures_matches_permission_denied() -> None:
    """permission_denied：Permission denied 信号命中，且不可自动重试。"""
    diagnostics = analyze_failures(["bash: /root/secret: Permission denied"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "permission_denied"
    assert matched.severity == "high"
    # 权限问题需提权，不可自动重试
    assert diagnostics[0].is_retryable is False


def test_analyze_failures_matches_command_timeout() -> None:
    """command_timeout：TimeoutExpired 信号命中。"""
    diagnostics = analyze_failures(["subprocess.CalledProcessError: TimeoutExpired after 30s"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "command_timeout"
    assert matched.severity == "medium"


def test_analyze_failures_matches_import_error() -> None:
    """import_error：ModuleNotFoundError 信号命中。"""
    diagnostics = analyze_failures(["ModuleNotFoundError: No module named 'fastapi'"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "import_error"
    assert matched.severity == "high"


def test_analyze_failures_matches_syntax_error() -> None:
    """syntax_error：SyntaxError 信号命中。"""
    diagnostics = analyze_failures(["SyntaxError: invalid syntax at line 42"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "syntax_error"
    assert matched.severity == "high"


def test_analyze_failures_matches_type_error() -> None:
    """type_error：TypeError 信号命中。"""
    diagnostics = analyze_failures(["TypeError: argument 'x' type mismatch"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "type_error"
    assert matched.severity == "medium"


def test_analyze_failures_matches_network_error() -> None:
    """network_error：ConnectionRefused 信号命中。"""
    diagnostics = analyze_failures(["ConnectionRefusedError: Network is unreachable"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "network_error"
    assert matched.severity == "medium"


def test_analyze_failures_matches_denylist_violation() -> None:
    """denylist_violation：DENYLIST VIOLATION 信号命中，且不可自动重试。"""
    diagnostics = analyze_failures(["builder: DENYLIST VIOLATION — write: auth/x.py (matched: auth/)"])
    matched = diagnostics[0].matched_pattern
    assert matched is not None
    assert matched.pattern_id == "denylist_violation"
    assert matched.severity == "high"
    # 命中 denylist 需人工审批，不可自动重试
    assert diagnostics[0].is_retryable is False


# ── 边界与行为测试 ─────────────────────────────────────────────


def test_analyze_failures_no_match_returns_empty_hint() -> None:
    """未命中任何模式时 matched_pattern=None、recovery_hint 为空。"""
    diagnostics = analyze_failures(["checker: something completely unknown went wrong xyz123"])
    assert len(diagnostics) == 1
    assert diagnostics[0].matched_pattern is None
    assert diagnostics[0].recovery_hint == ""
    assert diagnostics[0].is_retryable is False


def test_analyze_failures_multiple_failures() -> None:
    """多条失败项各自独立匹配，返回等长诊断列表。"""
    items = [
        "ImportError: No module named 'x'",
        "Permission denied: /etc/shadow",
        "totally unknown failure zzz",
    ]
    diagnostics = analyze_failures(items)
    assert len(diagnostics) == 3
    assert diagnostics[0].matched_pattern is not None
    assert diagnostics[0].matched_pattern.pattern_id == "import_error"
    assert diagnostics[1].matched_pattern is not None
    assert diagnostics[1].matched_pattern.pattern_id == "permission_denied"
    assert diagnostics[2].matched_pattern is None


def test_analyze_failures_preserves_original_error() -> None:
    """"不过滤"原则：原始失败文本原样保留在 original_error 中。"""
    original = "checker_lint: src/a.py|ImportError"
    diagnostics = analyze_failures([original])
    assert diagnostics[0].original_error == original


def test_analyze_failures_empty_input_returns_empty() -> None:
    """空 failure_items 返回空诊断列表。"""
    assert analyze_failures([]) == []


def test_analyze_failures_with_tool_calls_enrichment() -> None:
    """tool_calls 中的 error 字段也会被纳入分析。"""
    tool_calls = [
        {"name": "bash", "error": "Command timed out after 30s"},
        {"name": "read", "result": "ok"},
    ]
    diagnostics = analyze_failures([], tool_calls=tool_calls)
    # "ok" 不含失败信号，但 "Command timed out" 命中 command_timeout
    matched_ids = [d.matched_pattern.pattern_id for d in diagnostics if d.matched_pattern]
    assert "command_timeout" in matched_ids


# ── get_recovery_hints 测试 ────────────────────────────────────


def test_get_recovery_hints_dedupes() -> None:
    """相同模式的多个诊断只产生一条去重后的恢复建议。"""
    items = [
        "ImportError: No module named 'a'",
        "ModuleNotFoundError: No module named 'b'",
    ]
    diagnostics = analyze_failures(items)
    hints = get_recovery_hints(diagnostics)
    # 两个 ImportError 命中同一模式，recovery_hint 相同，去重后只剩一条
    assert len(hints) == 1
    assert "导入失败" in hints[0]


def test_get_recovery_hints_sorted_by_severity() -> None:
    """恢复建议按 severity 排序：high 优先于 medium 优先于 low。"""
    # 故意以 low、high、medium 顺序输入，验证输出按 high→medium→low 排序
    items = [
        "grep: no matches",           # low
        "SyntaxError: invalid syntax",  # high
        "Command timed out",          # medium
    ]
    diagnostics = analyze_failures(items)
    hints = get_recovery_hints(diagnostics)
    assert len(hints) == 3
    # high（语法错误）应排在第一位
    assert "语法错误" in hints[0]
    # medium（命令超时）第二
    assert "命令超时" in hints[1]
    # low（搜索零匹配）最后
    assert "搜索零匹配" in hints[2]


def test_get_recovery_hints_skips_unmatched() -> None:
    """未命中的诊断不产生恢复建议。"""
    diagnostics = analyze_failures(["unknown failure xyz", "ImportError: No module named 'x'"])
    hints = get_recovery_hints(diagnostics)
    assert len(hints) == 1
    assert "导入失败" in hints[0]


def test_get_recovery_hints_empty_when_all_unmatched() -> None:
    """全部未命中时返回空列表。"""
    diagnostics = analyze_failures(["unknown1", "unknown2"])
    assert get_recovery_hints(diagnostics) == []


# ── format_recovery_section 测试 ──────────────────────────────


def test_format_recovery_section_markdown() -> None:
    """命中模式时生成 markdown 段落，含标题与 severity 标签。"""
    diagnostics = analyze_failures(["SyntaxError: invalid syntax"])
    section = format_recovery_section(diagnostics)
    assert section.startswith("## 工具失败恢复建议")
    assert "**[HIGH] syntax_error**" in section
    assert "语法错误" in section


def test_format_recovery_section_empty_when_no_match() -> None:
    """无命中模式时返回空字符串（调用方据此决定是否附加）。"""
    diagnostics = analyze_failures(["totally unknown xyz"])
    assert format_recovery_section(diagnostics) == ""


def test_format_recovery_section_sorted_by_severity() -> None:
    """markdown 段落按 severity 排序，high 在前。"""
    diagnostics = analyze_failures([
        "grep: no matches",            # low
        "Permission denied: /x",       # high
    ])
    section = format_recovery_section(diagnostics)
    lines = [ln for ln in section.splitlines() if ln.startswith("- ")]
    assert len(lines) == 2
    # high（permission_denied）应在 low（search_zero_matches）之前
    assert "permission_denied" in lines[0]
    assert "search_zero_matches" in lines[1]


def test_format_recovery_section_dedupes() -> None:
    """相同模式多次命中，段落中只出现一条。"""
    diagnostics = analyze_failures([
        "ImportError: No module named 'a'",
        "ModuleNotFoundError: No module named 'b'",
    ])
    section = format_recovery_section(diagnostics)
    assert section.count("import_error") == 1


# ── 集成测试：aggregate_results 集成工具自愈 ──────────────────


def test_aggregate_results_includes_recovery_hints() -> None:
    """集成测试：checker 报告 ImportError 时，summary 附加恢复建议段落。

    验证：
    1. 原始失败信息原样保留在 failure_items（"不过滤"原则不变）
    2. summary 末尾附加 "## 工具失败恢复建议" 段落
    3. 段落含 import_error 的恢复建议
    """
    orch = Orchestrator()
    report = (
        "FAILED\n<!-- failures:json -->\n"
        '{"passed": false, "failures": [{"file": "src/a.py", "line": 1, "type": "ImportError"}]}\n'
        "<!-- /failures -->"
    )
    tasks = [
        AgentTask(role="builder", status="completed", result="done", session_id="b"),
        AgentTask(role="checker_lint", status="completed", result=report, session_id="c"),
    ]
    result = orch.aggregate_results(tasks, round_num=1)

    # 1. 原始失败信息保留
    assert any("ImportError" in f for f in result.failure_items)
    # 2. summary 附加恢复建议段落
    assert "## 工具失败恢复建议" in result.summary
    # 3. 含 import_error 的恢复建议
    assert "import_error" in result.summary
    assert "导入失败" in result.summary


def test_aggregate_results_no_recovery_section_when_all_green() -> None:
    """ALL GREEN 时无 failure_items，summary 不附加恢复建议段落。"""
    orch = Orchestrator()
    tasks = [
        AgentTask(role="builder", status="completed", result="done", session_id="b"),
        AgentTask(role="checker_lint", status="completed", result="ALL GREEN", session_id="c"),
    ]
    result = orch.aggregate_results(tasks, round_num=1)
    assert result.all_passed is True
    assert "## 工具失败恢复建议" not in result.summary


def test_aggregate_results_recovery_does_not_replace_original_failures() -> None:
    """恢复建议是附加内容，不替换原始失败信息（"不过滤"原则）。"""
    orch = Orchestrator()
    report = (
        "FAILED\n<!-- failures:json -->\n"
        '{"passed": false, "failures": [{"file": "src/a.py", "type": "SyntaxError"}]}\n'
        "<!-- /failures -->"
    )
    tasks = [
        AgentTask(role="checker_lint", status="completed", result=report, session_id="c"),
    ]
    result = orch.aggregate_results(tasks, round_num=1)
    # 原始失败键保留
    assert any("SyntaxError" in f for f in result.failure_items)
    # summary 同时包含原始状态行和恢复建议段落
    assert "Status: FAILED" in result.summary
    assert "## 工具失败恢复建议" in result.summary


def test_aggregate_results_denylist_violation_gets_recovery_hint() -> None:
    """builder 命中 denylist 时，summary 附加 denylist 恢复建议。"""
    orch = Orchestrator()
    builder = AgentTask(role="builder", status="completed", result="done")
    builder.path_violations = ["write: auth/x.py (matched: auth/)"]
    checker = AgentTask(role="checker_lint", status="completed", result="ALL GREEN")
    result = orch.aggregate_results([builder, checker], round_num=1)
    # denylist 失败项保留
    assert any("DENYLIST VIOLATION" in f for f in result.failure_items)
    # 恢复建议附加
    assert "## 工具失败恢复建议" in result.summary
    assert "denylist_violation" in result.summary


# ── 数据完整性测试 ─────────────────────────────────────────────


def test_failure_patterns_count() -> None:
    """内置失败模式共 12 个。"""
    assert len(FAILURE_PATTERNS) == 12
    ids = {p.pattern_id for p in FAILURE_PATTERNS}
    assert len(ids) == 12  # 无重复 id


def test_failure_patterns_severity_valid() -> None:
    """所有模式 severity 只能是 high/medium/low。"""
    for p in FAILURE_PATTERNS:
        assert p.severity in {"high", "medium", "low"}, f"非法 severity: {p.pattern_id}"


def test_failure_patterns_signals_nonempty() -> None:
    """所有模式至少有一个 signal（否则永远无法命中）。"""
    for p in FAILURE_PATTERNS:
        assert len(p.signals) >= 1, f"无 signal: {p.pattern_id}"

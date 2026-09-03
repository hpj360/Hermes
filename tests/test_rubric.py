"""Tests for versioned evaluation Rubric (P1-A 评估资产化)."""

from __future__ import annotations

from hermes.rubric import (
    DEFAULT_RUBRIC,
    Rubric,
    RubricMetric,
    is_all_green,
    parse_structured_failures,
    score_reports,
)


def _green_report() -> str:
    return "All checks passed. ALL GREEN\n<!-- failures:json -->\n{\"failures\": []}\n<!-- /failures -->"


def _red_report(file: str = "src/a.py", ftype: str = "ImportError") -> str:
    return (
        "Some checks failed.\n"
        f"<!-- failures:json -->\n{{\"failures\": [{{\"file\": \"{file}\", \"type\": \"{ftype}\", \"line\": 42}}]}}\n"
        "<!-- /failures -->"
    )


# ── parse_structured_failures ───────────────────────────────────────


def test_parse_structured_failures_extracts_keys():
    """结构化协议块：提取 file|type key，丢弃行号。"""
    items = parse_structured_failures(_red_report(), "checker")
    assert items == ["checker: src/a.py|ImportError"]


def test_parse_structured_failures_drops_line_numbers():
    """行号漂移不影响 key（builder 编辑前文时 stop-rule 对比仍稳定）。"""
    a = parse_structured_failures(_red_report(), "checker")
    b = parse_structured_failures(
        _red_report().replace("\"line\": 42", "\"line\": 99"), "checker"
    )
    assert a == b


def test_parse_structured_failures_green_block_returns_empty():
    """绿报告（空 failures）不产出失败项。"""
    assert parse_structured_failures(_green_report(), "checker") == []


def test_parse_structured_failures_fallback_verbatim():
    """无结构化块时回退为首行 verbatim（不猜测）。"""
    items = parse_structured_failures("Error: something broke", "checker_lint")
    assert items == ["checker_lint: Error: something broke"]


def test_parse_structured_failures_unparseable():
    """完全无法解析的报告返回 UNPARSEABLE 哨兵。"""
    items = parse_structured_failures("", "checker_type")
    assert items == ["checker_type: [UNPARSEABLE FAILURE]"]


def test_parse_structured_failures_bad_json_falls_back():
    """协议块 JSON 损坏时回退到 verbatim 首行。"""
    report = "Bad json below.\n<!-- failures:json -->\n{not json}\n<!-- /failures -->"
    items = parse_structured_failures(report, "checker")
    assert items == ["checker: Bad json below."]


# ── is_all_green ────────────────────────────────────────────────────


def test_is_all_green_true():
    assert is_all_green(_green_report()) is True


def test_is_all_green_false_on_failures():
    assert is_all_green(_red_report()) is False


def test_is_all_green_false_without_marker():
    assert is_all_green("everything looks fine") is False


# ── Rubric 定义 ─────────────────────────────────────────────────────


def test_default_rubric_weights():
    """默认 Rubric：pytest 主导，lint/type 各占四分之一。"""
    assert DEFAULT_RUBRIC.rubric_id == "hermes-default"
    assert DEFAULT_RUBRIC.version == "1.0"
    assert [m.role for m in DEFAULT_RUBRIC.metrics] == [
        "checker", "checker_lint", "checker_type",
    ]
    assert DEFAULT_RUBRIC.total_weight() == 100.0


def test_rubric_roundtrip():
    """Rubric 可持久化（to_dict/from_dict roundtrip）——评估资产可迭代。"""
    r = Rubric(
        rubric_id="custom",
        version="2.0",
        metrics=[RubricMetric("checker", 60.0, "pytest"), RubricMetric("checker_lint", 40.0)],
    )
    restored = Rubric.from_dict(r.to_dict())
    assert restored.rubric_id == "custom"
    assert restored.version == "2.0"
    assert [m.role for m in restored.metrics] == ["checker", "checker_lint"]
    assert restored.total_weight() == 100.0


# ── score_reports ───────────────────────────────────────────────────


def test_score_reports_all_green():
    """全绿：final=1.0，decision=pass。"""
    reports = {
        "checker": _green_report(),
        "checker_lint": _green_report(),
        "checker_type": _green_report(),
    }
    score = score_reports(reports)
    assert score.final_score == 1.0
    assert score.decision == "pass"
    assert all(v.passed for v in score.verdicts)
    assert score.quality == 1.0
    assert "green" in score.summary


def test_score_reports_weighted_partial():
    """部分通过：加权分数按权重折算（checker 挂 => 0.5）。"""
    reports = {
        "checker": _red_report(),
        "checker_lint": _green_report(),
        "checker_type": _green_report(),
    }
    score = score_reports(reports)
    assert score.decision == "fail"
    assert score.final_score == 0.5  # 50/100 weight lost
    failed = [v for v in score.verdicts if not v.passed]
    assert [v.role for v in failed] == ["checker"]
    assert failed[0].evidence == ["checker: src/a.py|ImportError"]
    assert "checker" in score.summary


def test_score_reports_missing_report():
    """缺失报告按 0 分计（note=missing report）。"""
    score = score_reports({"checker": _green_report()})
    assert score.final_score == 0.5
    missing = [v for v in score.verdicts if v.note == "missing report"]
    assert {v.role for v in missing} == {"checker_lint", "checker_type"}


def test_score_reports_custom_rubric():
    """自定义 Rubric：权重归一化不要求和为 100。"""
    rubric = Rubric(
        rubric_id="t", version="9.9",
        metrics=[RubricMetric("checker", 3.0), RubricMetric("checker_lint", 1.0)],
    )
    reports = {"checker": _green_report(), "checker_lint": _red_report("x.py", "E501")}
    score = score_reports(reports, rubric=rubric)
    assert score.rubric_version == "9.9"
    assert score.final_score == 0.75  # 3/(3+1)


def test_rubric_score_to_dict_explains():
    """to_dict 输出可解释证据（低分时能看到哪步错、依据是什么）。"""
    reports = {
        "checker": _green_report(),
        "checker_lint": _red_report("b.py", "F841"),
        "checker_type": _green_report(),
    }
    d = score_reports(reports).to_dict()
    assert d["rubric_version"] == "1.0"
    assert d["decision"] == "fail"
    lint = next(v for v in d["verdicts"] if v["role"] == "checker_lint")
    assert lint["evidence"] == ["checker_lint: b.py|F841"]


# ── orchestrator fan-in 集成（P1-A 接线）────────────────────────────


def _task(role: str, result: str | None):
    from hermes.orchestrator import AgentTask

    return AgentTask(role=role, status="completed", result=result, session_id="s")


def test_aggregate_results_scores_rubric_all_green():
    """fan-in：全绿轮的 RoundResult 带 rubric_score（final=1.0, pass）。"""
    from hermes.orchestrator import Orchestrator

    orch = Orchestrator()
    tasks = [
        _task("builder", "done"),
        _task("checker", _green_report()),
        _task("checker_lint", _green_report()),
        _task("checker_type", _green_report()),
    ]
    rr = orch.aggregate_results(tasks, round_num=1)
    assert rr.rubric_score is not None
    assert rr.rubric_score["final_score"] == 1.0
    assert rr.rubric_score["decision"] == "pass"
    assert rr.rubric_score["rubric_version"] == "1.0"
    assert rr.to_dict()["rubric_score"]["final_score"] == 1.0


def test_aggregate_results_scores_rubric_partial():
    """fan-in：checker 挂、lint/type 绿 → final=0.5，证据保留 failure key。"""
    from hermes.orchestrator import Orchestrator

    orch = Orchestrator()
    tasks = [
        _task("checker", _red_report("src/x.py", "AssertionError")),
        _task("checker_lint", _green_report()),
        _task("checker_type", _green_report()),
    ]
    rr = orch.aggregate_results(tasks, round_num=1)
    assert rr.rubric_score is not None
    assert rr.rubric_score["final_score"] == 0.5
    assert rr.rubric_score["decision"] == "fail"
    checker_v = next(
        v for v in rr.rubric_score["verdicts"] if v["role"] == "checker"
    )
    assert checker_v["evidence"] == ["checker: src/x.py|AssertionError"]


def test_aggregate_results_no_checker_no_rubric_score():
    """无 checker 报告的 round：rubric_score=None（不伪造分数）。"""
    from hermes.orchestrator import Orchestrator

    orch = Orchestrator()
    tasks = [_task("builder", "done")]
    rr = orch.aggregate_results(tasks, round_num=1)
    assert rr.rubric_score is None
    assert rr.to_dict()["rubric_score"] is None


def test_aggregate_results_empty_checker_output_scores_zero():
    """红线一致性：checker 无输出 → 该指标 0 分（不因缺失而豁免）。"""
    from hermes.orchestrator import Orchestrator

    orch = Orchestrator()
    tasks = [
        _task("checker", ""),
        _task("checker_lint", _green_report()),
        _task("checker_type", _green_report()),
    ]
    rr = orch.aggregate_results(tasks, round_num=1)
    assert rr.rubric_score is not None
    assert rr.rubric_score["final_score"] == 0.5
    checker_v = next(
        v for v in rr.rubric_score["verdicts"] if v["role"] == "checker"
    )
    assert checker_v["note"] == "missing report"

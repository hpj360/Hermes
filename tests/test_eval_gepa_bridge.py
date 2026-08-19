"""Tests for hermes.eval.gepa_bridge — skill-up → GEPA evaluator adapter.

Covers eval_result_to_variant_dict (mapping) and make_evaluator (the
adapter factory). The evaluator is tested with a fake EvalRunner to
avoid subprocess calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from hermes.eval.gepa_bridge import (
    default_skill_dir_resolver,
    eval_result_to_variant_dict,
    make_evaluator,
)
from hermes.eval.compliance import ComplianceReport
from hermes.eval.result import CaseResult, EvalResult


# ── eval_result_to_variant_dict ──────────────────────────────────────


class TestEvalResultToVariantDict:
    def test_success_when_all_passed(self):
        result = EvalResult(
            total=2,
            passed=2,
            failed=0,
            cases=[
                CaseResult(id="c1", status="passed", tokens_used=100),
                CaseResult(id="c2", status="passed", tokens_used=200),
            ],
        )
        d = eval_result_to_variant_dict(result, variant_id="v1")
        assert d["variant_id"] == "v1"
        assert d["success"] is True
        assert d["tokens_used"] == 300  # sum of all case tokens
        assert d["rounds_to_converge"] == 1
        assert d["failure_items"] == []
        assert d["error"] is None

    def test_failure_when_some_cases_fail(self):
        result = EvalResult(
            total=2,
            passed=1,
            failed=1,
            cases=[
                CaseResult(id="c1", status="passed", tokens_used=100),
                CaseResult(id="c2", status="failed", tokens_used=50, error="boom"),
            ],
        )
        d = eval_result_to_variant_dict(result, variant_id="v1")
        assert d["success"] is False
        assert d["tokens_used"] == 150
        assert d["rounds_to_converge"] == 0
        assert len(d["failure_items"]) == 1
        assert "c2" in d["failure_items"][0]
        assert "boom" in d["failure_items"][0]
        assert d["error"] is None

    def test_failure_uses_status_when_no_error_message(self):
        result = EvalResult(
            total=1,
            passed=0,
            failed=1,
            cases=[CaseResult(id="c1", status="error")],  # no error field
        )
        d = eval_result_to_variant_dict(result, variant_id="v1")
        assert d["success"] is False
        assert d["failure_items"] == ["c1: error"]

    def test_error_param_overrides_success(self):
        result = EvalResult(total=2, passed=2, cases=[])  # all passed
        d = eval_result_to_variant_dict(result, variant_id="v1", error="skill-up crashed")
        assert d["success"] is False
        assert d["tokens_used"] == 0  # error path zeroes tokens
        assert d["rounds_to_converge"] == 0
        assert d["failure_items"] == []
        assert d["error"] == "skill-up crashed"

    def test_empty_cases_returns_failure(self):
        result = EvalResult(total=0, passed=0)  # no cases
        d = eval_result_to_variant_dict(result, variant_id="v1")
        assert d["success"] is False  # all_passed is False when total=0
        assert d["tokens_used"] == 0

    def test_case_with_empty_id_uses_name(self):
        result = EvalResult(
            total=1,
            passed=0,
            failed=1,
            cases=[CaseResult(name="fallback-name", status="failed")],
        )
        d = eval_result_to_variant_dict(result, variant_id="v1")
        assert "fallback-name" in d["failure_items"][0]


# ── quality (graded completion signal) ──────────────────────────────


class TestQuality:
    def _result(self, passed: int, total: int) -> EvalResult:
        cases = [
            CaseResult(id=f"c{i+1}", status="passed" if i < passed else "failed")
            for i in range(total)
        ]
        return EvalResult(
            total=total,
            passed=passed,
            failed=total - passed,
            pass_rate=passed / total,
            cases=cases,
        )

    def test_all_passed_quality_is_one(self):
        d = eval_result_to_variant_dict(self._result(2, 2), variant_id="v1")
        assert d["quality"] == 1.0

    def test_majority_pass_capped_below_one(self):
        """过半但未全过：reward<1 封顶到 0.50，不与满分并列。"""
        d = eval_result_to_variant_dict(self._result(3, 4), variant_id="v1")
        assert d["quality"] == 0.5

    def test_minority_pass_keeps_proportional_gradient(self):
        """低于一半的通过率保留比例梯度（O2 部分分）。"""
        d = eval_result_to_variant_dict(self._result(1, 4), variant_id="v1")
        assert d["quality"] == 0.25

    def test_zero_pass_quality_zero(self):
        d = eval_result_to_variant_dict(self._result(0, 3), variant_id="v1")
        assert d["quality"] == 0.0

    def test_empty_result_quality_zero(self):
        d = eval_result_to_variant_dict(EvalResult(), variant_id="v1")
        assert d["quality"] == 0.0

    def test_error_path_quality_zero(self):
        d = eval_result_to_variant_dict(
            self._result(2, 2), variant_id="v1", error="crashed"
        )
        assert d["quality"] == 0.0

    def _compliance(self, score: float, label: str, nv: bool = False) -> ComplianceReport:
        return ComplianceReport(score=score, label=label, not_verifiable=nv)

    def test_compliance_cheating_caps_quality_to_zero(self):
        """全过但轨迹审计判 cheating：quality 封顶为 0（reward hacking 防御）。"""
        d = eval_result_to_variant_dict(
            self._result(2, 2), variant_id="v1",
            compliance=self._compliance(0.0, "cheating"),
        )
        assert d["quality"] == 0.0
        assert d["success"] is True  # success 语义不变，quality 承载正当性

    def test_compliance_suspected_caps_below_judgment_gap(self):
        d = eval_result_to_variant_dict(
            self._result(2, 2), variant_id="v1",
            compliance=self._compliance(0.49, "suspected_hacking"),
        )
        assert d["quality"] == 0.49

    def test_compliance_clean_does_not_raise_quality(self):
        """clean 报告不抬高 quality（min 语义，只封顶）。"""
        d = eval_result_to_variant_dict(
            self._result(1, 4), variant_id="v1",
            compliance=self._compliance(1.0, "clean"),
        )
        assert d["quality"] == 0.25

    def test_compliance_not_verifiable_does_not_cap(self):
        """证据缺失不封顶：NV 排除而非惩罚（三态语义）。"""
        d = eval_result_to_variant_dict(
            self._result(2, 2), variant_id="v1",
            compliance=self._compliance(0.0, "not_verifiable", nv=True),
        )
        assert d["quality"] == 1.0

    def test_evaluator_returns_quality(self):
        """make_evaluator 产出的 dict 携带 quality（GEPA 梯度信号贯通）。"""
        class _Runner:
            def run(self, skill_dir, **kwargs):
                return EvalResult(
                    total=2, passed=1, failed=1, pass_rate=0.5,
                    cases=[
                        CaseResult(id="c1", status="passed", tokens_used=100),
                        CaseResult(id="c2", status="failed", tokens_used=50),
                    ],
                )

        evaluator = make_evaluator(default_skill_dir_resolver, runner=_Runner())
        d = evaluator({"variant_id": "v1", "metadata": {"skill_dir": "/s"}}, "t", "c")
        assert d["quality"] == 0.5


# ── default_skill_dir_resolver ───────────────────────────────────────


class TestDefaultSkillDirResolver:
    def test_returns_skill_dir_from_metadata(self):
        variant = {"variant_id": "v1", "metadata": {"skill_dir": "/path/to/skill"}}
        assert default_skill_dir_resolver(variant) == "/path/to/skill"

    def test_returns_none_when_metadata_missing(self):
        variant = {"variant_id": "v1"}
        assert default_skill_dir_resolver(variant) is None

    def test_returns_none_when_skill_dir_not_in_metadata(self):
        variant = {"variant_id": "v1", "metadata": {"other": "value"}}
        assert default_skill_dir_resolver(variant) is None

    def test_returns_none_for_empty_variant(self):
        assert default_skill_dir_resolver({}) is None


# ── make_evaluator ────────────────────────────────────────────────────


class TestMakeEvaluator:
    @pytest.fixture
    def fake_runner(self):
        """Build a fake EvalRunner that returns a canned EvalResult.

        Tests override run_result to control what run() returns.
        """
        class FakeRunner:
            def __init__(self):
                self.run_calls: list[dict[str, Any]] = []
                self.run_result: EvalResult | None = None
                self.run_exception: Exception | None = None

            def run(self, skill_dir, **kwargs):
                self.run_calls.append({"skill_dir": skill_dir, **kwargs})
                if self.run_exception is not None:
                    raise self.run_exception
                return self.run_result or EvalResult(
                    total=1, passed=1, cases=[CaseResult(id="c1", status="passed", tokens_used=100)]
                )

            def is_available(self):
                return True

        return FakeRunner()

    def test_evaluator_returns_success_on_all_passed(self, fake_runner):
        fake_runner.run_result = EvalResult(
            total=2,
            passed=2,
            failed=0,
            cases=[
                CaseResult(id="c1", status="passed", tokens_used=100),
                CaseResult(id="c2", status="passed", tokens_used=200),
            ],
        )
        evaluator = make_evaluator(
            default_skill_dir_resolver,
            runner=fake_runner,
        )
        variant = {"variant_id": "v1", "metadata": {"skill_dir": "/skill"}}
        result = evaluator(variant, "task", "context")

        assert result["variant_id"] == "v1"
        assert result["success"] is True
        assert result["tokens_used"] == 300
        assert result["rounds_to_converge"] == 1
        assert result["error"] is None
        # Verify runner.run was called with the resolved skill_dir
        assert fake_runner.run_calls[0]["skill_dir"] == "/skill"

    def test_evaluator_returns_failure_on_partial_pass(self, fake_runner):
        fake_runner.run_result = EvalResult(
            total=2,
            passed=1,
            failed=1,
            cases=[
                CaseResult(id="c1", status="passed"),
                CaseResult(id="c2", status="failed", error="bad output"),
            ],
        )
        evaluator = make_evaluator(default_skill_dir_resolver, runner=fake_runner)
        result = evaluator({"variant_id": "v1", "metadata": {"skill_dir": "/s"}}, "t", "c")

        assert result["success"] is False
        assert len(result["failure_items"]) == 1
        assert "c2" in result["failure_items"][0]

    def test_evaluator_returns_failure_when_skill_dir_unresolved(self, fake_runner):
        """Resolver returns None — evaluator reports clear error, doesn't call runner."""
        evaluator = make_evaluator(default_skill_dir_resolver, runner=fake_runner)
        # No metadata.skill_dir
        result = evaluator({"variant_id": "v1"}, "task", "context")

        assert result["success"] is False
        assert "no skill_dir resolved" in result["error"]
        # Runner should not have been called
        assert len(fake_runner.run_calls) == 0

    def test_evaluator_catches_resolver_crash(self, fake_runner):
        """If resolver raises, evaluator returns failure (doesn't crash GEPA)."""
        def crashing_resolver(variant):
            raise RuntimeError("resolver bug")

        evaluator = make_evaluator(crashing_resolver, runner=fake_runner)
        result = evaluator({"variant_id": "v1"}, "t", "c")

        assert result["success"] is False
        assert "resolver crash" in result["error"]
        assert "RuntimeError" in result["error"]
        assert len(fake_runner.run_calls) == 0

    def test_evaluator_catches_skillup_error(self, fake_runner):
        from hermes.eval.client import SkillUpError

        fake_runner.run_exception = SkillUpError("binary crashed")
        evaluator = make_evaluator(default_skill_dir_resolver, runner=fake_runner)
        result = evaluator(
            {"variant_id": "v1", "metadata": {"skill_dir": "/s"}},
            "task", "context",
        )

        assert result["success"] is False
        assert "skill-up run failed" in result["error"]
        assert "SkillUpError" in result["error"]

    def test_evaluator_catches_filenotfound(self, fake_runner):
        fake_runner.run_exception = FileNotFoundError("eval.yaml missing")
        evaluator = make_evaluator(default_skill_dir_resolver, runner=fake_runner)
        result = evaluator(
            {"variant_id": "v1", "metadata": {"skill_dir": "/s"}},
            "t", "c",
        )

        assert result["success"] is False
        assert "skill-up run failed" in result["error"]
        assert "FileNotFoundError" in result["error"]

    def test_evaluator_catches_unexpected_exception(self, fake_runner):
        """Defensive: even non-skillup exceptions don't crash GEPA."""
        fake_runner.run_exception = ValueError("unexpected bug")
        evaluator = make_evaluator(default_skill_dir_resolver, runner=fake_runner)
        result = evaluator(
            {"variant_id": "v1", "metadata": {"skill_dir": "/s"}},
            "t", "c",
        )

        assert result["success"] is False
        assert "unexpected" in result["error"]
        assert "ValueError" in result["error"]

    def test_evaluator_forwards_run_options(self, fake_runner):
        """include_case/exclude_case/fmt/etc are forwarded to runner.run."""
        fake_runner.run_result = EvalResult(total=1, passed=1)
        evaluator = make_evaluator(
            default_skill_dir_resolver,
            runner=fake_runner,
            include_case=["case-1"],
            exclude_case=["case-2"],
            fmt=["junit"],
            engine="codex",
            model="openai/gpt-4o",
            timeout=300.0,
        )
        evaluator({"variant_id": "v1", "metadata": {"skill_dir": "/s"}}, "t", "c")

        call = fake_runner.run_calls[0]
        assert call["include_case"] == ["case-1"]
        assert call["exclude_case"] == ["case-2"]
        assert call["fmt"] == ["junit"]
        assert call["engine"] == "codex"
        assert call["model"] == "openai/gpt-4o"
        assert call["timeout"] == 300.0

    def test_evaluator_uses_custom_resolver(self, fake_runner):
        """Custom resolver can map variant → skill_dir any way it wants."""
        fake_runner.run_result = EvalResult(total=1, passed=1)
        captured: list[dict[str, Any]] = []

        def custom_resolver(variant):
            captured.append(variant)
            # Use agent_file's parent as skill_dir (POSIX path semantics,
            # independent of the host OS separator).
            from pathlib import PurePosixPath

            return str(PurePosixPath(variant["agent_file"]).parent)

        evaluator = make_evaluator(custom_resolver, runner=fake_runner)
        variant = {"variant_id": "v1", "agent_file": "/skills/foo/builder.md"}
        evaluator(variant, "task", "context")

        assert captured[0] == variant
        assert fake_runner.run_calls[0]["skill_dir"] == "/skills/foo"

    def test_evaluator_task_and_context_ignored_in_run_call(self, fake_runner):
        """GEPA passes task/context but runner.run doesn't use them (info only)."""
        fake_runner.run_result = EvalResult(total=1, passed=1)
        evaluator = make_evaluator(default_skill_dir_resolver, runner=fake_runner)
        evaluator(
            {"variant_id": "v1", "metadata": {"skill_dir": "/s"}},
            "benchmark task description",
            "extra context",
        )
        # Verify run was called (task/context are not run() kwargs)
        assert len(fake_runner.run_calls) == 1
        assert "task" not in fake_runner.run_calls[0]
        assert "context" not in fake_runner.run_calls[0]

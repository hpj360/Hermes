"""Tests for hermes.eval.result — result.json parsing.

Covers CaseResult/EvalResult dataclasses and parse_result_json.
Key focus: defensive parsing (missing fields, type drift, pass_rate
normalization from 0-100 to 0-1).
"""

from __future__ import annotations

import json

import pytest

from hermes.eval.result import CaseResult, EvalResult, parse_result_json


# ── CaseResult.from_dict ──────────────────────────────────────────────


class TestCaseResultParsing:
    def test_full_dict_parses_all_fields(self):
        data = {
            "id": "case-1",
            "name": "case-1",
            "status": "PASSED",
            "pass_rate": 1.0,
            "tokens_used": 1234,
            "duration_ms": 5000,
            "error": None,
            "output": "hello world",
        }
        c = CaseResult.from_dict(data)
        assert c.id == "case-1"
        assert c.name == "case-1"
        assert c.status == "passed"  # normalized to lowercase
        assert c.pass_rate == 1.0
        assert c.tokens_used == 1234
        assert c.duration_ms == 5000
        assert c.error is None
        assert c.output == "hello world"
        assert c.passed is True

    def test_missing_id_falls_back_to_name(self):
        c = CaseResult.from_dict({"name": "fallback-name", "status": "passed"})
        assert c.id == "fallback-name"
        assert c.name == "fallback-name"

    def test_missing_name_falls_back_to_id(self):
        c = CaseResult.from_dict({"id": "fallback-id", "status": "passed"})
        assert c.id == "fallback-id"
        assert c.name == "fallback-id"

    def test_missing_both_id_and_name_defaults_empty(self):
        c = CaseResult.from_dict({"status": "failed"})
        assert c.id == ""
        assert c.name == ""

    def test_status_normalized_to_lowercase(self):
        assert CaseResult.from_dict({"status": "PASSED"}).status == "passed"
        assert CaseResult.from_dict({"status": "FAILED"}).status == "failed"
        assert CaseResult.from_dict({"status": "Error"}).status == "error"

    def test_status_missing_defaults_unknown(self):
        assert CaseResult.from_dict({}).status == "unknown"

    def test_status_falls_back_to_result_field(self):
        c = CaseResult.from_dict({"result": "passed"})
        assert c.status == "passed"

    def test_pass_rate_normalized_from_percentage(self):
        """skill-up may emit 0-100; we normalize to 0-1."""
        assert CaseResult.from_dict({"pass_rate": 100}).pass_rate == 1.0
        assert CaseResult.from_dict({"pass_rate": 50}).pass_rate == 0.5
        assert CaseResult.from_dict({"pass_rate": 0}).pass_rate == 0.0

    def test_pass_rate_kept_when_already_fraction(self):
        assert CaseResult.from_dict({"pass_rate": 0.5}).pass_rate == 0.5
        assert CaseResult.from_dict({"pass_rate": 1.0}).pass_rate == 1.0

    def test_pass_rate_clamped_to_range(self):
        assert CaseResult.from_dict({"pass_rate": 150}).pass_rate == 1.0
        # Negative rates clamp to 0
        assert CaseResult.from_dict({"pass_rate": -10}).pass_rate == 0.0

    def test_pass_rate_invalid_type_defaults_zero(self):
        assert CaseResult.from_dict({"pass_rate": "not-a-number"}).pass_rate == 0.0

    def test_pass_rate_missing_defaults_zero(self):
        assert CaseResult.from_dict({}).pass_rate == 0.0

    def test_pass_rate_falls_back_to_passrate_field(self):
        c = CaseResult.from_dict({"passrate": 75})
        assert c.pass_rate == 0.75

    def test_tokens_used_invalid_type_defaults_zero(self):
        assert CaseResult.from_dict({"tokens_used": "many"}).tokens_used == 0

    def test_tokens_used_falls_back_to_tokens_field(self):
        assert CaseResult.from_dict({"tokens": 999}).tokens_used == 999

    def test_duration_invalid_type_defaults_zero(self):
        assert CaseResult.from_dict({"duration_ms": "fast"}).duration_ms == 0

    def test_error_extracted_from_failure_field(self):
        c = CaseResult.from_dict({"status": "failed", "failure": "boom"})
        assert c.error == "boom"

    def test_output_extracted_from_agent_output_field(self):
        c = CaseResult.from_dict({"agent_output": "result text"})
        assert c.output == "result text"

    def test_passed_property_only_true_for_passed_status(self):
        assert CaseResult.from_dict({"status": "passed"}).passed is True
        assert CaseResult.from_dict({"status": "failed"}).passed is False
        assert CaseResult.from_dict({"status": "error"}).passed is False
        assert CaseResult.from_dict({}).passed is False

    def test_to_dict_roundtrip(self):
        original = CaseResult(
            id="c1", name="c1", status="passed", pass_rate=1.0,
            tokens_used=100, duration_ms=50, error=None, output="ok",
        )
        d = original.to_dict()
        restored = CaseResult.from_dict(d)
        assert restored == original


# ── EvalResult.from_dict ──────────────────────────────────────────────


class TestEvalResultParsing:
    def test_full_dict_with_summary(self):
        data = {
            "summary": {"total": 3, "passed": 2, "failed": 1, "pass_rate": 0.667},
            "cases": [
                {"id": "c1", "status": "passed"},
                {"id": "c2", "status": "passed"},
                {"id": "c3", "status": "failed", "error": "boom"},
            ],
            "metadata": {"engine": "claude_code"},
        }
        r = EvalResult.from_dict(data, workspace="/tmp/ws")
        assert r.total == 3
        assert r.passed == 2
        assert r.failed == 1
        assert abs(r.pass_rate - 0.667) < 0.001
        assert len(r.cases) == 3
        assert r.workspace == "/tmp/ws"
        assert r.metadata == {"engine": "claude_code"}
        assert r.all_passed is False

    def test_summary_missing_recomputes_from_cases(self):
        data = {
            "cases": [
                {"id": "c1", "status": "passed"},
                {"id": "c2", "status": "failed"},
            ]
        }
        r = EvalResult.from_dict(data)
        assert r.total == 2
        assert r.passed == 1
        assert r.failed == 1
        assert r.pass_rate == 0.5

    def test_summary_partial_uses_summary_for_present_fields(self):
        data = {
            "summary": {"total": 5, "pass_rate": 0.8},
            "cases": [{"id": "c1", "status": "passed"}],
        }
        r = EvalResult.from_dict(data)
        assert r.total == 5
        # passed falls back to recomputing from cases (1)
        assert r.passed == 1
        # failed = total - passed
        assert r.failed == 4
        # pass_rate from summary
        assert r.pass_rate == 0.8

    def test_pass_rate_from_summary_normalized_from_percentage(self):
        data = {"summary": {"total": 2, "passed": 2, "pass_rate": 100}}
        r = EvalResult.from_dict(data)
        assert r.pass_rate == 1.0

    def test_pass_rate_invalid_in_summary_falls_back_to_computed(self):
        data = {
            "summary": {"total": 2, "passed": 2, "pass_rate": "bad"},
            "cases": [{"id": "c1", "status": "passed"}, {"id": "c2", "status": "passed"}],
        }
        r = EvalResult.from_dict(data)
        assert r.pass_rate == 1.0  # 2/2

    def test_pass_rate_missing_in_summary_computed_from_passed_total(self):
        data = {"summary": {"total": 4, "passed": 1}}
        r = EvalResult.from_dict(data)
        assert r.pass_rate == 0.25

    def test_total_zero_pass_rate_zero(self):
        r = EvalResult.from_dict({"summary": {"total": 0, "passed": 0}})
        assert r.pass_rate == 0.0
        assert r.all_passed is False  # total=0 means not all_passed

    def test_all_passed_true_when_all_cases_pass(self):
        data = {
            "summary": {"total": 2, "passed": 2, "failed": 0},
            "cases": [{"id": "c1", "status": "passed"}, {"id": "c2", "status": "passed"}],
        }
        r = EvalResult.from_dict(data)
        assert r.all_passed is True

    def test_cases_field_alias_results(self):
        """skill-up may use 'results' instead of 'cases'."""
        data = {"results": [{"id": "c1", "status": "passed"}]}
        r = EvalResult.from_dict(data)
        assert len(r.cases) == 1
        assert r.cases[0].id == "c1"

    def test_metadata_alias_meta(self):
        data = {"meta": {"engine": "codex"}}
        r = EvalResult.from_dict(data)
        assert r.metadata == {"engine": "codex"}

    def test_metadata_non_dict_defaults_empty(self):
        r = EvalResult.from_dict({"metadata": "not a dict"})
        assert r.metadata == {}

    def test_cases_non_dict_items_filtered(self):
        data = {"cases": [{"id": "c1", "status": "passed"}, "not-a-dict", None]}
        r = EvalResult.from_dict(data)
        assert len(r.cases) == 1

    def test_to_dict_roundtrip(self):
        original = EvalResult(
            total=2, passed=1, failed=1, pass_rate=0.5,
            cases=[CaseResult(id="c1", status="passed", pass_rate=1.0)],
            metadata={"engine": "claude_code"},
            workspace="/tmp/ws",
        )
        d = original.to_dict()
        assert d["total"] == 2
        assert d["passed"] == 1
        assert len(d["cases"]) == 1
        assert d["metadata"] == {"engine": "claude_code"}
        assert d["workspace"] == "/tmp/ws"

    def test_raw_preserves_original_data(self):
        data = {"summary": {"total": 1, "passed": 1}, "extra_field": "keep me"}
        r = EvalResult.from_dict(data)
        assert r.raw == data
        assert r.raw["extra_field"] == "keep me"


# ── parse_result_json ─────────────────────────────────────────────────


class TestParseResultJson:
    def test_parses_valid_file(self, tmp_path):
        result_file = tmp_path / "result.json"
        data = {
            "summary": {"total": 1, "passed": 1, "failed": 0, "pass_rate": 1.0},
            "cases": [{"id": "c1", "status": "passed"}],
        }
        result_file.write_text(json.dumps(data), encoding="utf-8")

        result = parse_result_json(result_file)
        assert result.total == 1
        assert result.passed == 1
        assert result.workspace == str(tmp_path)

    def test_raises_filenotfound_for_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_result_json(tmp_path / "nonexistent.json")

    def test_raises_jsondecodeerror_for_invalid_json(self, tmp_path):
        bad_file = tmp_path / "result.json"
        bad_file.write_text("not json {{{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            parse_result_json(bad_file)

    def test_accepts_string_path(self, tmp_path):
        result_file = tmp_path / "result.json"
        result_file.write_text('{"summary": {"total": 0}}', encoding="utf-8")
        result = parse_result_json(str(result_file))
        assert result.total == 0

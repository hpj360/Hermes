"""Tests for hermes.eval.runner — orchestration layer.

Covers path helpers (find_eval_yaml, default_output_dir, find_latest_iteration,
find_result_json) and operations (validate, list_cases, run, report).
Run tests use a fake SkillUpClient that writes a synthetic result.json
to a tmp workspace, simulating skill-up's real artifact output.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from hermes.eval.client import SkillUpClient, SkillUpError, SkillUpNotFoundError
from hermes.eval.runner import EvalRunner, ValidationResult


def _fake_completed(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=args or ["skill-up"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _make_available_client(
    monkeypatch,
    tmp_path,
    run_fn=None,
) -> SkillUpClient:
    """Build a SkillUpClient whose binary is 'available'."""
    fake_bin = tmp_path / "skill-up"
    fake_bin.write_text("#!/bin/sh\nexit 0\n")
    fake_bin.chmod(0o755)
    monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))
    if run_fn is None:
        def run_fn_default(argv, **kwargs):
            return _fake_completed(args=argv)
        run_fn = run_fn_default
    return SkillUpClient(run_fn=run_fn)


def _write_result_json(
    workspace: Path,
    iteration: int = 1,
    total: int = 1,
    passed: int = 1,
    failed: int = 0,
) -> Path:
    """Write a synthetic result.json into workspace/iteration-N/."""
    iter_dir = workspace / f"iteration-{iteration}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    result_file = iter_dir / "result.json"
    data = {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0.0,
        },
        "cases": [
            {"id": f"case-{i+1}", "status": "passed" if i < passed else "failed"}
            for i in range(total)
        ],
        "metadata": {"engine": "claude_code"},
    }
    result_file.write_text(json.dumps(data), encoding="utf-8")
    return result_file


# ── Path helpers ─────────────────────────────────────────────────────


class TestFindEvalYaml:
    def test_finds_standard_location(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        eval_yaml = skill_dir / "evals" / "eval.yaml"
        eval_yaml.write_text("schema_version: v1alpha1")
        assert EvalRunner.find_eval_yaml(skill_dir) == eval_yaml

    def test_falls_back_to_flat_layout(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        eval_yaml = skill_dir / "eval.yaml"
        eval_yaml.write_text("schema_version: v1alpha1")
        assert EvalRunner.find_eval_yaml(skill_dir) == eval_yaml

    def test_returns_none_when_not_found(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        assert EvalRunner.find_eval_yaml(skill_dir) is None

    def test_prefers_evals_subdir_over_flat(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        standard = skill_dir / "evals" / "eval.yaml"
        standard.write_text("standard")
        flat = skill_dir / "eval.yaml"
        flat.write_text("flat")
        # Standard location should win (checked first)
        assert EvalRunner.find_eval_yaml(skill_dir) == standard


class TestDefaultOutputDir:
    def test_returns_sibling_workspace_dir(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        result = EvalRunner.default_output_dir(skill_dir)
        assert result == tmp_path / "my-skill-workspace"

    def test_resolves_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skill_dir = Path("my-skill")
        skill_dir.mkdir()
        result = EvalRunner.default_output_dir(skill_dir)
        assert result == (tmp_path / "my-skill-workspace")


class TestFindLatestIteration:
    def test_returns_highest_iteration(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "iteration-1").mkdir()
        (ws / "iteration-3").mkdir()
        (ws / "iteration-2").mkdir()
        result = EvalRunner.find_latest_iteration(ws)
        assert result == ws / "iteration-3"

    def test_returns_none_when_no_iterations(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "other-dir").mkdir()
        (ws / "file.txt").write_text("x")
        assert EvalRunner.find_latest_iteration(ws) is None

    def test_returns_none_when_workspace_missing(self, tmp_path):
        assert EvalRunner.find_latest_iteration(tmp_path / "nonexistent") is None

    def test_ignores_non_iteration_dirs(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "iteration-1").mkdir()
        (ws / "not-iteration").mkdir()
        (ws / "iteration-abc").mkdir()  # non-numeric suffix ignored
        result = EvalRunner.find_latest_iteration(ws)
        assert result == ws / "iteration-1"


class TestFindResultJson:
    def test_returns_path_when_result_exists(self, tmp_path):
        ws = tmp_path / "workspace"
        iter_dir = ws / "iteration-1"
        iter_dir.mkdir(parents=True)
        result_file = iter_dir / "result.json"
        result_file.write_text("{}")
        assert EvalRunner.find_result_json(ws) == result_file

    def test_returns_none_when_no_iterations(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        assert EvalRunner.find_result_json(ws) is None

    def test_returns_none_when_result_json_missing(self, tmp_path):
        ws = tmp_path / "workspace"
        (ws / "iteration-1").mkdir(parents=True)
        # No result.json written
        assert EvalRunner.find_result_json(ws) is None


# ── Operations ───────────────────────────────────────────────────────


class TestValidate:
    def test_raises_filenotfound_when_eval_yaml_missing(self, tmp_path, monkeypatch):
        client = _make_available_client(monkeypatch, tmp_path)
        runner = EvalRunner(client=client)
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="eval.yaml not found"):
            runner.validate(skill_dir)

    def test_returns_valid_result_on_success(self, tmp_path, monkeypatch):
        captured: dict[str, Any] = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return _fake_completed(
                returncode=0,
                stdout="✓ eval.yaml is valid (loaded 3 case(s))",
                args=argv,
            )

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        result = runner.validate(skill_dir)
        assert isinstance(result, ValidationResult)
        assert result.valid is True
        assert result.case_count == 3
        assert "loaded 3 case" in result.message

    def test_returns_invalid_result_on_nonzero_exit(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            return _fake_completed(
                returncode=1,
                stdout="",
                stderr="eval.yaml: missing required field 'engine'",
                args=argv,
            )

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        result = runner.validate(skill_dir)
        assert result.valid is False
        assert result.case_count == 0

    def test_returns_invalid_on_skillup_error(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            raise SkillUpError("binary crashed")

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        result = runner.validate(skill_dir)
        assert result.valid is False
        assert "binary crashed" in result.message

    def test_case_count_defaults_to_zero_when_pattern_missing(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            return _fake_completed(returncode=0, stdout="all good", args=argv)

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        result = runner.validate(skill_dir)
        assert result.case_count == 0


class TestListCases:
    def test_returns_case_ids_from_stdout(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            return _fake_completed(
                returncode=0,
                stdout="case-1\ncase-2\ncase-3\n",
                args=argv,
            )

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        cases = runner.list_cases(skill_dir)
        assert cases == ["case-1", "case-2", "case-3"]

    def test_raises_filenotfound_when_eval_yaml_missing(self, tmp_path, monkeypatch):
        client = _make_available_client(monkeypatch, tmp_path)
        runner = EvalRunner(client=client)
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            runner.list_cases(skill_dir)

    def test_returns_empty_list_on_nonzero_exit(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            return _fake_completed(returncode=1, stderr="error", args=argv)

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        assert runner.list_cases(skill_dir) == []

    def test_returns_empty_list_on_skillup_error(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            raise SkillUpError("crash")

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        assert runner.list_cases(skill_dir) == []


class TestRun:
    def test_raises_filenotfound_when_eval_yaml_missing(self, tmp_path, monkeypatch):
        client = _make_available_client(monkeypatch, tmp_path)
        runner = EvalRunner(client=client)
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="eval.yaml not found"):
            runner.run(skill_dir)

    def test_parses_result_json_after_run(self, tmp_path, monkeypatch):
        """End-to-end: client runs, writes result.json, runner parses it."""
        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        # Default workspace: sibling of skill_dir
        expected_workspace = tmp_path / "my-skill-workspace"

        def fake_run(argv, **kwargs):
            # Simulate skill-up writing result.json
            output_dir = None
            # Extract --output-dir from argv
            if "--output-dir" in argv:
                idx = argv.index("--output-dir")
                output_dir = Path(argv[idx + 1])
            if output_dir is None:
                output_dir = expected_workspace
            _write_result_json(output_dir, iteration=1, total=2, passed=2, failed=0)
            return _fake_completed(
                returncode=0,
                stdout="[INFO] Results written to " + str(output_dir),
                args=argv,
            )

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        result = runner.run(skill_dir)
        assert result.total == 2
        assert result.passed == 2
        assert result.failed == 0
        assert result.all_passed is True
        assert str(expected_workspace) in result.workspace

    def test_run_with_partial_failure_still_parses_result(self, tmp_path, monkeypatch):
        """skill-up may exit non-zero on partial passes; result.json still written."""
        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        workspace = tmp_path / "my-skill-workspace"

        def fake_run(argv, **kwargs):
            _write_result_json(workspace, total=3, passed=2, failed=1)
            # Non-zero exit (partial failure)
            return _fake_completed(returncode=1, stderr="1 case failed", args=argv)

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        result = runner.run(skill_dir)
        assert result.total == 3
        assert result.passed == 2
        assert result.failed == 1
        assert result.all_passed is False

    def test_raises_filenotfound_when_result_json_missing(self, tmp_path, monkeypatch):
        """skill-up ran but didn't write result.json — raise clear error."""
        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        def fake_run(argv, **kwargs):
            # Don't write result.json
            return _fake_completed(returncode=0, stdout="done", args=argv)

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        with pytest.raises(FileNotFoundError, match="result.json not found"):
            runner.run(skill_dir)

    def test_propagates_skillup_not_found(self, tmp_path, monkeypatch):
        """Binary missing — propagate SkillUpNotFoundError, don't swallow."""
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: None)
        client = SkillUpClient()
        runner = EvalRunner(client=client)

        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        with pytest.raises(SkillUpNotFoundError):
            runner.run(skill_dir)

    def test_propagates_skillup_error_on_oserror(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        def fake_run(argv, **kwargs):
            raise OSError("disk full")

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        with pytest.raises(SkillUpError, match="invocation failed"):
            runner.run(skill_dir)

    def test_custom_output_dir_used(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        custom_output = tmp_path / "custom-output"

        def fake_run(argv, **kwargs):
            # Verify --output-dir was passed
            assert "--output-dir" in argv
            idx = argv.index("--output-dir")
            assert argv[idx + 1] == str(custom_output)
            _write_result_json(custom_output, total=1, passed=1)
            return _fake_completed(args=argv)

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        result = runner.run(skill_dir, output_dir=custom_output)
        assert result.total == 1
        assert str(custom_output) in result.workspace

    def test_forwards_filters_to_client(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "my-skill"
        (skill_dir / "evals").mkdir(parents=True)
        (skill_dir / "evals" / "eval.yaml").write_text("schema_version: v1alpha1")

        captured: dict[str, Any] = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            workspace = tmp_path / "my-skill-workspace"
            _write_result_json(workspace, total=1, passed=1)
            return _fake_completed(args=argv)

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        runner.run(
            skill_dir,
            include_case=["case-1"],
            exclude_case=["case-2"],
            fmt=["junit"],
            engine="codex",
            model="openai/gpt-4o",
            iteration=5,
        )
        argv = captured["argv"]
        assert "--include-case-name" in argv
        assert "case-1" in argv
        assert "--exclude-case-name" in argv
        assert "--format" in argv
        assert "junit" in argv
        assert "--engine" in argv
        assert "codex" in argv
        assert "--model" in argv
        assert "--iteration" in argv
        assert "5" in argv


class TestReport:
    def test_returns_success_dict_on_zero_exit(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            return _fake_completed(returncode=0, stdout="report written", args=argv)

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        result = runner.report(tmp_path / "workspace", fmt=["html"])
        assert result["success"] is True
        assert result["returncode"] == 0
        assert result["stdout"] == "report written"

    def test_returns_failure_dict_on_skillup_error(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            raise SkillUpError("report generation failed")

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        result = runner.report(tmp_path / "workspace")
        assert result["success"] is False
        assert "error" in result

    def test_returns_failure_dict_on_nonzero_exit(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            return _fake_completed(returncode=1, stderr="bad workspace", args=argv)

        client = _make_available_client(monkeypatch, tmp_path, run_fn=fake_run)
        runner = EvalRunner(client=client)

        result = runner.report(tmp_path / "workspace")
        assert result["success"] is False
        assert result["returncode"] == 1


class TestIsAvailable:
    def test_returns_true_when_binary_available(self, tmp_path, monkeypatch):
        client = _make_available_client(monkeypatch, tmp_path)
        runner = EvalRunner(client=client)
        assert runner.is_available() is True

    def test_returns_false_when_binary_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: None)
        client = SkillUpClient()
        runner = EvalRunner(client=client)
        assert runner.is_available() is False

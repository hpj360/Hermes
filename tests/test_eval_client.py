"""Tests for hermes.eval.client — skill-up subprocess wrapper.

All tests inject a fake run_fn to avoid needing the real skill-up binary.
is_available() is tested via monkeypatch of shutil.which.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from hermes.eval.client import SkillUpClient, SkillUpError, SkillUpNotFoundError


def _fake_completed(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Build a CompletedProcess for test fakes."""
    return subprocess.CompletedProcess(
        args=args or ["skill-up"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestIsAvailable:
    def test_returns_false_when_binary_not_on_path(self, monkeypatch):
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: None)
        client = SkillUpClient()
        assert client.is_available() is False

    def test_returns_true_when_binary_on_path(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))
        client = SkillUpClient()
        assert client.is_available() is True

    def test_explicit_path_checks_executable_bit(self, tmp_path):
        # Non-executable file
        non_exec = tmp_path / "skill-up"
        non_exec.write_text("binary")
        non_exec.chmod(0o644)  # no execute bit
        client = SkillUpClient(binary=str(non_exec))
        assert client.is_available() is False

        # Make executable
        non_exec.chmod(0o755)
        assert client.is_available() is True

    def test_explicit_path_missing_file_returns_false(self, tmp_path):
        client = SkillUpClient(binary=str(tmp_path / "nonexistent"))
        assert client.is_available() is False


class TestInvoke:
    def test_raises_not_found_when_binary_missing(self, monkeypatch):
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: None)
        client = SkillUpClient()
        with pytest.raises(SkillUpNotFoundError, match="skill-up binary not found"):
            client._invoke(["skill-up", "validate"])

    def test_returns_completed_process_on_success(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        captured: dict[str, Any] = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return _fake_completed(returncode=0, stdout="ok", args=argv)

        client = SkillUpClient(run_fn=fake_run)
        result = client._invoke(["skill-up", "validate"])
        assert result.returncode == 0
        assert result.stdout == "ok"
        assert captured["argv"] == ["skill-up", "validate"]
        assert captured["kwargs"]["capture_output"] is True
        assert captured["kwargs"]["text"] is True
        assert captured["kwargs"]["check"] is False

    def test_timeout_raises_skillup_error(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        def fake_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=5.0)

        client = SkillUpClient(run_fn=fake_run, default_timeout=5.0)
        with pytest.raises(SkillUpError, match="timed out after 5.0s"):
            client._invoke(["skill-up", "run"])

    def test_oserror_raises_skillup_error(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        def fake_run(argv, **kwargs):
            raise OSError("permission denied")

        client = SkillUpClient(run_fn=fake_run)
        with pytest.raises(SkillUpError, match="invocation failed"):
            client._invoke(["skill-up", "run"])

    def test_uses_custom_timeout_over_default(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        captured: dict[str, Any] = {}

        def fake_run(argv, **kwargs):
            captured["timeout"] = kwargs["timeout"]
            return _fake_completed(args=argv)

        client = SkillUpClient(run_fn=fake_run, default_timeout=600.0)
        client._invoke(["skill-up", "run"], timeout=120.0)
        assert captured["timeout"] == 120.0

    def test_cwd_passed_to_run_fn(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        captured: dict[str, Any] = {}

        def fake_run(argv, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            return _fake_completed(args=argv)

        client = SkillUpClient(run_fn=fake_run)
        client._invoke(["skill-up", "run"], cwd="/some/path")
        assert captured["cwd"] == "/some/path"

    def test_cwd_none_when_not_provided(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        captured: dict[str, Any] = {}

        def fake_run(argv, **kwargs):
            captured["cwd"] = kwargs.get("cwd")
            return _fake_completed(args=argv)

        client = SkillUpClient(run_fn=fake_run)
        client._invoke(["skill-up", "run"])
        assert captured["cwd"] is None


class TestSubcommandWrappers:
    @pytest.fixture
    def client_with_fake_run(self, monkeypatch, tmp_path):
        """Client with available binary and injectable fake run_fn."""
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        captured: list[dict[str, Any]] = []

        def fake_run(argv, **kwargs):
            captured.append({"argv": argv, "kwargs": kwargs})
            return _fake_completed(returncode=0, stdout="ok", args=argv)

        return SkillUpClient(run_fn=fake_run), captured

    def test_run_builds_correct_argv(self, client_with_fake_run):
        client, captured = client_with_fake_run
        client.run(
            "/path/to/eval.yaml",
            include_case=["case-1"],
            exclude_case=["case-2"],
            fmt=["junit", "html"],
            output_dir="/tmp/out",
            iteration=3,
            engine="codex",
            model="openai/gpt-4o",
        )
        argv = captured[0]["argv"]
        assert argv[0] == "skill-up"
        assert argv[1] == "run"
        assert "/path/to/eval.yaml" in argv
        assert "--include-case-name" in argv
        assert "case-1" in argv
        assert "--exclude-case-name" in argv
        assert "case-2" in argv
        assert argv.count("--format") == 2
        assert "junit" in argv
        assert "html" in argv
        assert "--output-dir" in argv
        assert "/tmp/out" in argv
        assert "--iteration" in argv
        assert "3" in argv
        assert "--engine" in argv
        assert "codex" in argv
        assert "--model" in argv
        assert "openai/gpt-4o" in argv

    def test_run_minimal_argv(self, client_with_fake_run):
        client, captured = client_with_fake_run
        client.run("/path/to/eval.yaml")
        argv = captured[0]["argv"]
        assert argv == ["skill-up", "run", "/path/to/eval.yaml"]

    def test_validate_builds_argv(self, client_with_fake_run):
        client, captured = client_with_fake_run
        client.validate("/path/to/eval.yaml", cwd="/skill")
        argv = captured[0]["argv"]
        assert argv == ["skill-up", "validate", "/path/to/eval.yaml"]
        assert captured[0]["kwargs"]["cwd"] == "/skill"

    def test_list_cases_builds_argv(self, client_with_fake_run):
        client, captured = client_with_fake_run
        client.list_cases("/path/to/eval.yaml")
        argv = captured[0]["argv"]
        assert argv == ["skill-up", "list-cases", "/path/to/eval.yaml"]

    def test_report_builds_argv_with_format(self, client_with_fake_run):
        client, captured = client_with_fake_run
        client.report("/workspace", fmt=["html"])
        argv = captured[0]["argv"]
        assert argv[1] == "report"
        assert "/workspace" in argv
        assert "--format" in argv
        assert "html" in argv

    def test_report_minimal_argv(self, client_with_fake_run):
        client, captured = client_with_fake_run
        client.report("/workspace")
        argv = captured[0]["argv"]
        assert argv == ["skill-up", "report", "/workspace"]


class TestVersion:
    def test_returns_unknown_when_binary_missing(self, monkeypatch):
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: None)
        client = SkillUpClient()
        assert client.version() == "unknown"

    def test_returns_stdout_stripped(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        def fake_run(argv, **kwargs):
            return _fake_completed(returncode=0, stdout="skill-up v1.2.3\n", args=argv)

        client = SkillUpClient(run_fn=fake_run)
        assert client.version() == "skill-up v1.2.3"

    def test_returns_unknown_on_skillup_error(self, monkeypatch, tmp_path):
        fake_bin = tmp_path / "skill-up"
        fake_bin.write_text("#!/bin/sh\nexit 0\n")
        fake_bin.chmod(0o755)
        monkeypatch.setattr("hermes.eval.client.shutil.which", lambda _: str(fake_bin))

        def fake_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=1.0)

        client = SkillUpClient(run_fn=fake_run, default_timeout=1.0)
        # Should not raise — version() catches SkillUpError
        assert client.version() == "unknown"


class TestBuildArgv:
    def test_builds_argv_with_subcommand_and_args(self):
        client = SkillUpClient(binary="my-skill-up")
        argv = client._build_argv("run", "path/to/eval", "--json")
        assert argv == ["my-skill-up", "run", "path/to/eval", "--json"]

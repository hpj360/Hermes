"""Security regression tests for skill subprocess environment isolation.

P1-10: a compromised skill must never be able to harvest secrets from the
parent process environment. These tests pin the allow-list boundary so any
future regression that leaks a secret-shaped variable is caught in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.workbench.skill_runner import SkillRunner, SkillSpec, _looks_sensitive


# ---------------------------------------------------------------------------
# 8 sensitive env var names that must NEVER leak into a skill subprocess.
# Each exercises a different part of the sensitive-name heuristic
# (_SENSITIVE_SUBSTRINGS / _SENSITIVE_SUFFIXES).
# ---------------------------------------------------------------------------
SENSITIVE_CASES = [
    "OPENAI_API_KEY",          # _api_key suffix
    "ANTHROPIC_API_KEY",       # _api_key suffix
    "NOTION_API_KEY",          # _api_key suffix
    "GITHUB_TOKEN",            # "token" substring
    "SLACK_BOT_TOKEN",         # "token" substring
    "AWS_SECRET_ACCESS_KEY",   # "secret" substring
    "DATABASE_PASSWORD",       # "password" substring
    "MYSQL_PWD",               # "pwd" substring
]

NON_SENSITIVE_CASES = [
    "PATH",
    "HERMES_STATE_DIR",
    "HERMES_PROJECT_ROOT",
    "LANG",
    "PYTHONIOENCODING",
]


def _spec(requires_env: list[str] | None = None) -> SkillSpec:
    """Build a minimal SkillSpec for _build_safe_env testing."""
    return SkillSpec(
        name="test",
        path=Path("/tmp/test"),
        description="",
        runtime="python",
        requires_bins=[],
        requires_env=requires_env or [],
        entrypoint=None,
        raw_metadata={},
    )


# ---------------------------------------------------------------------------
# _looks_sensitive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SENSITIVE_CASES)
def test_looks_sensitive_flags_secret_names(name: str) -> None:
    """Every sensitive-shaped name must be flagged."""
    assert _looks_sensitive(name) is True


@pytest.mark.parametrize("name", NON_SENSITIVE_CASES)
def test_looks_sensitive_ignores_benign_names(name: str) -> None:
    """Benign names must not be flagged."""
    assert _looks_sensitive(name) is False


# ---------------------------------------------------------------------------
# _build_safe_env — allow-list boundary
# ---------------------------------------------------------------------------


def test_build_safe_env_strips_all_sensitive(monkeypatch, tmp_path: Path) -> None:
    """No sensitive variable may survive the allow-list, even under passthrough."""
    runner = SkillRunner(base_dir=tmp_path)
    for name in SENSITIVE_CASES:
        monkeypatch.setenv(name, "supersecretvalue")
    monkeypatch.setenv("HERMES_STATE_DIR", str(tmp_path / "state"))

    env = runner._build_safe_env(_spec())

    for name in SENSITIVE_CASES:
        assert name not in env, f"sensitive {name} leaked into skill env"
    assert env["HERMES_STATE_DIR"] == str(tmp_path / "state")


def test_build_safe_env_keeps_benign_passthrough(monkeypatch, tmp_path: Path) -> None:
    """Non-sensitive variables should pass through for compatibility."""
    runner = SkillRunner(base_dir=tmp_path)
    monkeypatch.setenv("HERMES_PROJECT_ROOT", "/workspace/hermes")

    env = runner._build_safe_env(_spec())

    assert env["HERMES_PROJECT_ROOT"] == "/workspace/hermes"


def test_requires_env_cannot_force_sensitive(monkeypatch, tmp_path: Path) -> None:
    """A skill explicitly requiring a secret must still be denied."""
    runner = SkillRunner(base_dir=tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")

    env = runner._build_safe_env(_spec(requires_env=["GITHUB_TOKEN"]))

    assert "GITHUB_TOKEN" not in env


def test_requires_env_allows_benign_extra(monkeypatch, tmp_path: Path) -> None:
    """A skill may opt in to a non-sensitive variable via requires_env."""
    runner = SkillRunner(base_dir=tmp_path)
    monkeypatch.setenv("MY_APP_CONFIG", "/etc/myapp")

    env = runner._build_safe_env(_spec(requires_env=["MY_APP_CONFIG"]))

    assert env["MY_APP_CONFIG"] == "/etc/myapp"

"""Basic tests for Hermes configuration."""

from __future__ import annotations

from hermes.config import Settings, get_settings
from hermes.skills import discover_skills, list_knowledge_docs, skills_dir, knowledge_dir


def test_settings_defaults() -> None:
    settings = get_settings(force_reload=True)
    assert isinstance(settings, Settings)
    assert settings.openclaw_gateway_port == 18789
    assert settings.openclaw_model_primary == "anthropic/claude-sonnet-4-5"
    assert settings.openclaw_model_fallback == "openai/gpt-4o"
    assert settings.hermes_project_root.exists()


def test_provider_detection_includes_ollama_by_default() -> None:
    settings = get_settings()
    providers = settings.configured_providers()
    assert "ollama" in providers


def test_state_dirs_created() -> None:
    settings = get_settings(force_reload=True)
    assert settings.hermes_state_dir.exists()
    assert settings.hermes_cache_dir.exists()


def test_skills_discovery() -> None:
    root = skills_dir()
    assert root.exists()
    skills = discover_skills()
    assert len(skills) > 0
    assert any(s.name == "agent-browser" for s in skills)


def test_knowledge_discovery() -> None:
    root = knowledge_dir()
    assert root.exists()
    docs = list_knowledge_docs()
    assert len(docs) >= 4


def test_inherit_env_paths_overridable(monkeypatch) -> None:
    """阶段C: inherit_env_paths 应可通过 HERMES_INHERIT_ENV_PATHS 覆盖，
    不再是硬编码 ClassVar（发现2.1）。"""
    from pathlib import Path

    monkeypatch.setenv("HERMES_INHERIT_ENV_PATHS", "/custom/a:/custom/b")
    settings = get_settings(force_reload=True)
    paths = settings.inherit_env_paths()
    assert paths == [Path("/custom/a"), Path("/custom/b")]


def test_inherit_env_paths_repo_relative(monkeypatch) -> None:
    """阶段C: 无显式覆盖时，路径基于 hermes_main_repo_path 动态计算。"""
    from pathlib import Path

    monkeypatch.delenv("HERMES_INHERIT_ENV_PATHS", raising=False)
    monkeypatch.setenv("HERMES_MAIN_REPO_PATH", "/some/openclaw/repo")
    settings = get_settings(force_reload=True)
    paths = settings.inherit_env_paths()
    # Should include the project root .env and the custom repo .env.
    assert any(p == Path("/some/openclaw/repo/.env") for p in paths)

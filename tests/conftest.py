"""Shared pytest fixtures for Hermes tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Force child skill scripts to emit UTF-8 on stdout/stderr. On Windows the
# locale default is GBK, which crashes scripts that print non-GBK characters
# (emoji, CJK, etc.) to a pipe. Setting PYTHONIOENCODING makes subprocess
# captures use UTF-8 regardless of the platform locale.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


@pytest.fixture
def reset_settings() -> Iterator[None]:
    """Clear the settings singleton before and after the test."""
    from hermes import config as _config
    _config._hermes_settings = None
    yield
    _config._hermes_settings = None


@pytest.fixture
def tmp_state_dir(
    tmp_path: Path, reset_settings: Iterator[None], monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect HERMES_STATE_DIR/CACHE_DIR/PROFILE_PATH to tmp_path and reload settings."""
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    profile = tmp_path / "profile.json"
    state.mkdir()
    cache.mkdir()
    monkeypatch.setenv("HERMES_STATE_DIR", str(state))
    monkeypatch.setenv("HERMES_CACHE_DIR", str(cache))
    monkeypatch.setenv("HERMES_PROFILE_PATH", str(profile))
    from hermes.config import get_settings
    get_settings(force_reload=True)
    yield tmp_path

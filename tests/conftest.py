"""Shared test fixtures for Hermes tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_loops_dir(tmp_path, monkeypatch):
    """Redirect hermes.loop.loops_dir and _project_root to a per-test tmp dir.

    Loop persistence tests previously wrote to the real ``.loops/`` directory
    and relied on try/finally cleanup. This autouse fixture patches
    ``loops_dir`` so tests are fully isolated and never leak state into the
    real project.

    runner.py and main.py import ``loops_dir`` at module level (binding the
    original function at import time), which would bypass a module-attribute
    patch on ``hermes.loop`` alone. We patch their bindings too so future
    runner/main tests are isolated.

    ``_project_root`` is also patched because ``knowledge_hygiene_scan()``
    calls it directly (not via ``loops_dir``) to locate ``knowledge/``,
    ``skills/``, ``manifest.json`` and ``AGENTS.md``. Without this patch, any
    test that triggers a knowledge-hygiene round (e.g. via ``resume_loop``)
    would scan the real ``/workspace`` and become environment-dependent.
    """
    import hermes.loop

    test_loops_dir = tmp_path / ".loops"
    monkeypatch.setattr(hermes.loop, "loops_dir", lambda: test_loops_dir)
    # Patch _project_root so knowledge_hygiene_scan reads tmp_path (which has
    # no knowledge/skills/manifest/AGENTS.md) instead of the real /workspace.
    monkeypatch.setattr(hermes.loop, "_project_root", lambda: tmp_path)
    # Patch module-level imports in runner.py and main.py that bound loops_dir
    # at import time (before this fixture runs).
    import hermes.main
    import hermes.runner

    monkeypatch.setattr(hermes.runner, "loops_dir", lambda: test_loops_dir)
    monkeypatch.setattr(hermes.main, "loops_dir", lambda: test_loops_dir)
    yield

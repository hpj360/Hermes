"""workbench 测试的共享隔离 fixtures。

状态/缓存/画像路径的 env 隔离由 ``tests/conftest.py`` 的 autouse fixture
统一负责。这里额外重置 workbench 侧的进程级单例，确保每个测试拿到干净的
调度中心、记忆服务与审计存储（否则会串测并写入真实 ``.state``）。
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_workbench_singletons() -> Iterator[None]:
    """重置调度中心 / 记忆缓存 / 审计存储单例。"""
    _reset_singletons()
    yield
    _reset_singletons()


def _reset_singletons() -> None:
    """Drop cached scheduler center / memory services / audit store."""
    from hermes.workbench import audit as wb_audit
    from hermes.workbench import cli as wb_cli

    wb_cli._reset_scheduler_center()
    wb_cli._reset_memory_cache()
    wb_audit._store = None

"""Tests for hermes.workbench.async_bridge (P2-5)."""

from __future__ import annotations

import asyncio

import pytest

from hermes.workbench.async_bridge import run_async_in_sync, run_sync_in_async


def test_run_async_in_sync_returns_value() -> None:
    async def coro() -> int:
        return 42

    assert run_async_in_sync(coro()) == 42


def test_run_async_in_sync_raises_inside_running_loop() -> None:
    async def inner() -> None:
        coro = asyncio.sleep(0)
        with pytest.raises(RuntimeError):
            run_async_in_sync(coro)
        coro.close()  # avoid "never awaited" warning

    asyncio.run(inner())


def test_run_async_in_sync_propagates_exception() -> None:
    async def coro() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError):
        run_async_in_sync(coro())


def test_run_sync_in_async_offloads_blocking_call() -> None:
    calls: list[str] = []

    def blocking(x: int) -> int:
        calls.append("ran")
        return x * 2

    result = asyncio.run(run_sync_in_async(blocking, 21))
    assert result == 42
    assert calls == ["ran"]


def test_run_sync_in_async_preserves_args_kwargs() -> None:
    def fn(a: int, *, b: str) -> str:
        return f"{a}-{b}"

    result = asyncio.run(run_sync_in_async(fn, 7, b="x"))
    assert result == "7-x"

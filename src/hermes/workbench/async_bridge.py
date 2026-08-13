"""Sync/async bridge for the workbench runtime (P2-5).

The workbench runtime layer (``agent_loop`` / ``scheduler`` / ``skill_runner``)
is deliberately synchronous and stdlib-only. ``content_team`` exposes an async
FastAPI + SQLAlchemy-async surface. This module formalizes the boundary with
two thin, dependency-free helpers so neither layer has to be rewritten:

* :func:`run_async_in_sync` — call an awaitable from synchronous code (spins up
  a fresh event loop when none is running; raises when already inside a loop).
* :func:`run_sync_in_async` — offload a blocking callable to a worker thread
  from async code via ``asyncio.to_thread``.

See ADR-0007 for the boundary rationale and the "await directly in async
context" rule.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

__all__ = ["run_async_in_sync", "run_sync_in_async"]

T = TypeVar("T")


def run_async_in_sync(coro: Awaitable[T]) -> T:
    """Run an awaitable from synchronous code.

    Creates a fresh event loop when no loop is running (the common case for the
    synchronous workbench layer). Raises :class:`RuntimeError` when called from
    within a running event loop — in that case the caller is already async and
    must ``await`` the coroutine directly (the "await directly" rule).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "run_async_in_sync called from within a running event loop; "
        "await the coroutine directly instead"
    )


async def run_sync_in_async(fn: Callable[..., T], *args: object, **kwargs: object) -> T:
    """Run a blocking synchronous callable in a worker thread from async code.

    Bridges the other direction: an async caller (e.g. a FastAPI handler in
    ``content_team``) needing to invoke a blocking workbench primitive (e.g.
    ``AgentLoop.execute``) without stalling the event loop.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)

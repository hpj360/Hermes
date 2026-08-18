"""Atomic append-only JSONL persistence primitive (inlined, zero dependencies).

An exclusive sibling ``*.lock`` file guards each append so concurrent writers
(multiple processes / threads) never interleave bytes within a line. Works
cross-platform: ``fcntl.flock`` on Unix, ``msvcrt.locking`` on Windows.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

__all__ = ["atomic_append_jsonl"]


def _acquire_lock(path: Path) -> int:
    """Acquire an exclusive lock via a sibling ``*.lock`` file.

    Returns an fd that must be released via :func:`_release_lock`.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    if sys.platform == "win32":  # pragma: no cover on non-Windows CI
        import msvcrt

        # msvcrt.locking requires the file to have at least 1 byte.
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, 0)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _release_lock(fd: int) -> None:
    """Release a lock acquired via :func:`_acquire_lock`."""
    if sys.platform == "win32":  # pragma: no cover on non-Windows CI
        import msvcrt

        os.lseek(fd, 0, 0)
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def atomic_append_jsonl(path: Path, obj: Any) -> None:
    """Append *obj* as a JSON line to *path*, guarded by an exclusive lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    lock_fd = _acquire_lock(path)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    finally:
        _release_lock(lock_fd)

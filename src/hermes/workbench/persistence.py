"""Atomic file persistence primitives.

All Workbench state (facts, episodes, tasks, plans) is persisted via these
helpers to survive crashes and concurrent access:
- atomic_write_text / atomic_write_json: tempfile + os.replace
- safe_read_json: returns default on missing/corrupt, backs up corrupt as *.corrupt
- atomic_append_jsonl: cross-platform exclusive-lock guarded append
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str) -> None:
    """Write *content* to *path* atomically (tempfile + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    """Serialize *obj* to JSON and write atomically to *path*."""
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    atomic_write_text(path, text)


def safe_read_json(path: Path, default: Any = None) -> Any:
    """Read JSON from *path*. Return *default* if missing or corrupt.

    Corrupt files are renamed to ``<path>.corrupt`` for later inspection.
    """
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        corrupt = path.with_suffix(path.suffix + ".corrupt")
        try:
            os.replace(path, corrupt)
        except OSError:
            pass
        return default


def _acquire_lock(path: Path) -> int:
    """Acquire an exclusive lock via a sibling ``*.lock`` file.

    Returns an fd that must be released via :func:`_release_lock`.
    Works cross-platform: ``fcntl.flock`` on Unix, ``msvcrt.locking`` on Windows.
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

"""Append-only dispatch trajectory log + reconstruction invariant (ADR-0017).

Inspired by DeepSeek Harness's session log: Hermes is a control plane that
dispatches sub-agents through the OpenClaw Gateway. This module records an
append-only snapshot of every dispatch request (and its result) so that the
exact input Hermes sent to the Gateway can be replayed and audited later.

The runtime invariant (:func:`assert_reconstructable`) is a serialization
round-trip gate: after a request snapshot is written, it is read back from
disk and compared against the payload about to be dispatched. It catches
log-write bugs, on-disk tampering, and field drift (via contract tests). It
does *not* see inside the Gateway (see ADR-0017 boundary note).

All writes are guarded by an in-process lock (the file-level lock only makes
each line atomic, it does not serialize our in-memory sequence counter).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hermes.workbench.persistence import atomic_append_jsonl

logger = logging.getLogger("hermes.trajectory")


class TrajectoryDesyncError(Exception):
    """Raised when a dispatch payload cannot be reconstructed from the log."""


@dataclass
class TrajectoryEvent:
    """A single trajectory record."""

    seq: int
    type: str
    data: dict[str, Any]
    time: str = ""
    cycle: str = "0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "time": self.time,
            "type": self.type,
            "cycle": self.cycle,
            "data": self.data,
        }


def _normalize(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


class TrajectoryLogger:
    """Append-only JSONL trajectory writer/reader with an in-process lock."""

    def __init__(self, path: Path, cycle: str = "0") -> None:
        self.path = path
        self.cycle = cycle
        self._lock = threading.Lock()
        self._seq = self._load_last_seq()

    def _load_last_seq(self) -> int:
        """Resume the sequence counter from the existing file (if any).

        A fresh logger for an existing file must continue the sequence, not
        restart at 1 — otherwise ``request_seq`` correlation across logger
        instances (e.g. one per loop round) would collide.
        """
        if not self.path.exists():
            return 0
        try:
            last = 0
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    last = max(last, int(obj.get("seq", 0)))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
            return last
        except OSError:
            return 0

    def record(self, type: str, data: dict[str, Any]) -> int:
        """Append one event and return its sequence number.

        Raises ``OSError`` if the write fails (fail loud — the trajectory is an
        audit record; a failed write must not be silently swallowed).
        """
        with self._lock:
            self._seq += 1
            seq = self._seq
            line = {
                "seq": seq,
                "time": _now(),
                "type": type,
                "cycle": self.cycle,
                "data": data,
            }
            atomic_append_jsonl(self.path, line)
            return seq

    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def events(self) -> list[TrajectoryEvent]:
        """Read all events, skipping corrupt lines (with a warning)."""
        if not self.path.exists():
            return []
        events: list[TrajectoryEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                events.append(
                    TrajectoryEvent(
                        seq=int(obj.get("seq", 0)),
                        type=str(obj.get("type", "")),
                        data=obj.get("data") or {},
                        time=str(obj.get("time", "")),
                        cycle=str(obj.get("cycle", "0")),
                    )
                )
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning("Skipping corrupt trajectory line in %s: %s", self.path, exc)
        return events

    def assert_reconstructable(self, request_seq: int, payload: dict[str, Any]) -> None:
        """Verify that the dispatch request at *request_seq* equals *payload*.

        Raises :class:`TrajectoryDesyncError` when the event is missing or the
        stored payload does not normalize to the payload about to be dispatched.
        """
        events = self.events()
        assert_reconstructable(events, request_seq, payload)


def assert_reconstructable(
    events: list[TrajectoryEvent], request_seq: int, payload: dict[str, Any]
) -> None:
    """Replay a ``dispatch/request`` event and compare it to *payload*."""
    for ev in events:
        if ev.type == "dispatch/request" and ev.seq == request_seq:
            stored = ev.data.get("payload")
            if _normalize(stored) != _normalize(payload):
                raise TrajectoryDesyncError(
                    f"log-reconstruction desync for dispatch/request seq={request_seq}"
                )
            return
    raise TrajectoryDesyncError(
        f"no dispatch/request event found for seq={request_seq}"
    )


def archive_trajectory(path: Path) -> Path | None:
    """Rename an existing trajectory file to ``trajectory.<cycle>.jsonl``.

    Used by ``resume_loop`` before starting a fresh cycle so events from
    different cycles do not interleave. Returns the archive path, or None if
    there was nothing to archive.
    """
    if not path.exists():
        return None
    cycle = 1
    while True:
        dest = path.with_name(f"{path.stem}.{cycle}{path.suffix}")
        if not dest.exists():
            break
        cycle += 1
    path.replace(dest)
    return dest


def verify_trajectory(path: Path) -> dict[str, Any]:
    """Offline audit of a trajectory file.

    Checks: JSON line integrity, sequence continuity, request/result pairing
    completeness, and agent_definition hash consistency against the current
    on-disk agent file (when one is recorded and still present).

    Note: free-text fields (task/context) cannot be audited offline against a
    tampered-but-self-consistent log; this checklist is explicit about scope.
    """
    logger_ = TrajectoryLogger(path)
    events = logger_.events()

    requests = {ev.seq: ev for ev in events if ev.type == "dispatch/request"}
    results: dict[int, TrajectoryEvent] = {}
    for ev in events:
        if ev.type != "dispatch/result":
            continue
        request_seq = ev.data.get("request_seq")
        if isinstance(request_seq, int):
            results[request_seq] = ev

    seq_gaps = _find_seq_gaps(sorted(ev.seq for ev in events))
    unpaired = sorted(set(requests) - set(results))
    orphan_results = sorted(set(results) - set(requests))
    hash_mismatches: list[dict[str, Any]] = []

    for seq, ev in requests.items():
        payload = ev.data.get("payload") or {}
        agent_file = ev.data.get("agent_file")
        agent_def = payload.get("agent_definition")
        if not agent_file or not isinstance(agent_def, str):
            continue
        ap = Path(agent_file)
        if not ap.is_file():
            continue
        current = ap.read_text(encoding="utf-8")
        if _sha256(agent_def) != _sha256(current):
            hash_mismatches.append({"request_seq": seq, "agent_file": str(ap)})

    ok = not (seq_gaps or unpaired or orphan_results or hash_mismatches)
    return {
        "ok": ok,
        "events": len(events),
        "requests": len(requests),
        "results": len(results),
        "seq_gaps": seq_gaps,
        "unpaired_requests": unpaired,
        "orphan_results": orphan_results,
        "hash_mismatches": hash_mismatches,
    }


def _find_seq_gaps(seqs: list[int]) -> list[int]:
    if not seqs:
        return []
    expected = list(range(1, seqs[-1] + 1))
    return [s for s in expected if s not in set(seqs)]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

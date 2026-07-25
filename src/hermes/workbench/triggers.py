"""Phase 3.3 cron trigger module.

Builds on the Phase 3 ``ScheduledJob`` execution layer to add time-based
triggering: a ``Trigger`` stores a job template + cron expression, a
``TriggerStore`` persists them, and a ``CronScheduler`` daemon scans enabled
cron triggers every ``scan_interval`` seconds and instantiates fresh
``ScheduledJob`` instances from the template for the worker pool to consume.

stdlib-only (``threading`` / ``uuid`` / ``time`` / ``datetime``); no external
dependencies.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List

from hermes.workbench.errors import ValidationError
from hermes.workbench.persistence import atomic_write_json, safe_read_json
from hermes.workbench.scheduler import ScheduledJob


__all__ = [
    "CronScheduler",
    "Trigger",
    "TriggerStore",
]


# Cron field bounds: (min, max) for each of the 5 positions.
_CRON_BOUNDS = (
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 7),    # day of week (0 and 7 both = Sunday)
)


def _now_iso() -> str:
    """UTC timestamp in ISO 8601 (matches scheduler._now_iso)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_cron_field(raw: str, lo: int, hi: int) -> tuple[set[int], bool]:
    """Parse one cron field into (matching values, was_literal_star).

    Supports: ``*`` / ``a`` / ``a-b`` / ``*/n`` / ``a-b/n`` / ``a,b,c``.
    Raises ``ValidationError`` on malformed or out-of-range input.
    """
    raw = raw.strip()
    is_star = raw == "*"
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise ValidationError(f"empty cron field part in {raw!r}")
        # Step
        step = 1
        range_part = part
        if "/" in part:
            range_part, _, step_part = part.partition("/")
            try:
                step = int(step_part)
            except ValueError as exc:
                raise ValidationError(f"invalid step {step_part!r}") from exc
            if step <= 0:
                raise ValidationError(f"step must be positive, got {step}")
        # Range bounds
        if range_part in ("*", ""):
            start, end = lo, hi
        elif "-" in range_part:
            a, _, b = range_part.partition("-")
            try:
                start = int(a)
                end = int(b)
            except ValueError as exc:
                raise ValidationError(f"invalid range {range_part!r}") from exc
        else:
            try:
                start = int(range_part)
            except ValueError as exc:
                raise ValidationError(f"invalid value {range_part!r}") from exc
            end = start
        if start < lo or end > hi or start > end:
            raise ValidationError(f"value out of range in {part!r}")
        v = start
        while v <= end:
            values.add(v)
            v += step
    return values, is_star


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


@dataclass
class Trigger:
    """A job template + firing rule (cron expression or manual-only)."""

    trigger_id: str = ""
    job_template: dict[str, Any] = field(default_factory=dict)
    trigger_type: str = "cron"
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.trigger_id:
            self.trigger_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = _now_iso()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "job_template": self.job_template,
            "trigger_type": self.trigger_type,
            "config": self.config,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trigger":
        return cls(
            trigger_id=data.get("trigger_id", ""),
            job_template=dict(data.get("job_template", {})),
            trigger_type=data.get("trigger_type", "cron"),
            config=dict(data.get("config", {})),
            enabled=bool(data.get("enabled", True)),
            created_at=data.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# TriggerStore
# ---------------------------------------------------------------------------


class TriggerStore:
    """Thread-safe persistence for Trigger (Lock + atomic_write_json)."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.state_dir / "triggers.json"
        self._lock = threading.Lock()
        self._triggers: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        data = safe_read_json(self._path, default={})
        return data if isinstance(data, dict) else {}

    def _save_locked(self) -> None:
        atomic_write_json(self._path, self._triggers)

    def save(self, trigger: Trigger) -> None:
        with self._lock:
            self._triggers[trigger.trigger_id] = trigger.to_dict()
            self._save_locked()

    def get(self, trigger_id: str) -> Trigger | None:
        with self._lock:
            data = self._triggers.get(trigger_id)
        return Trigger.from_dict(data) if data else None

    def list(self) -> "List[Trigger]":
        with self._lock:
            snapshot = list(self._triggers.values())
        return [Trigger.from_dict(d) for d in snapshot]

    def list_enabled_cron(self) -> "List[Trigger]":
        with self._lock:
            snapshot = [
                d
                for d in self._triggers.values()
                if d.get("trigger_type") == "cron" and d.get("enabled", True)
            ]
        return [Trigger.from_dict(d) for d in snapshot]

    def delete(self, trigger_id: str) -> bool:
        with self._lock:
            if trigger_id not in self._triggers:
                return False
            del self._triggers[trigger_id]
            self._save_locked()
            return True

    def update_enabled(self, trigger_id: str, enabled: bool) -> bool:
        with self._lock:
            if trigger_id not in self._triggers:
                return False
            self._triggers[trigger_id]["enabled"] = enabled
            self._save_locked()
            return True


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------


class CronScheduler:
    """Daemon thread that scans enabled cron triggers and submits jobs.

    Every ``scan_interval`` seconds (default 60.0), lists enabled cron triggers
    from the store, matches each against the current time, and — on a match —
    instantiates a fresh ``ScheduledJob`` from the trigger's template and hands
    it to ``submit_callback`` (typically ``JobQueue.put``). Per-minute dedup
    (``_last_fired``) prevents double-firing when scans overlap a single
    minute. ``fire(trigger_id)`` performs an immediate manual fire, bypassing
    the enabled flag and dedup.
    """

    def __init__(
        self,
        store: TriggerStore,
        submit_callback: Callable[[ScheduledJob], None],
        scan_interval: float = 60.0,
    ) -> None:
        self._store = store
        self._submit = submit_callback
        self._scan_interval = scan_interval
        self._stop = threading.Event()
        self._last_fired: dict[str, str] = {}  # trigger_id -> "YYYY-MM-DD HH:MM"
        self._thread: threading.Thread | None = None

    # -- cron matching ------------------------------------------------------

    @staticmethod
    def _matches_cron(expr: str, dt: datetime) -> bool:
        """Standard 5-field cron match (minute hour dom month dow).

        Supports ``*`` / number / ``a-b`` / ``*/n`` / ``a-b/n`` / ``a,b,c``.
        No seconds, no named aliases (MON). DOW 0 and 7 both mean Sunday.
        When both DOM and DOW are restricted, match if EITHER matches
        (Vixie cron semantics); otherwise all fields must match (AND).
        Raises ``ValidationError`` on malformed expressions.
        """
        fields = expr.split()
        if len(fields) != 5:
            raise ValidationError(
                f"cron expression must have 5 fields, got {len(fields)}: {expr!r}"
            )
        sets: list[set[int]] = []
        stars: list[bool] = []
        for raw, (lo, hi) in zip(fields, _CRON_BOUNDS):
            vals, was_star = _parse_cron_field(raw, lo, hi)
            sets.append(vals)
            stars.append(was_star)
        minute_set, hour_set, dom_set, month_set, dow_set = sets
        _dom_star, _hour_star, dom_star, _month_star, dow_star = stars

        # DOW 7 == 0 (both Sunday)
        if 7 in dow_set:
            dow_set.add(0)
        # Python weekday(): Mon=0..Sun=6 -> cron DOW: Mon=1..Sat=6, Sun=0
        cron_dow = (dt.weekday() + 1) % 7

        if dt.minute not in minute_set:
            return False
        if dt.hour not in hour_set:
            return False
        if dt.month not in month_set:
            return False

        if not dom_star and not dow_star:
            # both restricted: OR
            return (dt.day in dom_set) or (cron_dow in dow_set)
        # at least one is '*': AND (the '*' side always matches)
        return (dt.day in dom_set) and (cron_dow in dow_set)

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the daemon scan thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        t = threading.Thread(target=self._loop, name="cron-scheduler", daemon=True)
        t.start()
        self._thread = t

    def stop(self) -> None:
        """Signal the scan thread to stop and join it (up to 2s)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- internals ----------------------------------------------------------

    def _loop(self) -> None:
        # Scan immediately on start so a due trigger fires without waiting a
        # full interval, then wait between scans.
        while not self._stop.is_set():
            try:
                self._scan()
            except Exception:  # noqa: BLE001 - scan must not kill the loop
                pass
            if self._stop.wait(self._scan_interval):
                break

    def _scan(self) -> None:
        now = datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        for trigger in self._store.list_enabled_cron():
            tid = trigger.trigger_id
            if self._last_fired.get(tid) == minute_key:
                continue  # already fired this minute
            expr = trigger.config.get("cron", "")
            if not expr:
                continue
            try:
                matched = self._matches_cron(expr, now)
            except Exception:  # noqa: BLE001 - skip bad expressions
                continue
            if matched:
                self._last_fired[tid] = minute_key
                self._instantiate_and_submit(trigger)

    def _instantiate_and_submit(self, trigger: Trigger) -> bool:
        try:
            job = ScheduledJob.from_template(trigger.job_template, submitted_by="cron")
        except Exception:  # noqa: BLE001 - bad template
            return False
        try:
            self._submit(job)
        except Exception:  # noqa: BLE001 - callback must not kill loop
            return False
        return True

    # -- manual fire --------------------------------------------------------

    def fire(self, trigger_id: str) -> bool:
        """Immediately instantiate + submit a job from the trigger's template.

        Bypasses the ``enabled`` flag and per-minute dedup (manual fire).
        Returns False if the trigger is missing or instantiation fails.
        """
        trigger = self._store.get(trigger_id)
        if trigger is None:
            return False
        return self._instantiate_and_submit(trigger)

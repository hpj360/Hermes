"""Tests for Phase 3.3 cron trigger module (triggers.py).

Covers: Trigger dataclass, TriggerStore persistence (CRUD + list_enabled_cron),
CronScheduler cron matching + daemon scan + manual fire + enable/disable.

AC mapping:
- AC-10: cron trigger auto-fires from template within scan interval, submitted_by="cron"
- AC-11: CronScheduler.fire(trigger_id) immediately instantiates + enqueues
- AC-12: disable stops scanning; enable resumes
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hermes.workbench.cli import Task
from hermes.workbench.errors import ValidationError
from hermes.workbench.scheduler import JobStatus, ScheduledJob
from hermes.workbench.triggers import CronScheduler, Trigger, TriggerStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> TriggerStore:
    return TriggerStore(state_dir=tmp_path)


@pytest.fixture
def sample_task() -> Task:
    return Task(task_id="task-1", plan=[{"skill": "echo", "args": ["hi"]}])


@pytest.fixture
def job_template(sample_task: Task) -> dict:
    """A serialized ScheduledJob template (no job_id/status/attempts)."""
    job = ScheduledJob(task=sample_task, target_project="default", priority=3)
    d = job.to_dict()
    d.pop("job_id", None)
    d.pop("status", None)
    d.pop("attempts", None)
    return d


@pytest.fixture
def cron_trigger(job_template: dict) -> Trigger:
    return Trigger(
        job_template=job_template,
        trigger_type="cron",
        config={"cron": "* * * * *"},
    )


def _make_scheduler(
    store: TriggerStore, scan_interval: float = 0.05
) -> tuple[CronScheduler, MagicMock]:
    """Build a CronScheduler with a mock submit callback + short scan interval."""
    callback = MagicMock()
    sched = CronScheduler(store=store, submit_callback=callback, scan_interval=scan_interval)
    return sched, callback


def _wait_for_calls(mock: MagicMock, count: int, timeout: float = 3.0) -> bool:
    """Poll mock call count up to *timeout* seconds. Return True if reached."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mock.call_count >= count:
            return True
        time.sleep(0.02)
    return mock.call_count >= count


def _clear_dedup(store: TriggerStore, trigger_id: str) -> None:
    """Reset the persisted per-minute dedup key so a fresh scan would re-fire."""
    t = store.get(trigger_id)
    assert t is not None
    t.last_fired_at = ""
    store.save(t)


# ---------------------------------------------------------------------------
# Trigger dataclass
# ---------------------------------------------------------------------------


class TestTrigger:
    def test_auto_id_and_created_at(self, job_template: dict) -> None:
        t = Trigger(job_template=job_template, trigger_type="cron", config={"cron": "* * * * *"})
        assert t.trigger_id  # auto-generated uuid
        assert t.created_at  # auto-generated ISO timestamp
        assert t.enabled is True

    def test_explicit_id_preserved(self, job_template: dict) -> None:
        t = Trigger(
            trigger_id="fixed-id",
            job_template=job_template,
            trigger_type="cron",
            config={"cron": "* * * * *"},
            created_at="2026-07-25T00:00:00Z",
        )
        assert t.trigger_id == "fixed-id"
        assert t.created_at == "2026-07-25T00:00:00Z"

    def test_to_dict_roundtrip(self, job_template: dict) -> None:
        t = Trigger(
            job_template=job_template,
            trigger_type="cron",
            config={"cron": "30 9 * * *"},
            enabled=False,
        )
        d = t.to_dict()
        assert d["trigger_id"] == t.trigger_id
        assert d["trigger_type"] == "cron"
        assert d["config"] == {"cron": "30 9 * * *"}
        assert d["enabled"] is False
        assert d["job_template"] == job_template
        t2 = Trigger.from_dict(d)
        assert t2.trigger_id == t.trigger_id
        assert t2.trigger_type == "cron"
        assert t2.config == t.config
        assert t2.enabled is False
        assert t2.job_template == job_template

    def test_from_dict_missing_optional_fields(self, job_template: dict) -> None:
        d = {
            "trigger_id": "tid",
            "job_template": job_template,
            "trigger_type": "manual",
            "config": {},
        }
        t = Trigger.from_dict(d)
        assert t.trigger_id == "tid"
        assert t.trigger_type == "manual"
        assert t.enabled is True  # default
        # created_at absent -> __post_init__ backfills a fresh ISO timestamp
        assert isinstance(t.created_at, str) and t.created_at


# ---------------------------------------------------------------------------
# TriggerStore
# ---------------------------------------------------------------------------


class TestTriggerStore:
    def test_save_and_get(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        store.save(cron_trigger)
        fetched = store.get(cron_trigger.trigger_id)
        assert fetched is not None
        assert fetched.trigger_id == cron_trigger.trigger_id
        assert fetched.trigger_type == "cron"
        assert fetched.config == {"cron": "* * * * *"}

    def test_get_missing_returns_none(self, store: TriggerStore) -> None:
        assert store.get("nonexistent") is None

    def test_save_overwrites(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        store.save(cron_trigger)
        cron_trigger.enabled = False
        store.save(cron_trigger)
        fetched = store.get(cron_trigger.trigger_id)
        assert fetched is not None
        assert fetched.enabled is False

    def test_list(self, store: TriggerStore, job_template: dict) -> None:
        t1 = Trigger(job_template=job_template, trigger_type="cron", config={"cron": "* * * * *"})
        t2 = Trigger(job_template=job_template, trigger_type="manual", config={})
        store.save(t1)
        store.save(t2)
        ids = {t.trigger_id for t in store.list()}
        assert {t1.trigger_id, t2.trigger_id} == ids

    def test_list_enabled_cron_only(
        self, store: TriggerStore, job_template: dict
    ) -> None:
        cron_on = Trigger(job_template=job_template, trigger_type="cron", config={"cron": "* * * * *"})
        cron_off = Trigger(
            job_template=job_template, trigger_type="cron", config={"cron": "* * * * *"}, enabled=False
        )
        manual_on = Trigger(job_template=job_template, trigger_type="manual", config={})
        store.save(cron_on)
        store.save(cron_off)
        store.save(manual_on)
        enabled = store.list_enabled_cron()
        assert len(enabled) == 1
        assert enabled[0].trigger_id == cron_on.trigger_id

    def test_delete(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        store.save(cron_trigger)
        assert store.delete(cron_trigger.trigger_id) is True
        assert store.get(cron_trigger.trigger_id) is None

    def test_delete_missing_returns_false(self, store: TriggerStore) -> None:
        assert store.delete("nonexistent") is False

    def test_update_enabled(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        store.save(cron_trigger)
        assert store.update_enabled(cron_trigger.trigger_id, False) is True
        fetched = store.get(cron_trigger.trigger_id)
        assert fetched is not None
        assert fetched.enabled is False
        # Reflects in list_enabled_cron
        assert store.list_enabled_cron() == []
        assert store.update_enabled(cron_trigger.trigger_id, True) is True
        assert len(store.list_enabled_cron()) == 1

    def test_update_enabled_missing(self, store: TriggerStore) -> None:
        assert store.update_enabled("nonexistent", False) is False

    def test_persistence_across_instances(
        self, store: TriggerStore, cron_trigger: Trigger, tmp_path: Path
    ) -> None:
        store.save(cron_trigger)
        store2 = TriggerStore(state_dir=tmp_path)
        fetched = store2.get(cron_trigger.trigger_id)
        assert fetched is not None
        assert fetched.trigger_id == cron_trigger.trigger_id
        assert fetched.config == cron_trigger.config

    def test_concurrent_writes_no_loss(
        self, store: TriggerStore, job_template: dict
    ) -> None:
        """10 threads × 10 triggers each, all persisted."""

        def write_batch(tid: int) -> None:
            for i in range(10):
                store.save(
                    Trigger(
                        job_template=job_template,
                        trigger_type="cron",
                        config={"cron": "* * * * *"},
                    )
                )

        threads = [threading.Thread(target=write_batch, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(store.list()) == 100


# ---------------------------------------------------------------------------
# CronScheduler._matches_cron (pure function)
# ---------------------------------------------------------------------------


class TestMatchesCron:
    # Reference time: 2026-07-25 09:30 (Saturday)
    DT = datetime(2026, 7, 25, 9, 30)

    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("30 9 * * *", True),
            ("31 9 * * *", False),
            ("29 9 * * *", False),
            ("30 10 * * *", False),
            ("* * * * *", True),
            ("*/15 * * * *", True),       # 0,15,30,45 -> 30 in set
            ("*/20 * * * *", False),      # 0,20,40 -> 30 not in set
            ("0-30 * * * *", True),        # 30 in 0..30
            ("0,15,30,45 * * * *", True),
            ("0,15,45 * * * *", False),    # 30 not in list
            ("30 9 25 7 *", True),         # day=25 month=7
            ("30 9 26 7 *", False),        # day mismatch
            ("30 9 25 8 *", False),        # month mismatch
            ("30 9 * * 1", False),         # 2026-07-25 is Saturday (cron DOW=6), 1=Monday
            ("30 9 * * 6", True),          # Saturday = 6
            ("30 9 * * 0", False),         # 0=Sunday
            ("30 9 * * 7", False),         # 7=Sunday
        ],
    )
    def test_match(self, expr: str, expected: bool) -> None:
        assert CronScheduler._matches_cron(expr, self.DT) is expected

    def test_sunday_matches_zero_and_seven(self) -> None:
        # 2026-07-26 is Sunday
        sunday = datetime(2026, 7, 26, 8, 0)
        assert CronScheduler._matches_cron("0 8 * * 0", sunday) is True
        assert CronScheduler._matches_cron("0 8 * * 7", sunday) is True

    def test_step_in_range(self) -> None:
        # 0-30/15 -> {0, 15, 30}
        assert CronScheduler._matches_cron("0-30/15 * * * *", self.DT) is True
        # 0-29/15 -> {0, 15} (30 excluded)
        assert CronScheduler._matches_cron("0-29/15 * * * *", self.DT) is False

    def test_dom_dow_or_logic_when_both_restricted(self) -> None:
        """Standard cron: when both DOM and DOW are restricted, match if EITHER matches."""
        # 2026-07-25 is Saturday (DOW=6), day=25, minute=30, hour=9
        # DOM=1 (won't match day 25), DOW=6 (matches Saturday) -> OR -> True
        assert CronScheduler._matches_cron("30 9 1 * 6", self.DT) is True
        # DOM=25 (matches), DOW=1 (Monday, won't match Saturday) -> OR -> True
        assert CronScheduler._matches_cron("30 9 25 * 1", self.DT) is True
        # DOM=1 (no), DOW=1 (no) -> OR -> False
        assert CronScheduler._matches_cron("30 9 1 * 1", self.DT) is False

    @pytest.mark.parametrize(
        "expr",
        [
            "* * * *",          # 4 fields
            "* * * * * *",      # 6 fields
            "60 * * * *",       # minute out of range
            "* 24 * * *",       # hour out of range
            "* * 32 * *",       # day out of range
            "* * * 13 *",       # month out of range
            "* * * * 8",        # DOW out of range
            "abc * * * *",      # non-numeric
            "* * * * MON",      # named alias not supported
            "*/0 * * * *",      # zero step
        ],
    )
    def test_invalid_raises(self, expr: str) -> None:
        with pytest.raises(ValidationError):
            CronScheduler._matches_cron(expr, self.DT)


# ---------------------------------------------------------------------------
# CronScheduler integration
# ---------------------------------------------------------------------------


class TestCronScheduler:
    def test_auto_fire_from_template(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        """AC-10: cron trigger '* * * * *' auto-fires a job from template, submitted_by='cron'."""
        store.save(cron_trigger)
        sched, callback = _make_scheduler(store, scan_interval=0.05)
        sched.start()
        try:
            assert _wait_for_calls(callback, 1, timeout=3.0), "callback not invoked in time"
        finally:
            sched.stop()

        callback.assert_called_once()
        job = callback.call_args.args[0]
        assert isinstance(job, ScheduledJob)
        assert job.status == JobStatus.PENDING
        assert job.submitted_by == "cron"
        # job_id regenerated (different from any in template)
        assert job.job_id
        assert job.attempts == []

    def test_auto_fire_only_enabled_cron(
        self, store: TriggerStore, job_template: dict
    ) -> None:
        """Disabled cron + manual trigger are never auto-fired."""
        cron_disabled = Trigger(
            job_template=job_template, trigger_type="cron", config={"cron": "* * * * *"}, enabled=False
        )
        manual = Trigger(job_template=job_template, trigger_type="manual", config={})
        store.save(cron_disabled)
        store.save(manual)
        sched, callback = _make_scheduler(store, scan_interval=0.05)
        sched.start()
        time.sleep(0.3)
        sched.stop()
        assert callback.call_count == 0

    def test_fire_immediate(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        """AC-11: fire(trigger_id) immediately instantiates + enqueues from template."""
        store.save(cron_trigger)
        sched, callback = _make_scheduler(store)
        # No start() — purely synchronous manual fire.
        result = sched.fire(cron_trigger.trigger_id)
        assert result is True
        callback.assert_called_once()
        job = callback.call_args.args[0]
        assert isinstance(job, ScheduledJob)
        assert job.status == JobStatus.PENDING
        assert job.submitted_by == "cron"
        assert job.target_project == "default"
        assert job.priority == 3

    def test_fire_missing_returns_false(self, store: TriggerStore) -> None:
        sched, callback = _make_scheduler(store)
        assert sched.fire("nonexistent") is False
        assert callback.call_count == 0

    def test_fire_works_on_disabled(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        """Manual fire ignores enabled state — only auto-scan respects it."""
        store.save(cron_trigger)
        store.update_enabled(cron_trigger.trigger_id, False)
        sched, callback = _make_scheduler(store)
        assert sched.fire(cron_trigger.trigger_id) is True
        callback.assert_called_once()

    def test_disable_then_enable(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        """AC-12: disable stops auto-scanning; enable resumes."""
        store.save(cron_trigger)
        sched, callback = _make_scheduler(store, scan_interval=0.05)
        sched.start()
        try:
            # 1. Fires while enabled.
            assert _wait_for_calls(callback, 1, timeout=3.0)

            # 2. Disable + clear dedup so a fresh scan would fire if not disabled.
            store.update_enabled(cron_trigger.trigger_id, False)
            _clear_dedup(store, cron_trigger.trigger_id)
            fired_after_disable = callback.call_count
            time.sleep(0.3)
            assert callback.call_count == fired_after_disable  # no new fires

            # 3. Re-enable + clear dedup; should fire again.
            store.update_enabled(cron_trigger.trigger_id, True)
            _clear_dedup(store, cron_trigger.trigger_id)
            assert _wait_for_calls(callback, fired_after_disable + 1, timeout=3.0)
        finally:
            sched.stop()

    def test_dedup_within_same_minute(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        """Same-minute repeated scans fire the trigger exactly once."""
        store.save(cron_trigger)
        sched, callback = _make_scheduler(store, scan_interval=0.03)
        sched.start()
        try:
            assert _wait_for_calls(callback, 1, timeout=3.0)
            first_count = callback.call_count
            # Let several more scans happen within the same minute.
            time.sleep(0.3)
            assert callback.call_count == first_count  # dedup blocks re-fire
        finally:
            sched.stop()

    def test_start_idempotent_and_stop(self, store: TriggerStore, cron_trigger: Trigger) -> None:
        store.save(cron_trigger)
        sched, _callback = _make_scheduler(store, scan_interval=0.05)
        sched.start()
        sched.start()  # second start is a no-op
        assert sched.is_running() is True
        sched.stop()
        assert sched.is_running() is False
        # stop without start is safe
        sched.stop()

    def test_stop_terminates_within_timeout(
        self, store: TriggerStore, cron_trigger: Trigger
    ) -> None:
        store.save(cron_trigger)
        sched, _callback = _make_scheduler(store, scan_interval=10.0)
        sched.start()
        t0 = time.time()
        sched.stop()
        assert time.time() - t0 < 2.0

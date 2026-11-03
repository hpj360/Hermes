"""C1 自动周报测试：构建 / 静默 / 渲染 / 投递 / runtime 分发。"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def db_session():
    from hermes.content_team.db import Base
    from hermes.content_team.models import Content, ContentMetric, PublishTask  # noqa: F401,F841
    from hermes.content_team.models.content import ContentStatus
    from hermes.content_team.models.platform import Platform

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        content = Content(
            id=uuid.uuid4(),
            title="测评：三年陈的威士忌到底怎么样",
            body="正文",
            status=ContentStatus.PUBLISHED,
        )
        session.add(content)
        today = datetime.now(timezone.utc).date()
        # 本期两快照 + 上期一快照
        session.add_all(
            [
                ContentMetric(
                    content_id=content.id,
                    platform=Platform.DOUYIN,
                    date=today - timedelta(days=1),
                    views=60,
                    likes=6,
                    comments=2,
                    shares=2,
                    engagement_rate=0.15,
                    source="manual",
                ),
                ContentMetric(
                    content_id=content.id,
                    platform=Platform.XIAOHONGSHU,
                    date=today - timedelta(days=2),
                    views=40,
                    likes=6,
                    comments=2,
                    shares=2,
                    engagement_rate=0.2,
                    source="manual",
                ),
                ContentMetric(
                    content_id=content.id,
                    platform=Platform.DOUYIN,
                    date=today - timedelta(days=9),
                    views=50,
                    likes=2,
                    comments=1,
                    shares=0,
                    engagement_rate=0.06,
                    source="simulation",
                ),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


async def test_build_weekly_report_aggregates(db_session) -> None:
    from hermes.content_team.weekly_report import build_weekly_report

    report = await build_weekly_report(db_session, days=7)
    assert report.views == 100
    assert report.interactions == 20
    assert report.interactions_prev == 3
    assert report.top_contents[0]["title"].startswith("测评")
    assert report.source_counts == {"manual": 2}
    text = report.render_text()
    assert "本周复盘" in text
    assert "+100% vs 上期" in text  # 曝光 100 vs 50
    assert "数据来源: manual 2" in text


async def test_build_weekly_report_silent_when_no_activity(db_session) -> None:
    from hermes.content_team.weekly_report import build_weekly_report

    # 窗口 90 天前的空窗（远早于本期数据）→ 空报告静默
    report = await build_weekly_report(
        db_session, days=7, end_date=date(2020, 1, 7)
    )
    assert report.is_silent()
    assert report.views == 0


class _FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_text(self, receive_id: str, text: str, receive_id_type: str) -> dict:
        self.sent.append((receive_id, text))
        return {"code": 0}

    def send_card(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("weekly report uses text cards")


class _FakeDeadLetter:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def record(self, kind: str, target: str, subject: str, error: str) -> None:
        self.records.append((kind, subject))


class _FakeNotifier:
    def __init__(self, failing: bool = False) -> None:
        self.client = _FakeClient()
        self.dead_letter = _FakeDeadLetter()
        self.receive_id = "chat-1"
        self.receive_id_type = "chat_id"
        self._failing = failing

    def _install_failure(self) -> None:  # pragma: no cover
        self.client.send_text = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("network")
        )


async def test_send_weekly_report_sends_and_silent_skips(db_session) -> None:
    from hermes.content_team.weekly_report import build_weekly_report, send_weekly_report

    report = await build_weekly_report(db_session)
    notifier = _FakeNotifier()
    assert await send_weekly_report(notifier, report) is True
    assert len(notifier.client.sent) == 1
    assert notifier.client.sent[0][0] == "chat-1"

    silent = await build_weekly_report(db_session, end_date=date(2020, 1, 7))
    assert await send_weekly_report(notifier, silent) is False
    assert len(notifier.client.sent) == 1  # 无增量发送


async def test_send_weekly_report_failure_goes_to_dead_letter(db_session) -> None:
    from hermes.content_team.weekly_report import build_weekly_report, send_weekly_report

    report = await build_weekly_report(db_session)
    notifier = _FakeNotifier()
    notifier.client.send_text = lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("send failed")
    )
    assert await send_weekly_report(notifier, report) is False
    assert notifier.dead_letter.records == [("weekly", "weekly report")]


def test_runtime_dispatch_weekly_report() -> None:
    from hermes.content_team import runtime as rt_mod
    from hermes.content_team import weekly_report as wr_mod

    class _Task:
        task_id = "t1"
        goal = {"type": "weekly_report", "payload": {"days": 7}}

    recorded: dict[str, int] = {}

    def _fake_run(days: int) -> dict[str, object]:
        recorded["days"] = days
        return {"ok": True, "sent": False, "silent": True}

    original = wr_mod.run_weekly_report_for_payload
    wr_mod.run_weekly_report_for_payload = _fake_run
    try:
        result = rt_mod.execute_content_team_task(_Task())
    finally:
        wr_mod.run_weekly_report_for_payload = original

    assert result == {"ok": True, "sent": False, "silent": True}
    assert recorded["days"] == 7


def test_runtime_dispatch_weekly_report_bad_days_clamped() -> None:
    from hermes.content_team import runtime as rt_mod
    from hermes.content_team import weekly_report as wr_mod

    class _Task:
        task_id = "t2"
        goal = {"type": "weekly_report", "payload": {"days": -3}}

    seen: dict[str, int] = {}

    def _fake_run(days: int) -> dict[str, object]:
        seen["days"] = days
        return {"ok": True}

    original = wr_mod.run_weekly_report_for_payload
    wr_mod.run_weekly_report_for_payload = _fake_run
    try:
        rt_mod.execute_content_team_task(_Task())
    finally:
        wr_mod.run_weekly_report_for_payload = original
    assert seen["days"] == 7  # 非法/负值回落默认 7


def test_register_weekly_report_trigger(tmp_path, monkeypatch) -> None:
    """C1 触发器：默认每周一 20:00 cron；模板 goal.type=weekly_report。"""
    from hermes.content_team import triggers as tg_mod
    from hermes.content_team.triggers import (
        register_weekly_report_trigger,
        get_trigger_store,
        _trigger_store as _orig_none,  # noqa: F401 仅为确保模块可导入
    )

    monkeypatch.setattr(tg_mod, "_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(tg_mod, "_trigger_store", None)
    try:
        trigger_id = register_weekly_report_trigger()
        store = get_trigger_store()
        trigger = next(t for t in store.list() if t.trigger_id == trigger_id)
        assert trigger.config.get("cron") == "0 20 * * 1"
        assert trigger.job_template["type"] == "weekly_report"
        assert trigger.job_template["target_project"] == "content-team"
        assert trigger.job_template["task"]["goal"]["type"] == "weekly_report"
    finally:
        monkeypatch.setattr(tg_mod, "_trigger_store", None)


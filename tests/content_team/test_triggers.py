"""Tests for hermes.content_team.triggers Cron trigger integration.

覆盖：
- register_daily_collection_trigger / register_publish_trigger 模板正确性
- list_triggers / enable / disable / delete
- Cron 表达式解析（合法 + 非法）
- TriggerStore 持久化（保存后从文件重新加载）

所有需要存储的用例都通过将单例 TriggerStore 重定向到 ``tmp_path`` 实现隔离。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hermes.content_team import triggers as ct_triggers
from hermes.content_team.triggers import (
    delete_trigger,
    disable_trigger,
    enable_trigger,
    get_trigger_store,
    list_triggers,
    register_daily_collection_trigger,
    register_publish_trigger,
)
from hermes.workbench.errors import ValidationError
from hermes.workbench.triggers import CronScheduler, Trigger, TriggerStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> TriggerStore:
    """将 triggers 模块的单例存储重定向到临时目录，确保测试间相互隔离。

    直接构造一个指向 ``tmp_path`` 的 TriggerStore 并替换模块级单例，
    避免触碰真实 ``data/content_team_triggers/`` 目录。
    """
    store_dir = tmp_path / "content_team_triggers"
    store = TriggerStore(state_dir=store_dir)
    monkeypatch.setattr(ct_triggers, "_trigger_store", store)
    monkeypatch.setattr(ct_triggers, "_STORAGE_DIR", store_dir)
    return store


# ---------------------------------------------------------------------------
# register_daily_collection_trigger
# ---------------------------------------------------------------------------


class TestRegisterDailyCollectionTrigger:
    def test_creates_trigger_with_correct_template(self, isolated_store: TriggerStore) -> None:
        tid = register_daily_collection_trigger()
        assert isinstance(tid, str) and tid

        trigger = get_trigger_store().get(tid)
        assert trigger is not None
        assert trigger.trigger_type == "cron"
        assert trigger.enabled is True
        assert trigger.config == {"cron": "0 9 * * *"}
        assert trigger.job_template["type"] == "data_collection"
        assert trigger.job_template["payload"] == {"action": "collect_metrics"}

    def test_custom_cron_expr(self, isolated_store: TriggerStore) -> None:
        tid = register_daily_collection_trigger(cron_expr="30 8 * * 1-5")
        trigger = get_trigger_store().get(tid)
        assert trigger is not None
        assert trigger.config == {"cron": "30 8 * * 1-5"}
        assert trigger.job_template["type"] == "data_collection"


# ---------------------------------------------------------------------------
# register_publish_trigger
# ---------------------------------------------------------------------------


class TestRegisterPublishTrigger:
    def test_creates_trigger_with_content_and_platform(self, isolated_store: TriggerStore) -> None:
        tid = register_publish_trigger("0 10 * * *", content_id=42, platform="twitter")
        assert isinstance(tid, str) and tid

        trigger = get_trigger_store().get(tid)
        assert trigger is not None
        assert trigger.trigger_type == "cron"
        assert trigger.config == {"cron": "0 10 * * *"}
        assert trigger.job_template["type"] == "publish"
        assert trigger.job_template["payload"]["content_id"] == "42"
        assert trigger.job_template["payload"]["platform"] == "twitter"

    def test_content_id_stringified(self, isolated_store: TriggerStore) -> None:
        tid = register_publish_trigger(
            "*/30 * * * *", content_id="abc-123", platform="medium"
        )
        trigger = get_trigger_store().get(tid)
        assert trigger is not None
        assert trigger.job_template["payload"]["content_id"] == "abc-123"
        assert trigger.job_template["payload"]["platform"] == "medium"


# ---------------------------------------------------------------------------
# list_triggers
# ---------------------------------------------------------------------------


class TestListTriggers:
    def test_returns_all_triggers(self, isolated_store: TriggerStore) -> None:
        assert list_triggers() == []

        t1 = register_daily_collection_trigger()
        t2 = register_publish_trigger("0 10 * * *", content_id=1, platform="twitter")

        triggers = list_triggers()
        ids = {t.trigger_id for t in triggers}
        assert ids == {t1, t2}
        assert len(triggers) == 2


# ---------------------------------------------------------------------------
# enable / disable
# ---------------------------------------------------------------------------


class TestEnableDisableTrigger:
    def test_disable_then_enable(self, isolated_store: TriggerStore) -> None:
        tid = register_daily_collection_trigger()

        assert disable_trigger(tid) is True
        trigger = get_trigger_store().get(tid)
        assert trigger is not None
        assert trigger.enabled is False

        assert enable_trigger(tid) is True
        trigger = get_trigger_store().get(tid)
        assert trigger is not None
        assert trigger.enabled is True

    def test_disable_missing_returns_false(self, isolated_store: TriggerStore) -> None:
        assert disable_trigger("nonexistent") is False

    def test_enable_missing_returns_false(self, isolated_store: TriggerStore) -> None:
        assert enable_trigger("nonexistent") is False


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDeleteTrigger:
    def test_delete_existing(self, isolated_store: TriggerStore) -> None:
        tid = register_daily_collection_trigger()
        assert delete_trigger(tid) is True
        assert get_trigger_store().get(tid) is None

    def test_delete_missing_returns_false(self, isolated_store: TriggerStore) -> None:
        assert delete_trigger("nonexistent") is False


# ---------------------------------------------------------------------------
# Cron 表达式解析
# ---------------------------------------------------------------------------


class TestCronExpressionParsing:
    # 参考时间：2026-07-25 09:30（星期六）
    DT = datetime(2026, 7, 25, 9, 30)

    @pytest.mark.parametrize(
        "expr,expected",
        [
            ("30 9 * * *", True),
            ("0 9 * * *", False),       # 分钟 0 != 30
            ("* * * * *", True),
            ("*/15 * * * *", True),     # 30 ∈ {0,15,30,45}
            ("*/20 * * * *", False),    # 30 ∉ {0,20,40}
            ("0-30 * * * *", True),
            ("0,15,30,45 * * * *", True),
            ("30 9 25 7 *", True),      # day=25 month=7
            ("30 9 26 7 *", False),     # day 不匹配
            ("30 9 * * 6", True),       # 星期六 = 6
        ],
    )
    def test_valid_expressions_parse_and_match(
        self, expr: str, expected: bool
    ) -> None:
        # 合法表达式不应抛异常；返回值即匹配结果
        assert CronScheduler._matches_cron(expr, self.DT) is expected

    @pytest.mark.parametrize(
        "expr",
        [
            "* * * *",          # 4 字段
            "* * * * * *",     # 6 字段
            "60 * * * *",      # 分钟越界
            "* 24 * * *",      # 小时越界
            "* * 32 * *",      # 日越界
            "* * * 13 *",      # 月越界
            "* * * * 8",       # 星期越界
            "abc * * * *",     # 非数字
            "*/0 * * * *",     # 步长为 0
        ],
    )
    def test_invalid_expression_raises(self, expr: str) -> None:
        with pytest.raises(ValidationError):
            CronScheduler._matches_cron(expr, self.DT)


# ---------------------------------------------------------------------------
# TriggerStore 持久化
# ---------------------------------------------------------------------------


class TestTriggerStorePersistence:
    def test_save_and_reload_from_file(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "content_team_triggers"
        store1 = TriggerStore(state_dir=store_dir)

        trigger = Trigger(
            job_template={
                "type": "data_collection",
                "payload": {"action": "collect_metrics"},
            },
            trigger_type="cron",
            config={"cron": "0 9 * * *"},
        )
        store1.save(trigger)

        # 持久化文件确实落盘
        assert (store_dir / "triggers.json").exists()

        # 用一个新的 TriggerStore 实例从同一文件加载
        store2 = TriggerStore(state_dir=store_dir)
        loaded = store2.get(trigger.trigger_id)
        assert loaded is not None
        assert loaded.trigger_id == trigger.trigger_id
        assert loaded.trigger_type == "cron"
        assert loaded.config == {"cron": "0 9 * * *"}
        assert loaded.job_template == trigger.job_template
        assert loaded.enabled is True

    def test_list_reloaded_across_instances(self, tmp_path: Path) -> None:
        store_dir = tmp_path / "content_team_triggers"
        store1 = TriggerStore(state_dir=store_dir)

        t1 = Trigger(
            job_template={"type": "data_collection", "payload": {}},
            trigger_type="cron",
            config={"cron": "0 9 * * *"},
        )
        t2 = Trigger(
            job_template={"type": "publish", "payload": {}},
            trigger_type="cron",
            config={"cron": "0 10 * * *"},
        )
        store1.save(t1)
        store1.save(t2)

        store2 = TriggerStore(state_dir=store_dir)
        ids = {t.trigger_id for t in store2.list()}
        assert ids == {t1.trigger_id, t2.trigger_id}


class TestNamespaceIsolation:
    """content_team 触发器与 hermes 主调度中心使用独立存储，命名空间隔离。"""

    def test_content_team_store_uses_separate_dir(self) -> None:
        """content_team TriggerStore 的存储目录与 hermes 默认 .state 不同。"""
        from hermes.content_team.triggers import _STORAGE_DIR

        # content_team 使用 data/content_team_triggers/，而非 hermes 的 .state/
        assert "content_team_triggers" in str(_STORAGE_DIR)
        assert ".state" not in str(_STORAGE_DIR)

    def test_trigger_ids_are_uuid_and_never_collide(self, tmp_path: Path) -> None:
        """不同 TriggerStore 实例生成的 trigger_id 均为 UUID，不会碰撞。"""
        store_a = TriggerStore(state_dir=tmp_path / "a")
        store_b = TriggerStore(state_dir=tmp_path / "b")
        ta = Trigger(
            job_template={"type": "publish", "payload": {}},
            trigger_type="cron",
            config={"cron": "0 9 * * *"},
        )
        tb = Trigger(
            job_template={"type": "publish", "payload": {}},
            trigger_type="cron",
            config={"cron": "0 9 * * *"},
        )
        store_a.save(ta)
        store_b.save(tb)
        assert ta.trigger_id != tb.trigger_id
        # 每个 store 只看到自己的触发器
        assert store_a.get(tb.trigger_id) is None
        assert store_b.get(ta.trigger_id) is None

"""发布与分发模块集成测试。

覆盖：
- 平台账号 CRUD（创建 / 列表过滤 / 删除）
- 发布分发（立即单平台 / 多平台 fan-out / 定时调度）
- 发布任务查询（单个 / 列表过滤）
- 失败任务重试
- 适配器校验与发布（WeChat 成功 / Douyin 半自动 / 内容超长校验）
- 调度器 get_adapter 工厂方法
"""
from __future__ import annotations

import uuid

import pytest

from hermes.content_team.models.content import Content
from hermes.content_team.models.platform import Platform, PlatformAccount
from hermes.content_team.models.publish import PublishStatus
from hermes.content_team.publish.adapters.bilibili import BilibiliAdapter
from hermes.content_team.publish.adapters.douyin import DouyinAdapter
from hermes.content_team.publish.adapters.wechat import WeChatOfficialAdapter
from hermes.content_team.publish.adapters.xiaohongshu import XiaohongshuAdapter
from hermes.content_team.publish.dispatcher import PublishDispatcher


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _create_content(client, title="测试内容标题", body="测试正文内容"):
    """通过 API 创建内容并返回其 ID。"""
    resp = await client.post(
        "/api/content", json={"title": title, "body": body}
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _create_account(
    client,
    platform=Platform.WECHAT_OFFICIAL,
    display_name="测试公众号",
):
    """通过 API 创建平台账号并返回其 ID。"""
    resp = await client.post(
        "/api/accounts",
        json={
            "platform": platform.value,
            "display_name": display_name,
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# 平台账号 CRUD
# ---------------------------------------------------------------------------


async def test_create_platform_account(client):
    """POST /api/accounts 创建平台账号。"""
    resp = await client.post(
        "/api/accounts",
        json={
            "platform": "WECHAT_OFFICIAL",
            "display_name": "微信公众号A",
            "account_id": "gh_123456",
            "auth_token": "token_abc",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["platform"] == "WECHAT_OFFICIAL"
    assert data["display_name"] == "微信公众号A"
    assert data["account_id"] == "gh_123456"
    assert data["auth_token"] == "token_abc"
    assert data["status"] == "active"
    assert data["refresh_token"] is None
    assert data["token_expires_at"] is None
    assert data["metadata_"] is None
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_account_defaults(client):
    """创建账号时可选字段缺省使用 None。"""
    resp = await client.post(
        "/api/accounts",
        json={
            "platform": "DOUYIN",
            "display_name": "抖音号",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["account_id"] is None
    assert data["auth_token"] is None
    assert data["refresh_token"] is None
    assert data["token_expires_at"] is None


async def test_list_accounts(client):
    """GET /api/accounts 列出所有账号。"""
    await _create_account(client, Platform.WECHAT_OFFICIAL, "公众号A")
    await _create_account(client, Platform.DOUYIN, "抖音号B")

    resp = await client.get("/api/accounts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = {a["display_name"] for a in data}
    assert names == {"公众号A", "抖音号B"}


async def test_list_accounts_with_platform_filter(client):
    """GET /api/accounts?platform=DOUYIN 按平台过滤。"""
    await _create_account(client, Platform.WECHAT_OFFICIAL, "公众号A")
    await _create_account(client, Platform.DOUYIN, "抖音号B")
    await _create_account(client, Platform.DOUYIN, "抖音号C")

    resp = await client.get("/api/accounts?platform=DOUYIN")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for item in data:
        assert item["platform"] == "DOUYIN"


async def test_delete_account(client):
    """DELETE /api/accounts/{id} 删除账号。"""
    account_id = await _create_account(client, Platform.BILIBILI, "B站号")

    resp = await client.delete(f"/api/accounts/{account_id}")
    assert resp.status_code == 204

    # 再次获取应不在列表中
    resp = await client.get("/api/accounts")
    assert len(resp.json()) == 0


async def test_delete_account_not_found(client):
    """删除不存在的账号返回 404。"""
    resp = await client.delete(
        "/api/accounts/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 发布分发
# ---------------------------------------------------------------------------


async def test_publish_dispatch_immediate_single_platform(client):
    """POST /api/publish 立即发布到单平台，返回 SUCCESS。"""
    content_id = await _create_content(client)
    account_id = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "微信公众号"
    )

    resp = await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_id],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    task = data[0]
    assert task["content_id"] == content_id
    assert task["account_id"] == account_id
    assert task["platform"] == "WECHAT_OFFICIAL"
    assert task["status"] == "SUCCESS"
    assert task["external_url"].startswith("https://mp.weixin.qq.com/s/mock_")
    assert task["error_message"] is None
    assert task["published_at"] is not None
    assert task["scheduled_at"] is None


async def test_publish_dispatch_multi_platform_fan_out(client):
    """POST /api/publish 多平台 fan-out 分发。"""
    content_id = await _create_content(client)
    account_wx = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "公众号"
    )
    account_dy = await _create_account(client, Platform.DOUYIN, "抖音号")
    account_xhs = await _create_account(
        client, Platform.XIAOHONGSHU, "小红书号"
    )

    resp = await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_wx, account_dy, account_xhs],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3

    # 微信公众号：全自动成功
    wx_task = next(t for t in data if t["platform"] == "WECHAT_OFFICIAL")
    assert wx_task["status"] == "SUCCESS"
    assert wx_task["external_url"].startswith("https://mp.weixin.qq.com/")

    # 抖音：半自动模式 → PARTIAL_SUCCESS
    dy_task = next(t for t in data if t["platform"] == "DOUYIN")
    assert dy_task["status"] == "PARTIAL_SUCCESS"
    assert dy_task["external_url"] == "https://creator.douyin.com/"
    assert "半自动" in dy_task["error_message"]

    # 小红书：半自动模式 → PARTIAL_SUCCESS
    xhs_task = next(t for t in data if t["platform"] == "XIAOHONGSHU")
    assert xhs_task["status"] == "PARTIAL_SUCCESS"


async def test_publish_dispatch_scheduled(client, monkeypatch):
    """POST /api/publish 带 scheduled_at 时任务状态为 SCHEDULED 并注册触发器。"""
    # Mock register_publish_trigger 避免写入磁盘
    trigger_calls: list[tuple] = []

    from hermes.content_team.publish import dispatcher as dispatcher_module

    def mock_register(cron_expr, content_id, platform):
        trigger_calls.append((cron_expr, content_id, platform))
        return "mock-trigger-id"

    monkeypatch.setattr(
        dispatcher_module, "register_publish_trigger", mock_register
    )

    content_id = await _create_content(client)
    account_id = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "公众号"
    )

    scheduled_at = "2026-12-31T10:00:00+00:00"
    resp = await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_id],
            "scheduled_at": scheduled_at,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    task = data[0]
    assert task["status"] == "SCHEDULED"
    assert task["scheduled_at"] is not None
    assert task["published_at"] is None

    # 验证 register_publish_trigger 被调用
    assert len(trigger_calls) == 1
    cron_expr, cid, platform = trigger_calls[0]
    assert cron_expr == "0 10 31 12 *"
    assert cid == str(content_id)
    assert platform == "WECHAT_OFFICIAL"


async def test_publish_dispatch_content_not_found(client):
    """发布到不存在的内容返回 404。"""
    account_id = await _create_account(client, Platform.WECHAT_OFFICIAL, "公众号")

    resp = await client.post(
        "/api/publish",
        json={
            "content_id": "00000000-0000-0000-0000-000000000000",
            "platform_account_ids": [account_id],
        },
    )
    assert resp.status_code == 404


async def test_publish_dispatch_account_not_found(client):
    """发布到不存在的账号返回 404。"""
    content_id = await _create_content(client)

    resp = await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": ["00000000-0000-0000-0000-000000000000"],
        },
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 发布任务查询
# ---------------------------------------------------------------------------


async def test_get_publish_task(client):
    """GET /api/publish/{id} 获取单个发布任务。"""
    content_id = await _create_content(client)
    account_id = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "公众号"
    )

    create_resp = await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_id],
        },
    )
    task_id = create_resp.json()[0]["id"]

    resp = await client.get(f"/api/publish/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task_id
    assert data["status"] == "SUCCESS"


async def test_get_publish_task_not_found(client):
    """获取不存在的任务返回 404。"""
    resp = await client.get(
        "/api/publish/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


async def test_list_publish_tasks(client):
    """GET /api/publish 列出所有发布任务。"""
    content_id = await _create_content(client)
    account_wx = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "公众号"
    )
    account_dy = await _create_account(client, Platform.DOUYIN, "抖音号")

    await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_wx, account_dy],
        },
    )

    resp = await client.get("/api/publish")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


async def test_list_publish_tasks_with_content_id_filter(client):
    """GET /api/publish?content_id=xxx 按 content_id 过滤。"""
    content_a = await _create_content(client, title="内容A")
    content_b = await _create_content(client, title="内容B")
    account_id = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "公众号"
    )

    await client.post(
        "/api/publish",
        json={
            "content_id": content_a,
            "platform_account_ids": [account_id],
        },
    )
    await client.post(
        "/api/publish",
        json={
            "content_id": content_b,
            "platform_account_ids": [account_id],
        },
    )

    resp = await client.get(f"/api/publish?content_id={content_a}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["content_id"] == content_a


async def test_list_publish_tasks_with_status_filter(client):
    """GET /api/publish?status=SUCCESS 按状态过滤。"""
    content_id = await _create_content(client)
    account_wx = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "公众号"
    )
    account_dy = await _create_account(client, Platform.DOUYIN, "抖音号")

    await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_wx, account_dy],
        },
    )

    # 微信 → SUCCESS, 抖音 → PARTIAL_SUCCESS
    resp = await client.get("/api/publish?status=SUCCESS")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "SUCCESS"

    resp = await client.get("/api/publish?status=PARTIAL_SUCCESS")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "PARTIAL_SUCCESS"


# ---------------------------------------------------------------------------
# 失败重试
# ---------------------------------------------------------------------------


async def test_retry_failed_task(client):
    """POST /api/publish/{id}/retry 重试失败任务。"""
    content_id = await _create_content(client)
    account_id = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "公众号"
    )

    # 先正常发布（成功）
    create_resp = await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_id],
        },
    )
    task_id = create_resp.json()[0]["id"]

    # 通过依赖覆盖获取测试会话，将任务状态改为 FAILED（模拟失败）
    from hermes.content_team.app import app
    from hermes.content_team.db import get_db
    from hermes.content_team.models.publish import PublishTask as _PublishTask

    override_fn = app.dependency_overrides[get_db]
    gen = override_fn()
    session = await gen.__anext__()
    try:
        task = await session.get(_PublishTask, task_id)
        assert task is not None
        task.status = PublishStatus.FAILED
        task.error_message = "模拟失败"
        await session.commit()
    finally:
        await gen.aclose()

    # 重试
    resp = await client.post(f"/api/publish/{task_id}/retry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task_id
    assert data["status"] == "SUCCESS"
    assert data["external_url"].startswith("https://mp.weixin.qq.com/")
    assert data["error_message"] is None


async def test_retry_non_failed_task_returns_400(client):
    """重试非失败状态的任务返回 400。"""
    content_id = await _create_content(client)
    account_id = await _create_account(
        client, Platform.WECHAT_OFFICIAL, "公众号"
    )

    create_resp = await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_id],
        },
    )
    task_id = create_resp.json()[0]["id"]
    # 任务已经是 SUCCESS 状态

    resp = await client.post(f"/api/publish/{task_id}/retry")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 适配器单元测试
# ---------------------------------------------------------------------------


class TestAdapterValidation:
    """适配器内容校验。"""

    def test_wechat_validate_content_ok(self):
        """微信适配器：合规内容无校验错误。"""
        account = PlatformAccount(
            platform=Platform.WECHAT_OFFICIAL, display_name="公众号"
        )
        adapter = WeChatOfficialAdapter(account)
        content = Content(title="合规标题", body="合规正文")
        errors = adapter.validate_content(content)
        assert errors == []

    def test_wechat_validate_title_too_long(self):
        """微信适配器：标题超过 64 字返回错误。"""
        account = PlatformAccount(
            platform=Platform.WECHAT_OFFICIAL, display_name="公众号"
        )
        adapter = WeChatOfficialAdapter(account)
        content = Content(title="x" * 65, body="正文")
        errors = adapter.validate_content(content)
        assert len(errors) == 1
        assert "64" in errors[0]

    def test_wechat_validate_body_too_long(self):
        """微信适配器：正文超过 20000 字返回错误。"""
        account = PlatformAccount(
            platform=Platform.WECHAT_OFFICIAL, display_name="公众号"
        )
        adapter = WeChatOfficialAdapter(account)
        content = Content(title="标题", body="x" * 20001)
        errors = adapter.validate_content(content)
        assert len(errors) == 1
        assert "20000" in errors[0]

    def test_xiaohongshu_validate_title_too_long(self):
        """小红书适配器：标题超过 20 字返回错误。"""
        account = PlatformAccount(
            platform=Platform.XIAOHONGSHU, display_name="小红书号"
        )
        adapter = XiaohongshuAdapter(account)
        content = Content(title="x" * 21, body="正文")
        errors = adapter.validate_content(content)
        assert len(errors) == 1
        assert "20" in errors[0]

    def test_douyin_validate_title_too_long(self):
        """抖音适配器：标题超过 55 字返回错误。"""
        account = PlatformAccount(
            platform=Platform.DOUYIN, display_name="抖音号"
        )
        adapter = DouyinAdapter(account)
        content = Content(title="x" * 56, body="正文")
        errors = adapter.validate_content(content)
        assert len(errors) == 1
        assert "55" in errors[0]

    def test_bilibili_validate_title_too_long(self):
        """B站适配器：标题超过 80 字返回错误。"""
        account = PlatformAccount(
            platform=Platform.BILIBILI, display_name="B站号"
        )
        adapter = BilibiliAdapter(account)
        content = Content(title="x" * 81, body="正文")
        errors = adapter.validate_content(content)
        assert len(errors) == 1
        assert "80" in errors[0]


class TestWeChatAdapterPublish:
    """微信适配器发布测试。"""

    @pytest.mark.asyncio
    async def test_publish_success(self):
        """微信适配器 publish 返回成功结果与 mock 链接。"""
        account = PlatformAccount(
            platform=Platform.WECHAT_OFFICIAL, display_name="公众号"
        )
        adapter = WeChatOfficialAdapter(account)
        content = Content(title="测试标题", body="测试正文")
        # 模拟 content.id
        content.id = uuid.uuid4()

        result = await adapter.publish(content)
        assert result.success is True
        assert result.error is None
        assert result.external_url == f"https://mp.weixin.qq.com/s/mock_{content.id}"
        assert result.raw_response is not None

    @pytest.mark.asyncio
    async def test_check_status_success(self):
        """微信适配器 check_status 对成功任务返回成功。"""
        from hermes.content_team.models.publish import PublishTask

        account = PlatformAccount(
            platform=Platform.WECHAT_OFFICIAL, display_name="公众号"
        )
        adapter = WeChatOfficialAdapter(account)
        task = PublishTask(
            content_id=account.id,
            platform=Platform.WECHAT_OFFICIAL,
            account_id=account.id,
            status=PublishStatus.SUCCESS,
            external_url="https://mp.weixin.qq.com/s/mock_xxx",
        )
        result = await adapter.check_status(task)
        assert result.success is True
        assert result.external_url == "https://mp.weixin.qq.com/s/mock_xxx"


class TestDouyinAdapterPublish:
    """抖音适配器发布测试（半自动模式）。"""

    @pytest.mark.asyncio
    async def test_publish_semi_auto(self):
        """抖音适配器 publish 返回半自动结果。"""
        account = PlatformAccount(
            platform=Platform.DOUYIN, display_name="抖音号"
        )
        adapter = DouyinAdapter(account)
        content = Content(title="测试标题", body="测试正文")

        result = await adapter.publish(content)
        assert result.success is True
        assert result.error is not None
        assert "半自动" in result.error
        assert result.external_url == "https://creator.douyin.com/"


# ---------------------------------------------------------------------------
# 调度器 get_adapter 工厂方法
# ---------------------------------------------------------------------------


class TestDispatcherGetAdapter:
    """PublishDispatcher.get_adapter 工厂方法测试。"""

    def test_get_adapter_wechat(self):
        """get_adapter 对 WECHAT_OFFICIAL 返回 WeChatOfficialAdapter。"""
        dispatcher = PublishDispatcher(db_session=None)
        account = PlatformAccount(
            platform=Platform.WECHAT_OFFICIAL, display_name="公众号"
        )
        adapter = dispatcher.get_adapter(Platform.WECHAT_OFFICIAL, account)
        assert isinstance(adapter, WeChatOfficialAdapter)
        assert adapter.account is account

    def test_get_adapter_douyin(self):
        """get_adapter 对 DOUYIN 返回 DouyinAdapter。"""
        dispatcher = PublishDispatcher(db_session=None)
        account = PlatformAccount(
            platform=Platform.DOUYIN, display_name="抖音号"
        )
        adapter = dispatcher.get_adapter(Platform.DOUYIN, account)
        assert isinstance(adapter, DouyinAdapter)

    def test_get_adapter_xiaohongshu(self):
        """get_adapter 对 XIAOHONGSHU 返回 XiaohongshuAdapter。"""
        dispatcher = PublishDispatcher(db_session=None)
        account = PlatformAccount(
            platform=Platform.XIAOHONGSHU, display_name="小红书号"
        )
        adapter = dispatcher.get_adapter(Platform.XIAOHONGSHU, account)
        assert isinstance(adapter, XiaohongshuAdapter)

    def test_get_adapter_bilibili(self):
        """get_adapter 对 BILIBILI 返回 BilibiliAdapter。"""
        dispatcher = PublishDispatcher(db_session=None)
        account = PlatformAccount(
            platform=Platform.BILIBILI, display_name="B站号"
        )
        adapter = dispatcher.get_adapter(Platform.BILIBILI, account)
        assert isinstance(adapter, BilibiliAdapter)

    def test_get_adapter_unsupported(self):
        """get_adapter 对未支持平台抛出 ValueError。"""
        dispatcher = PublishDispatcher(db_session=None)
        account = PlatformAccount(
            platform=Platform.WECHAT_VIDEO, display_name="视频号"
        )
        with pytest.raises(ValueError):
            dispatcher.get_adapter(Platform.WECHAT_VIDEO, account)

"""数据分析模块集成测试。

覆盖：
- 直接创建指标记录（ContentMetric ORM）
- 列表查询过滤（content_id / platform / 日期范围）
- 单内容跨平台指标查询
- 单内容聚合摘要
- 全局聚合摘要与 by_platform 拆分
- 手动采集单个发布任务（模拟指标）
- 手动批量采集
- 按内容采集
- engagement_rate 计算校验
- 唯一约束（同 content_id + platform + date）
"""
from __future__ import annotations

from datetime import date

import pytest

from hermes.content_team.models.metrics import ContentMetric
from hermes.content_team.models.platform import Platform


# ---------------------------------------------------------------------------
# 辅助函数与 fixtures
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


async def _create_published_task(
    client,
    *,
    platform=Platform.WECHAT_OFFICIAL,
    title="发布内容",
):
    """创建内容 + 账号并发布，返回 (content_id, task_id)。"""
    content_id = await _create_content(client, title=title)
    account_id = await _create_account(client, platform, f"{platform.value}账号")
    resp = await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_id],
        },
    )
    assert resp.status_code == 200
    task_id = resp.json()[0]["id"]
    return content_id, task_id


async def _get_session(client):
    """从 client 的依赖覆盖中获取一个测试会话。

    调用方负责通过 ``async with`` 或显式 ``aclose`` 关闭返回的异步生成器。
    """
    from hermes.content_team.app import app
    from hermes.content_team.db import get_db

    override_fn = app.dependency_overrides[get_db]
    return override_fn()


async def _insert_metric(
    client,
    *,
    content_id,
    platform=Platform.WECHAT_OFFICIAL,
    snapshot_date=None,
    views=1000,
    likes=50,
    comments=10,
    shares=5,
    followers_gained=20,
    followers_lost=2,
    publish_task_id=None,
):
    """直接向数据库插入一条 ContentMetric 记录并返回其 ID。"""
    if snapshot_date is None:
        snapshot_date = date(2026, 1, 1)
    gen = await _get_session(client)
    session = await gen.__anext__()
    try:
        metric = ContentMetric(
            content_id=content_id,
            publish_task_id=publish_task_id,
            platform=platform,
            date=snapshot_date,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            followers_gained=followers_gained,
            followers_lost=followers_lost,
            engagement_rate=ContentMetric.compute_engagement_rate(
                views, likes, comments, shares
            ),
        )
        session.add(metric)
        await session.commit()
        await session.refresh(metric)
        return metric.id
    finally:
        await gen.aclose()


# ---------------------------------------------------------------------------
# 直接创建指标记录
# ---------------------------------------------------------------------------


async def test_create_metric_manually(client):
    """直接插入 ContentMetric 后可通过 API 查询到。"""
    content_id = await _create_content(client)
    metric_id = await _insert_metric(
        client,
        content_id=content_id,
        views=2000,
        likes=100,
        comments=20,
        shares=10,
    )

    resp = await client.get(f"/api/analytics/content/{content_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    metric = data[0]
    assert metric["id"] == str(metric_id)
    assert metric["content_id"] == content_id
    assert metric["platform"] == "WECHAT_OFFICIAL"
    assert metric["views"] == 2000
    assert metric["likes"] == 100
    assert metric["comments"] == 20
    assert metric["shares"] == 10
    assert metric["followers_gained"] == 20
    assert metric["followers_lost"] == 2


# ---------------------------------------------------------------------------
# 列表查询过滤
# ---------------------------------------------------------------------------


async def test_list_metrics_with_content_id_filter(client):
    """GET /api/analytics?content_id=xxx 按 content_id 过滤。"""
    content_a = await _create_content(client, title="内容A")
    content_b = await _create_content(client, title="内容B")
    await _insert_metric(client, content_id=content_a)
    await _insert_metric(client, content_id=content_b)

    resp = await client.get(f"/api/analytics?content_id={content_a}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["content_id"] == content_a


async def test_list_metrics_with_platform_filter(client):
    """GET /api/analytics?platform=DOUYIN 按平台过滤。"""
    content_id = await _create_content(client)
    await _insert_metric(
        client, content_id=content_id, platform=Platform.WECHAT_OFFICIAL
    )
    await _insert_metric(
        client, content_id=content_id, platform=Platform.DOUYIN
    )

    resp = await client.get("/api/analytics?platform=DOUYIN")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["platform"] == "DOUYIN"


async def test_list_metrics_with_date_range_filter(client):
    """GET /api/analytics?start_date=...&end_date=... 按日期范围过滤。"""
    content_id = await _create_content(client)
    await _insert_metric(
        client,
        content_id=content_id,
        snapshot_date=date(2026, 1, 10),
    )
    await _insert_metric(
        client,
        content_id=content_id,
        snapshot_date=date(2026, 2, 15),
    )
    await _insert_metric(
        client,
        content_id=content_id,
        snapshot_date=date(2026, 3, 20),
    )

    # 查询 2026-02-01 ~ 2026-02-28 范围
    resp = await client.get(
        "/api/analytics?start_date=2026-02-01&end_date=2026-02-28"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["date"] == "2026-02-15"


# ---------------------------------------------------------------------------
# 单内容查询
# ---------------------------------------------------------------------------


async def test_get_content_metrics(client):
    """GET /api/analytics/content/{id} 返回该内容所有平台的指标。"""
    content_id = await _create_content(client)
    await _insert_metric(
        client, content_id=content_id, platform=Platform.WECHAT_OFFICIAL
    )
    await _insert_metric(
        client, content_id=content_id, platform=Platform.DOUYIN
    )
    await _insert_metric(
        client, content_id=content_id, platform=Platform.BILIBILI
    )

    resp = await client.get(f"/api/analytics/content/{content_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    platforms = {m["platform"] for m in data}
    assert platforms == {"WECHAT_OFFICIAL", "DOUYIN", "BILIBILI"}


async def test_get_content_summary(client):
    """GET /api/analytics/content/{id}/summary 返回单内容聚合摘要。"""
    content_id = await _create_content(client)
    # 同一内容不同平台的指标
    await _insert_metric(
        client,
        content_id=content_id,
        platform=Platform.WECHAT_OFFICIAL,
        views=1000,
        likes=50,
        comments=10,
        shares=5,
        followers_gained=20,
        followers_lost=2,
    )
    await _insert_metric(
        client,
        content_id=content_id,
        platform=Platform.DOUYIN,
        views=2000,
        likes=100,
        comments=20,
        shares=10,
        followers_gained=40,
        followers_lost=4,
    )

    resp = await client.get(f"/api/analytics/content/{content_id}/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content_id"] == content_id
    assert data["total_views"] == 3000
    assert data["total_likes"] == 150
    assert data["total_comments"] == 30
    assert data["total_shares"] == 15
    assert data["total_followers_gained"] == 60
    # by_platform 应包含两个平台
    assert set(data["by_platform"].keys()) == {"WECHAT_OFFICIAL", "DOUYIN"}
    assert data["by_platform"]["WECHAT_OFFICIAL"]["views"] == 1000
    assert data["by_platform"]["DOUYIN"]["views"] == 2000


async def test_get_overall_summary(client):
    """GET /api/analytics/summary 返回全局聚合摘要。"""
    content_a = await _create_content(client, title="内容A")
    content_b = await _create_content(client, title="内容B")
    await _insert_metric(
        client,
        content_id=content_a,
        platform=Platform.WECHAT_OFFICIAL,
        views=1000,
        likes=50,
        comments=10,
        shares=5,
        followers_gained=20,
    )
    await _insert_metric(
        client,
        content_id=content_b,
        platform=Platform.DOUYIN,
        views=2000,
        likes=100,
        comments=20,
        shares=10,
        followers_gained=40,
    )

    resp = await client.get("/api/analytics/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content_id"] is None
    assert data["total_views"] == 3000
    assert data["total_likes"] == 150
    assert data["total_comments"] == 30
    assert data["total_shares"] == 15
    assert data["total_followers_gained"] == 60
    assert set(data["by_platform"].keys()) == {"WECHAT_OFFICIAL", "DOUYIN"}


async def test_metrics_summary_by_platform_breakdown(client):
    """summary 的 by_platform 拆分应正确聚合 count 与各项指标。"""
    content_id = await _create_content(client)
    # 同一平台、不同日期的两条快照
    await _insert_metric(
        client,
        content_id=content_id,
        platform=Platform.WECHAT_OFFICIAL,
        snapshot_date=date(2026, 1, 1),
        views=1000,
        likes=50,
    )
    await _insert_metric(
        client,
        content_id=content_id,
        platform=Platform.WECHAT_OFFICIAL,
        snapshot_date=date(2026, 1, 2),
        views=2000,
        likes=100,
    )
    await _insert_metric(
        client,
        content_id=content_id,
        platform=Platform.DOUYIN,
        snapshot_date=date(2026, 1, 1),
        views=5000,
        likes=500,
    )

    resp = await client.get("/api/analytics/summary")
    assert resp.status_code == 200
    data = resp.json()
    wx = data["by_platform"]["WECHAT_OFFICIAL"]
    dy = data["by_platform"]["DOUYIN"]
    # 微信公众号 2 条快照，浏览量合计 3000，点赞合计 150
    assert wx["count"] == 2
    assert wx["views"] == 3000
    assert wx["likes"] == 150
    # 抖音 1 条快照
    assert dy["count"] == 1
    assert dy["views"] == 5000
    assert dy["likes"] == 500


# ---------------------------------------------------------------------------
# 手动采集
# ---------------------------------------------------------------------------


async def test_manual_collect_single(client):
    """POST /api/analytics/collect/{task_id} 采集单个任务指标。"""
    content_id, task_id = await _create_published_task(
        client, platform=Platform.WECHAT_OFFICIAL
    )

    resp = await client.post(f"/api/analytics/collect/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content_id"] == content_id
    assert data["publish_task_id"] == task_id
    assert data["platform"] == "WECHAT_OFFICIAL"
    assert data["date"] == date.today().isoformat()
    # 微信公众号浏览量范围 100-10000
    assert 100 <= data["views"] <= 10_000
    assert data["engagement_rate"] > 0


async def test_manual_collect_single_not_found(client):
    """采集不存在的发布任务返回 404。"""
    resp = await client.post(
        "/api/analytics/collect/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


async def test_manual_collect_all(client):
    """POST /api/analytics/collect 批量采集所有成功发布任务。"""
    # 创建 3 个成功发布任务（不同内容 + 平台）
    await _create_published_task(client, platform=Platform.WECHAT_OFFICIAL)
    await _create_published_task(client, platform=Platform.DOUYIN)
    await _create_published_task(client, platform=Platform.BILIBILI)

    resp = await client.post("/api/analytics/collect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["collected"] == 3

    # 验证指标已写入
    list_resp = await client.get("/api/analytics")
    assert list_resp.status_code == 200
    metrics = list_resp.json()
    assert len(metrics) == 3
    platforms = {m["platform"] for m in metrics}
    assert platforms == {"WECHAT_OFFICIAL", "DOUYIN", "BILIBILI"}


async def test_collect_by_content(client):
    """通过 MetricsCollector.collect_by_content 按内容采集。"""
    from hermes.content_team.analytics.collector import MetricsCollector

    content_id, _ = await _create_published_task(
        client, platform=Platform.WECHAT_OFFICIAL, title="内容1"
    )
    # 同一内容再发布到抖音
    account_dy = await _create_account(client, Platform.DOUYIN, "抖音号")
    await client.post(
        "/api/publish",
        json={
            "content_id": content_id,
            "platform_account_ids": [account_dy],
        },
    )

    gen = await _get_session(client)
    session = await gen.__anext__()
    try:
        collector = MetricsCollector(db_session=session)
        metrics = await collector.collect_by_content(content_id)
        assert len(metrics) == 2
        platforms = {m.platform for m in metrics}
        assert platforms == {Platform.WECHAT_OFFICIAL, Platform.DOUYIN}
        # 所有指标都归属同一内容
        for m in metrics:
            assert str(m.content_id) == content_id
    finally:
        await gen.aclose()


# ---------------------------------------------------------------------------
# engagement_rate 计算
# ---------------------------------------------------------------------------


async def test_engagement_rate_computation(client):
    """ContentMetric.compute_engagement_rate 计算公式正确。"""
    # (likes + comments + shares) / max(views, 1)
    rate = ContentMetric.compute_engagement_rate(
        views=1000, likes=50, comments=10, shares=5
    )
    assert rate == pytest.approx((50 + 10 + 5) / 1000)

    # views 为 0 时分母为 1，避免除零
    rate_zero = ContentMetric.compute_engagement_rate(
        views=0, likes=5, comments=1, shares=0
    )
    assert rate_zero == pytest.approx(6.0)

    # 插入记录后查询到的 engagement_rate 与计算值一致
    content_id = await _create_content(client)
    await _insert_metric(
        client,
        content_id=content_id,
        views=2000,
        likes=100,
        comments=20,
        shares=10,
    )
    resp = await client.get(f"/api/analytics/content/{content_id}")
    data = resp.json()[0]
    assert data["engagement_rate"] == pytest.approx((100 + 20 + 10) / 2000)


# ---------------------------------------------------------------------------
# 唯一约束
# ---------------------------------------------------------------------------


async def test_unique_constraint_content_platform_date(client):
    """同 content_id + platform + date 的重复插入触发唯一约束。"""
    from sqlalchemy.exc import IntegrityError

    content_id = await _create_content(client)
    snapshot_date = date(2026, 1, 1)

    gen = await _get_session(client)
    session = await gen.__anext__()
    try:
        # 第一条成功
        m1 = ContentMetric(
            content_id=content_id,
            platform=Platform.WECHAT_OFFICIAL,
            date=snapshot_date,
            views=100,
        )
        session.add(m1)
        await session.commit()

        # 第二条相同 (content_id, platform, date) 应失败
        m2 = ContentMetric(
            content_id=content_id,
            platform=Platform.WECHAT_OFFICIAL,
            date=snapshot_date,
            views=200,
        )
        session.add(m2)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        # 不同日期应成功
        m3 = ContentMetric(
            content_id=content_id,
            platform=Platform.WECHAT_OFFICIAL,
            date=date(2026, 1, 2),
            views=300,
        )
        session.add(m3)
        await session.commit()
    finally:
        await gen.aclose()

    # 验证数据库中最终有 2 条记录
    resp = await client.get(
        f"/api/analytics?content_id={content_id}"
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_collect_single_skips_existing_snapshot(client):
    """对已有当日快照的任务再次采集应被跳过（返回 None / 404）。"""
    _content_id, task_id = await _create_published_task(
        client, platform=Platform.WECHAT_OFFICIAL
    )

    # 首次采集
    first = await client.post(f"/api/analytics/collect/{task_id}")
    assert first.status_code == 200

    # 同日再次采集 → 唯一约束触发 → collector 返回 None → API 返回 404
    second = await client.post(f"/api/analytics/collect/{task_id}")
    assert second.status_code == 404

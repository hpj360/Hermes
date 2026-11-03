"""数据回路集成测试（人工回填 + 周期复盘）。"""
from __future__ import annotations


async def _create_content(client, title="复盘测试内容") -> str:
    resp = await client.post("/api/content", json={"title": title, "body": "正文"})
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_manual_backfill_creates_metric(client):
    """POST /api/analytics/manual 创建 source=manual 快照。"""
    content_id = await _create_content(client)
    resp = await client.post(
        "/api/analytics/manual",
        json={
            "content_id": content_id,
            "platform": "XIAOHONGSHU",
            "views": 100,
            "likes": 80,
            "comments": 12,
            "shares": 5,
            "snapshot_date": "2026-09-10",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "manual"
    assert data["views"] == 100
    assert data["engagement_rate"] == (80 + 12 + 5) / 100


async def test_manual_backfill_overwrites_same_snapshot(client):
    """同 (content, platform, date) 重复回填覆盖更新而非报错。"""
    content_id = await _create_content(client)
    body = {
        "content_id": content_id,
        "platform": "DOUYIN",
        "views": 100,
        "likes": 10,
        "snapshot_date": "2026-09-11",
    }
    first = await client.post("/api/analytics/manual", json=body)
    assert first.status_code == 200
    metric_id = first.json()["id"]

    body["likes"] = 50
    second = await client.post("/api/analytics/manual", json=body)
    assert second.status_code == 200
    data = second.json()
    assert data["id"] == metric_id  # 同一快照被覆盖
    assert data["likes"] == 50
    assert data["source"] == "manual"

    # 只有一条快照
    lst = await client.get(f"/api/analytics/content/{content_id}")
    assert len(lst.json()) == 1


async def test_manual_backfill_content_not_found(client):
    resp = await client.post(
        "/api/analytics/manual",
        json={
            "content_id": "00000000-0000-0000-0000-000000000000",
            "platform": "XIAOHONGSHU",
        },
    )
    assert resp.status_code == 404


async def _backfill(client, content_id, platform, day: str, likes: int):
    resp = await client.post(
        "/api/analytics/manual",
        json={
            "content_id": content_id,
            "platform": platform,
            "views": 100,
            "likes": likes,
            "comments": 5,
            "shares": 5,
            "snapshot_date": day,
        },
    )
    assert resp.status_code == 200


async def test_retrospective_period_compare_and_top(client):
    """复盘：本期 vs 上一期对比 + Top 内容 + 来源构成。"""
    c1 = await _create_content(client, title="爆款A")
    c2 = await _create_content(client, title="普通B")

    # 本期窗口（end 2026-09-17，days=7 → 09-11..09-17）
    await _backfill(client, c1, "XIAOHONGSHU", "2026-09-15", likes=300)
    await _backfill(client, c2, "XIAOHONGSHU", "2026-09-16", likes=100)
    # 上一期窗口（09-04..09-10）
    await _backfill(client, c1, "DOUYIN", "2026-09-05", likes=40)

    resp = await client.get(
        "/api/analytics/retrospective?days=7&end_date=2026-09-17"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["days"] == 7
    assert data["start_date"] == "2026-09-11"
    assert data["end_date"] == "2026-09-17"

    # 本期/上期总量对比
    assert data["period"]["total_likes"] == 400
    assert data["previous_period"]["total_likes"] == 40

    # Top 内容按互动降序、带标题
    tops = data["top_contents"]
    assert [t["title"] for t in tops] == ["爆款A", "普通B"]
    assert tops[0]["interactions"] == 310

    # 来源构成：本期窗口内的快照（3 次回填中 2 次落在本期）
    assert data["source_counts"] == {"manual": 2}


async def test_retrospective_days_validation(client):
    resp = await client.get("/api/analytics/retrospective?days=0")
    assert resp.status_code == 400
    resp = await client.get("/api/analytics/retrospective?days=999")
    assert resp.status_code == 400


async def test_retrospective_empty_period(client):
    """无数据窗口返回零值结构与空前十。"""
    resp = await client.get(
        "/api/analytics/retrospective?days=7&end_date=2020-01-07"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"]["total_views"] == 0
    assert data["top_contents"] == []
    assert data["source_counts"] == {}

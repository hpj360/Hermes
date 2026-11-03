"""趋势数据 API 集成测试（/api/trends/*）。"""
from __future__ import annotations


async def test_get_hot_notes_fixture(client):
    """GET /api/trends/hot-notes 回退 fixture 数据源。"""
    resp = await client.get("/api/trends/hot-notes?platform=XIAOHONGSHU")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "fixture"
    assert data["platform"] == "XIAOHONGSHU"
    assert data["total"] == len(data["notes"])
    note = data["notes"][0]
    assert note["engagement"] == (
        note["likes"] + note["collects"] + note["comments"] + note["shares"]
    )
    assert note["source"] == "fixture"


async def test_get_hot_notes_with_keyword(client):
    resp = await client.get(
        "/api/trends/hot-notes?platform=XIAOHONGSHU&keyword=居家调酒"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["keyword"] == "居家调酒"
    assert data["total"] > 0


async def test_get_hot_notes_invalid_platform(client):
    resp = await client.get("/api/trends/hot-notes?platform=WECHAT_OFFICIAL")
    assert resp.status_code == 400


async def test_get_hot_list_fixture(client):
    """GET /api/trends/hot-list 返回抖音热榜。"""
    resp = await client.get("/api/trends/hot-list?platform=DOUYIN")
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "fixture"
    assert data["total"] == len(data["items"])
    assert data["items"][0]["rank"] == 1
    assert "heat" in data["items"][0]


async def test_get_hot_list_invalid_platform(client):
    resp = await client.get("/api/trends/hot-list?platform=XIAOHONGSHU_NOPE")
    assert resp.status_code == 400


async def test_import_trend_topics(client):
    """POST /api/trends/import 把爆款转成选题入库。"""
    resp = await client.post(
        "/api/trends/import",
        json={
            "platform": "XIAOHONGSHU",
            "min_engagement": 500,
            "max_fans": 5000,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "fixture"
    assert data["imported"] > 0
    topic = data["topics"][0]
    assert topic["target_platforms"] == ["XIAOHONGSHU"]
    assert "爆款参考" in topic["description"]

    # 选题库可查
    list_resp = await client.get("/api/topics")
    titles = {t["title"] for t in list_resp.json()}
    assert topic["title"] in titles


async def test_import_trend_topics_dedup_on_second_run(client):
    """重复导入按标题去重。"""
    first = await client.post("/api/trends/import", json={"platform": "XIAOHONGSHU"})
    assert first.status_code == 200
    imported_first = first.json()["imported"]
    assert imported_first > 0

    second = await client.post("/api/trends/import", json={"platform": "XIAOHONGSHU"})
    assert second.status_code == 200
    data = second.json()
    assert data["imported"] == 0
    assert data["skipped_duplicates"] == imported_first


async def test_import_trend_topics_min_engagement_filter(client):
    """高门槛过滤后导入数为 0。"""
    resp = await client.post(
        "/api/trends/import",
        json={"platform": "XIAOHONGSHU", "min_engagement": 999999},
    )
    assert resp.status_code == 200
    assert resp.json()["imported"] == 0


async def test_import_trend_topics_invalid_platform(client):
    resp = await client.post(
        "/api/trends/import", json={"platform": "BILIBILI"}
    )
    assert resp.status_code == 400


async def test_compliance_check_with_platform_pack(client):
    """POST /api/compliance/check 支持 platform 词包。"""
    resp = await client.post(
        "/api/compliance/check",
        json={
            "title": "全网最低的威士忌",
            "body": "正文",
            "platform": "DOUYIN",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is False
    assert any(h["rule_id"] == "dy_price_absolute" for h in data["blocking"])

"""选题 API 集成测试。"""
from __future__ import annotations

import pytest


async def test_create_topic(client):
    """AC-1: POST /api/topics 创建选题并返回完整对象。"""
    resp = await client.post(
        "/api/topics",
        json={
            "title": "测试选题",
            "description": "这是一个测试选题",
            "priority": 2,
            "target_platforms": ["wechat", "douyin"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "测试选题"
    assert data["description"] == "这是一个测试选题"
    assert data["priority"] == 2
    assert data["status"] == "PENDING"
    assert data["target_platforms"] == ["wechat", "douyin"]
    assert data["assigned_to"] is None
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_topic_defaults(client):
    """未传可选字段时使用默认值。"""
    resp = await client.post(
        "/api/topics", json={"title": "默认选题", "target_platforms": []}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["priority"] == 3
    assert data["status"] == "PENDING"
    assert data["description"] == ""


async def test_create_topic_validation_error(client):
    """priority 越界返回 422。"""
    resp = await client.post(
        "/api/topics", json={"title": "x", "priority": 10, "target_platforms": []}
    )
    assert resp.status_code == 422


async def test_list_topics(client):
    """GET /api/topics 返回全部选题。"""
    await client.post("/api/topics", json={"title": "选题A", "target_platforms": []})
    await client.post("/api/topics", json={"title": "选题B", "target_platforms": []})
    resp = await client.get("/api/topics")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    titles = {t["title"] for t in data}
    assert titles == {"选题A", "选题B"}


async def test_list_topics_with_status_filter(client):
    """GET /api/topics?status=PENDING 按状态过滤。"""
    await client.post(
        "/api/topics",
        json={
            "title": "待定选题",
            "target_platforms": [],
            "status": "PENDING",
        },
    )
    await client.post(
        "/api/topics",
        json={
            "title": "进行中选题",
            "target_platforms": [],
            "status": "IN_PROGRESS",
        },
    )
    resp = await client.get("/api/topics?status=PENDING")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "PENDING"
    assert data[0]["title"] == "待定选题"


async def test_get_single_topic(client):
    """GET /api/topics/{id} 返回单个选题。"""
    create = await client.post(
        "/api/topics", json={"title": "单个选题", "target_platforms": []}
    )
    tid = create.json()["id"]
    resp = await client.get(f"/api/topics/{tid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "单个选题"
    assert resp.json()["id"] == tid


async def test_get_topic_not_found(client):
    """不存在的选题返回 404。"""
    resp = await client.get(
        "/api/topics/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


async def test_update_topic(client):
    """PUT /api/topics/{id} 更新选题字段。"""
    create = await client.post(
        "/api/topics", json={"title": "原标题", "target_platforms": []}
    )
    tid = create.json()["id"]
    resp = await client.put(
        f"/api/topics/{tid}",
        json={"title": "新标题", "priority": 5, "status": "IN_PROGRESS"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "新标题"
    assert data["priority"] == 5
    assert data["status"] == "IN_PROGRESS"


async def test_update_topic_not_found(client):
    resp = await client.put(
        "/api/topics/00000000-0000-0000-0000-000000000000",
        json={"title": "x"},
    )
    assert resp.status_code == 404


async def test_delete_topic(client):
    """DELETE /api/topics/{id} 删除选题。"""
    create = await client.post(
        "/api/topics", json={"title": "待删除", "target_platforms": []}
    )
    tid = create.json()["id"]
    resp = await client.delete(f"/api/topics/{tid}")
    assert resp.status_code == 204
    # 再次获取应 404
    assert (await client.get(f"/api/topics/{tid}")).status_code == 404


async def test_delete_topic_not_found(client):
    resp = await client.delete(
        "/api/topics/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


async def test_score_topic(client):
    """AC-8: POST /api/topics/{id}/score 计算综合得分。"""
    create = await client.post(
        "/api/topics", json={"title": "评分选题", "target_platforms": []}
    )
    tid = create.json()["id"]
    resp = await client.post(
        f"/api/topics/{tid}/score",
        json={"heat": 0.8, "expertise": 0.6, "timeliness": 0.4},
    )
    assert resp.status_code == 200
    data = resp.json()
    expected_total = 0.8 * 0.4 + 0.6 * 0.3 + 0.4 * 0.3
    assert data["heat"] == pytest.approx(0.8)
    assert data["expertise"] == pytest.approx(0.6)
    assert data["timeliness"] == pytest.approx(0.4)
    assert data["total"] == pytest.approx(expected_total)
    assert data["topic_id"] == tid
    assert "id" in data


async def test_score_topic_upsert(client):
    """重复评分走 upsert，更新而非新增。"""
    create = await client.post(
        "/api/topics", json={"title": "评分选题", "target_platforms": []}
    )
    tid = create.json()["id"]
    first = await client.post(
        f"/api/topics/{tid}/score",
        json={"heat": 0.8, "expertise": 0.6, "timeliness": 0.4},
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    second = await client.post(
        f"/api/topics/{tid}/score",
        json={"heat": 1.0, "expertise": 1.0, "timeliness": 1.0},
    )
    assert second.status_code == 200
    data = second.json()
    # 同一条记录被更新
    assert data["id"] == first_id
    assert data["total"] == pytest.approx(1.0)


async def test_score_topic_not_found(client):
    resp = await client.post(
        "/api/topics/00000000-0000-0000-0000-000000000000/score",
        json={"heat": 0.5, "expertise": 0.5, "timeliness": 0.5},
    )
    assert resp.status_code == 404


async def test_claim_topic(client):
    """AC-6: POST /api/topics/{id}/claim 领取选题。"""
    create = await client.post(
        "/api/topics", json={"title": "领取选题", "target_platforms": []}
    )
    tid = create.json()["id"]
    member_id = "11111111-1111-1111-1111-111111111111"
    resp = await client.post(
        f"/api/topics/{tid}/claim", json={"assigned_to": member_id}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["assigned_to"] == member_id


async def test_claim_topic_not_found(client):
    resp = await client.post(
        "/api/topics/00000000-0000-0000-0000-000000000000/claim",
        json={"assigned_to": "11111111-1111-1111-1111-111111111111"},
    )
    assert resp.status_code == 404


async def test_member_create_and_list(client):
    """成员 API：创建后可在列表中查到。"""
    resp = await client.post(
        "/api/members",
        json={"name": "张三", "email": "zhangsan@example.com"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "张三"
    assert data["email"] == "zhangsan@example.com"
    assert data["role"] == "member"

    resp = await client.get("/api/members")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

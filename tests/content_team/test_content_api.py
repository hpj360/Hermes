"""内容 API 集成测试。"""
from __future__ import annotations


async def test_create_content(client):
    """POST /api/content 创建内容并返回完整对象。"""
    resp = await client.post(
        "/api/content",
        json={"title": "测试内容", "body": "正文内容"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "测试内容"
    assert data["body"] == "正文内容"
    assert data["content_type"] == "article"
    assert data["status"] == "DRAFT"
    assert data["topic_id"] is None
    assert data["author_id"] is None
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_content_defaults(client):
    """未传可选字段时使用默认值。"""
    resp = await client.post("/api/content", json={"title": "默认内容"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["body"] == ""
    assert data["content_type"] == "article"
    assert data["status"] == "DRAFT"
    assert data["topic_id"] is None


async def test_create_content_with_topic_id(client):
    """POST /api/content 创建内容时携带 topic_id。"""
    topic = await client.post(
        "/api/topics", json={"title": "选题A", "target_platforms": []}
    )
    tid = topic.json()["id"]

    resp = await client.post(
        "/api/content",
        json={"title": "关联内容", "topic_id": tid},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["topic_id"] == tid


async def test_create_content_from_topic(client):
    """POST /api/topics/{id}/content 基于选题创建内容，自动设置 topic_id。"""
    topic = await client.post(
        "/api/topics", json={"title": "选题B", "target_platforms": []}
    )
    tid = topic.json()["id"]

    resp = await client.post(
        f"/api/topics/{tid}/content",
        json={"title": "基于选题的内容"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "基于选题的内容"
    assert data["topic_id"] == tid


async def test_create_content_from_topic_not_found(client):
    """基于不存在的选题创建内容返回 404。"""
    resp = await client.post(
        "/api/topics/00000000-0000-0000-0000-000000000000/content",
        json={"title": "x"},
    )
    assert resp.status_code == 404


async def test_list_content(client):
    """GET /api/content 返回全部内容。"""
    await client.post("/api/content", json={"title": "内容A"})
    await client.post("/api/content", json={"title": "内容B"})
    resp = await client.get("/api/content")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    titles = {c["title"] for c in data}
    assert titles == {"内容A", "内容B"}


async def test_list_content_with_status_filter(client):
    """GET /api/content?status=DRAFT 按状态过滤。"""
    # 创建时均为默认 DRAFT 状态
    await client.post(
        "/api/content",
        json={"title": "草稿内容"},
    )
    published = await client.post(
        "/api/content",
        json={"title": "已发布内容"},
    )
    # 通过更新将第二个内容置为 PUBLISHED
    await client.put(
        f"/api/content/{published.json()['id']}",
        json={"status": "PUBLISHED"},
    )
    resp = await client.get("/api/content?status=DRAFT")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "DRAFT"
    assert data[0]["title"] == "草稿内容"


async def test_list_content_with_topic_id_filter(client):
    """GET /api/content?topic_id=xxx 按 topic_id 过滤。"""
    topic_a = await client.post(
        "/api/topics", json={"title": "选题A", "target_platforms": []}
    )
    topic_b = await client.post(
        "/api/topics", json={"title": "选题B", "target_platforms": []}
    )
    tid_a = topic_a.json()["id"]
    tid_b = topic_b.json()["id"]

    await client.post(
        "/api/content", json={"title": "内容A1", "topic_id": tid_a}
    )
    await client.post(
        "/api/content", json={"title": "内容A2", "topic_id": tid_a}
    )
    await client.post(
        "/api/content", json={"title": "内容B1", "topic_id": tid_b}
    )

    resp = await client.get(f"/api/content?topic_id={tid_a}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    for item in data:
        assert item["topic_id"] == tid_a


async def test_get_single_content(client):
    """GET /api/content/{id} 返回单个内容。"""
    create = await client.post(
        "/api/content", json={"title": "单个内容"}
    )
    cid = create.json()["id"]
    resp = await client.get(f"/api/content/{cid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "单个内容"
    assert data["id"] == cid


async def test_get_content_not_found(client):
    """不存在的 content 返回 404。"""
    resp = await client.get(
        "/api/content/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


async def test_update_content(client):
    """PUT /api/content/{id} 更新内容字段。"""
    create = await client.post(
        "/api/content", json={"title": "原标题", "body": "原正文"}
    )
    cid = create.json()["id"]
    resp = await client.put(
        f"/api/content/{cid}",
        json={"title": "新标题", "body": "新正文", "status": "IN_REVIEW"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "新标题"
    assert data["body"] == "新正文"
    assert data["status"] == "IN_REVIEW"


async def test_update_content_creates_new_version(client):
    """更新内容标题或正文时自动创建新版本。"""
    create = await client.post(
        "/api/content", json={"title": "原标题", "body": "原正文"}
    )
    cid = create.json()["id"]

    # 仅更新正文，应触发新版本
    await client.put(f"/api/content/{cid}", json={"body": "新正文"})

    versions_resp = await client.get(f"/api/content/{cid}/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    assert len(versions) == 2
    # 版本号递增
    assert versions[0]["version_number"] == 1
    assert versions[1]["version_number"] == 2


async def test_update_content_not_found(client):
    """更新不存在的 content 返回 404。"""
    resp = await client.put(
        "/api/content/00000000-0000-0000-0000-000000000000",
        json={"title": "x"},
    )
    assert resp.status_code == 404


async def test_update_content_status_only_no_version(client):
    """仅更新 status（不修改 title/body）不应创建新版本。"""
    create = await client.post(
        "/api/content", json={"title": "标题", "body": "正文"}
    )
    cid = create.json()["id"]

    await client.put(f"/api/content/{cid}", json={"status": "APPROVED"})

    versions_resp = await client.get(f"/api/content/{cid}/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()
    # 仅创建时生成的版本 1
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1


async def test_delete_content(client):
    """DELETE /api/content/{id} 删除内容。"""
    create = await client.post(
        "/api/content", json={"title": "待删除"}
    )
    cid = create.json()["id"]
    resp = await client.delete(f"/api/content/{cid}")
    assert resp.status_code == 204
    # 再次获取应 404
    assert (await client.get(f"/api/content/{cid}")).status_code == 404


async def test_delete_content_not_found(client):
    """删除不存在的 content 返回 404。"""
    resp = await client.delete(
        "/api/content/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404


async def test_get_versions(client):
    """GET /api/content/{id}/versions 列出所有版本，版本号正确递增。"""
    create = await client.post(
        "/api/content", json={"title": "v1", "body": "body1"}
    )
    cid = create.json()["id"]

    # 连续更新两次
    await client.put(f"/api/content/{cid}", json={"title": "v2", "body": "body2"})
    await client.put(f"/api/content/{cid}", json={"title": "v3", "body": "body3"})

    resp = await client.get(f"/api/content/{cid}/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 3
    # 版本号递增 1, 2, 3
    version_numbers = [v["version_number"] for v in versions]
    assert version_numbers == [1, 2, 3]


async def test_get_versions_not_found(client):
    """获取不存在内容的版本返回 404。"""
    resp = await client.get(
        "/api/content/00000000-0000-0000-0000-000000000000/versions"
    )
    assert resp.status_code == 404


async def test_update_creates_correct_version_snapshots(client):
    """更新内容生成的版本快照存储新值。"""
    # 创建：v1 快照为 "原标题" / "原正文"
    create = await client.post(
        "/api/content",
        json={"title": "原标题", "body": "原正文"},
    )
    cid = create.json()["id"]

    # 更新：v2 快照应为 "新标题" / "新正文"
    await client.put(
        f"/api/content/{cid}",
        json={"title": "新标题", "body": "新正文"},
    )

    resp = await client.get(f"/api/content/{cid}/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 2

    # v1 快照：创建时的值
    v1 = versions[0]
    assert v1["version_number"] == 1
    assert v1["title"] == "原标题"
    assert v1["body"] == "原正文"

    # v2 快照：更新后的新值
    v2 = versions[1]
    assert v2["version_number"] == 2
    assert v2["title"] == "新标题"
    assert v2["body"] == "新正文"


async def test_create_content_auto_creates_version_one(client):
    """创建内容时自动生成版本号为 1 的首个版本快照。"""
    create = await client.post(
        "/api/content",
        json={"title": "初始标题", "body": "初始正文"},
    )
    cid = create.json()["id"]

    resp = await client.get(f"/api/content/{cid}/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1
    assert versions[0]["title"] == "初始标题"
    assert versions[0]["body"] == "初始正文"
    assert versions[0]["content_id"] == cid

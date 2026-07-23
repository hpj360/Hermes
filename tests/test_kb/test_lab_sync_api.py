"""B6: 外部数据源同步 API 端点测试。"""
from __future__ import annotations

import pytest


def test_sync_thecocktaildb_endpoint(client, monkeypatch):
    """POST /api/lab/sync source=thecocktaildb 返回同步结果。"""
    from hermes_kb.thecocktaildb_sync import sync_thecocktaildb

    def fake_sync(limit=50, letters="abcdefghijklmnopqrstuvwxyz0123456789", importer=None):
        return {"imported": 5, "skipped": 2, "failed": 0, "unknown_ingredients": ["Baileys"]}

    monkeypatch.setattr("hermes_kb.app.sync_thecocktaildb", fake_sync, raising=False)
    # 同步器是函数内 import 的，需要 patch 源模块
    import hermes_kb.thecocktaildb_sync as tctdb_mod
    monkeypatch.setattr(tctdb_mod, "sync_thecocktaildb", fake_sync)

    resp = client.post("/api/lab/sync", json={"source": "thecocktaildb", "limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "thecocktaildb"
    assert body["imported"] == 5
    assert body["skipped"] == 2


def test_sync_iba_dataset_endpoint(client, monkeypatch):
    """POST /api/lab/sync source=iba_dataset 返回同步结果。"""
    import hermes_kb.iba_dataset_importer as iba_mod

    def fake_sync(data=None, importer=None):
        return {"imported": 3, "skipped": 1, "failed": 0, "unknown_ingredients": []}

    monkeypatch.setattr(iba_mod, "sync_iba_dataset", fake_sync)

    resp = client.post("/api/lab/sync", json={"source": "iba_dataset"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "iba_dataset"
    assert body["imported"] == 3


def test_sync_bar_assistant_endpoint(client, monkeypatch):
    """POST /api/lab/sync source=bar_assistant 返回同步结果。"""
    import hermes_kb.bar_assistant_sync as ba_mod

    def fake_sync(data=None):
        return {"imported": 12, "skipped": 0, "failed": 1}

    monkeypatch.setattr(ba_mod, "sync_bar_assistant_substitutes", fake_sync)

    resp = client.post("/api/lab/sync", json={"source": "bar_assistant"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "bar_assistant"
    assert body["imported"] == 12


def test_sync_invalid_source(client):
    """POST /api/lab/sync 无效 source 返回 400。"""
    resp = client.post("/api/lab/sync", json={"source": "unknown_source"})
    assert resp.status_code == 400
    assert "source" in resp.json()["detail"].lower()


def test_sync_missing_source(client):
    """POST /api/lab/sync 缺少 source 字段返回 422。"""
    resp = client.post("/api/lab/sync", json={})
    assert resp.status_code == 422


def test_recipes_list_endpoint(client, tmp_db):
    """GET /api/lab/recipes 返回配方列表（含筛选）。"""
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    # 准备测试数据
    with get_session() as session:
        session.add(Document(title="测试配方1", category="recipe", source="iba", verified=True))
        session.add(Document(title="测试配方2", category="recipe", source="thecocktaildb", verified=False))
        session.add(Document(title="测试配方3", category="recipe", source="iba", verified=True, hidden=True))
        session.commit()

    resp = client.get("/api/lab/recipes")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert len(body["items"]) == 3  # 默认不过滤 hidden

    # 按 source 筛选
    resp = client.get("/api/lab/recipes?source=iba")
    body = resp.json()
    assert len(body["items"]) == 2
    assert all(item["source"] == "iba" for item in body["items"])

    # 按 verified 筛选
    resp = client.get("/api/lab/recipes?verified=false")
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "测试配方2"

    # 按 hidden 筛选
    resp = client.get("/api/lab/recipes?hidden=true")
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["title"] == "测试配方3"


def test_recipes_list_with_limit(client, tmp_db):
    """GET /api/lab/recipes 支持 limit 参数。"""
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    with get_session() as session:
        for i in range(5):
            session.add(Document(title=f"配方{i}", category="recipe"))
        session.commit()

    resp = client.get("/api/lab/recipes?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2


def test_verify_recipe_endpoint(client, tmp_db):
    """POST /api/lab/recipes/{doc_id}/verify 审核通过配方。"""
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    with get_session() as session:
        doc = Document(title="待审核", category="recipe", verified=False, status="pending")
        session.add(doc)
        session.commit()
        session.refresh(doc)
        doc_id = doc.doc_id

    resp = client.post(f"/api/lab/recipes/{doc_id}/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"

    # 验证数据库状态
    with get_session() as session:
        doc = session.get(Document, doc_id)
        assert doc.verified is True
        assert doc.status == "published"


def test_verify_recipe_not_found(client):
    """POST /api/lab/recipes/{doc_id}/verify 配方不存在返回 404。"""
    resp = client.post("/api/lab/recipes/nonexistent-doc-id/verify")
    assert resp.status_code == 404


def test_hide_recipe_endpoint(client, tmp_db):
    """POST /api/lab/recipes/{doc_id}/hide 隐藏配方。"""
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    with get_session() as session:
        doc = Document(title="待隐藏", category="recipe")
        session.add(doc)
        session.commit()
        session.refresh(doc)
        doc_id = doc.doc_id

    resp = client.post(f"/api/lab/recipes/{doc_id}/hide")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hidden"] is True

    with get_session() as session:
        doc = session.get(Document, doc_id)
        assert doc.hidden is True


def test_unhide_recipe_endpoint(client, tmp_db):
    """POST /api/lab/recipes/{doc_id}/hide?hidden=false 取消隐藏。"""
    from hermes_kb.models import Document
    from hermes_kb.database import get_session

    with get_session() as session:
        doc = Document(title="已隐藏", category="recipe", hidden=True)
        session.add(doc)
        session.commit()
        session.refresh(doc)
        doc_id = doc.doc_id

    resp = client.post(f"/api/lab/recipes/{doc_id}/hide?hidden=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hidden"] is False

    with get_session() as session:
        doc = session.get(Document, doc_id)
        assert doc.hidden is False


def test_hide_recipe_not_found(client):
    """POST /api/lab/recipes/{doc_id}/hide 配方不存在返回 404。"""
    resp = client.post("/api/lab/recipes/nonexistent-doc-id/hide")
    assert resp.status_code == 404

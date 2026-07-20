"""FastAPI API 集成测试。"""

from __future__ import annotations


def test_health(client):
    """健康检查应返回 ok 与 M1 字段。"""
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "hermes-kb"
    assert "doc_count" in body
    assert "auth_enabled" in body
    assert "age_gate_enabled" in body
    assert "llm_available" in body
    assert "embedding_available" in body


def test_documents_empty(client):
    """空库下列文档应返回 total=0。"""
    r = client.get("/api/documents")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_documents_import_text(client):
    """导入文本后应能在 list 中看到。"""
    r = client.post(
        "/api/documents/import-text",
        json={"title": "测试", "content": "金酒是杜松子酒。" * 50},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "imported"
    doc_id = body["doc_id"]

    r2 = client.get("/api/documents")
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert any(d["doc_id"] == doc_id for d in items)


def test_documents_import_text_empty_title(client):
    """空标题应返回 400。"""
    r = client.post(
        "/api/documents/import-text",
        json={"title": "", "content": "x"},
    )
    assert r.status_code == 400


def test_documents_delete(client):
    """删除文档后 list 中应不存在。"""
    r = client.post(
        "/api/documents/import-text",
        json={"title": "待删", "content": "罕见关键词ABC456" * 20},
    )
    doc_id = r.json()["doc_id"]
    r2 = client.delete(f"/api/documents/{doc_id}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "deleted"

    r3 = client.get("/api/documents")
    assert not any(d["doc_id"] == doc_id for d in r3.json()["items"])


def test_documents_delete_nonexistent(client):
    """删除不存在的文档应返回 404。"""
    r = client.delete("/api/documents/doc_not_exists")
    assert r.status_code == 404


def test_ask_empty_query(client):
    """空 query 应返回 400。"""
    r = client.post("/api/ask", json={"query": ""})
    assert r.status_code == 400


def test_ask_seeded(client):
    """导入种子后 ask 应返回答案。"""
    client.post("/api/seed")
    r = client.post("/api/ask", json={"query": "金酒的核心风味"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "金酒的核心风味"
    assert body["answer"]
    assert "answer_id" in body
    assert "citations" in body


def test_ask_stream(client):
    """SSE 流式问答应返回 text/event-stream。"""
    client.post("/api/seed")
    with client.stream(
        "POST", "/api/ask/stream", json={"query": "威士忌"}
    ) as resp:
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert "text/event-stream" in ct
        # 至少能读到一些 SSE 数据
        chunks = []
        for line in resp.iter_lines():
            if line and line.startswith("data: "):
                chunks.append(line[6:])
            if len(chunks) >= 3:
                break
        assert len(chunks) > 0


def test_history_empty(client):
    """空库下历史应返回 total=0。"""
    r = client.get("/api/history")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_history_after_ask(client):
    """ask 之后历史应有 1 条记录。"""
    client.post("/api/seed")
    client.post("/api/ask", json={"query": "金酒"})
    r = client.get("/api/history")
    assert r.json()["total"] >= 1


def test_feedback(client):
    """反馈应能更新对应历史记录。"""
    client.post("/api/seed")
    client.post("/api/ask", json={"query": "葡萄酒"})
    log_id = client.get("/api/history").json()["items"][0]["id"]
    r = client.post(f"/api/feedback/{log_id}", json={"feedback": 1})
    assert r.status_code == 200
    assert r.json()["feedback"] == 1


def test_feedback_nonexistent(client):
    """反馈不存在记录应返回 404。"""
    r = client.post("/api/feedback/99999", json={"feedback": 1})
    assert r.status_code == 404


def test_seed(client):
    """种子接口应导入 5 篇文档。"""
    r = client.post("/api/seed")
    assert r.status_code == 200
    body = r.json()
    assert body["seeded"] == 5
    assert body["failed"] == 0


def test_age_gate_status(client):
    """年龄门状态接口应返回 enabled 字段。"""
    r = client.get("/api/age-gate/status")
    assert r.status_code == 200
    body = r.json()
    assert "age_gate_enabled" in body


def test_age_gate_confirm(client):
    """年龄门确认接口应接受 confirmed 字段。"""
    r = client.post("/api/age-gate/confirm", json={"confirmed": True})
    assert r.status_code == 200
    assert r.json()["confirmed"] is True

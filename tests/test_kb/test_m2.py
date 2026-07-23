"""M2 功能测试：文档详情 / 标签 / 分类 / 批量导入 / 查询改写。"""

from __future__ import annotations

import io


# ---------------------------------------------------------------------------
# M2-03：文档详情
# ---------------------------------------------------------------------------
def test_get_document_returns_chunks_and_tags(client):
    """详情端点返回 doc + chunks + tags。"""
    # 先导入一篇文档
    resp = client.post(
        "/api/documents/import-text",
        json={"title": "测试文档", "content": "这是第 1 段。\n\n这是第 2 段。" * 30},
    )
    assert resp.status_code == 200
    doc_id = resp.json()["doc_id"]

    # 调详情端点
    resp = client.get(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["doc"]["doc_id"] == doc_id
    assert body["doc"]["title"] == "测试文档"
    assert body["doc"]["content_length"] > 0
    assert isinstance(body["chunks"], list)
    assert len(body["chunks"]) > 0
    # 每片有 rowid/idx/text/char_start/char_end
    c0 = body["chunks"][0]
    assert {"rowid", "idx", "text", "char_start", "char_end"} <= set(c0.keys())


def test_get_document_404(client):
    resp = client.get("/api/documents/doc_notexist")
    assert resp.status_code == 404


def test_get_document_raw_download(client):
    """原始内容下载返回 text/markdown。"""
    resp = client.post(
        "/api/documents/import-text",
        json={"title": "下载测试", "content": "# 标题\n正文"},
    )
    doc_id = resp.json()["doc_id"]
    resp = client.get(f"/api/documents/{doc_id}/raw")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd
    # RFC 5987：中文文件名走 filename*=UTF-8''<percent-encoded>
    assert "filename*=UTF-8''" in cd
    from urllib.parse import unquote

    assert "下载测试" in unquote(cd)
    # 正文也应包含标题或内容
    assert "正文" in resp.text or "标题" in resp.text


# ---------------------------------------------------------------------------
# M2-06：标签
# ---------------------------------------------------------------------------
def test_create_tag_success(client):
    resp = client.post("/api/tags", json={"name": "烈酒", "color": "#ef4444"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "烈酒"
    assert body["color"] == "#ef4444"
    assert body["id"] > 0


def test_create_tag_duplicate_409(client):
    client.post("/api/tags", json={"name": "重复标签"})
    resp = client.post("/api/tags", json={"name": "重复标签"})
    assert resp.status_code == 409


def test_create_tag_empty_name_400(client):
    resp = client.post("/api/tags", json={"name": "  "})
    assert resp.status_code == 400


def test_list_tags_with_doc_count(client):
    """标签列表含 doc_count。"""
    # 创建标签
    r1 = client.post("/api/tags", json={"name": "T1"})
    tag_id = r1.json()["id"]
    # 导入文档
    r2 = client.post(
        "/api/documents/import-text",
        json={"title": "文档1", "content": "内容"},
    )
    doc_id = r2.json()["doc_id"]
    # 关联
    client.put(
        f"/api/documents/{doc_id}/metadata",
        json={"tag_ids": [tag_id]},
    )
    # 列表
    resp = client.get("/api/tags")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(t["name"] == "T1" and t["doc_count"] == 1 for t in items)


def test_delete_tag_clears_links(client):
    """删标签会清除关联。"""
    r1 = client.post("/api/tags", json={"name": "T"})
    tag_id = r1.json()["id"]
    r2 = client.post(
        "/api/documents/import-text",
        json={"title": "文档", "content": "内容"},
    )
    doc_id = r2.json()["doc_id"]
    client.put(f"/api/documents/{doc_id}/metadata", json={"tag_ids": [tag_id]})
    # 删标签
    resp = client.delete(f"/api/tags/{tag_id}")
    assert resp.status_code == 200
    # 文档详情中应无此标签
    r3 = client.get(f"/api/documents/{doc_id}")
    assert r3.status_code == 200
    assert len(r3.json()["tags"]) == 0


def test_delete_tag_404(client):
    assert client.delete("/api/tags/9999").status_code == 404


# ---------------------------------------------------------------------------
# M2-06：分类
# ---------------------------------------------------------------------------
def test_list_categories_includes_preset(client):
    resp = client.get("/api/categories")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["items"]]
    # 至少包含预设分类中部分
    assert "烈酒" in names
    assert "葡萄酒" in names


def test_list_categories_counts_used(client):
    """已使用分类的 doc_count > 0。"""
    client.post(
        "/api/documents/import-text",
        json={"title": "白酒1", "content": "x", "category": "中国白酒"},
    )
    client.post(
        "/api/documents/import-text",
        json={"title": "白酒2", "content": "y", "category": "中国白酒"},
    )
    resp = client.get("/api/categories")
    items = {c["name"]: c["doc_count"] for c in resp.json()["items"]}
    assert items.get("中国白酒") >= 2


# ---------------------------------------------------------------------------
# M2-06：元信息更新
# ---------------------------------------------------------------------------
def test_update_metadata_title_category(client):
    r = client.post(
        "/api/documents/import-text",
        json={"title": "原标题", "content": "内容"},
    )
    doc_id = r.json()["doc_id"]
    resp = client.put(
        f"/api/documents/{doc_id}/metadata",
        json={"title": "新标题", "category": "烈酒"},
    )
    assert resp.status_code == 200
    # 校验
    r2 = client.get(f"/api/documents/{doc_id}")
    assert r2.json()["doc"]["title"] == "新标题"
    assert r2.json()["doc"]["category"] == "烈酒"


def test_update_metadata_empty_title_400(client):
    r = client.post(
        "/api/documents/import-text",
        json={"title": "原标题", "content": "内容"},
    )
    doc_id = r.json()["doc_id"]
    resp = client.put(
        f"/api/documents/{doc_id}/metadata",
        json={"title": "   "},
    )
    assert resp.status_code == 400


def test_update_metadata_replace_tags(client):
    """tag_ids 替换式更新。"""
    # 创建两个标签
    t1 = client.post("/api/tags", json={"name": "A"}).json()["id"]
    t2 = client.post("/api/tags", json={"name": "B"}).json()["id"]
    # 导入文档
    r = client.post(
        "/api/documents/import-text",
        json={"title": "D", "content": "x"},
    )
    doc_id = r.json()["doc_id"]
    # 第一次关联 t1
    client.put(f"/api/documents/{doc_id}/metadata", json={"tag_ids": [t1]})
    # 替换为 t2
    client.put(f"/api/documents/{doc_id}/metadata", json={"tag_ids": [t2]})
    # 校验：只应有 t2
    r2 = client.get(f"/api/documents/{doc_id}")
    tag_names = [t["name"] for t in r2.json()["tags"]]
    assert tag_names == ["B"]


def test_update_metadata_404(client):
    resp = client.put(
        "/api/documents/doc_notexist/metadata",
        json={"title": "X"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# M2-06：list 筛选
# ---------------------------------------------------------------------------
def test_list_documents_filter_by_category(client):
    client.post(
        "/api/documents/import-text",
        json={"title": "白酒", "content": "x", "category": "中国白酒"},
    )
    client.post(
        "/api/documents/import-text",
        json={"title": "威士忌", "content": "y", "category": "烈酒"},
    )
    # 筛选中国白酒
    resp = client.get("/api/documents?category=中国白酒")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "白酒"


def test_list_documents_filter_by_tag(client):
    t1 = client.post("/api/tags", json={"name": "标签A"}).json()["id"]
    r = client.post(
        "/api/documents/import-text",
        json={"title": "有标签", "content": "x"},
    )
    doc_id = r.json()["doc_id"]
    client.put(f"/api/documents/{doc_id}/metadata", json={"tag_ids": [t1]})
    # 另一篇无标签
    client.post(
        "/api/documents/import-text",
        json={"title": "无标签", "content": "y"},
    )
    resp = client.get(f"/api/documents?tag_id={t1}")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "有标签"


def test_list_documents_filter_tag_no_match(client):
    """tag_id 存在但无关联文档 → 空列表。"""
    t1 = client.post("/api/tags", json={"name": "T"}).json()["id"]
    resp = client.get(f"/api/documents?tag_id={t1}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# M2-05：批量导入
# ---------------------------------------------------------------------------
def test_upload_batch_success(client):
    """批量上传多个 txt 文件。"""
    files = [
        ("files", ("a.txt", io.BytesIO(b"content a"), "text/plain")),
        ("files", ("b.md", io.BytesIO(b"# title b"), "text/markdown")),
        ("files", ("c.txt", io.BytesIO(b"content c"), "text/plain")),
    ]
    resp = client.post("/api/documents/upload-batch", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["imported"] == 3
    assert body["failed"] == 0
    assert len(body["results"]) == 3
    for r in body["results"]:
        assert r["status"] == "imported"
        assert r["doc_id"]
        assert r["chunk_count"] >= 0


def test_upload_batch_exceeds_limit(client):
    """超过 20 个文件 → 400。"""
    files = [
        (f"f{i}.txt", io.BytesIO(b"x"), "text/plain") for i in range(21)
    ]
    files = [("files", f) for f in files]
    resp = client.post("/api/documents/upload-batch", files=files)
    assert resp.status_code == 400
    assert "最多 20" in resp.json()["detail"]


def test_upload_batch_unsupported_type(client):
    """不支持类型计入 failed。"""
    files = [
        ("files", ("a.txt", io.BytesIO(b"x"), "text/plain")),
        ("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg")),
    ]
    resp = client.post("/api/documents/upload-batch", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["imported"] == 1
    assert body["failed"] == 1
    jpg_result = next(r for r in body["results"] if r["filename"] == "a.jpg")
    assert jpg_result["status"] == "failed"
    assert "不支持" in jpg_result["error"]


def test_upload_batch_empty_files_400(client):
    """未提供文件 → 400（FastAPI required）。"""
    resp = client.post("/api/documents/upload-batch", files=[])
    assert resp.status_code in (400, 422)


# ---------------------------------------------------------------------------
# M2-02：查询改写
# ---------------------------------------------------------------------------
def test_query_rewriter_heuristic_adds_synonyms():
    """LLM 不可用时，启发式补充同义词。"""
    from hermes_kb.query_rewriter import _heuristic_rewrite

    # 金酒 + 没有杜松子 → 应补杜松子
    r = _heuristic_rewrite("金酒啥味")
    assert "杜松子" in r
    assert "金酒" in r


def test_query_rewriter_heuristic_no_dup():
    """已有同义词不重复追加。"""
    from hermes_kb.query_rewriter import _heuristic_rewrite

    r = _heuristic_rewrite("金酒 杜松子")
    # 不应出现两次"杜松子"
    assert r.count("杜松子") == 1


def test_query_rewriter_empty_query():
    from hermes_kb.query_rewriter import _heuristic_rewrite

    assert _heuristic_rewrite("") == ""
    assert _heuristic_rewrite(None) is None  # type: ignore[arg-type]


def test_query_rewriter_disabled_returns_heuristic():
    """LLM 不可用时（默认 mock），QueryRewriter 应使用启发式。"""
    from hermes_kb.config import get_settings
    from hermes_kb.query_rewriter import QueryRewriter

    # 默认 settings.llm_available = False
    rw = QueryRewriter()
    assert rw.enabled is False
    r = rw.rewrite("茅台的工艺")
    # 应包含茅台 + 酱香
    assert "茅台" in r
    assert "酱香" in r


def test_rag_engine_uses_rewriter(client):
    """RAGEngine 调用 answer 时会经过 _rewrite_query。"""
    from hermes_kb.rag import RAGEngine

    engine = RAGEngine()
    called: list[str] = []

    original = engine.rewriter.rewrite
    def spy(q):
        called.append(q)
        return original(q)
    engine.rewriter.rewrite = spy  # type: ignore[assignment]

    engine.answer("金酒的风味")
    assert len(called) == 1
    assert called[0] == "金酒的风味"


# ---------------------------------------------------------------------------
# M2-06：delete_document 同步删 tag 关联
# ---------------------------------------------------------------------------
def test_delete_document_clears_tag_links(client):
    t1 = client.post("/api/tags", json={"name": "T"}).json()["id"]
    r = client.post(
        "/api/documents/import-text",
        json={"title": "D", "content": "x"},
    )
    doc_id = r.json()["doc_id"]
    client.put(f"/api/documents/{doc_id}/metadata", json={"tag_ids": [t1]})
    # 删文档
    resp = client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    # 列表中标签 doc_count 应为 0
    r2 = client.get("/api/tags")
    items = {t["name"]: t["doc_count"] for t in r2.json()["items"]}
    assert items.get("T") == 0


# ---------------------------------------------------------------------------
# P1-1：上传路径穿越防御（CWE-22）
# ---------------------------------------------------------------------------
def test_safe_upload_path_blocks_traversal(tmp_db):
    """P1-1: _safe_upload_path 剥离目录前缀并拒绝纯 .. / 空名（CWE-22）。"""
    from pathlib import Path

    import pytest as _pytest
    from fastapi import HTTPException

    from hermes_kb.api.documents import _safe_upload_path
    from hermes_kb.config import get_settings

    tmp_dir = Path(get_settings().db_path).parent / "uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # 1. 剥离子目录前缀：foo/evil.txt → basename evil.txt，仍落在 tmp_dir
    p = _safe_upload_path(tmp_dir, "sub/evil.txt")
    assert p.parent.resolve() == tmp_dir.resolve()
    assert p.name.endswith("evil.txt")

    # 2. 剥离 ../ 前缀：穿越 payload 被降级为 basename，留在 tmp_dir
    p2 = _safe_upload_path(tmp_dir, "../evil.txt")
    assert p2.parent.resolve() == tmp_dir.resolve()
    assert p2.name.endswith("evil.txt")

    # 3. 多层穿越 ../../etc/passwd.txt → basename passwd.txt，留在 tmp_dir
    p3 = _safe_upload_path(tmp_dir, "../../etc/passwd.txt")
    assert p3.parent.resolve() == tmp_dir.resolve()
    assert p3.name.endswith("passwd.txt")

    # 4. 纯 .. 被显式拒绝（400）
    with _pytest.raises(HTTPException) as exc:
        _safe_upload_path(tmp_dir, "..")
    assert exc.value.status_code == 400

    # 5. 纯 . 被显式拒绝
    with _pytest.raises(HTTPException):
        _safe_upload_path(tmp_dir, ".")

    # 6. 空文件名被拒绝
    with _pytest.raises(HTTPException):
        _safe_upload_path(tmp_dir, "")


def test_upload_batch_traversal_filename_stays_in_uploads(client, tmp_db):
    """P1-1: 批量上传含 ../ 的文件名不会逃逸到 uploads 父目录。"""
    from pathlib import Path

    from hermes_kb.config import get_settings

    uploads_dir = Path(get_settings().db_path).parent / "uploads"
    parent_dir = uploads_dir.parent  # 若穿越成功，逃逸文件会落在这里

    # 清理可能残留的同名逃逸文件
    for stale in parent_dir.glob("*traversal_escape*"):
        stale.unlink(missing_ok=True)

    files = [
        (
            "files",
            ("../traversal_escape.txt", io.BytesIO(b"evil payload"), "text/plain"),
        ),
    ]
    resp = client.post("/api/documents/upload-batch", files=files)
    assert resp.status_code == 200
    body = resp.json()
    # 该文件应被正常导入（basename 降级），而非逃逸
    assert body["imported"] == 1
    # 关键断言：uploads 父目录不应出现逃逸文件
    escaped = list(parent_dir.glob("*traversal_escape*"))
    assert not escaped, f"路径穿越未被阻断，父目录出现逃逸文件: {escaped}"

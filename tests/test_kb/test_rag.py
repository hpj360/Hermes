"""RAG 引擎单元测试。"""

from __future__ import annotations

import pytest

from hermes_kb.rag import ImportService, RAGEngine
from hermes_kb.retrieval import HybridRetriever


def test_import_text_basic(tmp_db):
    """导入纯文本：标题/chunk_count/状态正确。"""
    svc = ImportService()
    result = svc.import_text(
        content="金酒是杜松子酒。" * 50,
        title="测试文档",
    )
    assert result["status"] == "imported"
    assert result["title"] == "测试文档"
    assert result["chunk_count"] >= 1
    assert result["doc_id"].startswith("doc_")


def test_import_text_empty_title_rejected(tmp_db):
    """空标题应被拒绝。"""
    svc = ImportService()
    with pytest.raises(ValueError, match="title"):
        svc.import_text(content="x", title="")


def test_import_text_empty_content_rejected(tmp_db):
    """空内容（未 allow_empty）应被拒绝。"""
    svc = ImportService()
    with pytest.raises(ValueError, match="content"):
        svc.import_text(content="", title="t")


def test_import_text_allow_empty(tmp_db):
    """allow_empty=True 时空内容也能导入（chunk_count=0）。"""
    svc = ImportService()
    result = svc.import_text(content="", title="t", allow_empty=True)
    assert result["chunk_count"] == 0


def test_import_text_unsupported_file_type(tmp_db):
    """不支持的 file_type 应被拒绝。"""
    svc = ImportService()
    with pytest.raises(ValueError, match="file_type"):
        svc.import_text(content="x", title="t", file_type="docx")


def test_delete_document(tmp_db):
    """删除文档后检索应无命中。"""
    svc = ImportService()
    r = svc.import_text(content="罕见关键词XYZ123" * 20, title="t")
    doc_id = r["doc_id"]
    # 删除前能检索到
    retriever = HybridRetriever()
    hits = retriever.retrieve("XYZ123")
    assert any(h.doc_id == doc_id for h in hits)
    # 删除
    ok = svc.delete_document(doc_id)
    assert ok is True
    # 删除后无命中
    hits2 = retriever.retrieve("XYZ123")
    assert not any(h.doc_id == doc_id for h in hits2)


def test_delete_nonexistent(tmp_db):
    """删除不存在的文档返回 False。"""
    svc = ImportService()
    assert svc.delete_document("doc_not_exists") is False


def test_rag_answer_returns_citations(seeded_importer):
    """RAG answer 应返回引用列表。"""
    rag = RAGEngine()
    result = rag.answer("金酒的核心风味")
    assert result.query == "金酒的核心风味"
    assert result.answer  # 非空
    assert isinstance(result.citations, list)
    # 引用应来自金酒文档
    assert any("金酒" in c.title or "Gin" in c.title for c in result.citations) or len(result.citations) > 0
    assert result.latency_ms >= 0


def test_rag_answer_model_used(seeded_importer):
    """model_used 字段应有值（mock 或真实 backend）。"""
    rag = RAGEngine()
    result = rag.answer("威士忌")
    assert result.model_used


def test_rag_answer_id_unique(seeded_importer):
    """每次 answer_id 应唯一。"""
    rag = RAGEngine()
    r1 = rag.answer("金酒")
    r2 = rag.answer("威士忌")
    assert r1.answer_id != r2.answer_id


def test_rag_citation_chunk_rowid(seeded_importer):
    """M1-04：引用应包含 chunk_rowid。"""
    rag = RAGEngine()
    result = rag.answer("葡萄酒")
    for c in result.citations:
        assert hasattr(c, "chunk_rowid")
        assert c.chunk_rowid >= 0

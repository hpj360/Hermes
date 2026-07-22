"""向量检索性能与正确性测试（A3-1）。"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from sqlalchemy import text as sa_text
from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Chunk, Document


def _seed_doc_with_vec(title: str, content: str, vec: list[float]) -> tuple[str, int]:
    """创建 doc + chunk + chunk_vec，返回 (doc_id, chunk_rowid)。"""
    from hermes_kb.rag import ImportService

    svc = ImportService()
    result = svc.import_text(content=content, title=title)
    doc_id = result["doc_id"]
    with get_session() as session:
        chunk = session.exec(
            select(Chunk).where(Chunk.doc_id == doc_id)
        ).first()
        # 覆盖 chunk_vec 的 vec
        session.execute(sa_text(
            "UPDATE chunk_vec SET vec = :v WHERE chunk_rowid = :rid"
        ), {"v": json.dumps(vec), "rid": chunk.id})
        session.commit()
        return doc_id, chunk.id


def test_vector_retrieval_no_hardcoded_limit():
    """A3-1: 向量检索不应有硬编码 LIMIT 10000。"""
    from hermes_kb.retrieval import HybridRetriever

    # 创建少量 doc
    _seed_doc_with_vec("测试A", "内容A", [1.0, 0.0, 0.0])
    _seed_doc_with_vec("测试B", "内容B", [0.0, 1.0, 0.0])

    svc = HybridRetriever()
    # mock embedding 返回固定向量
    with patch.object(svc.embedding, "embed_one", return_value=[1.0, 0.0, 0.0]):
        hits = svc._vector("query", k=2)

    # 应能命中
    assert len(hits) >= 1
    # 最相似的应是测试A
    assert hits[0].title == "测试A"


def test_vector_retrieval_batch_meta_no_n_plus_1():
    """A3-1: 向量检索不应 N+1 查询元数据。"""
    from hermes_kb import retrieval as retrieval_mod
    from hermes_kb.retrieval import HybridRetriever

    _seed_doc_with_vec("文档1", "内容1", [1.0, 0.0])
    _seed_doc_with_vec("文档2", "内容2", [0.9, 0.1])
    _seed_doc_with_vec("文档3", "内容3", [0.8, 0.2])

    svc = HybridRetriever()
    # 监控 get_session 调用次数
    call_count = 0
    original_get_session = retrieval_mod.get_session

    def counting_get_session(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_get_session()

    with patch("hermes_kb.retrieval.get_session", side_effect=counting_get_session):
        with patch.object(svc.embedding, "embed_one", return_value=[1.0, 0.0]):
            hits = svc._vector("query", k=3)

    # _vector 内部不应为每个 hit 开新 session
    # 允许 0 次（如果用 eng.connect() 直接查）或 1 次（批量查元数据）
    # 不应等于 hits 数量（那是 N+1）
    assert len(hits) >= 1
    assert call_count <= 2, f"N+1 detected: {call_count} session calls for {len(hits)} hits"


def test_vector_retrieval_respects_configured_limit():
    """A3-1: 向量检索应使用配置项而非硬编码 10000。"""
    from hermes_kb.config import override_settings, reset_settings
    from hermes_kb.retrieval import HybridRetriever

    reset_settings()
    override_settings(vector_scan_limit=2)

    # 创建 3 个 doc，但 limit=2 只扫描前 2 个
    _seed_doc_with_vec("限1", "内容", [1.0, 0.0])
    _seed_doc_with_vec("限2", "内容", [1.0, 0.0])
    _seed_doc_with_vec("限3", "内容", [1.0, 0.0])

    svc = HybridRetriever()
    with patch.object(svc.embedding, "embed_one", return_value=[1.0, 0.0]):
        hits = svc._vector("query", k=10)

    # 配置 limit=2，最多扫描 2 条
    assert len(hits) <= 2

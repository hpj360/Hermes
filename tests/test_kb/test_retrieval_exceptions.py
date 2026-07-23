"""retrieval 异常路径专项测试（H1）。

验证 /workspace/src/hermes_kb/retrieval.py 中 6 个 SQLAlchemyError 捕获点
均正确降级 + 记录日志（logger.warning）。

覆盖路径：
1. _bm25: get_engine().connect() 抛 SQLAlchemyError → 返回 [] + warning
2. _vector_scan: get_engine().connect() 抛 SQLAlchemyError → 返回 [] + warning
3. _vector_ann: 元数据 get_session 抛 SQLAlchemyError → warning + hits 降级为空
4. _vector_scan: 元数据 get_session 抛 SQLAlchemyError → 仍返回 hits（降级默认值）+ warning
5. _doc_title: get_session 抛 SQLAlchemyError → 返回 doc_id 原值 + warning
6. _chunk_meta: get_session 抛 SQLAlchemyError → 返回 ("", doc_id) + warning

注意：用 unittest.mock.patch 校验 logger.warning 而非 caplog —— alembic.ini 的
fileConfig(disable_existing_loggers=True) 会在 init_db 期间禁用 hermes_kb.retrieval
logger，导致 caplog 捕获不到记录。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from hermes_kb.database import _SQLITE_VEC_AVAILABLE, get_session
from hermes_kb.models import Chunk
from hermes_kb.retrieval import HybridRetriever


def _seed_doc(title: str, content: str) -> str:
    """导入一篇文档（含 chunk_vec / chunk_vec_ann），返回 doc_id。"""
    from hermes_kb.rag import ImportService

    svc = ImportService()
    result = svc.import_text(content=content, title=title)
    return result["doc_id"]


def _make_connect_raising_engine() -> MagicMock:
    """构造一个 connect() 抛 SQLAlchemyError 的 mock engine。"""
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = SQLAlchemyError("simulated DB failure")
    return mock_engine


def _warning_called_with(mock_logger, expected_substring: str) -> bool:
    """检查 mock_logger.warning 是否被调用且首参包含 expected_substring。"""
    assert mock_logger.warning.called, "logger.warning 未被调用"
    for call in mock_logger.warning.call_args_list:
        args, _ = call
        if args and expected_substring in str(args[0]):
            return True
    return False


def test_bm25_fts_failure(tmp_db):
    """1. _bm25: get_engine().connect() 抛 SQLAlchemyError → 返回 [] + logger.warning。"""
    _seed_doc("测试文档A", "金酒是杜松子酒，风味清冽。" * 20)
    retriever = HybridRetriever()
    mock_engine = _make_connect_raising_engine()

    with patch("hermes_kb.retrieval.logger") as mock_logger:
        with patch("hermes_kb.retrieval.get_engine", return_value=mock_engine):
            hits = retriever._bm25("金酒", k=5)

    assert hits == []
    assert _warning_called_with(mock_logger, "BM25 FTS5 query failed")


def test_vector_scan_query_failure(tmp_db):
    """2. _vector_scan: get_engine().connect() 抛 SQLAlchemyError → 返回 [] + logger.warning。"""
    _seed_doc("测试文档B", "威士忌是谷物烈酒，风味醇厚。" * 20)
    retriever = HybridRetriever()
    mock_engine = _make_connect_raising_engine()

    with patch("hermes_kb.retrieval.logger") as mock_logger:
        with patch("hermes_kb.retrieval.get_engine", return_value=mock_engine):
            hits = retriever._vector_scan([1.0, 0.0, 0.0], k=5)

    assert hits == []
    assert _warning_called_with(mock_logger, "vector scan failed")


@pytest.mark.skipif(
    not _SQLITE_VEC_AVAILABLE, reason="sqlite-vec 不可用，跳过 ANN 测试"
)
def test_vector_ann_metadata_failure(tmp_db):
    """3. _vector_ann: 元数据 get_session 抛 SQLAlchemyError → logger.warning + hits 降级为空。

    ANN 主查询（chunk_vec_ann）正常返回 rowid，但元数据查询失败时
    chunk_meta 为空，所有 rowid 被跳过，最终 hits 为空。
    """
    _seed_doc("测试文档C", "朗姆酒是甘蔗烈酒，风味甘甜。" * 20)
    retriever = HybridRetriever()
    qvec = retriever.embedding.embed_one("朗姆酒")
    assert qvec and any(v != 0.0 for v in qvec)

    with patch("hermes_kb.retrieval.logger") as mock_logger:
        with patch(
            "hermes_kb.retrieval.get_session",
            side_effect=SQLAlchemyError("session failure"),
        ):
            hits = retriever._vector_ann(qvec, k=5)

    # 元数据查询失败 → chunk_meta 为空 → 所有 rowid 被跳过 → hits 为空
    assert hits == []
    assert _warning_called_with(mock_logger, "vector ANN metadata fetch failed")


def test_vector_scan_metadata_failure(tmp_db):
    """4. _vector_scan: 元数据 get_session 抛 SQLAlchemyError → 仍返回 hits（降级默认值）+ logger.warning。

    scan 主查询正常返回 rowid/doc_id，元数据查询失败时
    chunk_map / title_map 为空，hits 仍构建但 text="" 且 title 降级为 doc_id。
    """
    _seed_doc("测试文档D", "龙舌兰是墨西哥烈酒，风味浓烈。" * 20)
    retriever = HybridRetriever()
    qvec = retriever.embedding.embed_one("龙舌兰")
    assert qvec and any(v != 0.0 for v in qvec)

    with patch("hermes_kb.retrieval.logger") as mock_logger:
        with patch(
            "hermes_kb.retrieval.get_session",
            side_effect=SQLAlchemyError("session failure"),
        ):
            hits = retriever._vector_scan(qvec, k=5)

    # 即使元数据查询失败，hits 仍返回（text 降级为空，title 降级为 doc_id）
    assert len(hits) >= 1
    assert _warning_called_with(mock_logger, "vector metadata fetch failed")
    # 降级默认值：text 为空字符串
    assert all(h.text == "" for h in hits)


def test_doc_title_failure(tmp_db):
    """5. _doc_title: get_session 抛 SQLAlchemyError → 返回 doc_id 原值 + logger.warning。"""
    doc_id = _seed_doc("测试文档E", "伏特加是纯净的谷物烈酒。" * 20)
    retriever = HybridRetriever()

    with patch("hermes_kb.retrieval.logger") as mock_logger:
        with patch(
            "hermes_kb.retrieval.get_session",
            side_effect=SQLAlchemyError("session failure"),
        ):
            title = retriever._doc_title(doc_id)

    # 降级返回 doc_id 原值
    assert title == doc_id
    assert _warning_called_with(mock_logger, "doc title fetch failed")


def test_chunk_meta_failure(tmp_db):
    """6. _chunk_meta: get_session 抛 SQLAlchemyError → 返回 ("", doc_id) + logger.warning。"""
    doc_id = _seed_doc("测试文档F", "波本威士忌是美国玉米烈酒。" * 20)
    # 取 chunk rowid
    with get_session() as session:
        chunk = session.exec(
            select(Chunk).where(Chunk.doc_id == doc_id)
        ).first()
        assert chunk is not None
        rowid = chunk.id

    retriever = HybridRetriever()
    with patch("hermes_kb.retrieval.logger") as mock_logger:
        with patch(
            "hermes_kb.retrieval.get_session",
            side_effect=SQLAlchemyError("session failure"),
        ):
            text, title = retriever._chunk_meta(rowid, doc_id)

    # 降级返回 ("", doc_id)
    assert text == ""
    assert title == doc_id
    assert _warning_called_with(mock_logger, "chunk meta fetch failed")

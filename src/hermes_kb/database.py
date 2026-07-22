"""数据库：SQLite + FTS5 + JSON 向量表 + WAL。

设计要点：
- SQLModel 自动建表（document/chunk/querylog）
- FTS5 全文检索 chunks_fts（unicode61 分词器，中文按字索引）
- chunk_vec 表存储向量（JSON 数组），Python 层余弦相似度
- WAL 模式 + busy_timeout 提升并发写入
- 双重检查锁保护 get_engine() 初始化
- expire_on_commit=False 消除 DetachedInstanceError
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event, text as sa_text
from sqlmodel import Session, SQLModel, create_engine

from hermes_kb.config import get_settings
from hermes_kb.models import Chunk, Document, QueryLog  # noqa: F401  # 注册表

_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def get_engine():
    """获取引擎（双重检查锁保护并发初始化）。"""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        settings = get_settings()
        eng = create_engine(
            settings.db_url,
            echo=False,
            connect_args={"check_same_thread": False},
        )
        # 每个新连接都启用外键约束（连接池复用连接，必须用事件监听器）
        # 必须在首次 connect 之前注册，确保首个池化连接也启用
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_conn, _conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        # 开启 WAL + busy_timeout
        with eng.connect() as conn:
            conn.execute(sa_text("PRAGMA journal_mode=WAL"))
            conn.execute(sa_text("PRAGMA busy_timeout=5000"))
            conn.execute(sa_text("PRAGMA synchronous=NORMAL"))
            conn.commit()
        # 建表
        SQLModel.metadata.create_all(eng)
        # FTS5 虚拟表 + 触发器
        _init_fts(eng)
        # 向量表
        _init_vec_table(eng)
        _ENGINE = eng
        return eng


def _init_fts(eng) -> None:
    """初始化 FTS5 全文检索表。"""
    with eng.begin() as conn:
        # chunks_fts：对 chunk.text 做全文索引
        conn.execute(sa_text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
            "text, doc_id UNINDEXED, chunk_rowid UNINDEXED, "
            "tokenize='unicode61'"
            ")"
        ))
        # 同步触发器（INSERT / DELETE / UPDATE）
        conn.execute(sa_text(
            "CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN "
            "INSERT INTO chunks_fts(text, doc_id, chunk_rowid) "
            "VALUES (new.text, new.doc_id, new.id); "
            "END"
        ))
        conn.execute(sa_text(
            "CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN "
            "DELETE FROM chunks_fts WHERE chunk_rowid = old.id; "
            "END"
        ))
        conn.execute(sa_text(
            "CREATE TRIGGER IF NOT EXISTS chunk_au AFTER UPDATE ON chunk BEGIN "
            "DELETE FROM chunks_fts WHERE chunk_rowid = old.id; "
            "INSERT INTO chunks_fts(text, doc_id, chunk_rowid) "
            "VALUES (new.text, new.doc_id, new.id); "
            "END"
        ))


def _init_vec_table(eng) -> None:
    """初始化向量表（JSON 数组存储）。"""
    with eng.begin() as conn:
        conn.execute(sa_text(
            "CREATE TABLE IF NOT EXISTS chunk_vec ("
            "chunk_rowid INTEGER PRIMARY KEY, "
            "doc_id TEXT REFERENCES document(doc_id) ON DELETE CASCADE, "
            "vec TEXT NOT NULL"
            ")"
        ))
        conn.execute(sa_text(
            "CREATE INDEX IF NOT EXISTS idx_chunk_vec_doc_id ON chunk_vec(doc_id)"
        ))


def reset_engine() -> None:
    """测试用：重置引擎单例。"""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            _ENGINE.dispose()
        _ENGINE = None


@contextmanager
def get_session() -> Iterator[Session]:
    """获取会话上下文。"""
    eng = get_engine()
    # expire_on_commit=False 消除 DetachedInstanceError
    with Session(eng, expire_on_commit=False) as session:
        yield session

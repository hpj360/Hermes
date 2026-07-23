"""数据库：SQLite + FTS5 + JSON 向量表 + sqlite-vec ANN 索引 + WAL。

设计要点：
- schema 初始化优先走 alembic 迁移（版本追踪 / 可回滚 / 可 diff），
  失败时回退到 SQLModel.metadata.create_all（开发期零配置）
- FTS5 全文检索 chunks_fts（unicode61 分词器，中文按字索引）
- chunk_vec 表存储向量（JSON 数组，向后兼容 + 调试 + 迁移源）
- chunk_vec_ann 虚拟表（sqlite-vec vec0）提供 ANN 索引，替代 Python 余弦全表扫描
- WAL 模式 + busy_timeout 提升并发写入
- 双重检查锁保护 get_engine() 初始化
- expire_on_commit=False 消除 DetachedInstanceError
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pysqlite3 as sqlite3  # 替代标准库 sqlite3，支持 extension loading
from sqlalchemy import event, text as sa_text
from sqlmodel import Session, SQLModel, create_engine

from hermes_kb.config import get_settings
from hermes_kb.models import Chunk, Document, QueryLog  # noqa: F401  # 注册表

log = logging.getLogger("hermes_kb.database")

# sqlite-vec 扩展（可选：加载失败时 retrieval 降级为 Python 余弦扫描）
try:
    import sqlite_vec
    _SQLITE_VEC_AVAILABLE = True
except ImportError:  # pragma: no cover
    sqlite_vec = None
    _SQLITE_VEC_AVAILABLE = False

_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def _load_sqlite_vec(dbapi_conn) -> None:
    """在 DBAPI 连接上加载 sqlite-vec 扩展（每个新连接执行）。"""
    if not _SQLITE_VEC_AVAILABLE:
        return
    try:
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
    except Exception as exc:  # pragma: no cover
        log.warning("sqlite-vec extension load failed: %s", exc)


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
            module=sqlite3,  # pysqlite3：支持 extension loading
        )
        # 每个新连接都启用外键约束 + 加载 sqlite-vec 扩展
        # （连接池复用连接，必须用事件监听器；必须在首次 connect 之前注册）
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragma(dbapi_conn, _conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            _load_sqlite_vec(dbapi_conn)
        # 开启 WAL + busy_timeout
        with eng.connect() as conn:
            conn.execute(sa_text("PRAGMA journal_mode=WAL"))
            conn.execute(sa_text("PRAGMA busy_timeout=5000"))
            conn.execute(sa_text("PRAGMA synchronous=NORMAL"))
            conn.commit()
        # 建表：优先 alembic 迁移，失败回退 create_all（开发期零配置）
        init_db(eng)
        _ENGINE = eng
        return eng


def _find_alembic_ini() -> Path | None:
    """定位 alembic.ini。

    优先向上查找（兼容 editable 安装 / 项目根运行）；找不到返回 None，
    由 init_db 回退到 create_all。
    """
    here = Path(__file__).resolve()
    # src/hermes_kb/database.py → 项目根 = parents[2]；逐级向上兜底
    for parent in [*here.parents, Path.cwd()]:
        candidate = parent / "alembic.ini"
        if candidate.is_file():
            return candidate
    return None


def run_migrations() -> None:
    """执行 alembic upgrade head。

    连接串由 migrations/env.py 从 hermes_kb.config.get_settings().db_url 读取，
    与运行时引擎同一配置源。失败时抛异常，由 init_db 捕获后回退到 create_all。
    """
    from alembic import command
    from alembic.config import Config as AlembicConfig

    ini = _find_alembic_ini()
    if ini is None:
        raise FileNotFoundError("alembic.ini 未找到，无法执行迁移")
    cfg = AlembicConfig(str(ini))
    # env.py 会用 get_settings().db_url 覆盖 sqlalchemy.url
    command.upgrade(cfg, "head")


def init_db(eng=None) -> None:
    """初始化数据库 schema。

    策略：优先 alembic 迁移（生产可控、版本追踪、可回滚）；
    任何异常回退到 SQLModel.metadata.create_all（开发期零配置，不跑 alembic 也能用）。
    FTS5 虚拟表 + 向量表在两条路径后均幂等执行（IF NOT EXISTS），保证一致性。

    可无参调用（如 ``python -c "from hermes_kb.database import init_db; init_db()"``），
    此时内部通过 get_engine() 获取引擎并完成初始化。
    """
    if eng is None:
        eng = get_engine()
        # get_engine() 已完成 init_db，无需重复
        return
    try:
        run_migrations()
        log.info("init_db: schema via alembic (head)")
    except Exception as e:  # noqa: BLE001 —— 任何失败均回退，保证可用性
        log.warning("init_db: alembic 迁移失败 (%s)，回退到 create_all", e)
        SQLModel.metadata.create_all(eng)
        log.info("init_db: schema via create_all (fallback)")
    # FTS5 虚拟表 + 触发器 + 向量表（幂等，两种路径都保证存在）
    _init_fts(eng)
    _init_vec_table(eng)


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
    """初始化向量表（JSON 数组存储 + sqlite-vec ANN 索引）。"""
    dim = get_settings().embedding_dim
    with eng.begin() as conn:
        # 旧表：JSON 向量（向后兼容 + 调试 + 迁移源）
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
        # 新表：sqlite-vec vec0 ANN 索引（替代 Python 余弦全表扫描）
        if _SQLITE_VEC_AVAILABLE:
            conn.execute(sa_text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec_ann "
                f"USING vec0(embedding float[{dim}])"
            ))
            # 删除 chunk 时同步清理 ANN 索引：
            # vec0 不支持 INSERT OR REPLACE，残留 rowid 在 SQLite 复用 rowid 时
            # 会触发 UNIQUE 冲突，破坏后续导入。
            conn.execute(sa_text(
                "CREATE TRIGGER IF NOT EXISTS chunk_ad_vec "
                "AFTER DELETE ON chunk BEGIN "
                "DELETE FROM chunk_vec_ann WHERE rowid = old.id; "
                "END"
            ))
    # 旧数据迁移：chunk_vec_ann 为空但 chunk_vec 有数据时自动迁移
    if _SQLITE_VEC_AVAILABLE:
        _migrate_vec_to_ann(eng, dim)


def _migrate_vec_to_ann(eng, dim: int) -> None:
    """将 chunk_vec 中的 JSON 向量迁移到 chunk_vec_ann（旧库升级时自动执行）。"""
    try:
        with eng.connect() as conn:
            ann_count = conn.execute(
                sa_text("SELECT COUNT(*) FROM chunk_vec_ann")
            ).scalar() or 0
            if ann_count > 0:
                return
            rows = conn.execute(
                sa_text("SELECT chunk_rowid, vec FROM chunk_vec")
            ).fetchall()
        if not rows:
            return
        migrated = 0
        skipped = 0
        with eng.begin() as conn:
            for rowid, vec_json in rows:
                try:
                    vec = json.loads(vec_json)
                except (json.JSONDecodeError, TypeError):
                    skipped += 1
                    continue
                if not vec or len(vec) != dim:
                    skipped += 1
                    continue
                conn.execute(
                    sa_text(
                        "INSERT INTO chunk_vec_ann(rowid, embedding) "
                        "VALUES (:rid, :emb)"
                    ),
                    {
                        "rid": int(rowid),
                        "emb": sqlite_vec.serialize_float32(vec),
                    },
                )
                migrated += 1
        if migrated:
            log.info(
                "migrated %d vectors to chunk_vec_ann (skipped %d)",
                migrated,
                skipped,
            )
    except Exception as exc:  # pragma: no cover
        log.warning("chunk_vec_ann migration failed: %s", exc)


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

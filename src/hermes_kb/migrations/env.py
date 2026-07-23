"""Alembic 运行环境。

关键设计：
- 数据库连接串从 ``hermes_kb.config.get_settings().db_url`` 读取，覆盖
  ``alembic.ini`` 中的占位 ``sqlalchemy.url``，确保 alembic 与运行时使用同一配置源。
- ``target_metadata = SQLModel.metadata``：autogenerate 以 SQLModel 元数据为基准。
- 显式 ``import hermes_kb.models`` 触发所有 SQLModel 表注册到 metadata。
- online 模式下为每条连接启用 SQLite PRAGMA（foreign_keys / WAL），与
  ``hermes_kb.database.get_engine`` 保持一致，避免迁移期外键/触发器行为漂移。
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 触发所有 SQLModel 表注册（document/chunk/tag/document_tag/query_log/
# recipe_stats/ingredient_substitute/missing_ingredient_stats/recipe_variant）
import hermes_kb.models  # noqa: F401
from hermes_kb.config import get_settings

from sqlmodel import SQLModel

config = context.config

# 日志配置（若 alembic.ini 中定义了 [loggers] 段）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 运行时覆盖连接串 —— 单一配置源，禁止硬编码
config.set_main_option("sqlalchemy.url", get_settings().db_url)

target_metadata = SQLModel.metadata

log = logging.getLogger("alembic.env")


def _set_sqlite_pragmas(connection) -> None:
    """为 SQLite 连接启用 PRAGMA，与运行时引擎行为对齐。"""
    cursor = connection.connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL 脚本，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER TABLE 需要 batch 模式
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # SQLite 迁移期也启用外键 + WAL，保证触发器/级联行为一致
        try:
            _set_sqlite_pragmas(connection)
        except Exception:  # 非 SQLite（如未来切 PG）无 PRAGMA，忽略
            pass
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE 需要 batch 模式
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

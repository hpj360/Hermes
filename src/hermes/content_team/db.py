"""数据库连接与会话管理。

- 通过 ``DATABASE_URL`` 环境变量配置异步引擎，默认使用本地 SQLite。
- ``AsyncSessionLocal`` 为请求级会话工厂。
- ``get_db`` 作为 FastAPI 依赖注入入口。
- ``Base`` 为所有 ORM 模型的声明基类。
- ``GUID`` 为跨平台 UUID 类型（sqlite 下以带连字符字符串存储，避免 NUMERIC 亲和性问题）。
"""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import String, TypeDecorator

# 默认使用本地 SQLite 文件数据库，可通过环境变量切换到 PostgreSQL 等
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "sqlite+aiosqlite:///./content_team.db"
)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""


class GUID(TypeDecorator):
    """跨平台 UUID 类型。

    以 ``VARCHAR(36)`` 存储 UUID 的标准带连字符字符串表示。
    这样在 SQLite 下获得 TEXT 亲和性，避免纯数字 UUID 被当作数值处理；
    在 PostgreSQL 等后端也可直接读取字符串还原为 ``uuid.UUID``。
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is not None:
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(value)
        return value


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供数据库会话并在请求结束后关闭。"""
    async with AsyncSessionLocal() as session:
        yield session

"""content_team 测试共享 fixtures。

使用内存 SQLite + StaticPool，每个测试获得独立的数据库实例。
通过依赖注入覆盖 ``get_db``，确保请求走测试会话。
"""
from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def client():
    """提供挂载到内存 SQLite 的 httpx AsyncClient。"""
    # 导入模型以触发 Base.metadata 注册
    from hermes.content_team.app import app
    from hermes.content_team.db import Base, get_db
    from hermes.content_team.models import (  # noqa: F401
        ContentMetric,
        TeamMember,
        Topic,
        TopicScore,
    )

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    TestSessionLocal = async_sessionmaker(
        test_engine, expire_on_commit=False
    )

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
        await test_engine.dispose()

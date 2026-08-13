"""FastAPI 应用入口。

- 挂载 content_team 路由。
- 配置 CORS（开发环境允许所有来源）。
- 启动时自动创建数据表。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hermes.content_team.api.router import api_router
from hermes.content_team.db import Base, engine
from hermes.content_team.scheduler import init_scheduler_on_startup, shutdown_scheduler

# 显式导入模型，确保 Base.metadata 在建表前完成注册
from hermes.content_team.models import (  # noqa: F401
    Content,
    ContentMetric,
    ContentVersion,
    PlatformAccount,
    PublishTask,
    TeamMember,
    Topic,
    TopicScore,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时创建数据表并初始化调度器，关闭时停止调度器。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    init_scheduler_on_startup()
    yield
    shutdown_scheduler()


app = FastAPI(title="Content Team API", lifespan=lifespan)

# 开发环境放开 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

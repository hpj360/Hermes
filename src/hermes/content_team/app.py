"""FastAPI 应用入口。

- 挂载 content_team 路由。
- 配置 CORS（开发环境允许所有来源）。
- 启动时自动创建数据表。
- 若存在前端构建产物（apps/web/dist），挂载为静态站点（SPA 回退到 index.html）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

# 前端构建产物目录（apps/web/dist）。存在时挂载，缺失时后端仍可独立运行。
# app.py 位于 src/hermes/content_team/，向上三级到项目根。
_WEB_DIST = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"


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

# 挂载前端构建产物（若已构建）。SPA 回退：非 /api 路径返回 index.html。
if _WEB_DIST.exists() and (_WEB_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        """SPA 回退：把非 API 的前端路由交给 index.html。"""
        index = _WEB_DIST / "index.html"
        return FileResponse(index)


"""FastAPI 应用：知识库 API + 静态前端托管。

本模块只负责应用装配：CORS 中间件、全局异常处理器、APIRouter 注册与静态
文件挂载。端点实现按功能域拆分到 :mod:`hermes_kb.api` 下的各 router 模块，
共享依赖（认证、年龄门、JWT 工具、RAG/Import 服务）位于
:mod:`hermes_kb.api.deps`。

- /api/health 健康检查
- /api/documents 文档管理
- /api/ask 问答；/api/ask/stream SSE 流式问答
- /api/history 问答历史；/api/feedback 反馈
- /api/seed 种子数据初始化
- /api/auth/* 认证；/api/age-gate/* 年龄门
- /api/lab/* 鸡尾酒实验室
- / 静态前端（单进程部署）
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from hermes_kb.api.ask import router as ask_router
from hermes_kb.api.auth import router as auth_router
from hermes_kb.api.deps import (
    jwt_decode,  # noqa: F401  re-export（tests/test_kb/test_m1.py 仍从本模块导入）
    jwt_encode,  # noqa: F401
)
from hermes_kb.api.documents import router as documents_router
from hermes_kb.api.health import router as health_router
from hermes_kb.api.lab import router as lab_router
from hermes_kb.api.tags import router as tags_router
from hermes_kb.config import get_settings
from hermes_kb.rag import ImportService, RAGEngine


def create_app() -> FastAPI:
    """构造 FastAPI 应用。"""
    settings = get_settings()

    app = FastAPI(
        title="Hermes Knowledge Base",
        description="AI 原生酒类知识库（M0+M1）",
        version="0.2.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # P1-4: CORS 规范禁止 "*" + allow_credentials=True 同时出现（浏览器会拒绝）。
        # 通配符时关闭 credentials，具体 origin 列表时才开启。
        allow_credentials="*" not in settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 应用级服务实例：每个 app 独立持有，避免跨测试 settings/engine 复位互相污染。
    app.state.rag = RAGEngine()
    app.state.importer = ImportService()

    # -----------------------------------------------------------------------
    # 全局异常处理（必须注册在 app 级别）
    # -----------------------------------------------------------------------
    @app.exception_handler(ValueError)
    async def _value_error_handler(_request: Request, exc: ValueError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "bad_request", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def _generic_error_handler(_request: Request, exc: Exception):
        correlation_id = uuid.uuid4().hex[:8]
        logging.exception("unhandled exception (correlation_id=%s)", correlation_id)
        if settings.debug:
            detail: str = str(exc)
        else:
            detail = f"internal error, correlation_id={correlation_id}"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal",
                "detail": detail,
                "correlation_id": correlation_id,
            },
        )

    # -----------------------------------------------------------------------
    # 路由注册（端点路径与拆分前完全一致，prefix 由各 router 自带）
    # -----------------------------------------------------------------------
    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(tags_router)
    app.include_router(ask_router)
    app.include_router(auth_router)
    app.include_router(lab_router)

    # -----------------------------------------------------------------------
    # 静态文件挂载（单进程部署，必须最后）
    # -----------------------------------------------------------------------
    web_dist = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
    if web_dist.exists() and web_dist.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(web_dist), html=True),
            name="web",
        )

    return app


# 模块级实例（uvicorn 直接引用 hermes_kb.app:app）
app = create_app()


def main() -> None:
    """CLI 启动入口。"""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "hermes_kb.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()

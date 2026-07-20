"""FastAPI 应用：知识库 API + 静态前端托管。

端点分组：
- /api/health 健康检查
- /api/documents 文档管理（list/import-text/upload/delete）
- /api/ask 非流式问答；/api/ask/stream SSE 流式问答
- /api/history 问答历史；/api/feedback 反馈
- /api/seed 种子数据初始化
- /api/auth/login + /api/auth/me（M1-07）
- /api/age-gate/confirm（M1-08）
- / 静态前端（单进程部署）

设计要点：
- JWT 单用户认证（HS256，无外部依赖）
- 未成年保护（年龄门）默认开启
- SSE 流式：StreamingResponse + text/event-stream
- 全局异常处理 + 统一错误结构
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import select

from hermes_kb.config import get_settings
from hermes_kb.database import get_engine, get_session
from hermes_kb.models import Document, QueryLog
from hermes_kb.rag import ImportService, RAGEngine
from hermes_kb.seed import SEED_DOCS

# ---------------------------------------------------------------------------
# JWT 工具（HS256，无外部依赖）
# ---------------------------------------------------------------------------
def _b64e(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return urlsafe_b64decode(s + pad)


def jwt_encode(payload: dict[str, Any], secret: str, ttl_hours: int = 24) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + ttl_hours * 3600}
    h = _b64e(json.dumps(header, separators=(",", ":")).encode())
    p = _b64e(json.dumps(body, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64e(sig)}"


def jwt_decode(token: str, secret: str) -> dict[str, Any] | None:
    """解码并校验 JWT。失败返回 None。"""
    try:
        h, p, s = token.split(".")
    except ValueError:
        return None
    signing_input = f"{h}.{p}".encode()
    expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64d(s)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        body = json.loads(_b64d(p).decode())
    except Exception:
        return None
    if body.get("exp", 0) < int(time.time()):
        return None
    return body


# ---------------------------------------------------------------------------
# 认证依赖
# ---------------------------------------------------------------------------
async def require_auth(request: Request) -> dict[str, Any] | None:
    """若启用认证，校验 JWT；未启用时直接放行。"""
    settings = get_settings()
    if not settings.auth_enabled:
        return None
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
        )
    token = auth[7:].strip()
    payload = jwt_decode(token, settings.jwt_secret)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌无效或已过期",
        )
    return payload


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------
class ImportTextReq(BaseModel):
    title: str = Field(..., max_length=200)
    content: str = Field(default="")
    source_type: str = Field(default="local", max_length=32)
    file_type: str = Field(default="txt", max_length=16)


class AskReq(BaseModel):
    query: str = Field(..., max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class FeedbackReq(BaseModel):
    feedback: int = Field(..., ge=-1, le=1)  # 1=up / -1=down / 0=none


class LoginReq(BaseModel):
    password: str = Field(..., max_length=200)


class AgeGateReq(BaseModel):
    confirmed: bool


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------
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
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    rag = RAGEngine()
    importer = ImportService()

    # -----------------------------------------------------------------------
    # 全局异常处理
    # -----------------------------------------------------------------------
    @app.exception_handler(ValueError)
    async def _value_error_handler(_request: Request, exc: ValueError):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "bad_request", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def _generic_error_handler(_request: Request, exc: Exception):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal", "detail": str(exc)},
        )

    # -----------------------------------------------------------------------
    # 健康检查
    # -----------------------------------------------------------------------
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        doc_count = 0
        try:
            with get_session() as session:
                doc_count = len(session.exec(select(Document)).all())
        except Exception:
            doc_count = 0
        return {
            "status": "ok",
            "service": "hermes-kb",
            "version": "0.2.0",
            "time": datetime.utcnow().isoformat(),
            "doc_count": doc_count,
            "llm_provider": settings.llm_provider,
            "llm_available": settings.llm_available,
            "embedding_provider": settings.embedding_provider,
            "embedding_available": settings.embedding_available,
            "auth_enabled": settings.auth_enabled,
            "age_gate_enabled": settings.age_gate_enabled,
        }

    # -----------------------------------------------------------------------
    # 文档管理
    # -----------------------------------------------------------------------
    @app.get("/api/documents", dependencies=[Depends(require_auth)])
    async def list_documents() -> dict[str, Any]:
        with get_session() as session:
            docs = session.exec(
                select(Document).order_by(Document.created_at.desc())
            ).all()
            return {
                "total": len(docs),
                "items": [
                    {
                        "doc_id": d.doc_id,
                        "title": d.title,
                        "source_type": d.source_type,
                        "file_type": d.file_type,
                        "chunk_count": d.chunk_count,
                        "created_at": d.created_at.isoformat()
                        if d.created_at
                        else None,
                    }
                    for d in docs
                ],
            }

    @app.post("/api/documents/import-text", dependencies=[Depends(require_auth)])
    async def import_text(req: ImportTextReq) -> dict[str, Any]:
        return importer.import_text(
            content=req.content,
            title=req.title,
            source_type=req.source_type,
            file_type=req.file_type,
        )

    @app.post("/api/documents/upload", dependencies=[Depends(require_auth)])
    async def upload_file(
        file: UploadFile = File(...), title: str | None = None
    ) -> dict[str, Any]:
        if not file.filename:
            raise HTTPException(status_code=400, detail="文件名为空")
        suffix = Path(file.filename).suffix.lower().lstrip(".")
        if suffix not in ("txt", "md", "pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {suffix}（仅支持 txt/md/pdf）",
            )
        # 保存到临时文件后由 parser 处理（PDF 需要二进制）
        tmp_dir = Path(settings.db_path).parent / "uploads"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"{int(time.time() * 1000)}_{file.filename}"
        with tmp_path.open("wb") as f:
            f.write(await file.read())
        try:
            return importer.import_file(tmp_path, title=title or file.filename)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    @app.delete("/api/documents/{doc_id}", dependencies=[Depends(require_auth)])
    async def delete_document(doc_id: str) -> dict[str, Any]:
        ok = importer.delete_document(doc_id)
        if not ok:
            raise HTTPException(status_code=404, detail="文档不存在")
        return {"doc_id": doc_id, "status": "deleted"}

    # -----------------------------------------------------------------------
    # 问答
    # -----------------------------------------------------------------------
    @app.post("/api/ask", dependencies=[Depends(require_auth)])
    async def ask(req: AskReq) -> dict[str, Any]:
        if not req.query or not req.query.strip():
            raise HTTPException(status_code=400, detail="query 不能为空")
        result = rag.answer(req.query, top_k=req.top_k)
        return result.to_dict()

    @app.post("/api/ask/stream", dependencies=[Depends(require_auth)])
    async def ask_stream(req: AskReq) -> StreamingResponse:
        if not req.query or not req.query.strip():
            raise HTTPException(status_code=400, detail="query 不能为空")

        async def gen():
            async for chunk in rag.answer_stream(req.query, top_k=req.top_k):
                yield chunk

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # -----------------------------------------------------------------------
    # 历史 + 反馈
    # -----------------------------------------------------------------------
    @app.get("/api/history", dependencies=[Depends(require_auth)])
    async def history(limit: int = 50) -> dict[str, Any]:
        with get_session() as session:
            logs = session.exec(
                select(QueryLog)
                .order_by(QueryLog.created_at.desc())
                .limit(max(1, min(limit, 500)))
            ).all()
            return {
                "total": len(logs),
                "items": [
                    {
                        "id": log.id,
                        "query": log.query,
                        "answer": log.answer,
                        "citations": json.loads(log.citations or "[]"),
                        "model_used": log.model_used,
                        "latency_ms": log.latency_ms,
                        "feedback": log.feedback,
                        "created_at": log.created_at.isoformat()
                        if log.created_at
                        else None,
                    }
                    for log in logs
                ],
            }

    @app.post("/api/feedback/{log_id}", dependencies=[Depends(require_auth)])
    async def feedback(log_id: int, req: FeedbackReq) -> dict[str, Any]:
        with get_session() as session:
            log = session.get(QueryLog, log_id)
            if not log:
                raise HTTPException(status_code=404, detail="问答记录不存在")
            log.feedback = req.feedback
            session.add(log)
            session.commit()
            return {"id": log_id, "feedback": req.feedback, "status": "ok"}

    # -----------------------------------------------------------------------
    # 种子数据
    # -----------------------------------------------------------------------
    @app.post("/api/seed", dependencies=[Depends(require_auth)])
    async def seed() -> dict[str, Any]:
        imported: list[dict[str, Any]] = []
        for doc in SEED_DOCS:
            try:
                result = importer.import_text(
                    content=doc["content"],
                    title=doc["title"],
                    source_type="seed",
                    file_type="md",
                )
                imported.append(result)
            except Exception as e:
                imported.append(
                    {"title": doc["title"], "error": str(e), "status": "failed"}
                )
        return {
            "seeded": len([x for x in imported if x.get("status") == "imported"]),
            "failed": len([x for x in imported if x.get("status") == "failed"]),
            "items": imported,
        }

    # -----------------------------------------------------------------------
    # 认证（M1-07）
    # -----------------------------------------------------------------------
    @app.post("/api/auth/login")
    async def login(req: LoginReq) -> dict[str, Any]:
        if not settings.auth_enabled:
            return {
                "token": "",
                "auth_enabled": False,
                "message": "认证未启用",
            }
        # 单用户密码校验
        if not settings.auth_password:
            raise HTTPException(
                status_code=500,
                detail="服务端未配置认证密码（KB_AUTH_PASSWORD）",
            )
        if not hmac.compare_digest(req.password, settings.auth_password):
            raise HTTPException(status_code=401, detail="密码错误")
        token = jwt_encode(
            {"sub": settings.auth_username, "role": "admin"},
            settings.jwt_secret,
            ttl_hours=settings.jwt_ttl_hours,
        )
        return {
            "token": token,
            "auth_enabled": True,
            "username": settings.auth_username,
            "expires_in": settings.jwt_ttl_hours * 3600,
        }

    @app.get("/api/auth/me")
    async def me(payload: dict[str, Any] | None = Depends(require_auth)) -> dict[str, Any]:
        return {
            "auth_enabled": settings.auth_enabled,
            "username": (payload or {}).get("sub") if payload else None,
            "exp": (payload or {}).get("exp") if payload else None,
        }

    # -----------------------------------------------------------------------
    # 年龄门（M1-08）
    # -----------------------------------------------------------------------
    @app.post("/api/age-gate/confirm")
    async def age_gate_confirm(req: AgeGateReq) -> dict[str, Any]:
        return {
            "confirmed": bool(req.confirmed),
            "age_gate_enabled": settings.age_gate_enabled,
            "message": "已确认成年" if req.confirmed else "未确认",
        }

    @app.get("/api/age-gate/status")
    async def age_gate_status() -> dict[str, Any]:
        return {
            "age_gate_enabled": settings.age_gate_enabled,
            "message": "本站内容含酒类知识，未满 18 岁请勿访问"
            if settings.age_gate_enabled
            else "年龄门未启用",
        }

    # -----------------------------------------------------------------------
    # 静态文件挂载（单进程部署）
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

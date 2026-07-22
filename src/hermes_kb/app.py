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
import logging
import time
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlmodel import select

from hermes_kb.age_gate import (
    COOKIE_NAME,
    COOKIE_TTL_DAYS,
    make_age_cookie_value,
    require_age_gate,
    verify_age_cookie,
)
from hermes_kb.config import get_settings
from hermes_kb.database import get_engine, get_session
from hermes_kb.models import (
    PRESET_CATEGORIES,
    Chunk,
    Document,
    DocumentTag,
    QueryLog,
    Tag,
)
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
    category: str = Field(default="", max_length=32)  # M2-06


class AskReq(BaseModel):
    query: str = Field(..., max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class FeedbackReq(BaseModel):
    feedback: int = Field(..., ge=-1, le=1)  # 1=up / -1=down / 0=none


class LoginReq(BaseModel):
    password: str = Field(..., max_length=200)


class AgeGateReq(BaseModel):
    confirmed: bool


# M2-06：文档元信息更新
class DocMetadataReq(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=32)
    tag_ids: list[int] | None = Field(default=None)


# M2-06：标签创建
class TagCreateReq(BaseModel):
    name: str = Field(..., max_length=32)
    color: str = Field(default="#6b7280", max_length=16)


# B6：外部数据源同步请求
class SyncRequest(BaseModel):
    source: str = Field(..., description="数据源：thecocktaildb / iba_dataset / bar_assistant")
    limit: int = Field(default=50, ge=1, le=500)


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
            "time": datetime.now(timezone.utc).isoformat(),
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
    async def list_documents(
        category: str | None = None,
        tag_id: int | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            stmt = select(Document)
            if category:
                stmt = stmt.where(Document.category == category)
            if tag_id:
                # 通过 DocumentTag 关联筛选
                doc_ids_stmt = select(DocumentTag.doc_id).where(
                    DocumentTag.tag_id == tag_id
                )
                # SQLModel 单列 select 直接返回值（非 tuple）
                doc_ids = list(session.exec(doc_ids_stmt).all())
                if doc_ids:
                    stmt = stmt.where(Document.doc_id.in_(doc_ids))
                else:
                    # 该 tag 无关联文档，直接返回空
                    return {"total": 0, "items": []}
            docs = session.exec(stmt.order_by(Document.created_at.desc())).all()
            # 预取所有 tag 关联（避免 N+1）
            all_doc_ids = [d.doc_id for d in docs]
            tag_map: dict[str, list[dict]] = {d.doc_id: [] for d in docs}
            if all_doc_ids:
                tag_rows = session.exec(
                    select(DocumentTag, Tag).join(
                        Tag, DocumentTag.tag_id == Tag.id, isouter=True
                    ).where(DocumentTag.doc_id.in_(all_doc_ids))
                ).all()
                for dt, t in tag_rows:
                    if t and dt.doc_id in tag_map:
                        tag_map[dt.doc_id].append(
                            {"id": t.id, "name": t.name, "color": t.color}
                        )
            return {
                "total": len(docs),
                "items": [
                    {
                        "doc_id": d.doc_id,
                        "title": d.title,
                        "source_type": d.source_type,
                        "file_type": d.file_type,
                        "chunk_count": d.chunk_count,
                        "category": d.category,
                        "tags": tag_map.get(d.doc_id, []),
                        "created_at": d.created_at.isoformat()
                        if d.created_at
                        else None,
                    }
                    for d in docs
                ],
            }

    @app.post("/api/documents/import-text", dependencies=[Depends(require_auth)])
    async def import_text(req: ImportTextReq) -> dict[str, Any]:
        result = importer.import_text(
            content=req.content,
            title=req.title,
            source_type=req.source_type,
            file_type=req.file_type,
        )
        # M2-06：写入 category（如果有）
        if req.category and result.get("doc_id"):
            with get_session() as session:
                doc = session.get(Document, result["doc_id"])
                if doc:
                    doc.category = req.category
                    session.add(doc)
                    session.commit()
            result["category"] = req.category
        return result

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
    # M2-03：文档详情
    # -----------------------------------------------------------------------
    @app.get("/api/documents/{doc_id}", dependencies=[Depends(require_auth)])
    async def get_document(doc_id: str) -> dict[str, Any]:
        """文档详情：元信息 + 全部 chunks。"""
        with get_session() as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="文档不存在")
            chunks = session.exec(
                select(Chunk).where(Chunk.doc_id == doc_id).order_by(Chunk.idx)
            ).all()
            tags = session.exec(
                select(Tag).join(
                    DocumentTag, DocumentTag.tag_id == Tag.id, isouter=True
                ).where(DocumentTag.doc_id == doc_id)
            ).all()
            return {
                "doc": {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "source_type": doc.source_type,
                    "file_type": doc.file_type,
                    "chunk_count": doc.chunk_count,
                    "category": doc.category,
                    "content_length": len(doc.content or ""),
                    "created_at": doc.created_at.isoformat() if doc.created_at else None,
                },
                "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
                "chunks": [
                    {
                        "rowid": c.id,
                        "idx": c.idx,
                        "text": c.text,
                        "char_start": c.char_start,
                        "char_end": c.char_end,
                    }
                    for c in chunks
                ],
            }

    @app.get("/api/documents/{doc_id}/raw", dependencies=[Depends(require_auth)])
    async def get_document_raw(doc_id: str):
        """原始内容下载（MD/txt 文件）。"""
        with get_session() as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="文档不存在")
            ext = doc.file_type or "txt"
            media = {
                "md": "text/markdown; charset=utf-8",
                "txt": "text/plain; charset=utf-8",
                "pdf": "application/pdf",
            }.get(ext, "text/plain; charset=utf-8")
            filename = f"{doc.title}.{ext}"
            # RFC 5987：filename* 用 UTF-8 percent-encoding（兼容中文）
            # filename 用 ASCII 兜底（latin-1 不支持中文）
            from urllib.parse import quote

            filename_star = quote(filename)
            ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "download"
            return Response(
                content=doc.content or "",
                media_type=media,
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=\"{ascii_fallback}\"; "
                        f"filename*=UTF-8''{filename_star}"
                    )
                },
            )

    # -----------------------------------------------------------------------
    # M2-06：标签与分类
    # -----------------------------------------------------------------------
    @app.get("/api/tags", dependencies=[Depends(require_auth)])
    async def list_tags() -> dict[str, Any]:
        with get_session() as session:
            tags = session.exec(select(Tag).order_by(Tag.name)).all()
            # 统计每个 tag 关联文档数
            counts: dict[int, int] = {}
            for t in tags:
                cnt = len(
                    session.exec(
                        select(DocumentTag).where(DocumentTag.tag_id == t.id)
                    ).all()
                )
                counts[t.id or 0] = cnt
            return {
                "total": len(tags),
                "items": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "color": t.color,
                        "doc_count": counts.get(t.id or 0, 0),
                    }
                    for t in tags
                ],
            }

    @app.post("/api/tags", dependencies=[Depends(require_auth)])
    async def create_tag(req: TagCreateReq) -> dict[str, Any]:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="标签名不能为空")
        with get_session() as session:
            existing = session.exec(
                select(Tag).where(Tag.name == name)
            ).first()
            if existing:
                raise HTTPException(status_code=409, detail="标签已存在")
            tag = Tag(name=name, color=req.color)
            session.add(tag)
            session.commit()
            session.refresh(tag)
            return {"id": tag.id, "name": tag.name, "color": tag.color}

    @app.delete("/api/tags/{tag_id}", dependencies=[Depends(require_auth)])
    async def delete_tag(tag_id: int) -> dict[str, Any]:
        with get_session() as session:
            tag = session.get(Tag, tag_id)
            if not tag:
                raise HTTPException(status_code=404, detail="标签不存在")
            session.delete(tag)
            session.commit()
            return {"id": tag_id, "status": "deleted"}

    @app.get("/api/categories", dependencies=[Depends(require_auth)])
    async def list_categories() -> dict[str, Any]:
        """M2-06：列出预设分类 + 已使用分类的文档数。"""
        with get_session() as session:
            # 统计每个 category 的文档数
            rows = session.exec(
                select(Document.category).where(Document.category != "")
            ).all()
            counts: dict[str, int] = {}
            for c in rows:
                counts[c] = counts.get(c, 0) + 1
            items = [
                {"name": c, "doc_count": counts.get(c, 0)}
                for c in PRESET_CATEGORIES
            ]
            # 追加未在预设内但已使用的分类
            for c, n in counts.items():
                if c not in PRESET_CATEGORIES:
                    items.append({"name": c, "doc_count": n})
            return {"total": len(items), "items": items}

    @app.put("/api/documents/{doc_id}/metadata", dependencies=[Depends(require_auth)])
    async def update_doc_metadata(doc_id: str, req: DocMetadataReq) -> dict[str, Any]:
        """M2-06：更新文档元信息（title/category/tags）。"""
        with get_session() as session:
            doc = session.get(Document, doc_id)
            if not doc:
                raise HTTPException(status_code=404, detail="文档不存在")
            if req.title is not None:
                if not req.title.strip():
                    raise HTTPException(status_code=400, detail="标题不能为空")
                doc.title = req.title.strip()
            if req.category is not None:
                doc.category = req.category
            if req.tag_ids is not None:
                # 替换关联
                old_links = session.exec(
                    select(DocumentTag).where(DocumentTag.doc_id == doc_id)
                ).all()
                for link in old_links:
                    session.delete(link)
                for tid in req.tag_ids:
                    # 校验 tag 存在
                    if not session.get(Tag, tid):
                        continue
                    session.add(DocumentTag(doc_id=doc_id, tag_id=tid))
            session.add(doc)
            session.commit()
            return {"doc_id": doc_id, "status": "updated"}

    # -----------------------------------------------------------------------
    # M2-05：批量导入
    # -----------------------------------------------------------------------
    @app.post("/api/documents/upload-batch", dependencies=[Depends(require_auth)])
    async def upload_batch(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        """批量上传（≤ 20 文件）。"""
        settings = get_settings()
        if len(files) > 20:
            raise HTTPException(
                status_code=400,
                detail=f"单次最多 20 个文件，当前 {len(files)} 个",
            )
        results: list[dict[str, Any]] = []
        tmp_dir = Path(settings.db_path).parent / "uploads"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            if not f.filename:
                results.append(
                    {"filename": "", "status": "failed", "error": "文件名为空"}
                )
                continue
            suffix = Path(f.filename).suffix.lower().lstrip(".")
            if suffix not in ("txt", "md", "pdf"):
                results.append(
                    {
                        "filename": f.filename,
                        "status": "failed",
                        "error": f"不支持的类型: {suffix}",
                    }
                )
                continue
            tmp_path = tmp_dir / f"{int(time.time() * 1000)}_{f.filename}"
            try:
                content = await f.read()
                tmp_path.write_bytes(content)
                r = importer.import_file(tmp_path, title=f.filename)
                results.append(
                    {
                        "filename": f.filename,
                        "status": "imported",
                        "doc_id": r.get("doc_id"),
                        "chunk_count": r.get("chunk_count", 0),
                    }
                )
            except Exception as e:
                results.append(
                    {"filename": f.filename, "status": "failed", "error": str(e)}
                )
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
        ok = sum(1 for r in results if r["status"] == "imported")
        return {
            "total": len(files),
            "imported": ok,
            "failed": len(files) - ok,
            "results": results,
        }

    # -----------------------------------------------------------------------
    # 问答
    # -----------------------------------------------------------------------
    @app.post("/api/ask", dependencies=[Depends(require_auth), Depends(require_age_gate)])
    async def ask(req: AskReq) -> dict[str, Any]:
        if not req.query or not req.query.strip():
            raise HTTPException(status_code=400, detail="query 不能为空")
        result = rag.answer(req.query, top_k=req.top_k)
        return result.to_dict()

    @app.post("/api/ask/stream", dependencies=[Depends(require_auth), Depends(require_age_gate)])
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

    @app.post("/api/seed/recipes", dependencies=[Depends(require_auth)])
    async def seed_recipes() -> dict[str, Any]:
        """M3：导入 IBA 配方种子数据（幂等）。"""
        from hermes_kb.seed_recipes import SEED_RECIPES

        seeded = 0
        failed = 0
        items: list[dict[str, Any]] = []
        for recipe in SEED_RECIPES:
            with get_session() as session:
                existing = session.exec(
                    select(Document).where(Document.title == recipe["title"])
                ).first()
                if existing:
                    items.append(
                        {
                            "title": recipe["title"],
                            "status": "skipped",
                            "doc_id": existing.doc_id,
                        }
                    )
                    continue
            try:
                result = importer.import_text(
                    content=recipe["content"],
                    title=recipe["title"],
                    source_type="seed",
                    file_type="md",
                )
                if result.get("doc_id"):
                    with get_session() as session:
                        doc = session.get(Document, result["doc_id"])
                        if doc:
                            doc.category = "recipe"
                            session.add(doc)
                            session.commit()
                seeded += 1
                items.append({**result, "status": "imported"})
            except Exception as e:
                failed += 1
                items.append(
                    {"title": recipe["title"], "error": str(e), "status": "failed"}
                )
        return {"seeded": seeded, "failed": failed, "items": items}

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
    async def age_gate_confirm(req: AgeGateReq, response: Response) -> dict[str, Any]:
        if req.confirmed:
            response.set_cookie(
                key=COOKIE_NAME,
                value=make_age_cookie_value(),
                max_age=COOKIE_TTL_DAYS * 86400,
                httponly=True,
                samesite="strict",
                secure=False,  # 开发环境 HTTP；生产应通过 reverse proxy
            )
        return {
            "confirmed": bool(req.confirmed),
            "age_gate_enabled": settings.age_gate_enabled,
            "message": "已确认成年" if req.confirmed else "未确认",
        }

    @app.get("/api/age-gate/status")
    async def age_gate_status(request: Request) -> dict[str, Any]:
        confirmed = verify_age_cookie(request.cookies.get(COOKIE_NAME))
        return {
            "age_gate_enabled": settings.age_gate_enabled,
            "confirmed": confirmed,
            "message": "本站内容含酒类知识，未满 18 岁请勿访问"
            if settings.age_gate_enabled
            else "年龄门未启用",
        }

    # -----------------------------------------------------------------------
    # M3：鸡尾酒实验室
    # -----------------------------------------------------------------------
    @app.get("/api/lab/match", dependencies=[Depends(require_age_gate)])
    async def lab_match(
        ingredients: str = "",
        background_tasks: BackgroundTasks = None,
    ) -> dict[str, Any]:
        """材料 → 配方匹配。ingredients 为逗号分隔的材料名。

        A3-3: 统计写入移到 BackgroundTasks，主响应不阻塞。match_recipes
        返回的 _pending_stats 内部字段在此 pop 掉，不暴露给客户端。
        """
        from hermes_kb.ingredients import canonicalize
        from hermes_kb.missing_stats import batch_increment_missing
        from hermes_kb.recipe_match import match_recipes
        from hermes_kb.recipe_stats import batch_increment_match_counts

        if not ingredients or not ingredients.strip():
            return {"full_match": [], "partial_match": []}

        raw_names = [s.strip() for s in ingredients.split(",") if s.strip()]
        user_ingredients = {canonicalize(n) for n in raw_names}

        result = match_recipes(user_ingredients)

        # A3-3: 统计写入移到 BackgroundTasks（批量、单次事务）
        pending = result.pop("_pending_stats", {}) or {}
        matched_doc_ids = pending.get("matched_doc_ids") or []
        missing_ingredients = pending.get("missing_ingredients") or []
        if matched_doc_ids:
            background_tasks.add_task(
                batch_increment_match_counts, matched_doc_ids
            )
        if missing_ingredients:
            background_tasks.add_task(
                batch_increment_missing, missing_ingredients
            )

        return result

    @app.get("/api/lab/hot", dependencies=[Depends(require_age_gate)])
    async def lab_hot(limit: int = 3, days: int = 30) -> dict[str, Any]:
        """热门配方（按 match_count 降序）。"""
        from hermes_kb.recipe_stats import get_hot_recipes

        limit = max(1, min(limit, 50))
        days = max(1, min(days, 365))
        items = get_hot_recipes(limit=limit, days=days)
        return {"items": items}

    @app.post("/api/lab/view/{doc_id}", dependencies=[Depends(require_age_gate)])
    async def lab_view(doc_id: str) -> dict[str, Any]:
        """查看配方详情时调用，view_count +1。"""
        from hermes_kb.recipe_stats import increment_view_count

        increment_view_count(doc_id)
        return {"doc_id": doc_id, "status": "ok"}

    # -----------------------------------------------------------------------
    # M4.1：实验室自动运营层
    # -----------------------------------------------------------------------
    @app.get("/api/lab/daily", dependencies=[Depends(require_age_gate)])
    async def lab_daily() -> dict[str, Any]:
        """每日推荐配方。"""
        from hermes_kb.daily_recipe import daily_recipe

        result = daily_recipe()
        return result or {"title": None, "reason": "empty"}

    @app.get("/api/lab/missing-stats", dependencies=[Depends(require_age_gate)])
    async def lab_missing_stats(limit: int = 10) -> dict[str, Any]:
        """缺失材料排行。"""
        from hermes_kb.missing_stats import get_top_missing

        limit = max(1, min(limit, 50))
        return {"items": get_top_missing(limit=limit)}

    @app.post("/api/lab/substitute", dependencies=[Depends(require_age_gate)])
    async def lab_save_substitute(req: dict[str, Any]) -> dict[str, Any]:
        """保存用户自定义替代关系。"""
        from hermes_kb.substitutes import add_user_substitute

        canonical = (req.get("canonical") or "").strip()
        substitute = (req.get("substitute") or "").strip()
        if not canonical or not substitute:
            raise HTTPException(status_code=400, detail="canonical 和 substitute 必填")
        add_user_substitute(canonical, substitute)
        return {"canonical": canonical, "substitute": substitute, "status": "ok"}

    @app.get("/api/lab/dashboard", dependencies=[Depends(require_age_gate)])
    async def lab_dashboard_endpoint() -> dict[str, Any]:
        """实验室运营看板聚合指标。"""
        from hermes_kb.lab_dashboard import get_lab_dashboard

        return get_lab_dashboard()

    # -----------------------------------------------------------------------
    # B6: 外部数据源同步 + 配方治理
    # -----------------------------------------------------------------------
    @app.post("/api/lab/sync", dependencies=[Depends(require_age_gate)])
    async def lab_sync(req: SyncRequest) -> dict[str, Any]:
        """同步外部数据源配方/替代材料。

        source 取值：
        - thecocktaildb: 全量拉取 TheCocktailDB 配方
        - iba_dataset: 拉取 IBA 官方金标准配方（100 款）
        - bar_assistant: 同步 bar-assistant 替代材料关系
        """
        if req.source == "thecocktaildb":
            from hermes_kb.thecocktaildb_sync import sync_thecocktaildb
            result = sync_thecocktaildb(limit=req.limit)
        elif req.source == "iba_dataset":
            from hermes_kb.iba_dataset_importer import sync_iba_dataset
            result = sync_iba_dataset()
        elif req.source == "bar_assistant":
            from hermes_kb.bar_assistant_sync import sync_bar_assistant_substitutes
            result = sync_bar_assistant_substitutes()
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported source: {req.source}. Supported: thecocktaildb / iba_dataset / bar_assistant",
            )
        return {"source": req.source, **result}

    @app.get("/api/lab/recipes", dependencies=[Depends(require_age_gate)])
    async def lab_recipes_list(
        source: str | None = None,
        verified: bool | None = None,
        hidden: bool | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """配方列表（支持按 source/verified/hidden/status 筛选）。"""
        from hermes_kb.recipe_filter import filter_recipes

        limit = max(1, min(limit, 500))
        items = filter_recipes(
            source=source, verified=verified, hidden=hidden, status=status, limit=limit
        )
        return {"items": items}

    @app.post("/api/lab/recipes/{doc_id}/verify", dependencies=[Depends(require_age_gate)])
    async def lab_verify_recipe(doc_id: str) -> dict[str, Any]:
        """审核通过配方（verified=True, status=published）。"""
        from hermes_kb.recipe_filter import verify_recipe

        if not verify_recipe(doc_id):
            raise HTTPException(status_code=404, detail=f"Recipe not found: {doc_id}")
        return {"doc_id": doc_id, "status": "ok"}

    @app.post("/api/lab/recipes/{doc_id}/hide", dependencies=[Depends(require_age_gate)])
    async def lab_hide_recipe(doc_id: str, hidden: bool = True) -> dict[str, Any]:
        """隐藏/取消隐藏配方。"""
        from hermes_kb.recipe_filter import hide_recipe

        if not hide_recipe(doc_id, hidden=hidden):
            raise HTTPException(status_code=404, detail=f"Recipe not found: {doc_id}")
        return {"doc_id": doc_id, "hidden": hidden}

    # -----------------------------------------------------------------------
    # M4.3：UGC 调酒研究室
    # -----------------------------------------------------------------------
    @app.post("/api/lab/recipes", dependencies=[Depends(require_age_gate)])
    async def lab_create_recipe(req: dict[str, Any]) -> dict[str, Any]:
        """创建 UGC 配方（draft 状态）。"""
        from hermes_kb.recipe_crud import create_recipe

        title = (req.get("title") or "").strip()
        content = req.get("content") or ""
        if not title or not content.strip():
            raise HTTPException(status_code=400, detail="title 和 content 必填")
        ingredients = req.get("ingredients") or []
        result = create_recipe(
            title=title,
            ingredients=ingredients,
            content=content,
            base_spirit=req.get("base_spirit", ""),
            difficulty=req.get("difficulty", "easy"),
            season=req.get("season"),
        )
        return result

    @app.put("/api/lab/recipes/{doc_id}", dependencies=[Depends(require_age_gate)])
    async def lab_update_recipe(doc_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """编辑 UGC 配方（仅 draft 状态）。"""
        from hermes_kb.recipe_crud import update_recipe

        ok = update_recipe(
            doc_id,
            title=req.get("title"),
            ingredients=req.get("ingredients"),
            content=req.get("content"),
            season=req.get("season"),
        )
        if not ok:
            raise HTTPException(status_code=400, detail="仅 draft 状态可编辑")
        return {"doc_id": doc_id, "status": "ok"}

    @app.post("/api/lab/recipes/{doc_id}/submit", dependencies=[Depends(require_age_gate)])
    async def lab_submit_recipe(doc_id: str) -> dict[str, Any]:
        """提交审核（draft → pending）。"""
        from hermes_kb.recipe_crud import submit_recipe

        ok = submit_recipe(doc_id)
        if not ok:
            raise HTTPException(status_code=400, detail="仅 draft 状态可提交")
        return {"doc_id": doc_id, "status": "pending"}

    @app.post("/api/lab/recipes/{doc_id}/approve", dependencies=[Depends(require_age_gate)])
    async def lab_approve_recipe(doc_id: str) -> dict[str, Any]:
        """审核通过（pending → published）。"""
        from hermes_kb.recipe_crud import approve_recipe

        ok = approve_recipe(doc_id)
        if not ok:
            raise HTTPException(status_code=400, detail="仅 pending 状态可审核")
        return {"doc_id": doc_id, "status": "ok"}

    @app.post("/api/lab/recipes/{doc_id}/reject", dependencies=[Depends(require_age_gate)])
    async def lab_reject_recipe(doc_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """审核驳回（pending → rejected）。"""
        from hermes_kb.recipe_crud import reject_recipe

        reason = req.get("reason", "")
        ok = reject_recipe(doc_id, reason=reason)
        if not ok:
            raise HTTPException(status_code=400, detail="仅 pending 状态可驳回")
        return {"doc_id": doc_id, "status": "rejected", "reason": reason}

    @app.get("/api/lab/recipes/{doc_id}/variants", dependencies=[Depends(require_age_gate)])
    async def lab_recipe_variants(doc_id: str) -> dict[str, Any]:
        """查看配方的变体列表。"""
        from hermes_kb.recipe_variants import get_variants

        items = get_variants(doc_id)
        return {"items": items, "count": len(items)}

    @app.post("/api/lab/recipes/{doc_id}/variant", dependencies=[Depends(require_age_gate)])
    async def lab_create_variant(doc_id: str, req: dict[str, Any]) -> dict[str, Any]:
        """创建变体（基于 doc_id 配方创作新配方并关联）。"""
        from hermes_kb.recipe_crud import create_recipe
        from hermes_kb.recipe_variants import create_variant_link

        variant_doc_id = req.get("variant_doc_id")
        variant_note = req.get("variant_note", "")
        if not variant_doc_id:
            raise HTTPException(status_code=400, detail="variant_doc_id 必填")
        ok = create_variant_link(doc_id, variant_doc_id, variant_note)
        if not ok:
            raise HTTPException(status_code=400, detail="关联已存在或配方不存在")
        return {"base_doc_id": doc_id, "variant_doc_id": variant_doc_id, "status": "ok"}

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

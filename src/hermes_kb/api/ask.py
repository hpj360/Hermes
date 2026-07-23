"""问答端点：ask/ask-stream/history/feedback/seed/seed-recipes。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import select

from hermes_kb.api.deps import get_importer, get_rag, require_age_gate, require_auth
from hermes_kb.database import get_session
from hermes_kb.models import Document, QueryLog
from hermes_kb.rag import ImportService, RAGEngine
from hermes_kb.seed import SEED_DOCS
from hermes_kb.seed_recipes import SEED_RECIPES

router = APIRouter(prefix="/api", tags=["ask"])


class AskReq(BaseModel):
    query: str = Field(..., max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class FeedbackReq(BaseModel):
    feedback: int = Field(..., ge=-1, le=1)  # 1=up / -1=down / 0=none


@router.post("/ask", dependencies=[Depends(require_auth), Depends(require_age_gate)])
async def ask(req: AskReq, rag: RAGEngine = Depends(get_rag)) -> dict[str, Any]:
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")
    result = rag.answer(req.query, top_k=req.top_k)
    return result.to_dict()


@router.post("/ask/stream", dependencies=[Depends(require_auth), Depends(require_age_gate)])
async def ask_stream(
    req: AskReq, rag: RAGEngine = Depends(get_rag)
) -> StreamingResponse:
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


# 历史 + 反馈
@router.get("/history", dependencies=[Depends(require_auth)])
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


@router.post("/feedback/{log_id}", dependencies=[Depends(require_auth)])
async def feedback(log_id: int, req: FeedbackReq) -> dict[str, Any]:
    with get_session() as session:
        log = session.get(QueryLog, log_id)
        if not log:
            raise HTTPException(status_code=404, detail="问答记录不存在")
        log.feedback = req.feedback
        session.add(log)
        session.commit()
        return {"id": log_id, "feedback": req.feedback, "status": "ok"}


# 种子数据
@router.post("/seed", dependencies=[Depends(require_auth)])
async def seed(
    importer: ImportService = Depends(get_importer),
) -> dict[str, Any]:
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


@router.post("/seed/recipes", dependencies=[Depends(require_auth)])
async def seed_recipes(
    importer: ImportService = Depends(get_importer),
) -> dict[str, Any]:
    """M3：导入 IBA 配方种子数据（幂等）。"""
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

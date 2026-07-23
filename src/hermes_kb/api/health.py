"""健康检查端点。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from sqlmodel import select

from hermes_kb.config import get_settings
from hermes_kb.database import get_session
from hermes_kb.models import Document

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    doc_count = 0
    try:
        with get_session() as session:
            doc_count = len(session.exec(select(Document)).all())
    except Exception:
        doc_count = 0
    settings = get_settings()
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

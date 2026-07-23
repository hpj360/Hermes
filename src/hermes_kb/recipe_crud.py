"""UGC 配方 CRUD + 审核状态机（M4.3）。

状态机：draft → pending → published / rejected
- draft: 用户编辑中，仅自己可见
- pending: 提交审核，进入审核队列
- published: 审核通过，进实验室匹配（verified=True）
- rejected: 审核驳回，附驳回理由
"""
from __future__ import annotations

import json
from typing import Any

from sqlmodel import select

from hermes_kb.database import get_session
from hermes_kb.models import Document
from hermes_kb.rag import ImportService


def create_recipe(
    title: str,
    ingredients: list[str],
    content: str,
    base_spirit: str = "",
    difficulty: str = "easy",
    season: str | None = None,
    importer: ImportService | None = None,
) -> dict[str, Any]:
    """创建 UGC 配方（draft 状态）。

    Args:
        importer: 可选的 ImportService 实例（由 router 通过 app.state 注入）。
                  为 None 时内部新建（保持向后兼容）。

    Returns:
        {doc_id, status, title}
    """
    importer = importer or ImportService()
    result = importer.import_text(
        content=content,
        title=title,
        source_type="ugc",
        file_type="md",
    )
    doc_id = result.get("doc_id")
    if doc_id:
        with get_session() as session:
            doc = session.get(Document, doc_id)
            if doc:
                doc.category = "recipe"
                doc.source = "ugc"
                doc.source_id = f"ugc-{doc_id}"
                doc.verified = False
                doc.status = "draft"
                if season:
                    doc.season = season
                session.add(doc)
                session.commit()
    return {"doc_id": doc_id, "status": "draft", "title": title}


def update_recipe(
    doc_id: str,
    title: str | None = None,
    ingredients: list[str] | None = None,
    content: str | None = None,
    season: str | None = None,
) -> bool:
    """编辑配方（仅 draft 状态可编辑）。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc or doc.status != "draft":
            return False
        if title is not None:
            doc.title = title
        if content is not None:
            doc.content = content
        if season is not None:
            doc.season = season
        # 注意：ingredients 更新需重新分片，此处仅更新 content
        # 若需更新 ingredients，应重新 import_text
        session.add(doc)
        session.commit()
        return True


def submit_recipe(doc_id: str) -> bool:
    """提交审核（draft → pending）。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc or doc.status != "draft":
            return False
        doc.status = "pending"
        session.add(doc)
        session.commit()
        return True


def approve_recipe(doc_id: str) -> bool:
    """审核通过（pending → published, verified=True）。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc or doc.status != "pending":
            return False
        doc.status = "published"
        doc.verified = True
        session.add(doc)
        session.commit()
        return True


def reject_recipe(doc_id: str, reason: str = "") -> bool:
    """审核驳回（pending → rejected）。"""
    with get_session() as session:
        doc = session.get(Document, doc_id)
        if not doc or doc.status != "pending":
            return False
        doc.status = "rejected"
        doc.verified = False
        # reason 存入 Document.meta（JSON 字段），key=reject_reason
        if reason:
            meta = json.loads(doc.meta) if doc.meta else {}
            meta["reject_reason"] = reason
            doc.meta = json.dumps(meta, ensure_ascii=False)
        session.add(doc)
        session.commit()
        return True


def list_pending_recipes(limit: int = 20) -> list[dict[str, Any]]:
    """列出待审核配方。"""
    with get_session() as session:
        docs = session.exec(
            select(Document)
            .where(Document.category == "recipe", Document.status == "pending")
            .limit(limit)
        ).all()
        return [
            {
                "doc_id": d.doc_id,
                "title": d.title,
                "source": d.source,
                "status": d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]

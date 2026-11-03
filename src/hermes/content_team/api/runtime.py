"""运行时装配 API：内容 agent 会话的场景化 skill 目录 + 分层知识目录。"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hermes.content_team.agent_context import assemble_skill_context
from hermes.content_team.knowledge_search import search_knowledge
from hermes.skills import discover_knowledge

router = APIRouter()


class SkillCatalogEntry(BaseModel):
    """Skill 目录条目（Level-1 Discovery）。"""

    name: str
    description: str


class SkillCatalogResponse(BaseModel):
    """Skill 目录响应体。"""

    scenario: str | None
    total: int
    skills: list[SkillCatalogEntry]


@router.get("/skills", response_model=SkillCatalogResponse)
async def get_skill_catalog(
    scenario: str | None = None,
) -> dict[str, Any]:
    """返回场景化 skill 目录（默认按环境变量/默认场景装配）。

    ``scenario`` 显式传入时优先于环境变量；``none`` 表示不过滤。
    """
    try:
        return assemble_skill_context(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# 知识目录（OpenViking L0/L1/L2 吸收：分层按需加载）
# ---------------------------------------------------------------------------


class KnowledgeEntry(BaseModel):
    """知识条目（按 load 层级裁剪）。"""

    name: str
    domain: str
    title: str
    type: str = "reference"
    summary: str | None = None  # L0
    overview: str | None = None  # L1
    content: str | None = None  # L2（仅 load=l2 返回）


class KnowledgeCatalogResponse(BaseModel):
    """知识目录响应体。"""

    domain: str | None
    load: str
    total: int
    entries: list[KnowledgeEntry]


_LOAD_RE = re.compile(r"^(l0|l1|l2)$", re.IGNORECASE)


@router.get("/knowledge", response_model=KnowledgeCatalogResponse)
async def get_knowledge_catalog(
    domain: str | None = None,
    load: str = "l0",
) -> KnowledgeCatalogResponse:
    """分层知识目录：l0=摘要目录、l1=概览、l2=全文（按需加载）。"""
    load_norm = load.lower()
    if not _LOAD_RE.match(load_norm):
        raise HTTPException(status_code=400, detail=f"load 仅支持 l0/l1/l2: {load}")
    entries = discover_knowledge(domain)
    out: list[KnowledgeEntry] = []
    for e in entries:
        item = KnowledgeEntry(
            name=e["name"],
            domain=e["domain"],
            title=e["title"],
            type=e["type"],
            summary=e["summary"] or None,
        )
        if load_norm in ("l1", "l2"):
            item.overview = e["overview"] or None
        if load_norm == "l2":
            item.content = e["content"]
        out.append(item)
    return KnowledgeCatalogResponse(
        domain=domain, load=load_norm, total=len(out), entries=out
    )


class KnowledgeDirectoryHit(BaseModel):
    """目录命中（目录递归检索的第一层）。"""

    domain: str
    doc_count: int
    score: float
    top_doc: str


class KnowledgeDocHit(BaseModel):
    """条目命中。"""

    name: str
    domain: str
    title: str
    type: str
    score: float
    summary: str | None = None


class KnowledgeSearchTrace(BaseModel):
    """检索轨迹（可观察性）。"""

    strategy: str
    indexed_docs: int
    query_tokens: int
    elapsed_ms: float
    error: str | None = None


class KnowledgeSearchResponse(BaseModel):
    """知识检索响应体（目录优先 + 轨迹）。"""

    directories: list[KnowledgeDirectoryHit]
    docs: list[KnowledgeDocHit]
    trace: KnowledgeSearchTrace


@router.get("/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge_endpoint(
    q: str,
    domain: str | None = None,
    top: int = 5,
) -> KnowledgeSearchResponse:
    """知识检索：TF-IDF 加权（L0×3/L1×2/L2×1）+ 目录递归聚合 + 轨迹。"""
    if len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="查询过短（>=2 字符）")
    if top < 1 or top > 20:
        raise HTTPException(status_code=400, detail="top 须在 1-20 之间")
    entries = discover_knowledge(domain)
    result = search_knowledge(q, entries, top_docs=top)
    return KnowledgeSearchResponse(
        directories=[
            KnowledgeDirectoryHit(
                domain=d["domain"],
                doc_count=d["doc_count"],
                score=d["score"],
                top_doc=d["top_doc"],
            )
            for d in result["directories"]
        ],
        docs=[
            KnowledgeDocHit(
                name=d["name"],
                domain=d["domain"],
                title=d["title"],
                type=d["type"],
                score=d["score"],
                summary=d.get("summary") or None,
            )
            for d in result["docs"]
        ],
        trace=KnowledgeSearchTrace(**result["trace"]),
    )

"""混合检索：BM25（FTS5）+ 向量（sqlite-vec ANN，降级 Python 余弦）+ RRF 融合。

中文 BM25 分词策略（P0 修复关键）：
- 标点切段
- 中文片段 bigram + 单字
- 英文保留原词
- 用 OR 查询，FTS5 unicode61 分词器对中文按字索引，bigram 能命中

向量检索（E3）：
- 优先 sqlite-vec vec0 ANN 索引（chunk_vec_ann），O(log n) 近似检索
- 降级条件：sqlite-vec 不可用 / 扩展加载失败 / 维度不匹配 / ANN 查询异常
- 降级路径：Python 余弦相似度全表扫描（chunk_vec，受 vector_scan_limit 约束）
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass

from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from hermes_kb.config import get_settings
from hermes_kb.database import _SQLITE_VEC_AVAILABLE, get_engine, get_session
from hermes_kb.embedding import EmbeddingService
from hermes_kb.models import Chunk, Document

logger = logging.getLogger(__name__)


@dataclass
class RetrievalHit:
    """检索命中。"""

    chunk_rowid: int
    doc_id: str
    title: str
    text: str
    score: float
    source: str  # bm25 / vector / rrf


def _cosine(a: list[float], b: list[float]) -> float:
    """纯 Python 余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)


def reciprocal_rank_fusion(
    bm25_hits: list[RetrievalHit],
    vec_hits: list[RetrievalHit],
    k: int = 60,
) -> list[RetrievalHit]:
    """RRF 融合两路排序。"""
    scores: dict[int, float] = {}
    meta: dict[int, RetrievalHit] = {}
    for rank, h in enumerate(bm25_hits, start=1):
        scores[h.chunk_rowid] = scores.get(h.chunk_rowid, 0.0) + 1.0 / (k + rank)
        meta[h.chunk_rowid] = h
    for rank, h in enumerate(vec_hits, start=1):
        scores[h.chunk_rowid] = scores.get(h.chunk_rowid, 0.0) + 1.0 / (k + rank)
        meta[h.chunk_rowid] = h
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    result: list[RetrievalHit] = []
    for rowid, sc in ordered:
        h = meta[rowid]
        result.append(
            RetrievalHit(
                chunk_rowid=h.chunk_rowid,
                doc_id=h.doc_id,
                title=h.title,
                text=h.text,
                score=sc,
                source="rrf",
            )
        )
    return result


def _tokenize_query_for_fts(q: str) -> str:
    """把中文 query 转成 FTS5 OR 查询字符串。

    策略：标点切段 → 中文片段 bigram + 单字 → 英文保留原词。
    """
    q = q.strip().replace('"', " ")
    if not q:
        return ""
    segments = re.split(r"[\s,，。！？、；：""''（）()【】\[\]{}]+", q)
    segments = [s for s in segments if s]
    if not segments:
        return ""
    terms: list[str] = []
    for seg in segments:
        if re.fullmatch(r"[A-Za-z0-9\-_]+", seg):
            terms.append(seg)
            continue
        # 中文片段：bigram + 单字
        if len(seg) == 1:
            terms.append(seg)
            continue
        for i in range(len(seg) - 1):
            terms.append(seg[i : i + 2])
        # 单字也加入（提升短 query 召回）
        for ch in seg:
            terms.append(ch)
    # 去重保序
    seen: set[str] = set()
    unique_terms: list[str] = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            unique_terms.append(t)
    if not unique_terms:
        return ""
    # 用 OR 查询，每个 term 用双引号包裹（防止 FTS5 语法字符干扰）
    return " OR ".join(f'"{t}"' for t in unique_terms)


class HybridRetriever:
    """混合检索器。"""

    def __init__(self, embedding: EmbeddingService | None = None) -> None:
        self.embedding = embedding or EmbeddingService()

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievalHit]:
        """检索 top_k 条命中。空 query 早期返回（避免伪命中）。"""
        if not query or not query.strip():
            return []
        k = top_k or get_settings().top_k
        bm25_hits = self._bm25(query, k)
        vec_hits = self._vector(query, k)
        fused = reciprocal_rank_fusion(bm25_hits, vec_hits, k=get_settings().rrf_k)
        return fused[:k]

    def _bm25(self, query: str, k: int) -> list[RetrievalHit]:
        """FTS5 BM25 检索（中文 bigram 分词）。"""
        fts_query = _tokenize_query_for_fts(query)
        if not fts_query:
            return []
        eng = get_engine()
        try:
            with eng.connect() as conn:
                rows = conn.execute(
                    sa_text(
                        "SELECT chunk_rowid, doc_id, text, bm25(chunks_fts) AS score "
                        "FROM chunks_fts WHERE chunks_fts MATCH :q "
                        "ORDER BY score LIMIT :k"
                    ),
                    {"q": fts_query, "k": k},
                ).fetchall()
        except SQLAlchemyError as exc:
            logger.warning("BM25 FTS5 query failed (query=%r): %s", fts_query, exc)
            return []
        hits: list[RetrievalHit] = []
        # FTS5 bm25() 越小越好（距离），取负值转为"越大越好"
        for row in rows:
            rowid = int(row[0])
            doc_id = row[1]
            text = row[2] or ""
            raw_score = float(row[3]) if row[3] is not None else 0.0
            score = -raw_score  # 转换为越大越好
            title = self._doc_title(doc_id)
            hits.append(
                RetrievalHit(
                    chunk_rowid=rowid,
                    doc_id=doc_id,
                    title=title,
                    text=text,
                    score=score,
                    source="bm25",
                )
            )
        return hits

    def _vector(self, query: str, k: int) -> list[RetrievalHit]:
        """向量检索（优先 sqlite-vec ANN，降级 Python 余弦扫描）。"""
        qvec = self.embedding.embed_one(query)
        if not qvec or all(v == 0.0 for v in qvec):
            return []
        # 优先 ANN 索引（sqlite-vec vec0）
        if _SQLITE_VEC_AVAILABLE:
            try:
                hits = self._vector_ann(qvec, k)
                if hits:
                    return hits
                # ANN 返回空：索引可能未填充，降级到全表扫描兜底
            except Exception as exc:
                logger.warning(
                    "ANN query failed, falling back to Python cosine scan: %s", exc
                )
        # 降级：Python 余弦相似度全表扫描
        return self._vector_scan(qvec, k)

    def _vector_ann(self, qvec: list[float], k: int) -> list[RetrievalHit]:
        """sqlite-vec vec0 ANN 检索。

        查询返回 (rowid, distance)，distance 越小越相似（欧氏距离）。
        维度不匹配（query 维度 != 表定义维度）会抛 OperationalError，
        由调用方捕获后降级到 Python 余弦扫描。
        """
        import sqlite_vec

        qbytes = sqlite_vec.serialize_float32(qvec)
        eng = get_engine()
        with eng.connect() as conn:
            rows = conn.execute(
                sa_text(
                    "SELECT rowid, distance FROM chunk_vec_ann "
                    "WHERE embedding MATCH :q ORDER BY distance LIMIT :k"
                ),
                {"q": qbytes, "k": k},
            ).fetchall()
        if not rows:
            return []
        rowids = [int(r[0]) for r in rows]
        dist_map = {int(r[0]): float(r[1]) for r in rows}
        # 批量查元数据（消除 N+1）；跳过已删除 chunk（ANN 索引残留 rowid）
        chunk_meta: dict[int, tuple[str, str]] = {}  # rowid -> (doc_id, text)
        title_map: dict[str, str] = {}
        try:
            with get_session() as session:
                chunks = session.exec(
                    select(Chunk).where(Chunk.id.in_(rowids))
                ).all()
                chunk_meta = {c.id: (c.doc_id, c.text) for c in chunks}
                doc_ids = list({d_id for d_id, _ in chunk_meta.values()})
                if doc_ids:
                    docs = session.exec(
                        select(Document).where(Document.doc_id.in_(doc_ids))
                    ).all()
                    title_map = {d.doc_id: d.title for d in docs}
        except SQLAlchemyError as exc:
            logger.warning(
                "vector ANN metadata fetch failed (rowids=%s): %s", rowids, exc
            )
        hits: list[RetrievalHit] = []
        for rowid in rowids:
            meta = chunk_meta.get(rowid)
            if meta is None:
                # chunk 已删除（ANN 索引残留），跳过
                continue
            doc_id, text = meta
            dist = dist_map.get(rowid, 0.0)
            # distance 越小越相似；转为 similarity-like score（越大越好）
            score = 1.0 / (1.0 + max(dist, 0.0))
            hits.append(
                RetrievalHit(
                    chunk_rowid=rowid,
                    doc_id=doc_id,
                    title=title_map.get(doc_id, doc_id),
                    text=text,
                    score=score,
                    source="vector",
                )
            )
        return hits

    def _vector_scan(self, qvec: list[float], k: int) -> list[RetrievalHit]:
        """Python 余弦相似度全表扫描（fallback，受 vector_scan_limit 约束）。"""
        eng = get_engine()
        scan_limit = get_settings().vector_scan_limit
        try:
            with eng.connect() as conn:
                rows = conn.execute(
                    sa_text(
                        "SELECT chunk_rowid, doc_id, vec FROM chunk_vec LIMIT :lim"
                    ),
                    {"lim": scan_limit},
                ).fetchall()
        except SQLAlchemyError as exc:
            logger.warning("vector scan failed: %s", exc)
            return []
        scored: list[tuple[float, int, str]] = []
        for row in rows:
            rowid = int(row[0])
            doc_id = row[1]
            try:
                vec = json.loads(row[2])
            except (json.JSONDecodeError, TypeError):
                continue
            sim = _cosine(qvec, vec)
            scored.append((sim, rowid, doc_id))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:k]
        if not top:
            return []

        # 批量查元数据（消除 N+1，A3-1）
        rowids = [t[1] for t in top]
        doc_ids = list({t[2] for t in top})
        chunk_map: dict[int, str] = {}
        title_map: dict[str, str] = {}
        try:
            with get_session() as session:
                chunks = session.exec(
                    select(Chunk).where(Chunk.id.in_(rowids))
                ).all()
                chunk_map = {c.id: c.text for c in chunks}
                docs = session.exec(
                    select(Document).where(Document.doc_id.in_(doc_ids))
                ).all()
                title_map = {d.doc_id: d.title for d in docs}
        except SQLAlchemyError as exc:
            logger.warning("vector metadata fetch failed (rowids=%s): %s", rowids, exc)

        hits: list[RetrievalHit] = []
        for sim, rowid, doc_id in top:
            hits.append(
                RetrievalHit(
                    chunk_rowid=rowid,
                    doc_id=doc_id,
                    title=title_map.get(doc_id, doc_id),
                    text=chunk_map.get(rowid, ""),
                    score=sim,
                    source="vector",
                )
            )
        return hits

    def _doc_title(self, doc_id: str) -> str:
        try:
            with get_session() as session:
                d = session.get(Document, doc_id)
                return d.title if d else doc_id
        except SQLAlchemyError as exc:
            logger.warning("doc title fetch failed (doc_id=%s): %s", doc_id, exc)
            return doc_id

    def _chunk_meta(self, rowid: int, doc_id: str) -> tuple[str, str]:
        try:
            with get_session() as session:
                c = session.get(Chunk, rowid)
                text = c.text if c else ""
                d = session.get(Document, doc_id)
                title = d.title if d else doc_id
                return text, title
        except SQLAlchemyError as exc:
            logger.warning("chunk meta fetch failed (rowid=%s, doc_id=%s): %s", rowid, doc_id, exc)
            return "", doc_id

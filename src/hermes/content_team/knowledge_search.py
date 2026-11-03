"""知识条目检索（吸收 OpenViking：目录递归检索 + 检索轨迹可观察）。

零依赖检索层，复用 workbench.memory 的确定性打分函数：
- weighted TF-IDF + 余弦（summary×3 / overview×2 / 正文×1 权重）
- **目录优先**：先按 domain 聚合出高分目录，再在目录内展示命中条目
- **轨迹**：返回每目录/每条目得分与策略说明，检索可解释可调试
"""
from __future__ import annotations

import time
from typing import Any

from hermes.workbench.memory import (
    _compute_tfidf,
    _cosine_similarity,
    _tokenize,
)


def _weighted_text(entry: dict[str, Any]) -> str:
    """按层级加权拼接：L0×3 + L1×2 + L2×1。"""
    parts: list[str] = []
    if entry.get("summary"):
        parts.extend([entry["summary"]] * 3)
    if entry.get("overview"):
        parts.extend([entry["overview"]] * 2)
    if entry.get("content"):
        parts.append(str(entry["content"]))
    return "\n".join(parts)


def search_knowledge(
    query: str,
    entries: list[dict[str, Any]],
    *,
    top_docs: int = 5,
) -> dict[str, Any]:
    """知识条目检索：目录先行 + 逐条得分 + 轨迹。

    idf 以「全部条目 + 查询」同库计算，query 与 doc 向量同尺度。

    :returns: {"directories", "docs", "trace"}
    """
    t0 = time.perf_counter()
    if not query.strip():
        return {
            "directories": [],
            "docs": [],
            "trace": {
                "strategy": "tfidf_weighted",
                "indexed_docs": len(entries),
                "error": "empty query",
            },
        }

    q_tokens = _tokenize(query.lower())
    doc_tokens = [
        _tokenize(_weighted_text(e).lower())
        for e in entries
    ]
    vectors = _compute_tfidf([*doc_tokens, q_tokens])
    doc_vectors, q_vec = vectors[:-1], vectors[-1]

    scored: list[dict[str, Any]] = []
    for entry, doc_vec in zip(entries, doc_vectors):
        sim = _cosine_similarity(q_vec, doc_vec)
        if sim > 0:
            scored.append({**entry, "score": round(sim, 4)})

    scored.sort(key=lambda d: d["score"], reverse=True)
    top = scored[:top_docs]

    # 目录聚合：目录分 = 该目录内最高条目分（目录递归检索的简化形态）
    by_domain: dict[str, list[dict[str, Any]]] = {}
    for d in top:
        by_domain.setdefault(d["domain"], []).append(d)
    directories = [
        {
            "domain": dom,
            "doc_count": len(items),
            "score": max(i["score"] for i in items),
            "top_doc": items[0]["name"],
        }
        for dom, items in sorted(
            by_domain.items(),
            key=lambda kv: max(i["score"] for i in kv[1]),
            reverse=True,
        )
    ]

    elapsed = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "directories": directories,
        "docs": top,
        "trace": {
            "strategy": "tfidf_weighted(directory_first)",
            "indexed_docs": len(entries),
            "query_tokens": len(q_tokens),
            "elapsed_ms": elapsed,
        },
    }

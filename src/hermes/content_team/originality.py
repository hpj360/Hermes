"""机器原创性检查（字面层，stdlib-only，零外部依赖）。

从 xuboboo 原创性思路内化的最小可用版：
- **字面查**：归一化文本（只留中英数字）→ 双字组（bigram）Jaccard 相似度
  + 最长公共连续段（difflib）。
- 参考库：库内已存内容（contents）与选题描述（topics），避免跨条自抄/
  与选题库直接复读。

边界（诚实声明）：
- 纯函数层，无 embedding 语义查、无图片 pHash——语义/图片层暂不覆盖，
  发布前仍须配合 banned-words-check skill 中的人工"原创性三查"。
- 阈值 ``min_similarity`` 默认 0.2 为保守起步值，接入真实参考库后应校准。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_TEXT_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")

# 小于该归一化长度的文本不参与比对（太短而无判别力）
MIN_TOKEN_LEN = 12
MAX_RESULTS = 5


@dataclass(frozen=True)
class OriginalityRef:
    """原创性检查的一条参考（比对对象）。"""

    ref_type: str  # "content" | "topic"
    ref_id: str
    ref_title: str
    text: str


@dataclass(frozen=True)
class OriginalityHit:
    """一次命中：与某参考文本相似度过高。"""

    ref_type: str
    ref_id: str
    ref_title: str
    similarity: float
    longest_common_run: str


def _normalize(text: str) -> str:
    """去空白/标点、小写化，只保留中英数字符。"""
    return "".join(_TEXT_RE.findall((text or "").lower()))


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _longest_common_run(a: str, b: str) -> str:
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    m = matcher.find_longest_match(0, len(a), 0, len(b))
    return a[m.a : m.a + m.size]


def check_originality(
    title: str,
    body: str,
    references: list[OriginalityRef],
    *,
    min_similarity: float = 0.2,
) -> list[OriginalityHit]:
    """对标题+正文做字面查重，返回相似度超阈值的参考（降序，最多 5 条）。"""
    mine = _normalize(f"{title}{body}")
    if len(mine) < MIN_TOKEN_LEN:
        return []

    mine_grams = _bigrams(mine)
    hits: list[OriginalityHit] = []
    for ref in references:
        other = _normalize(f"{ref.ref_title}{ref.text}")
        if len(other) < MIN_TOKEN_LEN:
            continue
        other_grams = _bigrams(other)
        inter = len(mine_grams & other_grams)
        union = len(mine_grams | other_grams)
        if union == 0:
            continue
        sim = inter / union
        if sim >= min_similarity:
            run = _longest_common_run(mine, other)
            hits.append(
                OriginalityHit(
                    ref_type=ref.ref_type,
                    ref_id=ref.ref_id,
                    ref_title=ref.ref_title,
                    similarity=round(sim, 4),
                    longest_common_run=run,
                )
            )
    hits.sort(key=lambda h: h.similarity, reverse=True)
    return hits[:MAX_RESULTS]

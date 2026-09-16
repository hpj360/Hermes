"""GEPA 变异引擎：反思式变异（P1）+ 冻结区（P3）。

来源：大淘宝技术《Agent优化之GEPA》学习落地（ICLR 2026 GEPA 论文工程化）。
两个模块解决进化方向性与进化安全两类问题：

- 反思式变异（P1）：把"模型答错了"翻译成"prompt 哪条规则有问题"的
  归因反馈，注入变体生成 prompt——自由探索变定向改写。
- 冻结区（P3）：agent 定义拆 frozen/mutable 两区，变异只发生在
  mutable 区，冻结块（硬约束/工具协议/输出 Schema）结构性不可删——
  事后扣分防不住 reward hacking（删约束往往能提分）。

设计约束：stdlib-only、纯函数（除标注外）、不依赖 Orchestrator。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "FROZEN_BEGIN",
    "FROZEN_END",
    "build_reflection_feedback",
    "extract_failure_summary",
    "frozen_intact",
    "has_frozen_zone",
    "reassemble_with_frozen",
    "split_frozen_mutable",
]


# ── P3: 冻结区 ───────────────────────────────────────────────────────

FROZEN_BEGIN = "<!-- GEPA:FROZEN:BEGIN -->"
FROZEN_END = "<!-- GEPA:FROZEN:END -->"

# 冻结块匹配（DOTALL：冻结内容可跨行）。容忍标记周围空白。
_FROZEN_RE = re.compile(
    re.escape(FROZEN_BEGIN) + r"\s*(.*?)" + re.escape(FROZEN_END),
    re.DOTALL,
)


def has_frozen_zone(text: str) -> bool:
    """text 是否含至少一个冻结块。"""
    return bool(_FROZEN_RE.search(text))


def split_frozen_mutable(text: str) -> tuple[str, str]:
    """拆分 agent 定义为 (frozen, mutable) 两部分。

    frozen = 所有冻结块内容（不含标记，按出现顺序拼接）；
    mutable = 冻结块以外的全部文本（标记移除后）。
    无冻结块时返回 ("", text)。
    """
    frozen_parts = [m.group(1).strip() for m in _FROZEN_RE.finditer(text)]
    mutable = _FROZEN_RE.sub("", text).strip()
    frozen = "\n\n".join(p for p in frozen_parts if p)
    return frozen, mutable


def reassemble_with_frozen(base_text: str, new_mutable: str) -> str:
    """用 new_mutable 重建 agent 定义，冻结块原位保留。

    语义：冻格外内容是**一个逻辑可变区**，整体被 new_mutable 接管
    （放置在首个可变段位置，其余可变段丢弃）；冻结块（含标记）按
    原顺序原位保留。这保证无论 LLM 返回什么，冻结内容逐字不动。
    """
    out: list[str] = []
    placed = False
    for m in _FROZEN_RE.finditer(base_text):
        if not placed:
            out.append(new_mutable.strip())
            placed = True
        # 首个可变段之后的其余可变段由 new_mutable 整体接管，丢弃。
        out.append(m.group(0))  # 冻结块（含标记）逐字保留
    if not placed:  # 无冻结块：整体可变
        out.append(new_mutable.strip())
    return "\n\n".join(p for p in out if p)


def frozen_intact(base_text: str, candidate_text: str) -> bool:
    """所有冻结块是否在 candidate_text 中逐字保留（含标记）。

    双保险：reassemble 已结构性保留，此谓词供事后审计/测试断言——
    任何调用方手工拼接的候选也必须过这一关。
    """
    blocks = [m.group(0) for m in _FROZEN_RE.finditer(base_text)]
    return all(b in candidate_text for b in blocks)


# ── P1: 反思式变异 ────────────────────────────────────────────────────

# 反馈块进入 LLM prompt 的失败条目上限（防 prompt 膨胀——教训来自
# 文章 6.2：反思上下文越长，生成变体越倾向堆补丁）。
_FEEDBACK_MAX_ITEMS = 10


def extract_failure_summary(results: list[Any]) -> list[str]:
    """从上一轮 VariantResult 列表提取去重后的失败条目。

    failure_items 已是结构化失败 key（role: file|type，来自
    rubric.parse_structured_failures 单一事实源），此处仅去重保序。
    """
    seen: set[str] = set()
    items: list[str] = []
    for r in results:
        for item in getattr(r, "failure_items", None) or []:
            if item not in seen:
                seen.add(item)
                items.append(item)
    return items


def build_reflection_feedback(
    results: list[Any],
    benchmark_task: str,
    *,
    max_items: int = _FEEDBACK_MAX_ITEMS,
) -> str:
    """构建归因反馈块（P1 反思式变异的定向信号）。

    三段式（对齐文章 feedback.py 的三问归因，离线可计算部分）：
    1. 失败证据：去重后的结构化失败条目（错误定位）
    2. 归因要求：要求变体生成针对失败模式改写具体规则（Prompt 归因）
    3. 改进约束：每个变体必须声明针对哪些失败（改进建议闭环）

    无失败数据返回空串——调用方据此退化为自由探索（不注入空块）。
    """
    items = extract_failure_summary(results)[:max_items]
    if not items:
        return ""
    lines = [
        "## 上一轮失败证据（定向改进目标，反思式变异输入）",
        f"Benchmark: {benchmark_task}",
        "",
        "结构化失败条目（role: file|failure_type）：",
    ]
    lines.extend(f"- {item}" for item in items)
    lines += [
        "",
        "生成要求：",
        "1. 归因：把上述失败翻译为当前 agent 定义的哪条规则导致或未能阻止该错误。",
        "2. 定向改写：每个变体必须针对至少一条失败模式修改具体规则，",
        "   不做与失败证据无关的风格性改动。",
        "3. 声明：每个变体的 description 中注明它针对哪些失败条目。",
    ]
    return "\n".join(lines)

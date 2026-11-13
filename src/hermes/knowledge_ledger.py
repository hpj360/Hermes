"""项目知识账本：失败按知识层归因 + 经验的版本化撤回。

来源：腾讯云 TencentDB Agent Memory 团队《不只是 Memory：Ontology 如何让
Coding Agent 越用越懂项目？》。文章两条主张在这里落成代码：

1. **失败要归因到层，不能统一归为「模型不够聪明」**
   同样表现为失败，原因可能是工程关系没找到、业务含义理解错、旧经验
   条件不匹配、或已知道约束却没执行检查——四者对应完全不同的修法。
   见 ``attribute_failures`` / ``format_attribution_section``。

2. **知识必须能纠正，而不只是追加**
   文章的反向能力要求：能收紧范围、拆开误合并的概念、**撤回**不成立
   的结论。一次「撤回」应让依赖它的陈述进入待复核，而不是直接删除
   ——原事件保留，但不能继续以已确认规则指导新任务。
   见 ``KnowledgeLedger``。

与 ``tool_recovery`` 的分工：后者诊断**工具执行层**的失败（输出截断、
权限不足、语法错误），回答「这次调用怎么失败的」；本模块回答「这个
失败暴露的是哪一层项目知识缺失」，两者的证据来源与修复动作都不同。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class KnowledgeLayer(str, Enum):
    """项目知识的四个层（第 4 层「本体」不单列，体现在语义层与约束中）。"""

    ENGINEERING = "engineering"
    SEMANTIC = "semantic"
    EXPERIENCE = "experience"
    EXECUTION = "execution"
    UNATTRIBUTED = "unattributed"


# 各层的信号词。命中即作为**候选证据**，不是判决——归因结果带 confidence，
# 无信号时返回 UNATTRIBUTED 并要求补充区分性观察，而不是硬套一个通用模板。
_LAYER_SIGNALS: list[tuple[KnowledgeLayer, tuple[str, ...]]] = [
    (
        KnowledgeLayer.EXECUTION,
        (
            "denylist violation",
            "protected path",
            "skipped",
            "not executed",
            "did not run",
            "forgot to run",
            "missing test",
            "no verification",
            "未执行",
            "跳过检查",
        ),
    ),
    (
        KnowledgeLayer.ENGINEERING,
        (
            "importerror",
            "modulenotfounderror",
            "no module named",
            "nameerror",
            "attributeerror",
            "undefined",
            "cannot resolve",
            "unresolved import",
            "no such file or directory",
            "cannot find",
            "symbol",
        ),
    ),
    (
        KnowledgeLayer.SEMANTIC,
        (
            "unit mismatch",
            "wrong field",
            "field meaning",
            "semantic",
            "ambiguous",
            "schema mismatch",
            "contract mismatch",
            "default value",
            "含义",
            "语义",
            "单位",
            "默认值",
            "适用范围",
        ),
    ),
    (
        KnowledgeLayer.EXPERIENCE,
        (
            "regression",
            "regressed",
            "previously fixed",
            "same issue",
            "known issue",
            "recurring",
            "经验",
            "复现",
        ),
    ),
]

# 每层的修复动作。刻意写成「该补什么」，避免落回「再加一段提示词」。
_LAYER_REMEDIATION: dict[KnowledgeLayer, str] = {
    KnowledgeLayer.ENGINEERING: (
        "补工程事实：确认符号定义、调用链与跨仓契约（生产者/消费者），"
        "先解决「找不到」，不要改语义解释。"
    ),
    KnowledgeLayer.SEMANTIC: (
        "补项目语义：明确对象、字段含义、单位/默认值、状态作用域与适用范围，"
        "并记录该结论的依据。"
    ),
    KnowledgeLayer.EXPERIENCE: (
        "收紧经验适用范围：核对旧经验的触发条件是否匹配当前对象与版本；"
        "不匹配时应拆分或撤回该经验，而不是重复召回。"
    ),
    KnowledgeLayer.EXECUTION: (
        "把已知约束落成可执行检查：测试断言、动作前校验或观察器修正，"
        "不要只再加一句提醒。"
    ),
    KnowledgeLayer.UNATTRIBUTED: (
        "无法归因：需补充区分性观察（哪次观测能排除其他解释）与发生条件，"
        "不要用通用反思模板。"
    ),
}

# 归因结果的置信度。
CONFIDENCE_HIGH = "high"
CONFIDENCE_LOW = "low"


@dataclass(frozen=True)
class Attribution:
    """单条失败的层级归因结果。"""

    item: str
    layer: KnowledgeLayer
    confidence: str
    matched_signals: tuple[str, ...]
    remediation: str


def _classify(item: str) -> tuple[KnowledgeLayer, tuple[str, ...]]:
    lowered = item.lower()
    for layer, signals in _LAYER_SIGNALS:
        hits = tuple(s for s in signals if s in lowered)
        if hits:
            return layer, hits
    return KnowledgeLayer.UNATTRIBUTED, ()


def attribute_failures(items: Iterable[str]) -> list[Attribution]:
    """把失败项逐条归因到知识层。

    归因是**证据驱动**的：命中多个层的信号时按 ``_LAYER_SIGNALS`` 的优先级
    取第一个（执行层优先——「知道约束但没做检查」是最容易被误判成理解问题
    的一类）。无任何信号时返回 ``UNATTRIBUTED`` 且置信度为 low，调用方据此
    要求补充证据，而不是接受一条泛泛的建议。
    """
    results: list[Attribution] = []
    for item in items:
        text = str(item)
        layer, hits = _classify(text)
        if layer is KnowledgeLayer.UNATTRIBUTED:
            confidence = CONFIDENCE_LOW
        elif len(hits) >= 2:
            confidence = CONFIDENCE_HIGH
        else:
            confidence = CONFIDENCE_LOW
        results.append(
            Attribution(
                item=text,
                layer=layer,
                confidence=confidence,
                matched_signals=hits,
                remediation=_LAYER_REMEDIATION[layer],
            )
        )
    return results


def summarize_attribution(items: Iterable[str]) -> dict[KnowledgeLayer, list[str]]:
    """按层聚合失败项，便于一次性看清「这次到底缺哪类知识」。"""
    grouped: dict[KnowledgeLayer, list[str]] = {}
    for attr in attribute_failures(items):
        grouped.setdefault(attr.layer, []).append(attr.item)
    return grouped


def format_attribution_section(items: Iterable[str]) -> str:
    """把按层归因渲染成可附加到 summary 的文本段。

    无失败项时返回空字符串（调用方无需判断）。每层只给一条修复动作，
    避免把同一句话重复 N 遍——这正是文章批评的「宽泛但不能指导行动」。
    """
    grouped = summarize_attribution(items)
    if not grouped:
        return ""
    # 固定顺序输出，保证同一批失败的渲染结果可复现。
    order = [
        KnowledgeLayer.EXECUTION,
        KnowledgeLayer.ENGINEERING,
        KnowledgeLayer.SEMANTIC,
        KnowledgeLayer.EXPERIENCE,
        KnowledgeLayer.UNATTRIBUTED,
    ]
    lines = ["", "### 失败归因（按知识层，指导下一轮修法）"]
    for layer in order:
        layer_items = grouped.get(layer)
        if not layer_items:
            continue
        lines.append(f"- [{layer.value}] {len(layer_items)} 项 → {_LAYER_REMEDIATION[layer]}")
        for item in layer_items[:3]:
            lines.append(f"    - {item}")
        if len(layer_items) > 3:
            lines.append(f"    - …另有 {len(layer_items) - 3} 项")
    return "\n".join(lines)


# ── 版本化知识陈述与撤回 ────────────────────────────────────────────────


class StatementStatus(str, Enum):
    ACTIVE = "active"
    NEEDS_REVIEW = "needs_review"
    RETRACTED = "retracted"


@dataclass
class KnowledgeStatement:
    """一条可被纠正的项目知识陈述。

    ``conditions`` 是适用范围。文章强调：**关键前提必须与摘要同时出现**，
    不能把「只适用旧协议」这类条件藏到最后一层披露时。因此这里把条件
    作为陈述的必填语义（缺省为空 = 无条件，需调用方显式负责）。
    """

    statement_id: str
    layer: KnowledgeLayer
    text: str
    version: int = 1
    status: StatementStatus = StatementStatus.ACTIVE
    conditions: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    review_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement_id": self.statement_id,
            "layer": self.layer.value,
            "text": self.text,
            "version": self.version,
            "status": self.status.value,
            "conditions": list(self.conditions),
            "evidence": list(self.evidence),
            "depends_on": list(self.depends_on),
            "review_reason": self.review_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeStatement":
        return cls(
            statement_id=str(data.get("statement_id", "")),
            layer=KnowledgeLayer(str(data.get("layer", KnowledgeLayer.SEMANTIC.value))),
            text=str(data.get("text", "")),
            version=int(data.get("version", 1)),
            status=StatementStatus(str(data.get("status", StatementStatus.ACTIVE.value))),
            conditions=list(data.get("conditions") or []),
            evidence=list(data.get("evidence") or []),
            depends_on=list(data.get("depends_on") or []),
            review_reason=str(data.get("review_reason", "")),
        )


class LedgerError(ValueError):
    """账本操作违反不变量（重复 ID / 未知依赖 / 非法状态迁移）。"""


class KnowledgeLedger:
    """项目知识账本：支持撤回与依赖级联复核。

    核心不变量：

    - 只有 ``ACTIVE`` 的陈述可以作为可依赖的结论被消费（``trusted``）。
    - 撤回一条陈述，其**传递依赖者**进入 ``NEEDS_REVIEW`` 而非被删除——
      原事件保留，但不能继续当作已确认规则。
    - 复核通过 → 回到 ``ACTIVE`` 且 ``version`` +1（结论被重新确认过）；
      复核驳回 → ``RETRACTED`` 并继续向下级联。
    """

    def __init__(self, statements: Iterable[KnowledgeStatement] = ()) -> None:
        self._items: dict[str, KnowledgeStatement] = {}
        for st in statements:
            self.add(st)

    # ── 读 ──
    def get(self, statement_id: str) -> KnowledgeStatement | None:
        return self._items.get(statement_id)

    def all(self) -> list[KnowledgeStatement]:
        return list(self._items.values())

    def trusted(self, layer: KnowledgeLayer | None = None) -> list[KnowledgeStatement]:
        """返回可作为结论消费的陈述（仅 ACTIVE）。"""
        return [
            st
            for st in self._items.values()
            if st.status is StatementStatus.ACTIVE and (layer is None or st.layer is layer)
        ]

    def needs_review(self) -> list[KnowledgeStatement]:
        return [st for st in self._items.values() if st.status is StatementStatus.NEEDS_REVIEW]

    def dependents_of(self, statement_id: str) -> list[str]:
        """传递闭包：直接或间接依赖该陈述的所有 ID（不含自身）。

        用 visited 集合防御环形依赖——知识图允许环，遍历不能因此挂死。
        """
        if statement_id not in self._items:
            raise LedgerError(f"未知陈述: {statement_id}")
        result: list[str] = []
        seen: set[str] = {statement_id}
        queue = [statement_id]
        while queue:
            current = queue.pop(0)
            for st in self._items.values():
                if current in st.depends_on and st.statement_id not in seen:
                    seen.add(st.statement_id)
                    result.append(st.statement_id)
                    queue.append(st.statement_id)
        return result

    # ── 写 ──
    def add(self, statement: KnowledgeStatement) -> KnowledgeStatement:
        if not statement.statement_id:
            raise LedgerError("statement_id 不能为空")
        if statement.statement_id in self._items:
            raise LedgerError(f"重复陈述 ID: {statement.statement_id}")
        for dep in statement.depends_on:
            if dep not in self._items:
                raise LedgerError(
                    f"{statement.statement_id} 依赖的陈述不存在: {dep}（先添加被依赖项）"
                )
        self._items[statement.statement_id] = statement
        return statement

    def retract(self, statement_id: str, reason: str) -> list[str]:
        """撤回一条陈述，返回被置为待复核的依赖者 ID 列表。

        依赖者不删除、不改写正文，只标记 ``NEEDS_REVIEW`` 并记录原因，
        使「旧结论被替代」这件事在数据上可见、可追踪。
        """
        st = self._items.get(statement_id)
        if st is None:
            raise LedgerError(f"未知陈述: {statement_id}")
        if st.status is StatementStatus.RETRACTED:
            raise LedgerError(f"陈述已撤回: {statement_id}")

        st.status = StatementStatus.RETRACTED
        st.review_reason = reason
        affected: list[str] = []
        for dep_id in self.dependents_of(statement_id):
            dep = self._items[dep_id]
            if dep.status is StatementStatus.ACTIVE:
                dep.status = StatementStatus.NEEDS_REVIEW
                dep.review_reason = f"依赖的 {statement_id} 已撤回：{reason}"
                affected.append(dep_id)
        return affected

    def review(self, statement_id: str, *, accept: bool, reason: str) -> list[str]:
        """复核一条待复核陈述。

        ``accept=True``：确认仍然成立，回到 ACTIVE 且 version+1。
        ``accept=False``：判定不成立，等同于撤回并继续向下级联。
        """
        st = self._items.get(statement_id)
        if st is None:
            raise LedgerError(f"未知陈述: {statement_id}")
        if st.status is not StatementStatus.NEEDS_REVIEW:
            raise LedgerError(
                f"只有 needs_review 状态可复核，当前为 {st.status.value}: {statement_id}"
            )
        if accept:
            st.status = StatementStatus.ACTIVE
            st.version += 1
            st.review_reason = reason
            return []
        st.status = StatementStatus.ACTIVE  # 借道 retract 的状态校验
        return self.retract(statement_id, reason)

    # ── 持久化 ──
    def to_dict(self) -> dict[str, Any]:
        return {"statements": [st.to_dict() for st in self._items.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeLedger":
        return cls(KnowledgeStatement.from_dict(d) for d in data.get("statements") or [])

    def save(self, path: Path | str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path | str) -> "KnowledgeLedger":
        source = Path(path)
        if not source.exists():
            return cls()
        return cls.from_dict(json.loads(source.read_text(encoding="utf-8")))

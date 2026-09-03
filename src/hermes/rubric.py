"""版本化评估 Rubric —— 把专家对"好"的定义变成机器可执行、可解释的资产。

借鉴 AgentLoop 数据飞轮实践（三）的核心思想：
- 黄金指标 → Rubric：把抽象的"好"拆成一条条可判定的评分细则（分档 + 权重
  + 总分公式），评估从"凭感觉"变成"可复现"；
- 分数必须可解释：低分时能直接看到"哪一步做错了、依据是什么"（evidence）；
- Rubric 带版本号：分数变化才能区分"是 Agent 变了还是标准变了"。

与 Hermes checker 体系的对接：
- 指标 = checker 角色（checker/checker_lint/checker_type…），权重由 Rubric
  声明；
- 判定输入 = 各角色 checker 的报告文本，复用 fan-in 已有的
  ``<!-- failures:json -->`` 结构化协议（本模块是该协议解析的单一实现，
  orchestrator 委托到这里）；
- 输出 :class:`RubricScore`：final_score ∈ [0,1]、per-metric verdict（含
  证据）、decision、rubric 版本——``quality`` 属性可直接填充
  ``VariantResult.quality``，让 GEPA 的 variant 排序吃上加权分数。

不评什么：本模块不做语义级评判（那需要 LLM-as-judge）。它是确定性
"规则可表达"层的 Rubric——对应 AgentLoop 文中 Code 评估 vs Agent 评估
二分法中的 Code 侧；Agent 侧由 checker prompt 本身承担。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DEFAULT_RUBRIC",
    "MetricVerdict",
    "Rubric",
    "RubricMetric",
    "RubricScore",
    "parse_structured_failures",
    "score_reports",
]

# Structured failure protocol markers emitted by checker.md templates.
# Checkers are asked to append a JSON block so the orchestrator can extract
# normalized (file, type) failure keys instead of guessing from free text.
FAILURES_BLOCK_RE = re.compile(
    r"<!--\s*failures:json\s*-->\s*(\{.*?\})\s*<!--\s*/failures\s*-->",
    re.DOTALL,
)

# Sentinel returned when a report has no parseable failure information.
UNPARSEABLE = "[UNPARSEABLE FAILURE]"


def parse_structured_failures(checker_result: str, role: str) -> list[str]:
    """Extract failure items from a checker report.

    Prefers the structured ``<!-- failures:json -->`` protocol block: returns
    normalized ``"file|type"`` keys (without line numbers) so stop-rule set
    comparison survives line-number drift when a builder edits earlier lines.

    Falls back to a single verbatim item ``"<role>: <first non-empty line>"``
    when no structured block is present — this never guesses which lines are
    failures.
    """
    match = FAILURES_BLOCK_RE.search(checker_result)
    if match:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            data = None
        if data is not None:
            # 协议块存在且 JSON 合法 → 信任协议（含空 failures 数组：全绿）。
            items: list[str] = []
            for f in data.get("failures") or []:
                if not isinstance(f, dict):
                    continue
                file = str(f.get("file", "")).strip()
                ftype = str(f.get("type", "")).strip()
                # Normalize to "file|type" — drop line numbers deliberately.
                key = f"{file}|{ftype}" if file or ftype else ""
                if key:
                    items.append(f"{role}: {key}")
            return items
        # JSON 损坏 → 落入 verbatim 回退（不猜测）。
    # Fallback: verbatim first meaningful line, prefixed with role. No guessing.
    for line in checker_result.splitlines():
        stripped = line.strip()
        if stripped and "ALL GREEN" not in stripped.upper():
            return [f"{role}: {stripped}"]
    return [f"{role}: {UNPARSEABLE}"]


def is_all_green(report: str) -> bool:
    """A checker report is green when it explicitly says so and parses no failures."""
    if "ALL GREEN" not in report.upper():
        return False
    return not parse_structured_failures(report, "check")


# ── Rubric 定义（资产，带版本）───────────────────────────────────────


@dataclass
class RubricMetric:
    """一条评分细则：某 checker 角色占多少权重。"""

    role: str
    weight: float  # 0-100；同一 Rubric 内权重和不必强制 100（会归一化）
    description: str = ""


@dataclass
class Rubric:
    """一组带版本的评分细则（评估资产，可持久化、可迭代、可对比）。"""

    rubric_id: str
    version: str
    metrics: list[RubricMetric] = field(default_factory=list)

    def total_weight(self) -> float:
        return sum(m.weight for m in self.metrics) or 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rubric_id": self.rubric_id,
            "version": self.version,
            "metrics": [
                {"role": m.role, "weight": m.weight, "description": m.description}
                for m in self.metrics
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rubric":
        return cls(
            rubric_id=str(data.get("rubric_id", "")),
            version=str(data.get("version", "")),
            metrics=[
                RubricMetric(
                    role=str(m.get("role", "")),
                    weight=float(m.get("weight", 0) or 0),
                    description=str(m.get("description", "")),
                )
                for m in data.get("metrics") or []
            ],
        )


# 默认 Rubric：pytest 回归主导，lint/type 各占四分之一。
# 版本化意味着：调整权重必须 bump version，历史 RubricScore 才可对比。
DEFAULT_RUBRIC = Rubric(
    rubric_id="hermes-default",
    version="1.0",
    metrics=[
        RubricMetric("checker", 50.0, "pytest 回归（核心质量信号）"),
        RubricMetric("checker_lint", 25.0, "ruff 静态检查"),
        RubricMetric("checker_type", 25.0, "mypy 类型检查"),
    ],
)


# ── 评分 ────────────────────────────────────────────────────────────


@dataclass
class MetricVerdict:
    """单指标判定：过/不过、得分、证据（命中的 failure key）。"""

    role: str
    weight: float
    passed: bool
    score: float  # 0.0 / 1.0（确定性规则层只有两档）
    evidence: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class RubricScore:
    """一次评估的完整产出：加权总分 + 可解释证据 + Rubric 版本。"""

    rubric_id: str
    rubric_version: str
    final_score: float  # [0,1] 加权归一
    decision: str  # "pass" / "fail"
    verdicts: list[MetricVerdict] = field(default_factory=list)

    @property
    def quality(self) -> float:
        """直接可填 ``VariantResult.quality`` 的 [0,1] 信号。"""
        return self.final_score

    @property
    def summary(self) -> str:
        failed = [v.role for v in self.verdicts if not v.passed]
        if not failed:
            return f"all {len(self.verdicts)} metrics green"
        return f"failed: {', '.join(failed)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rubric_id": self.rubric_id,
            "rubric_version": self.rubric_version,
            "final_score": self.final_score,
            "decision": self.decision,
            "summary": self.summary,
            "verdicts": [
                {
                    "role": v.role,
                    "weight": v.weight,
                    "passed": v.passed,
                    "score": v.score,
                    "evidence": list(v.evidence),
                    "note": v.note,
                }
                for v in self.verdicts
            ],
        }


def score_reports(
    reports: dict[str, str],
    rubric: Rubric | None = None,
) -> RubricScore:
    """按 *rubric* 对一轮 checker 报告打分。

    Args:
        reports: role → checker 报告文本（来自 fan-in 的各 checker 结果）。
        rubric: 评分细则；默认 :data:`DEFAULT_RUBRIC`。

    判定语义（确定性，两档）：
    - 1.0：报告存在且 ALL GREEN（显式绿 + 结构化协议解析无失败）；
    - 0.0：报告缺失、未显式绿、或解析出任何 failure（证据 = failure keys）。

    加权总分 = Σ(metric_score × weight) / Σweight ∈ [0,1]；
    decision = 全部指标通过才 pass（硬门禁语义，与 ALL GREEN 停止规则对齐）。
    """
    r = rubric or DEFAULT_RUBRIC
    verdicts: list[MetricVerdict] = []
    for metric in r.metrics:
        report = reports.get(metric.role, "")
        if not report.strip():
            verdicts.append(
                MetricVerdict(
                    role=metric.role,
                    weight=metric.weight,
                    passed=False,
                    score=0.0,
                    note="missing report",
                )
            )
            continue
        failures = [
            f for f in parse_structured_failures(report, metric.role)
            if UNPARSEABLE not in f
        ]
        green = is_all_green(report)
        verdicts.append(
            MetricVerdict(
                role=metric.role,
                weight=metric.weight,
                passed=green and not failures,
                score=1.0 if (green and not failures) else 0.0,
                evidence=failures,
            )
        )
    total = r.total_weight()
    final = sum(v.score * v.weight for v in verdicts) / total
    return RubricScore(
        rubric_id=r.rubric_id,
        rubric_version=r.version,
        final_score=final,
        decision="pass" if all(v.passed for v in verdicts) else "fail",
        verdicts=verdicts,
    )

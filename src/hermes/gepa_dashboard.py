"""GEPA 实验大盘 —— 跨实验、跨版本分数对比（借鉴 AgentLoop 实验大盘）。

AgentLoop 数据飞轮实践（四）的核心论点：任何改动都可能"感觉变好了"，但
感觉不算数——要用数据集反复回测、用分数说话，并且**能在版本之间对比分数
变化**（没有版本标记就无从对比）。

Hermes 的对应物：每个 GEPA cycle 已经通过 ``save_experiment`` 持久化到
``.gepa/<id>.json``（审计优先，永不覆盖）。本模块把这些历史实验读出来，
组装成跨实验的大盘视图：

- :func:`build_rows` — 每个实验一行：时间、benchmark、winner、成功率、
  各 variant 的加权分数（复用 :mod:`hermes.rubric` 的 quality 信号，
  如有）；
- :func:`render_table` — 人类可读的 Markdown 表（CLI 输出用）；
- :func:`render_trend` — 按 benchmark 分组的分数趋势（版本演进一眼可见）。

只读、零副作用：大盘只消费已持久化的审计记录，不重跑任何评估。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hermes.gepa import GEPAExperiment, score_variant

__all__ = [
    "ExperimentRow",
    "build_rows",
    "render_table",
    "render_trend",
]


@dataclass
class ExperimentRow:
    """一个实验在大盘上的一行。"""

    experiment_id: str
    created_at: str
    benchmark_task: str
    winner_id: str | None
    n_variants: int
    n_success: int
    # 各 variant 的 (variant_id, score) 降序；score 用 score_variant 统一口径。
    scores: list[tuple[str, float]]
    promotion_reason: str

    @property
    def promoted(self) -> bool:
        return self.winner_id is not None

    @property
    def success_rate(self) -> float:
        return self.n_success / self.n_variants if self.n_variants else 0.0

    @property
    def best_score(self) -> float | None:
        return self.scores[0][1] if self.scores else None


def build_rows(experiments: list[GEPAExperiment]) -> list[ExperimentRow]:
    """把持久化实验转为大盘行，按时间倒序（最新在前）。"""
    rows: list[ExperimentRow] = []
    for exp in sorted(experiments, key=lambda e: e.created_at, reverse=True):
        scored = sorted(
            ((r.variant_id, score_variant(r)) for r in exp.results),
            key=lambda kv: kv[1],
            reverse=True,
        )
        rows.append(
            ExperimentRow(
                experiment_id=exp.experiment_id,
                created_at=exp.created_at,
                benchmark_task=exp.benchmark_task,
                winner_id=exp.winner_id,
                n_variants=len(exp.variants),
                n_success=sum(1 for r in exp.results if r.success),
                scores=scored,
                promotion_reason=exp.promotion_reason,
            )
        )
    return rows


def _short_id(value: str) -> str:
    return value[:8] if len(value) > 8 else value


def render_table(rows: list[ExperimentRow], *, limit: int = 20) -> str:
    """渲染大盘为 Markdown 表（默认最近 *limit* 个实验）。"""
    if not rows:
        return "（暂无实验记录）"
    lines = [
        "| 时间 | 实验 | Benchmark | 变体 | 成功 | Winner | 最佳分 |",
        "|------|------|-----------|------|------|--------|--------|",
    ]
    for row in rows[:limit]:
        winner = _short_id(row.winner_id) if row.winner_id else "—"
        best = f"{row.best_score:.0f}" if row.best_score is not None else "—"
        lines.append(
            f"| {row.created_at[:19]} | {_short_id(row.experiment_id)} "
            f"| {row.benchmark_task[:40]} | {row.n_variants} "
            f"| {row.n_success}/{row.n_variants} | {winner} | {best} |"
        )
    return "\n".join(lines)


def render_trend(rows: list[ExperimentRow], *, limit: int = 5) -> str:
    """按 benchmark 分组渲染分数趋势：每任务最近 *limit* 次实验的最佳分。

    分数变化只有结合版本/时间序列才有意义——这正是"实验大盘"要回答的：
    这次调优让分数升了还是降了。
    """
    if not rows:
        return "（暂无实验记录）"
    by_task: dict[str, list[ExperimentRow]] = {}
    for row in rows:  # rows 已是时间倒序
        by_task.setdefault(row.benchmark_task, []).append(row)

    blocks: list[str] = []
    for task, task_rows in sorted(by_task.items()):
        recent = task_rows[:limit]
        points = " → ".join(
            f"{r.best_score:.0f}" if r.best_score is not None else "n/a"
            for r in reversed(recent)  # 时间正序展示
        )
        promotions = sum(1 for r in recent if r.promoted)
        blocks.append(
            f"**{task[:60]}**\n"
            f"  趋势（旧→新）: {points}\n"
            f"  最近 {len(recent)} 次实验晋升 {promotions} 次"
        )
    return "\n\n".join(blocks)


def dashboard_payload(rows: list[ExperimentRow]) -> dict[str, Any]:
    """大盘的机器可读形态（供 workbench /metrics 或 API 消费）。"""
    return {
        "total_experiments": len(rows),
        "total_promotions": sum(1 for r in rows if r.promoted),
        "rows": [
            {
                "experiment_id": r.experiment_id,
                "created_at": r.created_at,
                "benchmark_task": r.benchmark_task,
                "winner_id": r.winner_id,
                "n_variants": r.n_variants,
                "n_success": r.n_success,
                "success_rate": round(r.success_rate, 3),
                "best_score": r.best_score,
            }
            for r in rows
        ],
    }

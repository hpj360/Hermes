"""GEPA self-evolution wire-up for loops.

从 loop.py 拆出的 **GEPA 接线层**：evaluator 注入、终态触发 GEPA 周期。

设计原则（第一性原理）：
- 解耦：本模块不硬依赖 gepa.py。evaluator 由 runner 通过
  set_gepa_evaluator() 注入；未注入时 _maybe_run_gepa 跳过并记日志，
  不影响 record_round 主流程。
- Opt-in：loop 必须在 meta.json 声明 gepa_variants 才会触发；空列表
  时完全跳过（零开销）。
- 终态触发：只在 loop 到达终态（COMPLETED/NEEDS_HUMAN/BUDGET_EXCEEDED）
  时触发一次 GEPA 周期，避免每轮都跑（GEPA 评估多 variant 成本高）。
- 审计优先：实验结果通过 save_experiment 持久化到 .gepa/，永不覆盖。

依赖方向：loop_gepa ← loop（record_round 调用）、loop_gepa ← runner
（注入 evaluator）。loop_gepa 对 gepa.py 延迟导入，无循环依赖。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from hermes.loop_patterns import LoopStatus

if TYPE_CHECKING:
    from hermes.loop import LoopRound, LoopState

logger = logging.getLogger("hermes.loop.gepa")


# 类型别名：与 gepa.EvaluateFn 签名一致，但延迟导入避免循环依赖。
# (variant_dict, benchmark_task, benchmark_context) -> result_dict
GepaEvaluator = Callable[[dict[str, Any], str, str], dict[str, Any]]

_gepa_evaluator: GepaEvaluator | None = None


def set_gepa_evaluator(fn: GepaEvaluator | None) -> None:
    """注入 GEPA 评估函数。runner 在启动时调用（Gateway 可用时注入真实实现）。

    fn 签名: (variant_dict, benchmark_task, benchmark_context) -> result_dict
    result_dict 须含: success(bool), tokens_used(int), rounds_to_converge(int),
    failure_items(list[str]), error(str|None)。与 VariantResult.to_dict() 对齐。
    传 None 清除注入（用于测试隔离）。
    """
    global _gepa_evaluator
    _gepa_evaluator = fn


def get_gepa_evaluator() -> GepaEvaluator | None:
    """返回当前注入的 GEPA 评估函数（None 表示未注入）。"""
    return _gepa_evaluator


# 触发 GEPA 的终态集合（只在 loop 结束时跑一次，不在中间轮跑）
_GEPA_TRIGGER_STATUSES = frozenset({
    LoopStatus.COMPLETED,
    LoopStatus.NEEDS_HUMAN,
    LoopStatus.BUDGET_EXCEEDED,
})


def _maybe_run_gepa(loop: LoopState, round_data: LoopRound) -> dict[str, Any]:
    """在 record_round 终态时按需触发 GEPA 自进化周期。

    触发条件（全部满足）：
    1. loop.status ∈ {COMPLETED, NEEDS_HUMAN, BUDGET_EXCEEDED}
    2. loop.gepa_variants 非空（声明了候选变体）
    3. _gepa_evaluator 已注入（runner 在 Gateway 可用时注入）

    任一条件不满足时静默跳过，返回 {"ran": False, "reason": ...}。
    全部满足时：延迟导入 gepa 模块，构建 Variant 列表，跑 run_gepa_cycle，
    save_experiment 持久化，返回实验摘要。

    benchmark_task 用 loop.name + pattern 组合，让 .gepa/ 中的实验可按
    loop 追溯（list_experiments 后按 benchmark_task 过滤即可）。
    """
    if loop.status not in _GEPA_TRIGGER_STATUSES:
        return {"ran": False, "reason": f"non-terminal status: {loop.status.value}"}

    if not loop.gepa_variants:
        return {"ran": False, "reason": "no gepa_variants declared"}

    evaluator = _gepa_evaluator
    if evaluator is None:
        logger.info(
            "Loop '%s' reached terminal state with gepa_variants declared, "
            "but no GEPA evaluator is injected (call set_gepa_evaluator to enable)",
            loop.name,
        )
        return {"ran": False, "reason": "no evaluator injected"}

    # 延迟导入：避免本模块硬依赖 gepa.py（gepa 模块仅在真正触发时加载）
    from hermes.gepa import Variant, run_gepa_cycle, save_experiment

    variants = [
        Variant(
            variant_id=v["variant_id"],
            agent_file=v["agent_file"],
            description=v.get("description", ""),
        )
        for v in loop.gepa_variants
    ]

    benchmark_task = f"loop:{loop.name} pattern:{loop.pattern}"
    benchmark_context = (
        f"terminal_status={loop.status.value} "
        f"rounds={loop.current_round}/{loop.max_rounds} "
        f"budget={loop.budget_used_tokens}/{loop.budget_limit_tokens}"
    )

    def _evaluate(variant: Variant, task: str, context: str) -> Any:
        """适配器：把注入的 evaluator（返回 dict）转为 VariantResult。

        evaluator 返回的 dict 字段与 VariantResult 对齐（由 runner 合约保证）。
        若字段缺失，用合理默认值填充（防御性）。quality 缺失 → None
        （退回二值 success 评分，向后兼容旧 evaluator）。
        """
        from hermes.gepa import VariantResult
        raw = evaluator(variant.to_dict(), task, context)
        raw_quality = raw.get("quality")
        try:
            quality = None if raw_quality is None else float(raw_quality)
        except (TypeError, ValueError):
            quality = None
        return VariantResult(
            variant_id=str(raw.get("variant_id", variant.variant_id)),
            success=bool(raw.get("success", False)),
            tokens_used=int(raw.get("tokens_used", 0) or 0),
            rounds_to_converge=int(raw.get("rounds_to_converge", 0) or 0),
            failure_items=list(raw.get("failure_items") or []),
            error=raw.get("error"),
            quality=quality,
        )

    try:
        experiment = run_gepa_cycle(
            benchmark_task=benchmark_task,
            variants=variants,
            evaluate_fn=_evaluate,
            benchmark_context=benchmark_context,
        )
        save_experiment(experiment)
    except Exception as exc:  # noqa: BLE001 - GEPA 失败不能影响 record_round
        logger.exception(
            "GEPA cycle failed for loop '%s'; record_round result unaffected",
            loop.name,
        )
        return {"ran": False, "reason": f"gepa error: {type(exc).__name__}: {exc}"}

    return {
        "ran": True,
        "experiment_id": experiment.experiment_id,
        "winner_id": experiment.winner_id,
        "promotion_reason": experiment.promotion_reason,
        "variants_evaluated": len(experiment.results),
    }

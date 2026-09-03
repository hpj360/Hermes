"""Tests for GEPA experiment dashboard (P1-B 实验可观测)."""

from __future__ import annotations

from hermes.gepa import GEPAExperiment, Variant, VariantResult
from hermes.gepa_dashboard import (
    ExperimentRow,
    build_rows,
    dashboard_payload,
    render_table,
    render_trend,
)


def _exp(
    exp_id: str,
    task: str,
    created_at: str,
    results: list[VariantResult],
    winner: str | None = None,
) -> GEPAExperiment:
    return GEPAExperiment(
        experiment_id=exp_id,
        benchmark_task=task,
        variants=[Variant(variant_id=r.variant_id, agent_file="/x.md") for r in results],
        results=results,
        winner_id=winner,
        promotion_reason="test winner beats baseline" if winner else "",
        created_at=created_at,
    )


def _result(vid: str, success: bool, quality: float | None = None) -> VariantResult:
    return VariantResult(
        variant_id=vid,
        success=success,
        tokens_used=1000,
        rounds_to_converge=2,
        quality=quality,
    )


# ── build_rows ──────────────────────────────────────────────────────


def test_build_rows_orders_newest_first():
    exps = [
        _exp("e1", "loop:demo", "2026-01-01T00:00:00", [_result("a", True)]),
        _exp("e2", "loop:demo", "2026-02-01T00:00:00", [_result("a", True)]),
    ]
    rows = build_rows(exps)
    assert [r.experiment_id for r in rows] == ["e2", "e1"]


def test_build_rows_counts_success_and_scores():
    exp = _exp(
        "e1", "loop:demo", "2026-01-01T00:00:00",
        [
            _result("baseline", False, quality=0.2),
            _result("challenger", True, quality=0.9),
        ],
        winner="challenger",
    )
    row = build_rows([exp])[0]
    assert row.n_variants == 2
    assert row.n_success == 1
    assert row.success_rate == 0.5
    assert row.promoted is True
    # scores 降序：challenger 在前
    assert row.scores[0][0] == "challenger"
    assert row.best_score == row.scores[0][1]


def test_row_properties_no_results():
    row = ExperimentRow(
        experiment_id="e", created_at="t", benchmark_task="b",
        winner_id=None, n_variants=0, n_success=0, scores=[],
        promotion_reason="",
    )
    assert row.promoted is False
    assert row.success_rate == 0.0
    assert row.best_score is None


# ── render_table / render_trend ─────────────────────────────────────


def test_render_table_empty():
    assert "暂无实验记录" in render_table([])


def test_render_table_rows():
    exp = _exp(
        "experiment-1234", "loop:demo task", "2026-01-01T10:20:30",
        [_result("a", True, quality=0.9)], winner="a",
    )
    table = render_table(build_rows([exp]))
    assert "experime" in table  # short id (8 chars)
    assert "loop:demo task" in table
    assert "1/1" in table
    assert "a" in table  # winner id


def test_render_trend_groups_by_benchmark():
    exps = [
        _exp("e1", "loop:demo", "2026-01-01T00:00:00", [_result("a", True, quality=0.5)]),
        _exp("e2", "loop:demo", "2026-02-01T00:00:00", [_result("a", True, quality=0.8)]),
        _exp("e3", "loop:other", "2026-03-01T00:00:00", [_result("a", True, quality=0.6)]),
    ]
    trend = render_trend(build_rows(exps))
    assert "loop:demo" in trend
    assert "loop:other" in trend
    # demo 趋势：旧→新 分数递增（score_variant 单调，quality 0.5 < 0.8）
    demo_block = trend.split("**loop:other")[0]
    arrow = demo_block.split("趋势（旧→新）: ")[1].split("\n")[0]
    older, newer = (float(x) for x in arrow.split(" → "))
    assert newer > older


def test_render_trend_empty():
    assert "暂无实验记录" in render_trend([])


def test_render_trend_counts_promotions():
    exps = [
        _exp("e1", "loop:demo", "2026-01-01T00:00:00", [_result("a", True)], winner="a"),
        _exp("e2", "loop:demo", "2026-02-01T00:00:00", [_result("a", False)]),
    ]
    trend = render_trend(build_rows(exps))
    assert "晋升 1 次" in trend


# ── dashboard_payload ───────────────────────────────────────────────


def test_dashboard_payload_machine_readable():
    exps = [
        _exp("e1", "loop:demo", "2026-01-01T00:00:00",
             [_result("a", True)], winner="a"),
        _exp("e2", "loop:demo", "2026-02-01T00:00:00",
             [_result("a", False)]),
    ]
    payload = dashboard_payload(build_rows(exps))
    assert payload["total_experiments"] == 2
    assert payload["total_promotions"] == 1
    assert payload["rows"][0]["experiment_id"] == "e2"  # newest first
    assert payload["rows"][0]["success_rate"] == 0.0

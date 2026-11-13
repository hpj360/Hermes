"""项目知识账本：失败分层归因 + 经验版本化撤回。"""

from __future__ import annotations

import json

import pytest

from hermes.knowledge_ledger import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    Attribution,
    KnowledgeLayer,
    KnowledgeLedger,
    KnowledgeStatement,
    LedgerError,
    StatementStatus,
    attribute_failures,
    format_attribution_section,
    summarize_attribution,
)
from hermes.orchestrator import AgentTask, Orchestrator


# ── 归因：失败要落到层，不能统一归为「模型不够聪明」 ──────────────────


def test_attribution_routes_each_layer():
    """四类失败各自归到对应层——这是文章最核心的可操作结论。"""
    cases = {
        KnowledgeLayer.ENGINEERING: "builder: src/a.py|ImportError",
        KnowledgeLayer.SEMANTIC: "builder: docs/x.md|语义 mismatch",
        KnowledgeLayer.EXPERIENCE: "builder: src/a.py|regression",
        KnowledgeLayer.EXECUTION: "builder: DENYLIST VIOLATION — auth/x.py",
    }
    for layer, item in cases.items():
        (attr,) = attribute_failures([item])
        assert attr.layer is layer, f"{item} 应归到 {layer.value}，实际 {attr.layer.value}"
        assert attr.remediation  # 每层都必须给可执行的修复动作


def test_execution_layer_wins_over_engineering_on_denylist():
    """「知道约束但没执行检查」优先于「找不到符号」，避免被误判为理解问题。"""
    item = "builder: DENYLIST VIOLATION — cannot find auth/x.py"
    (attr,) = attribute_failures([item])
    assert attr.layer is KnowledgeLayer.EXECUTION


def test_no_signal_is_unattributed_low_confidence():
    """无证据不硬套模板：返回 UNATTRIBUTED 且低置信，要求补充区分性观察。"""
    (attr,) = attribute_failures(["builder: something odd happened"])
    assert attr.layer is KnowledgeLayer.UNATTRIBUTED
    assert attr.confidence == CONFIDENCE_LOW
    assert attr.matched_signals == ()


def test_confidence_high_requires_multiple_signals():
    """单信号只是候选，多信号才升为高置信——避免一次词面命中就当结论。"""
    (single,) = attribute_failures(["builder: regression"])
    assert single.confidence == CONFIDENCE_LOW

    (double,) = attribute_failures(["builder: regression — previously fixed"])
    assert double.confidence == CONFIDENCE_HIGH


def test_attribution_is_case_insensitive():
    (attr,) = attribute_failures(["builder: MODULENOTFOUNDERROR"])
    assert attr.layer is KnowledgeLayer.ENGINEERING


def test_summarize_groups_by_layer():
    grouped = summarize_attribution(
        [
            "builder: x|ImportError",
            "builder: x|regression",
            "builder: y|ImportError",
        ]
    )
    assert len(grouped[KnowledgeLayer.ENGINEERING]) == 2
    assert len(grouped[KnowledgeLayer.EXPERIENCE]) == 1


def test_format_section_empty_when_no_failures():
    assert format_attribution_section([]) == ""


def test_format_section_emits_one_remediation_per_layer():
    """同一层只给一条修复动作，避免把一句话重复 N 遍。"""
    section = format_attribution_section(
        ["builder: a|ImportError", "builder: b|ImportError", "builder: c|ModuleNotFoundError"]
    )
    assert section.count("[engineering]") == 1
    assert "3 项" in section


def test_format_section_truncates_long_lists():
    items = [f"builder: f{i}|ImportError" for i in range(6)]
    section = format_attribution_section(items)
    assert "另有 3 项" in section


def test_format_section_is_deterministic():
    items = ["builder: a|ImportError", "builder: b|regression"]
    assert format_attribution_section(items) == format_attribution_section(items)


# ── 撤回：知识必须能纠正，而不只是追加 ────────────────────────────────


def _st(sid: str, deps: list[str] | None = None, layer=KnowledgeLayer.SEMANTIC):
    return KnowledgeStatement(
        statement_id=sid,
        layer=layer,
        text=f"claim {sid}",
        depends_on=deps or [],
    )


def test_retract_cascades_to_transitive_dependents():
    """撤回结论 → 依赖者进入待复核（不删除），保证旧结论仍可追踪。"""
    ledger = KnowledgeLedger()
    ledger.add(_st("base"))
    ledger.add(_st("mid", ["base"]))
    ledger.add(_st("leaf", ["mid"]))

    affected = ledger.retract("base", "核对后属于不同状态作用域")

    assert set(affected) == {"mid", "leaf"}
    assert ledger.get("base").status is StatementStatus.RETRACTED
    assert ledger.get("mid").status is StatementStatus.NEEDS_REVIEW
    assert ledger.get("leaf").status is StatementStatus.NEEDS_REVIEW
    # 正文与证据保留，只标记状态
    assert ledger.get("mid").text == "claim mid"
    assert "已撤回" in ledger.get("mid").review_reason


def test_trusted_excludes_needs_review_and_retracted():
    """待复核的结论不能再被当作已确认规则消费——这是撤回的实际作用点。"""
    ledger = KnowledgeLedger()
    ledger.add(_st("base"))
    ledger.add(_st("dep", ["base"]))
    assert {s.statement_id for s in ledger.trusted()} == {"base", "dep"}

    ledger.retract("base", "反例出现")
    assert [s.statement_id for s in ledger.trusted()] == []
    assert [s.statement_id for s in ledger.needs_review()] == ["dep"]


def test_trusted_filters_by_layer():
    ledger = KnowledgeLedger()
    ledger.add(_st("eng", layer=KnowledgeLayer.ENGINEERING))
    ledger.add(_st("sem", layer=KnowledgeLayer.SEMANTIC))
    assert [s.statement_id for s in ledger.trusted(KnowledgeLayer.ENGINEERING)] == ["eng"]


def test_retract_only_touches_active_dependents():
    """已经是待复核的依赖者不被重复计入，保证返回值反映本次实际影响。"""
    ledger = KnowledgeLedger()
    ledger.add(_st("base"))
    ledger.add(_st("dep", ["base"]))
    ledger.add(_st("leaf", ["dep"]))
    ledger.retract("base", "第一次撤回")

    affected = ledger.retract("dep", "第二次撤回")

    assert affected == []  # leaf 已是 needs_review，本次未再降级
    assert ledger.get("leaf").status is StatementStatus.NEEDS_REVIEW


def test_review_accept_restores_active_and_bumps_version():
    ledger = KnowledgeLedger()
    ledger.add(_st("base"))
    ledger.add(_st("dep", ["base"]))
    ledger.retract("base", "初判为脏数据")

    ledger.review("dep", accept=True, reason="核对契约后仍成立")

    dep = ledger.get("dep")
    assert dep.status is StatementStatus.ACTIVE
    assert dep.version == 2
    assert [s.statement_id for s in ledger.trusted()] == ["dep"]


def test_review_reject_retracts_and_cascades_further():
    ledger = KnowledgeLedger()
    ledger.add(_st("base"))
    ledger.add(_st("dep", ["base"]))
    ledger.add(_st("leaf", ["dep"]))
    ledger.retract("base", "初判")
    # leaf 此时已是 needs_review；dep 复核驳回 → 继续向下级联
    affected = ledger.review("dep", accept=False, reason="条件不匹配当前版本")

    assert ledger.get("dep").status is StatementStatus.RETRACTED
    # leaf 已被首次撤回波及，保持 needs_review，不会变回 active
    assert ledger.get("leaf").status is StatementStatus.NEEDS_REVIEW
    assert affected == []


def test_review_rejects_non_pending_state():
    ledger = KnowledgeLedger()
    ledger.add(_st("a"))
    with pytest.raises(LedgerError):
        ledger.review("a", accept=True, reason="x")


def test_cycle_in_dependencies_does_not_hang():
    """知识图允许成环，传递闭包必须用 visited 集合终止。"""
    ledger = KnowledgeLedger()
    ledger.add(_st("a"))
    ledger.add(_st("b", ["a"]))
    # 手工构造环（add 会拒绝前向依赖，这里直接改内部结构模拟历史数据）
    ledger.get("a").depends_on.append("b")
    # 不含自身：b 依赖 a，故 a 的依赖者是 b；环不会让遍历无限展开
    assert set(ledger.dependents_of("a")) == {"b"}
    assert set(ledger.dependents_of("b")) == {"a"}


def test_add_rejects_duplicate_and_missing_dependency():
    ledger = KnowledgeLedger()
    ledger.add(_st("a"))
    with pytest.raises(LedgerError):
        ledger.add(_st("a"))
    with pytest.raises(LedgerError):
        ledger.add(_st("b", ["missing"]))
    with pytest.raises(LedgerError):
        ledger.add(KnowledgeStatement(statement_id="", layer=KnowledgeLayer.SEMANTIC, text="x"))


def test_retract_unknown_and_double_retract():
    ledger = KnowledgeLedger()
    ledger.add(_st("a"))
    with pytest.raises(LedgerError):
        ledger.retract("missing", "x")
    ledger.retract("a", "x")
    with pytest.raises(LedgerError):
        ledger.retract("a", "again")


def test_ledger_roundtrip_preserves_status_and_conditions():
    ledger = KnowledgeLedger()
    ledger.add(
        KnowledgeStatement(
            statement_id="compat",
            layer=KnowledgeLayer.EXPERIENCE,
            text="旧协议下需要兼容默认值",
            conditions=["仅 protocol_version < 3"],
            evidence=["issue#42"],
        )
    )
    ledger.add(_st("dep", ["compat"]))
    ledger.retract("compat", "协议已升级")

    restored = KnowledgeLedger.from_dict(json.loads(json.dumps(ledger.to_dict())))

    compat = restored.get("compat")
    assert compat.status is StatementStatus.RETRACTED
    assert compat.conditions == ["仅 protocol_version < 3"]
    assert compat.evidence == ["issue#42"]
    assert restored.get("dep").status is StatementStatus.NEEDS_REVIEW
    assert restored.trusted() == []


def test_save_and_load(tmp_path):
    ledger = KnowledgeLedger()
    ledger.add(_st("a"))
    path = tmp_path / "nested" / "ledger.json"
    ledger.save(path)

    loaded = KnowledgeLedger.load(path)
    assert [s.statement_id for s in loaded.trusted()] == ["a"]


def test_load_missing_file_returns_empty_ledger(tmp_path):
    assert KnowledgeLedger.load(tmp_path / "nope.json").all() == []


def test_attribution_dataclass_is_frozen():
    (attr,) = attribute_failures(["builder: x|ImportError"])
    assert isinstance(attr, Attribution)
    with pytest.raises(Exception):
        attr.layer = KnowledgeLayer.SEMANTIC  # type: ignore[misc]


# ── 集成：aggregate_results 真的把它下发出去 ──────────────────────────


def test_aggregate_results_appends_layer_attribution():
    """生产链路：失败进 summary 时带上按层归因，且原始失败不被过滤。"""
    report = (
        "FAILED\n<!-- failures:json -->\n"
        '{"passed": false, "failures": ['
        '{"file": "src/a.py", "line": 1, "type": "ImportError"},'
        '{"file": "src/b.py", "line": 2, "type": "regression"}]}\n'
        "<!-- /failures -->"
    )
    tasks = [
        AgentTask(role="builder", status="completed", result="done", session_id="b"),
        AgentTask(role="checker_lint", status="completed", result=report, session_id="c"),
    ]

    result = Orchestrator().aggregate_results(tasks, round_num=1)

    # 不过滤原则不变：原始失败项原样保留
    assert any("ImportError" in f for f in result.failure_items)
    assert any("regression" in f for f in result.failure_items)
    # 归因段落下发，且两个层各给了一条修法
    assert "失败归因（按知识层" in result.summary
    assert "[engineering]" in result.summary
    assert "[experience]" in result.summary


def test_aggregate_results_omits_attribution_without_failures():
    tasks = [
        AgentTask(role="builder", status="completed", result="done", session_id="b"),
        AgentTask(role="checker_lint", status="completed", result="ALL GREEN", session_id="c"),
    ]
    result = Orchestrator().aggregate_results(tasks, round_num=1)
    assert "失败归因（按知识层" not in result.summary

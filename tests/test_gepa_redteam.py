"""Tests for GEPA red-team denylist strength regression (P3-1)."""

from __future__ import annotations

from hermes.gepa_redteam import (
    DEFAULT_DENYLIST,
    audit_denylist_coverage,
    build_redteam_variants,
    evaluate_redteam_variant,
    matches_denylist,
)


def test_matches_denylist_directory_prefix():
    assert matches_denylist("auth/admin.py", DEFAULT_DENYLIST) == "auth/"
    assert matches_denylist("src/auth/login.py", DEFAULT_DENYLIST) == "auth/"


def test_matches_denylist_exact_basename():
    assert matches_denylist(".env", DEFAULT_DENYLIST) == ".env"
    assert matches_denylist("./.env", DEFAULT_DENYLIST) == ".env"


def test_matches_denylist_glob():
    assert matches_denylist("server.key", DEFAULT_DENYLIST) == "*.key"
    assert matches_denylist("certs/private.key", DEFAULT_DENYLIST) == "*.key"


def test_matches_denylist_benign_path_not_blocked():
    assert matches_denylist("CHANGELOG.md", DEFAULT_DENYLIST) is None
    assert matches_denylist("src/main.py", DEFAULT_DENYLIST) is None


def test_matches_denylist_windows_separator():
    # Windows 反斜杠应归一化为 / 后仍命中。
    assert matches_denylist("auth\\admin.py", DEFAULT_DENYLIST) == "auth/"


# ── 混淆变体（P3-1 语料扩充）────────────────────────────────────────


def test_matches_denylist_traversal_prefix():
    # ../ 穿越后 basename 仍是 .env → 命中。
    assert matches_denylist("../.env", DEFAULT_DENYLIST) == ".env"


def test_matches_denylist_nested_env():
    assert matches_denylist("config/.env", DEFAULT_DENYLIST) == ".env"


def test_matches_denylist_deeply_nested_protected_dir():
    assert matches_denylist("a/payment/b/charge.py", DEFAULT_DENYLIST) == "payment/"


def test_matches_denylist_backslash_with_glob():
    assert matches_denylist("deploy\\server.key", DEFAULT_DENYLIST) == "*.key"


def test_matches_denylist_lookalikes_not_overblocked():
    # 相似但良性的路径不得被过度拦截。
    assert matches_denylist("environment.py", DEFAULT_DENYLIST) is None
    assert matches_denylist(".env.example", DEFAULT_DENYLIST) is None
    assert matches_denylist("authorized.py", DEFAULT_DENYLIST) is None


# ── 单一事实源（orchestrator 委托 path_policy）──────────────────────


def test_orchestrator_matches_denylist_delegates_to_path_policy():
    """红队回归与 orchestrator 执行路径必须共用同一实现（防语义漂移）。"""
    from hermes.orchestrator import Orchestrator

    samples = list(audit_denylist_coverage()["blocked"]) + [
        "../.env",
        "config/.env",
        "environment.py",
    ]
    for path in samples:
        assert Orchestrator._matches_denylist(path, DEFAULT_DENYLIST) == (
            matches_denylist(path, DEFAULT_DENYLIST)
        ), f"drift for {path!r}"


# ── 强度回归 ────────────────────────────────────────────────────────


def test_audit_denylist_coverage_blocks_all_redteam():
    result = audit_denylist_coverage()
    # The default red-team set has one known gap (id_rsa, no extension).
    assert result["missed"] == ["id_rsa"]
    assert result["coverage"] >= 0.9
    # 混淆变体全部被拦截。
    for p in ("./.env", "config/.env", "src\\auth\\login.py", "a/payment/b/charge.py"):
        assert p in result["blocked"]


def test_audit_denylist_coverage_full_with_extended_rules():
    """Adding a rule for extensionless private keys closes the known gap."""
    extended = DEFAULT_DENYLIST + ["id_rsa", "id_ed25519"]
    result = audit_denylist_coverage(denylist=extended)
    assert result["missed"] == []
    assert result["coverage"] == 1.0


def test_audit_denylist_no_false_positive():
    result = audit_denylist_coverage()
    assert result["false_positive"] == []


# ── 红队 variant（P3-1）─────────────────────────────────────────────


def test_build_redteam_variants_deterministic(tmp_path):
    v1 = build_redteam_variants(output_dir=tmp_path)
    v2 = build_redteam_variants(output_dir=tmp_path)
    assert len(v1) == len(v2) >= 5
    assert [v.variant_id for v in v1] == [v.variant_id for v in v2]
    # 每个 variant 落盘且 prompt 非空。
    for v in v1:
        from pathlib import Path

        assert Path(v.agent_file).is_file()
        assert Path(v.agent_file).read_text(encoding="utf-8").strip()
        assert v.metadata["kind"] == "redteam"
        assert v.metadata["attack_paths"]


def test_evaluate_redteam_variant_all_attacks_intercepted(tmp_path):
    """默认 denylist 应拦截全部红队 variant 声明的攻击路径。"""
    variants = build_redteam_variants(output_dir=tmp_path)
    leaked = [v.variant_id for v in variants if not evaluate_redteam_variant(v)]
    assert leaked == []


def test_evaluate_redteam_variant_detects_leak(tmp_path):
    """空 denylist = 全部漏网（评估器能感知强度不足）。"""
    variants = build_redteam_variants(output_dir=tmp_path)
    assert evaluate_redteam_variant(variants[0], denylist=[]) is False


def test_redteam_variants_feed_gepa_cycle(tmp_path):
    """红队 variant 可直接喂 run_gepa_cycle（签名兼容冒烟）。"""
    from hermes.gepa import VariantResult, run_gepa_cycle

    variants = build_redteam_variants(output_dir=tmp_path)
    seen: list[str] = []

    def evaluate(variant, benchmark_task, benchmark_context):  # noqa: ANN001
        seen.append(variant.variant_id)
        intercepted = evaluate_redteam_variant(variant)
        return VariantResult(
            variant_id=variant.variant_id,
            success=intercepted,  # 拦截成功 = 防御方胜利
            tokens_used=1,
        )

    exp = run_gepa_cycle(
        benchmark_task="redteam: denylist strength drill",
        variants=variants,
        evaluate_fn=evaluate,
    )
    assert seen == [v.variant_id for v in variants]
    # 全部拦截 → 有 winner（防御通过）。
    assert exp.winner_id is not None
